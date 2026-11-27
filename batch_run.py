"""
Batch runner — iterate over personas from a JSONL file and generate a UserWorld for each.

Each world runs as a separate subprocess (uv run python cold_start.py ...) with a
per-world timeout. Concurrency is managed via asyncio.Semaphore — no threads needed.
Resume support via _complete marker.

Usage:
    uv run python batch_run.py --input personas_subset_1k.jsonl
    uv run python batch_run.py --input personas_subset_1k.jsonl --limit 10
    uv run python batch_run.py --input personas_subset_1k.jsonl --limit 10 --offset 50
    uv run python batch_run.py --input personas_subset_1k.jsonl --max-generate 5
    uv run python batch_run.py --input personas_subset_1k.jsonl --concurrency 5
    uv run python batch_run.py --input personas_subset_1k.jsonl --timeout 3600
"""

import argparse
import asyncio
import json
import os
import shutil
import signal
import sys
import time
from datetime import datetime


def _load_personas(input_file: str, offset: int, limit: int | None) -> list[tuple[int, str]]:
    """Read personas from a JSONL file, applying offset and limit."""
    personas = []
    with open(input_file, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i < offset:
                continue
            if limit is not None and len(personas) >= limit:
                break
            line = line.strip()
            if line:
                try:
                    data = json.loads(line)
                    persona_text = data.get("persona", "")
                    if persona_text:
                        personas.append((offset + len(personas), persona_text))
                except json.JSONDecodeError:
                    pass
    return personas


async def _process_one(
    line_num: int,
    persona_text: str,
    worlds_root: str,
    prefix: str,
    model: str | None,
    max_generate: int | None,
    timestamp: str | None,
    plugins: list[str] | None,
    timeout: int,
    semaphore: asyncio.Semaphore,
    counters: dict,
    total: int,
) -> dict:
    """Run cold_start for one world in a subprocess with timeout."""
    world_id = f"{prefix}_{line_num:06d}"
    world_dir = os.path.join(worlds_root, world_id)

    # Skip already-completed worlds
    if os.path.exists(os.path.join(world_dir, "_complete")):
        counters["skipped"] += 1
        counters["completed"] += 1
        print(f"[SKIP] {world_id} already complete. ({counters['completed']}/{total})")
        return {"world_id": world_id, "line": line_num, "status": "skipped"}

    # Write persona to a temp file in worlds_root
    os.makedirs(worlds_root, exist_ok=True)
    persona_file = os.path.join(worlds_root, f".persona_{world_id}.txt")
    with open(persona_file, "w", encoding="utf-8") as f:
        f.write(persona_text)

    # Build command
    cmd = [
        sys.executable, "cold_start.py",
        "--persona-file", persona_file,
        "--world-id", world_id,
        "--worlds-root", worlds_root,
    ]
    if model:
        cmd.extend(["--model", model])
    if max_generate is not None:
        cmd.extend(["--max-generate", str(max_generate)])
    if timestamp:
        cmd.extend(["--timestamp", timestamp])
    if plugins:
        cmd.extend(["--plugins"] + plugins)

    print(f"[START] {world_id} (line {line_num}): {persona_text[:80]}{'...' if len(persona_text) > 80 else ''}")

    async with semaphore:
        proc = None
        try:
            # start_new_session=True on Unix so we can kill the whole process group
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=None,  # inherit stdout for real-time tagged log lines
                stderr=asyncio.subprocess.PIPE,
                start_new_session=(sys.platform != "win32"),
            )
            try:
                _, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                # Kill the process tree
                _kill_process_tree(proc.pid)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=15)
                except asyncio.TimeoutError:
                    proc.kill()
                counters["timed_out"] += 1
                counters["completed"] += 1
                print(f"[TIMEOUT] {world_id} killed after {timeout}s. ({counters['completed']}/{total})")
                return {"world_id": world_id, "line": line_num, "status": "timeout"}

            if proc.returncode == 0:
                counters["succeeded"] += 1
                counters["completed"] += 1
                print(f"[OK] {world_id} complete. ({counters['completed']}/{total} done, "
                      f"{counters['succeeded']} ok, {counters['failed']} failed, "
                      f"{counters['timed_out']} timeout)")
                return {"world_id": world_id, "line": line_num, "status": "ok"}
            else:
                stderr = stderr_bytes.decode(errors="replace")[-500:] if stderr_bytes else ""
                counters["failed"] += 1
                counters["completed"] += 1
                print(f"[ERROR] {world_id} exit code {proc.returncode}. ({counters['completed']}/{total})")
                if stderr:
                    print(f"  stderr: {stderr}")
                return {"world_id": world_id, "line": line_num, "status": "error", "error": stderr}

        except Exception as e:
            counters["failed"] += 1
            counters["completed"] += 1
            print(f"[ERROR] {world_id}: {e}. ({counters['completed']}/{total})")
            return {"world_id": world_id, "line": line_num, "status": "error", "error": str(e)}

        finally:
            if os.path.exists(persona_file):
                os.unlink(persona_file)


def _kill_process_tree(pid: int):
    """Kill a process and all its children (cross-platform)."""
    if sys.platform == "win32":
        os.system(f"taskkill /T /F /PID {pid} >nul 2>&1")
    else:
        # Kill the process group (requires start_new_session=True on subprocess)
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass


async def async_main():
    parser = argparse.ArgumentParser(description="Batch Cold Start runner")
    parser.add_argument("--input", type=str, required=True, help="Path to personas JSONL file")
    parser.add_argument("--limit", type=int, default=None, help="Max number of personas to process")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N personas")
    parser.add_argument("--prefix", type=str, default="world",
                        help="World ID prefix. Default: world (produces world_000000, world_000001, ...)")
    parser.add_argument("--worlds-root", type=str, default="worlds", help="Output directory")
    parser.add_argument("--max-generate", type=int, default=None, help="Max files to generate per world")
    parser.add_argument("--timestamp", type=str, default=None,
                        help="Current timestamp for all worlds (ISO format, e.g. 2025-12-31T23:59:59). Default: now")
    parser.add_argument("--model", type=str, default="claude-sonnet-4-6",
                        help="Claude model. Default: claude-sonnet-4-6")
    parser.add_argument("--plugins", type=str, nargs="*", default=None, help="Plugin directories")
    parser.add_argument("--concurrency", type=int, default=5,
                        help="Number of concurrent worlds to generate. Default: 5")
    parser.add_argument("--timeout", type=int, default=18000,
                        help="Per-world timeout in seconds. Default: 18000 (5 hours)")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    personas = _load_personas(args.input, args.offset, args.limit)
    total = len(personas)

    print(f"Loaded {total} personas (offset={args.offset}, limit={args.limit})")
    print(f"Model: {args.model or 'default'}")
    print(f"Concurrency: {args.concurrency}")
    print(f"Per-world timeout: {args.timeout}s")
    print(f"Worlds root: {args.worlds_root}")
    if args.max_generate is not None:
        print(f"Max generate per world: {args.max_generate}")
    print()

    counters = {"succeeded": 0, "failed": 0, "skipped": 0, "timed_out": 0, "completed": 0}
    semaphore = asyncio.Semaphore(args.concurrency)

    tasks = [
        _process_one(
            line_num, persona_text,
            args.worlds_root, args.prefix, args.model, args.max_generate,
            args.timestamp, args.plugins, args.timeout,
            semaphore, counters, total,
        )
        for line_num, persona_text in personas
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Handle any exceptions that slipped through
    clean_results = []
    for r in results:
        if isinstance(r, Exception):
            print(f"[FATAL] Unhandled exception: {r}")
        elif isinstance(r, dict):
            clean_results.append(r)

    # Final summary
    print(f"\n{'=' * 60}")
    print(f"Batch complete: {counters['succeeded']} succeeded, {counters['failed']} failed, "
          f"{counters['timed_out']} timed out, {counters['skipped']} skipped out of {total}")
    print(f"{'=' * 60}")

    # Save results log
    log_path = os.path.join(args.worlds_root, "batch_log.jsonl")
    with open(log_path, "a", encoding="utf-8") as f:
        for r in clean_results:
            r["timestamp"] = datetime.now().isoformat()
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Results appended to {log_path}")


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()

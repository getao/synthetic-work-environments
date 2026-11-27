"""
Batch Daily Simulation runner — find all Cold Start worlds and run daily_sim.py concurrently.

Scans worlds_root for worlds that have completed Cold Start (_complete) but not
Daily Sim (_daily_sim_complete), and runs daily_sim.py on each with concurrency control.

Usage:
    uv run python batch_daily_sim.py
    uv run python batch_daily_sim.py --concurrency 50 --limit 100 --start-date 2026-01-01
    uv run python batch_daily_sim.py --offset 100 --limit 50
    uv run python batch_daily_sim.py --plan-only
    uv run python batch_daily_sim.py --world-ids world_000000 world_000001
    uv run python batch_daily_sim.py --prefix gdpeval_world --timeout 36000
"""

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from datetime import datetime


def _find_eligible_worlds(
    worlds_root: str,
    prefix: str | None,
    world_ids: list[str] | None,
) -> list[str]:
    """Find worlds with Cold Start complete.

    Returns sorted list of world_id strings.  Does NOT filter by daily sim
    status — resume logic inside daily_simulate() handles skipping already-done
    steps automatically.
    """
    if world_ids:
        # Explicit list — just validate they exist and have Cold Start done
        eligible = []
        for wid in world_ids:
            wdir = os.path.join(worlds_root, wid)
            if not os.path.isdir(wdir):
                print(f"WARNING: {wid} not found in {worlds_root}, skipping.")
                continue
            if not os.path.exists(os.path.join(wdir, "_complete")):
                print(f"WARNING: {wid} has not completed Cold Start, skipping.")
                continue
            eligible.append(wid)
        return sorted(eligible)

    eligible = []
    if not os.path.isdir(worlds_root):
        return eligible

    for name in sorted(os.listdir(worlds_root)):
        wdir = os.path.join(worlds_root, name)
        if not os.path.isdir(wdir):
            continue
        if prefix and not name.startswith(prefix):
            continue
        # Must have Cold Start complete
        if not os.path.exists(os.path.join(wdir, "_complete")):
            continue
        eligible.append(name)

    return eligible


async def _process_one(
    world_id: str,
    worlds_root: str,
    model: str | None,
    start_date: str | None,
    weeks: int,
    plan_only: bool,
    plugins: list[str] | None,
    timeout: int,
    semaphore: asyncio.Semaphore,
    counters: dict,
    total: int,
    eval_model: str | None = None,
    use_occupation_skills: bool = False,
) -> dict:
    """Run daily_sim.py for one world in a subprocess with timeout."""
    cmd = [
        sys.executable, "daily_sim.py",
        "--world-id", world_id,
        "--worlds-root", worlds_root,
        "--weeks", str(weeks),
    ]
    if model:
        cmd.extend(["--model", model])
    if eval_model:
        cmd.extend(["--eval-model", eval_model])
    if start_date:
        cmd.extend(["--start-date", start_date])
    if plan_only:
        cmd.append("--plan-only")
    if use_occupation_skills:
        cmd.append("--use-occupation-skills")
    if plugins:
        cmd.extend(["--plugins"] + plugins)

    label = "plan" if plan_only else "daily_sim"
    print(f"[START] {world_id} ({label})")

    async with semaphore:
        t0 = time.monotonic()
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=None,  # inherit stdout for real-time log lines
                stderr=asyncio.subprocess.PIPE,
                start_new_session=(sys.platform != "win32"),
            )
            try:
                _, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                _kill_process_tree(proc.pid)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=15)
                except asyncio.TimeoutError:
                    proc.kill()
                elapsed = int(time.monotonic() - t0)
                counters["timed_out"] += 1
                counters["completed"] += 1
                print(f"[TIMEOUT] {world_id} killed after {elapsed}s. ({counters['completed']}/{total})")
                return {"world_id": world_id, "status": "timeout", "elapsed_s": elapsed}

            elapsed = int(time.monotonic() - t0)
            if proc.returncode == 0:
                counters["succeeded"] += 1
                counters["completed"] += 1
                print(f"[OK] {world_id} done in {elapsed}s. ({counters['completed']}/{total} done, "
                      f"{counters['succeeded']} ok, {counters['failed']} failed, "
                      f"{counters['timed_out']} timeout)")
                return {"world_id": world_id, "status": "ok", "elapsed_s": elapsed}
            else:
                stderr = stderr_bytes.decode(errors="replace")[-500:] if stderr_bytes else ""
                counters["failed"] += 1
                counters["completed"] += 1
                print(f"[ERROR] {world_id} exit code {proc.returncode} after {elapsed}s. ({counters['completed']}/{total})")
                if stderr:
                    print(f"  stderr: {stderr}")
                return {"world_id": world_id, "status": "error", "error": stderr, "elapsed_s": elapsed}

        except Exception as e:
            elapsed = int(time.monotonic() - t0)
            counters["failed"] += 1
            counters["completed"] += 1
            print(f"[ERROR] {world_id}: {e}. ({counters['completed']}/{total})")
            return {"world_id": world_id, "status": "error", "error": str(e), "elapsed_s": elapsed}


def _kill_process_tree(pid: int):
    """Kill a process and all its children (cross-platform)."""
    if sys.platform == "win32":
        os.system(f"taskkill /T /F /PID {pid} >nul 2>&1")
    else:
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass


async def async_main():
    parser = argparse.ArgumentParser(description="Batch Daily Simulation runner")
    parser.add_argument("--worlds-root", type=str, default="worlds", help="Root directory for worlds. Default: worlds/")
    parser.add_argument("--prefix", type=str, default=None,
                        help="Only process world dirs matching this prefix (e.g. 'world', 'gdpeval_world')")
    parser.add_argument("--world-ids", type=str, nargs="*", default=None,
                        help="Explicit list of world IDs to process (overrides --prefix)")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N worlds (after sorting). Default: 0")
    parser.add_argument("--limit", type=int, default=None, help="Max number of worlds to process (after offset)")
    parser.add_argument("--model", type=str, default=None,
                        help="Claude model (e.g. claude-sonnet-4-6). Default: SDK default.")
    parser.add_argument("--eval-model", type=str, default=None,
                        help="Override model for Step 9 evaluation only. Default: same as --model.")
    parser.add_argument("--start-date", type=str, default=None,
                        help="Simulation start date (YYYY-MM-DD). Default: today")
    parser.add_argument("--weeks", type=int, default=4, help="Number of weeks to simulate. Default: 4")
    parser.add_argument("--plan-only", action="store_true",
                        help="Only run Steps 6 + 6.5 (planning), then stop.")
    parser.add_argument("--use-occupation-skills", action="store_true",
                        help="Inject an 'Occupation Skills' hint into Steps 7/8 prompts "
                             "(tells the agent to read the matching .claude/skills/<role>/ "
                             "before planning / producing). No-op for plan-only.")
    parser.add_argument("--plugins", type=str, nargs="*", default=None, help="Plugin directories")
    parser.add_argument("--concurrency", type=int, default=3,
                        help="Number of concurrent worlds. Default: 3")
    parser.add_argument("--timeout", type=int, default=36000,
                        help="Per-world timeout in seconds. Default: 36000 (10 hours)")

    args = parser.parse_args()

    worlds = _find_eligible_worlds(args.worlds_root, args.prefix, args.world_ids)
    worlds = worlds[args.offset:]
    if args.limit:
        worlds = worlds[:args.limit]

    if not worlds:
        print("No eligible worlds found.")
        sys.exit(0)

    label = "planning (Steps 6+6.5)" if args.plan_only else "Daily Sim (Steps 6-9)"
    print(f"Found {len(worlds)} eligible worlds for {label}")
    print(f"Model: {args.model or 'default'}")
    print(f"Concurrency: {args.concurrency}")
    print(f"Per-world timeout: {args.timeout}s")
    print(f"Worlds root: {args.worlds_root}")
    print()

    counters = {"succeeded": 0, "failed": 0, "timed_out": 0, "completed": 0}
    semaphore = asyncio.Semaphore(args.concurrency)

    tasks = [
        _process_one(
            world_id, args.worlds_root, args.model, args.start_date,
            args.weeks, args.plan_only, args.plugins, args.timeout,
            semaphore, counters, len(worlds),
            eval_model=args.eval_model,
            use_occupation_skills=args.use_occupation_skills,
        )
        for world_id in worlds
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    clean_results = []
    for r in results:
        if isinstance(r, Exception):
            print(f"[FATAL] Unhandled exception: {r}")
        elif isinstance(r, dict):
            clean_results.append(r)

    # Final summary
    print(f"\n{'=' * 60}")
    print(f"Batch complete: {counters['succeeded']} succeeded, {counters['failed']} failed, "
          f"{counters['timed_out']} timed out out of {len(worlds)}")
    print(f"{'=' * 60}")

    # Save results log
    log_path = os.path.join(args.worlds_root, "batch_daily_sim_log.jsonl")
    with open(log_path, "a", encoding="utf-8") as f:
        for r in clean_results:
            r["timestamp"] = datetime.now().isoformat()
            r["plan_only"] = args.plan_only
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Results appended to {log_path}")


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()

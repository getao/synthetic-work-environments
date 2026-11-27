"""
Analyze a completed world and produce a detailed diagnostic report.

The agent runs agentically — it reads files using tools (Read, Grep, Bash)
and explores the world data as needed, following leads from evaluation
results back into turn logs and NPC interactions.

Usage:
    uv run python analyze_world.py --world worlds/world_000000
    uv run python analyze_world.py --world worlds/world_000000 --model claude-opus-4-6
    uv run python analyze_world.py --batch worlds --limit 10 --concurrency 3

Output:
    <world>/analysis_report.md    — detailed diagnostic report
    <world>/analysis_cost.json    — analysis cost/tokens
"""

import argparse
import asyncio
import json
import os
import signal
import sys
import time

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    UserMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    ThinkingBlock,
    ResultMessage,
)


# ---------------------------------------------------------------------------
# SDK helpers (inlined for standalone use)
# ---------------------------------------------------------------------------

async def _as_stream(text: str):
    yield {"type": "user", "message": {"role": "user", "content": text}}


def _truncate(s: str, max_len: int = 200) -> str:
    if len(s) <= max_len:
        return s
    return s[:max_len] + f"...({len(s)} chars)"


async def call_claude(
    prompt: str,
    cwd: str,
    max_turns: int = 200,
    model: str | None = None,
    log_file: str | None = None,
) -> dict:
    """Call Claude Code agentic session. Agent has Read/Grep/Bash tools."""
    options = ClaudeAgentOptions(
        permission_mode="bypassPermissions",
        cwd=cwd,
        max_turns=max_turns,
    )
    if model:
        options.model = model

    output_parts: list[str] = []
    result_info: dict = {}
    fh = open(log_file, "a", encoding="utf-8") if log_file else None

    try:
        async for message in query(prompt=_as_stream(prompt), options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        if fh:
                            fh.write(block.text)
                            fh.flush()
                        else:
                            print(block.text, end="", flush=True)
                        output_parts.append(block.text)
            elif isinstance(message, ResultMessage):
                result_info = {
                    "cost_usd": message.total_cost_usd or 0.0,
                    "usage": message.usage or {},
                    "num_turns": message.num_turns,
                    "session_id": message.session_id,
                }
    finally:
        if fh:
            fh.write("\n")
            fh.close()

    if not fh:
        print()
    result_info["text"] = "".join(output_parts)
    return result_info


# ---------------------------------------------------------------------------
# Analysis prompt
# ---------------------------------------------------------------------------

ANALYSIS_PROMPT = """\
You are a senior performance analyst. Your job is to produce a COMPREHENSIVE
diagnostic report on one AI agent's month-long work simulation.

## Files Available (in the current directory)

- `monthly_objectives.json` — deliverables, milestones, weekly focus
- `external_context.json` — NPC definitions (background, role, what they provide)
- `week_1_plan.json` through `week_4_plan.json` — daily activity plans
- `npc_interaction_logs.json` — full conversation history with all NPCs
- `evaluation_summary.json` — rubric scoring (every item: criterion, met/unmet, notes)
- `daily_activity_log.jsonl` — agent's self-reported daily activities
- `daily_sim_turns.jsonl` — turn-by-turn execution log (tool calls, tool results, errors, timing)

## Your Process

1. **Start with evaluation_summary.json** — Read it fully. For every deliverable,
   note the score and list ALL unmet/partial items with their criterion and notes.

2. **Read monthly_objectives.json and external_context.json** — Understand what
   was planned and who the NPCs are.

3. **For each unmet rubric item, investigate WHY it was unmet:**
   - Search `npc_interaction_logs.json` for relevant NPC exchanges — did the NPC
     provide the information? Did the agent ask for it? Did the agent incorporate it?
   - Search `daily_sim_turns.jsonl` for relevant tool calls — grep for file names,
     NPC ids, or key terms from the criterion.
   - Check `daily_activity_log.jsonl` for what the agent claimed it did.
   - Trace the causal chain: information source → agent action → deliverable gap.

4. **Analyze NPC communication quality:**
   - Read all NPC interactions. Were messages specific and actionable?
   - Were there missed opportunities (info needed but never requested)?
   - Was feedback acknowledged but not applied?

5. **Analyze efficiency:**
   - Search `daily_sim_turns.jsonl` for error patterns (grep for "is_error")
   - Look for spinning turns (high thinking_len, no tool_calls)
   - Check if weekly plans matched actual execution

6. **Write the report to `analysis_report.md`** in the current directory.

## Report Structure

### 1. Executive Summary
Who is this person, what did they do, overall score, one-paragraph assessment.

### 2. Deliverable-by-Deliverable Analysis
For EACH deliverable:
- Score and key strengths
- **Every unmet rubric item**: what was the criterion, what the evaluator noted,
  and your root cause analysis (with references to specific NPC messages, days, files)
- What should have been done differently

### 3. NPC Communication Analysis
For each NPC:
- Summary of all interactions (with day references)
- Effectiveness: did the agent get what it needed?
- Missed feedback: NPC corrections that weren't applied (cite specific messages)
- Missed opportunities: questions that should have been asked earlier

### 4. Workflow & Efficiency
- Error patterns from turn log
- Time/token waste (spinning, retries, dead ends)
- Plan vs execution gaps
- Work sequencing issues (should have done X before Y)

### 5. Domain-Specific Insights
- What professional knowledge was missing or wrong?
- What would an expert in this field have done differently?

### 6. Actionable Recommendations
5-15 SPECIFIC recommendations. Each must have:
- **What happened**: concrete incident (day, NPC, file, criterion)
- **What should have happened**: concrete alternative action
- **Generalizable lesson**: how to apply this to future work

Be EXHAUSTIVE. Read the files. Grep for specific terms. Follow every lead.
Every unmet rubric item must have a root cause.

Write the report now.
"""


# ---------------------------------------------------------------------------
# Single world analysis
# ---------------------------------------------------------------------------

async def analyze_world(world_dir: str, model: str | None = None,
                        max_turns: int = 200) -> dict:
    world_dir = os.path.abspath(world_dir)
    world_name = os.path.basename(world_dir)
    report_path = os.path.join(world_dir, "analysis_report.md")
    cost_path = os.path.join(world_dir, "analysis_cost.json")
    log_path = os.path.join(world_dir, "analysis_output.log")

    # Skip if already analyzed
    if os.path.exists(report_path):
        print(f"[SKIP] {world_name} already analyzed.")
        return {"world": world_name, "status": "skipped"}

    # Check required files
    required = ["evaluation_summary.json", "monthly_objectives.json", "daily_sim_turns.jsonl"]
    for f in required:
        if not os.path.exists(os.path.join(world_dir, f)):
            print(f"[SKIP] {world_name} missing {f}")
            return {"world": world_name, "status": "missing_data"}

    print(f"[START] {world_name}: launching analysis agent...")
    t0 = time.monotonic()

    result = await call_claude(
        ANALYSIS_PROMPT,
        cwd=world_dir,
        max_turns=max_turns,
        model=model,
        log_file=log_path,
    )

    elapsed = time.monotonic() - t0
    cost_usd = result.get("cost_usd", 0)

    # Check if report was written by the agent
    if not os.path.exists(report_path):
        # Agent might have output text but not written the file — save its output
        text = result.get("text", "")
        if text:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(f"# Analysis Report: {world_name}\n\n")
                f.write(text)

    # Save cost
    cost_info = {
        "world": world_name,
        "cost_usd": round(cost_usd, 4),
        "elapsed_s": round(elapsed, 1),
        "num_turns": result.get("num_turns", 0),
        "usage": result.get("usage", {}),
    }
    with open(cost_path, "w", encoding="utf-8") as f:
        json.dump(cost_info, f, indent=2, ensure_ascii=False)

    report_size = os.path.getsize(report_path) if os.path.exists(report_path) else 0
    print(f"[OK] {world_name}: report={report_size:,} bytes, ${cost_usd:.4f}, "
          f"{result.get('num_turns',0)} turns, {elapsed:.0f}s")
    return {"world": world_name, "status": "ok", **cost_info}


# ---------------------------------------------------------------------------
# Batch mode (subprocess + semaphore)
# ---------------------------------------------------------------------------

def _kill_process_tree(pid: int):
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


async def _run_one_subprocess(
    world_dir: str, model: str | None, max_turns: int, timeout: int,
    semaphore: asyncio.Semaphore, counters: dict, total: int,
) -> dict:
    name = os.path.basename(world_dir)

    if os.path.exists(os.path.join(world_dir, "analysis_report.md")):
        counters["skipped"] += 1
        counters["completed"] += 1
        print(f"[SKIP] {name} ({counters['completed']}/{total})")
        return {"world": name, "status": "skipped"}

    cmd = [sys.executable, __file__, "--world", world_dir, "--max-turns", str(max_turns)]
    if model:
        cmd.extend(["--model", model])

    async with semaphore:
        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=None, stderr=asyncio.subprocess.PIPE,
                start_new_session=(sys.platform != "win32"),
            )
            try:
                _, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                _kill_process_tree(proc.pid)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=15)
                except asyncio.TimeoutError:
                    proc.kill()
                counters["timed_out"] += 1
                counters["completed"] += 1
                return {"world": name, "status": "timeout"}

            elapsed = int(time.monotonic() - t0)
            if proc.returncode == 0:
                counters["succeeded"] += 1
                counters["completed"] += 1
                print(f"[OK] {name} in {elapsed}s ({counters['completed']}/{total})")
                return {"world": name, "status": "ok", "elapsed_s": elapsed}
            else:
                stderr = stderr_bytes.decode(errors="replace")[-300:] if stderr_bytes else ""
                counters["failed"] += 1
                counters["completed"] += 1
                print(f"[ERROR] {name} ({counters['completed']}/{total}): {stderr}")
                return {"world": name, "status": "error"}
        except Exception as e:
            counters["failed"] += 1
            counters["completed"] += 1
            return {"world": name, "status": "error", "error": str(e)}


async def run_batch(batch_root: str, model: str | None, max_turns: int,
                    concurrency: int, timeout: int, offset: int, limit: int | None):
    worlds = []
    for name in sorted(os.listdir(batch_root)):
        d = os.path.join(batch_root, name)
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "_daily_sim_complete")):
            worlds.append(d)
    worlds = worlds[offset:]
    if limit:
        worlds = worlds[:limit]

    if not worlds:
        print("No completed worlds found.")
        return

    total = len(worlds)
    print(f"Analyzing {total} worlds (concurrency={concurrency}, max_turns={max_turns})")

    counters = {"succeeded": 0, "failed": 0, "skipped": 0, "timed_out": 0, "completed": 0}
    semaphore = asyncio.Semaphore(concurrency)

    tasks = [
        _run_one_subprocess(w, model, max_turns, timeout, semaphore, counters, total)
        for w in worlds
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    clean = [r for r in results if isinstance(r, dict)]
    print(f"\nDone: {counters['succeeded']} ok, {counters['failed']} fail, "
          f"{counters['skipped']} skip, {counters['timed_out']} timeout / {total}")

    # Aggregate costs
    total_cost = 0
    for r in clean:
        cp = os.path.join(batch_root, r.get("world", ""), "analysis_cost.json")
        if os.path.exists(cp):
            try:
                total_cost += json.load(open(cp)).get("cost_usd", 0)
            except:
                pass
    print(f"Total analysis cost: ${total_cost:.2f}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Analyze completed worlds (agentic)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--world", type=str, help="Single world directory")
    group.add_argument("--batch", type=str, help="Root directory containing worlds")

    parser.add_argument("--model", type=str, default="claude-opus-4-6[1m]",
                        help="Model for analysis. Default: claude-opus-4-6[1m]")
    parser.add_argument("--max-turns", type=int, default=1000,
                        help="Max agent turns for analysis. Default: 1000")
    parser.add_argument("--concurrency", type=int, default=50,
                        help="Batch concurrency. Default: 50")
    parser.add_argument("--timeout", type=int, default=900,
                        help="Per-world timeout (s). Default: 900 (15min)")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N worlds")
    parser.add_argument("--limit", type=int, default=None, help="Max worlds to analyze")

    args = parser.parse_args()

    if args.world:
        asyncio.run(analyze_world(args.world, args.model, args.max_turns))
    else:
        asyncio.run(run_batch(args.batch, args.model, args.max_turns,
                              args.concurrency, args.timeout, args.offset, args.limit))


if __name__ == "__main__":
    main()

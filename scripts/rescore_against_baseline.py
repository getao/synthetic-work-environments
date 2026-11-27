"""Re-score target worlds' deliverables against baseline's frozen rubric.

For each (world, deliverable) where both baseline and target have data, take
the rubric items (criterion + points_possible) from baseline's evaluation_*.json
and run a SCORE-ONLY pass against target's deliverable files. The evaluator
does not regenerate the rubric — it only judges met/unmet for each pre-existing
criterion.

Output written into target world dirs:
    evaluation_{pid}_{dlv}_rescored.json    — per deliverable
    evaluation_summary_rescored.json        — per world (aggregate)

Usage:
    uv run python scripts/rescore_against_baseline.py \\
        --baseline baseline-worlds --target skill-worlds-v3 \\
        --eval-model claude-opus-4-7 --concurrency 5 [--worlds win_world_000017,...]
"""

import argparse
import asyncio
import glob
import json
import os
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.common import call_claude, _read_json, _logical_to_physical


def _resolve_deliverable(world_dir: str, name_or_path: str) -> str | None:
    """Map an output_files entry (logical path OR bare filename) to a relative
    physical path. Returns None if not found.

    Bare filenames are searched under {world_dir}/drives/. Prefer matches under
    a 'share/' folder (final delivery), then most-recent mtime.
    """
    # Logical path: handle via the existing helper
    if ":/" in name_or_path:
        phys = _logical_to_physical(world_dir, name_or_path)
        if phys and os.path.exists(phys):
            return os.path.relpath(phys, world_dir).replace("\\", "/")
        return None

    # Bare filename: walk drives/ and find by name
    drives = os.path.join(world_dir, "drives")
    if not os.path.isdir(drives):
        return None
    matches = []
    for root, _dirs, files in os.walk(drives):
        if name_or_path in files:
            matches.append(os.path.join(root, name_or_path))
    if not matches:
        return None
    share = [m for m in matches if os.sep + "share" + os.sep in m]
    pick = (share or sorted(matches, key=lambda p: os.path.getmtime(p), reverse=True))[0]
    return os.path.relpath(pick, world_dir).replace("\\", "/")


def find_eval_files(world_dir: str) -> list[tuple[str, str, dict]]:
    """Return [(eval_pid, dlv_id, eval_data)] for each evaluation_*.json in world_dir."""
    out = []
    for p in sorted(glob.glob(os.path.join(world_dir, "evaluation_*.json"))):
        name = os.path.basename(p)
        if name in ("evaluation_summary.json", "evaluation_summary_rescored.json"):
            continue
        if name.endswith("_rescored.json"):
            continue
        # name = evaluation_{pid}_{dlv}.json
        stem = name[len("evaluation_"):-len(".json")]
        # split on last "_dlv_" to handle pid containing underscores
        if "_dlv_" not in stem:
            continue
        pid, dlv_tail = stem.rsplit("_dlv_", 1)
        dlv_id = "dlv_" + dlv_tail
        try:
            data = _read_json(p)
        except Exception:
            continue
        out.append((pid, dlv_id, data))
    return out


def build_score_only_prompt(
    evaluator_name: str,
    evaluator_id: str,
    deliverable_id: str,
    deliverable_title: str,
    deliverable_files: dict[str, str],
    reference_files: list[str],
    rubric_items: list[dict],
    output_filename: str,
) -> str:
    """Build a prompt that asks the evaluator NPC to score (only) against a fixed rubric."""
    # Filter out malformed items (missing criterion or zero/missing points)
    rubric_items = [it for it in rubric_items
                    if it.get("criterion") and it.get("points_possible", 0) > 0]
    rubric_for_prompt = [
        {
            "id": i,
            "criterion": it["criterion"],
            "source": it.get("source", "unknown"),
            "points_possible": it["points_possible"],
        }
        for i, it in enumerate(rubric_items)
    ]
    rubric_json = json.dumps(rubric_for_prompt, indent=2, ensure_ascii=False)
    deliv_lines = "\n".join(f"  - `{phys}`  (← {logical})" for logical, phys in deliverable_files.items()) or "  (No deliverable files found)"
    ref_lines = "\n".join(f"  - `{p}`" for p in reference_files) or "  (No reference files)"
    total_possible = sum(it["points_possible"] for it in rubric_items)

    return f"""\
You are **{evaluator_name}**, the evaluator for deliverable **{deliverable_id} — {deliverable_title}**.

You previously authored a detailed rubric for this deliverable. Your task NOW
is purely to **score the deliverable against that pre-existing rubric**. Do
NOT invent new criteria, do NOT change the criteria text, do NOT change
points_possible. Score every item.

## The Frozen Rubric ({len(rubric_items)} items, total {total_possible} pts)

{rubric_json}

## Files You Must Read

**Reference files** (your own materials — for resolving expected values):
{ref_lines}

**Deliverable files to evaluate**:
{deliv_lines}

Read every file above using the Read tool before scoring. The Read tool
handles .xlsx, .docx, and .pdf transparently.

═══════════════════════════════════════════════════════════════════

## SCORING TASK

For EACH of the {len(rubric_items)} rubric items, decide:
- `points_earned`: integer between 0 and `points_possible`
- `met`: true if `points_earned == points_possible`, else false
- `notes`: one short sentence with concrete evidence (file/sheet/section/value)
  citing what you saw

If a deliverable file is missing, items that depend on its content score 0
with `notes: "deliverable file not present"`.

If you cannot determine an item with confidence, score conservatively
(prefer 0 over guessing high) and explain in notes.

## OUTPUT

Write a single JSON file at this exact path (relative to your cwd):

    {output_filename}

with this exact schema:

```json
{{
  "deliverable_id": "{deliverable_id}",
  "evaluator_id": "{evaluator_id}",
  "evaluator_name": "{evaluator_name}",
  "total_possible": {total_possible},
  "total_earned": <int — sum of all points_earned>,
  "percentage": <float, 1 decimal>,
  "items": [
    {{
      "criterion": "<verbatim copy of criterion text>",
      "source": "<verbatim source>",
      "points_possible": <int>,
      "points_earned": <int>,
      "met": <bool>,
      "notes": "<one short sentence with evidence>"
    }},
    ... (one entry per rubric item, in the same order)
  ]
}}
```

The `criterion`, `source`, and `points_possible` fields MUST be copied
verbatim from the rubric above — do not paraphrase or alter them.

After writing the file, respond with one line: "Scored {deliverable_id}: <total_earned>/{total_possible}".
"""


async def rescore_one(
    sem: asyncio.Semaphore,
    target_world_dir: str,
    pid: str,
    dlv_id: str,
    baseline_eval: dict,
    objectives: dict,
    eval_model: str,
    log: callable,
):
    out_name = f"evaluation_{pid}_{dlv_id}_rescored.json"
    out_path = os.path.join(target_world_dir, out_name)
    if os.path.exists(out_path):
        log(f"  SKIP (already rescored) {os.path.basename(target_world_dir)} {pid} {dlv_id}")
        return _read_json(out_path)

    # Find the deliverable in objectives → output_files list
    dlv_obj = next(
        (d for d in objectives.get("deliverables", []) if d.get("id") == dlv_id),
        {},
    )
    deliv_paths: dict[str, str] = {}
    for path in dlv_obj.get("output_files", []):
        rel = _resolve_deliverable(target_world_dir, path)
        if rel:
            deliv_paths[path] = rel

    # Reference files: external_refs/{pid}/
    ref_paths = []
    ref_dir = os.path.join(target_world_dir, "external_refs", pid)
    if os.path.isdir(ref_dir):
        for fn in sorted(os.listdir(ref_dir)):
            fp = os.path.join(ref_dir, fn)
            if os.path.isfile(fp):
                ref_paths.append(os.path.relpath(fp, target_world_dir).replace("\\", "/"))

    rubric_items = baseline_eval.get("items", [])
    if not rubric_items:
        log(f"  WARN no rubric items for {pid} {dlv_id} — skipping")
        return None

    prompt = build_score_only_prompt(
        evaluator_name=baseline_eval.get("evaluator_name", "Evaluator"),
        evaluator_id=pid,
        deliverable_id=dlv_id,
        deliverable_title=dlv_obj.get("title", ""),
        deliverable_files=deliv_paths,
        reference_files=ref_paths,
        rubric_items=rubric_items,
        output_filename=out_name,
    )

    async with sem:
        log(f"  -> rescoring {os.path.basename(target_world_dir)} {pid} {dlv_id} ({len(rubric_items)} items)")
        try:
            await call_claude(
                prompt,
                cwd=target_world_dir,
                max_turns=40,
                model=eval_model,
                step_label=f"rescore_{dlv_id}_{pid}",
            )
        except Exception as e:
            log(f"  FAIL {pid} {dlv_id}: {type(e).__name__}: {e}")
            return None

    if not os.path.exists(out_path):
        log(f"  WARN no output file written for {pid} {dlv_id}")
        return None

    try:
        result = _read_json(out_path)
        log(f"  OK   {os.path.basename(target_world_dir)} {pid} {dlv_id}: {result.get('percentage','?')}%")
        return result
    except Exception as e:
        log(f"  WARN bad JSON in {out_path}: {e}")
        return None


async def rescore_world(
    sem: asyncio.Semaphore,
    baseline_world: str,
    target_world: str,
    eval_model: str,
):
    wid = os.path.basename(target_world)
    log = lambda m: print(f"[{wid}] {m}", flush=True)

    # Skip if v3 not done — partial worlds don't have all deliverables
    if not os.path.exists(os.path.join(target_world, "_daily_sim_complete")):
        log("target not _daily_sim_complete — skipping")
        return

    # Load shared objectives from target (same as baseline by md5)
    obj_path = os.path.join(target_world, "monthly_objectives.json")
    if not os.path.exists(obj_path):
        log("no monthly_objectives.json — skipping")
        return
    objectives = _read_json(obj_path)

    baseline_evals = find_eval_files(baseline_world)
    if not baseline_evals:
        log("no baseline eval files — skipping")
        return

    tasks = [
        rescore_one(sem, target_world, pid, dlv_id, data, objectives, eval_model, log)
        for pid, dlv_id, data in baseline_evals
    ]
    results = await asyncio.gather(*tasks)
    results = [r for r in results if r]

    if results:
        summary_path = os.path.join(target_world, "evaluation_summary_rescored.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        total_p = sum(r.get("total_possible", 0) for r in results)
        total_e = sum(r.get("total_earned", 0) for r in results)
        pct = round(100 * total_e / total_p, 1) if total_p else 0
        log(f"DONE: {len(results)} deliverables, {total_e}/{total_p} = {pct}%")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True, help="baseline worlds root")
    ap.add_argument("--target", required=True, help="target worlds root (the one to rescore)")
    ap.add_argument("--eval-model", default="claude-opus-4-7")
    ap.add_argument("--concurrency", type=int, default=5,
                    help="max simultaneous in-flight Claude calls (across all worlds)")
    ap.add_argument("--worlds", default="",
                    help="comma-separated world IDs to limit to (e.g. win_world_000017,win_world_000026)")
    ap.add_argument("--prefix", default="win_world_",
                    help="world dir prefix to discover (default: win_world_)")
    args = ap.parse_args()

    target_worlds = sorted(glob.glob(os.path.join(args.target, f"{args.prefix}*")))
    if args.worlds:
        wanted = set(args.worlds.split(","))
        target_worlds = [w for w in target_worlds if os.path.basename(w) in wanted]

    sem = asyncio.Semaphore(args.concurrency)

    print(f"Rescoring {len(target_worlds)} target worlds with concurrency={args.concurrency}, model={args.eval_model}")
    print(f"  baseline: {args.baseline}")
    print(f"  target:   {args.target}")

    coros = []
    for tw in target_worlds:
        wid = os.path.basename(tw)
        bw = os.path.join(args.baseline, wid)
        if not os.path.isdir(bw):
            print(f"[{wid}] no baseline counterpart at {bw} — skipping")
            continue
        coros.append(rescore_world(sem, bw, tw, args.eval_model))

    await asyncio.gather(*coros)
    print("All worlds processed.")


if __name__ == "__main__":
    asyncio.run(main())

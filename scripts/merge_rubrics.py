"""Merge baseline and v3 rubrics into a neutral, problem-level rubric per (world, dlv).

For each (world, deliverable) where both baseline and v3 have evaluation_*.json,
load both rubrics + spec + reference files + interaction history, then call
Claude to author a SINGLE merged rubric. Inspired by both rubrics, but each item
must be at the problem/capability level — NOT tied to a specific deliverable's
file layout, section numbers, or path.

Output:
    merged_rubrics/{world_id}/merged_{eval_pid}_{dlv_id}.json

Usage:
    uv run python scripts/merge_rubrics.py \\
        --baseline baseline-worlds --v3 skill-worlds-v3 \\
        --out merged_rubrics --model claude-opus-4-7 --concurrency 4 \\
        [--worlds win_world_000017,...]
"""

import argparse
import asyncio
import glob
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.common import call_claude, _read_json


def find_eval_files(world_dir: str) -> list[tuple[str, str, dict]]:
    out = []
    for p in sorted(glob.glob(os.path.join(world_dir, "evaluation_*.json"))):
        name = os.path.basename(p)
        if name in ("evaluation_summary.json", "evaluation_summary_rescored.json"):
            continue
        if "_rescored" in name or "_merged" in name:
            continue
        stem = name[len("evaluation_"):-len(".json")]
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


def filter_usable(items):
    return [it for it in items
            if it.get("criterion") and it.get("points_possible", 0) > 0]


def build_merge_prompt(
    evaluator_name: str,
    evaluator_id: str,
    deliverable: dict,
    interaction_history: list[dict],
    reference_file_paths: list[str],
    rubric_a: list[dict],   # baseline
    rubric_b: list[dict],   # v3
    output_filename: str,
) -> str:
    dlv_id = deliverable.get("id", "unknown")
    dlv_title = deliverable.get("title", "")
    dlv_desc = deliverable.get("description", "")
    milestones = deliverable.get("milestones", [])
    output_files = deliverable.get("output_files", [])
    milestones_text = "\n".join(f"  Week {m.get('week','?')}: {m.get('goal','')}" for m in milestones) or "  (none)"
    out_files_text = "\n".join(f"  - {f}" for f in output_files) or "  (none)"
    history_json = json.dumps(interaction_history, indent=2, ensure_ascii=False) if interaction_history else "[]"
    ref_text = "\n".join(f"  - `{p}`" for p in reference_file_paths) or "  (none)"

    def slim(items):
        return [{"criterion": it["criterion"], "source": it.get("source","unknown"),
                 "points_possible": it["points_possible"]} for it in items]

    a_pts = sum(it["points_possible"] for it in rubric_a)
    b_pts = sum(it["points_possible"] for it in rubric_b)
    rub_a_json = json.dumps(slim(rubric_a), indent=2, ensure_ascii=False)
    rub_b_json = json.dumps(slim(rubric_b), indent=2, ensure_ascii=False)

    return f"""\
You are **{evaluator_name}**, the evaluator for deliverable **{dlv_id} — {dlv_title}**.

You are constructing a NEUTRAL, FAIR evaluation rubric for this deliverable.

## Deliverable Specification
**Description**: {dlv_desc}
**Milestones**:
{milestones_text}
**Expected output files (informational; do not anchor rubric items to these names)**:
{out_files_text}

## Your Reference Files (data/templates you shared)
{ref_text}

(You may Read these files if needed to understand domain expectations.)

## Your Interaction History with the Worker
{history_json}

## Two Inspiration Rubrics

Two evaluators independently authored detailed rubrics after reviewing two
DIFFERENT candidate deliverables for this same problem. Use these as
**INSPIRATION** to discover what aspects matter — NOT as templates to copy.

**Rubric A** ({len(rubric_a)} items, {a_pts} pts):
{rub_a_json}

**Rubric B** ({len(rubric_b)} items, {b_pts} pts):
{rub_b_json}

═══════════════════════════════════════════════════════════════════

## YOUR TASK

Produce a SINGLE merged rubric (45–65 items) that fairly evaluates ANY plausible
deliverable for this problem — not biased toward either of the two specific
deliverables that inspired the prior rubrics.

### Critical principles

**1. Author at the PROBLEM level, not the deliverable level.**

  ✗ BAD (file/structure-specific):
    "Section 3.2 of vanguard1_article_FINAL.docx references all 8 sources from
     reference_bibliography.docx"
  ✓ GOOD (problem-level):
    "All sources cited in the bibliography are referenced in the body of the
     manuscript"

  ✗ BAD: "appendix_A.xlsx contains the orbital lifetime workings"
  ✓ GOOD: "Quantitative orbital lifetime calculations are provided as a
     verifiable supporting calculation"

  Drop file paths, section numbers, exact filenames. Abstract to the
  capability/property the deliverable should have.

**2. Use BOTH rubrics as inspiration; both reveal what matters.**

  If Rubric A asked about quantitative rigor and Rubric B asked about narrative
  quality, your merged rubric should ask about BOTH. Each rubric author saw
  one valid set of problem requirements; combine the unions of insight.

**3. Drop items that ONLY make sense if the deliverable took a specific approach.**

  If Rubric A has "the v2 draft addresses my Jan 9 feedback re: paragraph length"
  and a different deliverable might take a wholly different approach, re-author
  to: "the deliverable substantively incorporates the corrections raised during
  interaction".

**4. Dedup paraphrases.**

  Same problem requirement worded differently across the two rubrics → keep one
  clearer wording.

**5. Source field MUST reflect WHERE the requirement comes from:**
   - `spec`: from the deliverable specification (above)
   - `reference`: from the reference files / data the evaluator provided
   - `interaction`: from corrections / requirements / agreements during the month
   - `expertise`: from domain best practices for this kind of work
   - `quality`: general professional polish (clarity, completeness, accuracy)

**6. Weight items meaningfully.**
   `points_possible` is integer; typical 1-5. Critical correctness items get
   higher weight. Aim for total 100-220 pts.

═══════════════════════════════════════════════════════════════════

## OUTPUT

Write a single JSON file at this EXACT path (relative to your cwd):

    {output_filename}

Schema:

```json
{{
  "deliverable_id": "{dlv_id}",
  "evaluator_id": "{evaluator_id}",
  "evaluator_name": "{evaluator_name}",
  "total_possible": <sum of points_possible>,
  "items": [
    {{
      "criterion": "<problem-level statement, deliverable-agnostic>",
      "source": "<spec|reference|interaction|expertise|quality>",
      "points_possible": <int>
    }},
    ...
  ]
}}
```

`total_possible` MUST equal sum of `points_possible` across items.

After writing, respond ONE line: "Merged {dlv_id}: <N> items, <total> pts".
"""


async def merge_one(
    sem: asyncio.Semaphore,
    world_id: str,
    pid: str,
    dlv_id: str,
    baseline_eval: dict,
    v3_eval: dict,
    objectives: dict,
    npcs: list[dict],
    npc_interaction_logs: dict,
    eval_model: str,
    log: callable,
    work_cwd: str,
):
    # Write merged rubric inside the world dir (path guard allows it)
    out_filename = f"merged_rubric_{pid}_{dlv_id}.json"
    out_path = os.path.join(work_cwd, out_filename)
    if os.path.exists(out_path):
        log(f"  SKIP {pid} {dlv_id} (already merged)")
        try: return _read_json(out_path)
        except: return None

    rubric_a = filter_usable(baseline_eval.get("items", []))
    rubric_b = filter_usable(v3_eval.get("items", []))
    if not rubric_a and not rubric_b:
        log(f"  WARN {pid} {dlv_id}: both rubrics empty — skipping")
        return None
    if not rubric_a or not rubric_b:
        log(f"  WARN {pid} {dlv_id}: only one side has usable rubric (a={len(rubric_a)},b={len(rubric_b)}) — skipping merge")
        return None

    deliverable = next((d for d in objectives.get("deliverables", []) if d.get("id") == dlv_id), {})

    # Find evaluator NPC for name lookup
    evaluator_npc = next((p for p in npcs if p.get("id") == pid), {})
    evaluator_name = evaluator_npc.get("name") or baseline_eval.get("evaluator_name") or "Evaluator"

    # Reference files: external_refs/{pid}/ in the work_cwd (use baseline's; identical between sides)
    ref_paths = []
    ref_dir = os.path.join(work_cwd, "external_refs", pid)
    if os.path.isdir(ref_dir):
        for fn in sorted(os.listdir(ref_dir)):
            fp = os.path.join(ref_dir, fn)
            if os.path.isfile(fp):
                ref_paths.append(os.path.relpath(fp, work_cwd).replace("\\", "/"))

    interaction = npc_interaction_logs.get(pid, [])

    # Output written inside work_cwd — relative path is just the filename
    rel_out = out_filename

    prompt = build_merge_prompt(
        evaluator_name=evaluator_name,
        evaluator_id=pid,
        deliverable=deliverable,
        interaction_history=interaction,
        reference_file_paths=ref_paths,
        rubric_a=rubric_a,
        rubric_b=rubric_b,
        output_filename=rel_out,
    )

    async with sem:
        log(f"  -> merging {pid} {dlv_id} (a={len(rubric_a)}, b={len(rubric_b)} items)")
        try:
            await call_claude(prompt, cwd=work_cwd, max_turns=30, model=eval_model,
                              step_label=f"merge_{dlv_id}_{pid}")
        except Exception as e:
            log(f"  FAIL {pid} {dlv_id}: {type(e).__name__}: {e}")
            return None

    if not os.path.exists(out_path):
        log(f"  WARN {pid} {dlv_id}: no output written")
        return None
    try:
        m = _read_json(out_path)
        n = len(m.get("items", []))
        pts = m.get("total_possible", 0)
        log(f"  OK {pid} {dlv_id}: {n} items, {pts} pts")
        return m
    except Exception as e:
        log(f"  WARN {pid} {dlv_id}: bad merged JSON: {e}")
        return None


async def merge_world(
    sem: asyncio.Semaphore,
    baseline_world: str,
    v3_world: str,
    eval_model: str,
):
    wid = os.path.basename(v3_world)
    log = lambda m: print(f"[{wid}] {m}", flush=True)

    obj = _read_json(os.path.join(v3_world, "monthly_objectives.json"))
    npcs = _read_json(os.path.join(v3_world, "npcs.json")) if os.path.exists(os.path.join(v3_world, "npcs.json")) else []
    intlog_path = os.path.join(v3_world, "npc_interaction_logs.json")
    interaction_logs = _read_json(intlog_path) if os.path.exists(intlog_path) else {}

    base_evals = {(pid, dlv_id): data for pid, dlv_id, data in find_eval_files(baseline_world)}
    v3_evals   = {(pid, dlv_id): data for pid, dlv_id, data in find_eval_files(v3_world)}
    common_keys = sorted(set(base_evals) & set(v3_evals))

    if not common_keys:
        log("no common (pid, dlv_id) pairs — skipping")
        return

    log(f"merging {len(common_keys)} deliverables")
    tasks = [
        merge_one(sem, wid, pid, dlv_id,
                  base_evals[(pid, dlv_id)], v3_evals[(pid, dlv_id)],
                  obj, npcs, interaction_logs,
                  eval_model, log,
                  work_cwd=v3_world)
        for pid, dlv_id in common_keys
    ]
    await asyncio.gather(*tasks)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--v3", required=True)
    ap.add_argument("--model", default="claude-opus-4-7")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--worlds", default="")
    ap.add_argument("--prefix", default="win_world_")
    args = ap.parse_args()

    v3_worlds = sorted(glob.glob(os.path.join(args.v3, f"{args.prefix}*")))
    if args.worlds:
        wanted = set(args.worlds.split(","))
        v3_worlds = [w for w in v3_worlds if os.path.basename(w) in wanted]

    sem = asyncio.Semaphore(args.concurrency)
    print(f"Merging {len(v3_worlds)} worlds, concurrency={args.concurrency}, model={args.model}")
    print(f"  baseline: {args.baseline}\n  v3:       {args.v3}")
    print(f"  output:   merged_rubric_*.json inside each v3 world dir")

    coros = []
    for v3w in v3_worlds:
        wid = os.path.basename(v3w)
        bw = os.path.join(args.baseline, wid)
        if not os.path.isdir(bw):
            print(f"[{wid}] no baseline counterpart — skipping")
            continue
        coros.append(merge_world(sem, bw, v3w, args.model))
    await asyncio.gather(*coros)
    print("All worlds processed.")


if __name__ == "__main__":
    asyncio.run(main())

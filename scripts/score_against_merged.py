"""Score deliverables against merged rubrics.

For each (world, deliverable) where a merged rubric exists in skill-worlds-v3,
score the SAME deliverable on both sides (baseline-worlds and skill-worlds-v3)
using that merged rubric, with the rubric items frozen.

Output:
    {target}/{world}/evaluation_{pid}_{dlv}_merged.json     — per deliverable
    {target}/{world}/evaluation_summary_merged.json         — per world (aggregate)

Usage:
    uv run python scripts/score_against_merged.py \\
        --rubric-source skill-worlds-v3 \\
        --target baseline-worlds \\
        --eval-model claude-opus-4-7 --concurrency 6 \\
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
from scripts.rescore_against_baseline import _resolve_deliverable, build_score_only_prompt


def find_merged_rubrics(world_dir: str):
    """Yield (pid, dlv_id, merged_data) for each merged_rubric_*.json file."""
    for p in sorted(glob.glob(os.path.join(world_dir, "merged_rubric_*.json"))):
        name = os.path.basename(p)  # merged_rubric_{pid}_{dlv}.json
        stem = name[len("merged_rubric_"):-len(".json")]
        if "_dlv_" not in stem: continue
        pid, dlv_tail = stem.rsplit("_dlv_", 1)
        dlv_id = "dlv_" + dlv_tail
        try: data = _read_json(p)
        except Exception: continue
        yield pid, dlv_id, data


async def score_one(
    sem: asyncio.Semaphore,
    target_world: str,
    pid: str,
    dlv_id: str,
    merged_rubric: dict,
    objectives: dict,
    eval_model: str,
    log: callable,
):
    out_filename = f"evaluation_{pid}_{dlv_id}_merged.json"
    out_path = os.path.join(target_world, out_filename)
    if os.path.exists(out_path):
        log(f"  SKIP (already scored) {os.path.basename(target_world)} {pid} {dlv_id}")
        return _read_json(out_path)

    dlv_obj = next((d for d in objectives.get("deliverables", []) if d.get("id") == dlv_id), {})
    deliv_paths = {}
    for path in dlv_obj.get("output_files", []):
        rel = _resolve_deliverable(target_world, path)
        if rel: deliv_paths[path] = rel

    ref_paths = []
    ref_dir = os.path.join(target_world, "external_refs", pid)
    if os.path.isdir(ref_dir):
        for fn in sorted(os.listdir(ref_dir)):
            fp = os.path.join(ref_dir, fn)
            if os.path.isfile(fp):
                ref_paths.append(os.path.relpath(fp, target_world).replace("\\", "/"))

    items = merged_rubric.get("items", [])
    items = [it for it in items if it.get("criterion") and it.get("points_possible", 0) > 0]
    if not items:
        log(f"  WARN no usable items in merged rubric for {pid} {dlv_id}")
        return None

    prompt = build_score_only_prompt(
        evaluator_name=merged_rubric.get("evaluator_name", "Evaluator"),
        evaluator_id=pid,
        deliverable_id=dlv_id,
        deliverable_title=dlv_obj.get("title", ""),
        deliverable_files=deliv_paths,
        reference_files=ref_paths,
        rubric_items=items,
        output_filename=out_filename,
    )

    async with sem:
        log(f"  -> scoring {os.path.basename(target_world)} {pid} {dlv_id} ({len(items)} items)")
        try:
            await call_claude(prompt, cwd=target_world, max_turns=40,
                              model=eval_model, step_label=f"merged_score_{dlv_id}_{pid}")
        except Exception as e:
            log(f"  FAIL {pid} {dlv_id}: {type(e).__name__}: {e}")
            return None

    if not os.path.exists(out_path):
        log(f"  WARN no output for {pid} {dlv_id}")
        return None
    try:
        result = _read_json(out_path)
        log(f"  OK {os.path.basename(target_world)} {pid} {dlv_id}: {result.get('percentage','?')}%")
        return result
    except Exception as e:
        log(f"  WARN bad JSON: {e}")
        return None


async def score_world(sem, rubric_world, target_world, eval_model):
    wid = os.path.basename(target_world)
    log = lambda m: print(f"[{wid}/{os.path.basename(target_world.rstrip('/').rsplit('/',2)[0])}] {m}", flush=True)

    obj_path = os.path.join(target_world, "monthly_objectives.json")
    if not os.path.exists(obj_path):
        log("no monthly_objectives.json — skipping"); return
    obj = _read_json(obj_path)

    rubrics = list(find_merged_rubrics(rubric_world))
    if not rubrics:
        log("no merged rubrics found — skipping"); return

    tasks = [score_one(sem, target_world, pid, dlv, data, obj, eval_model, log)
             for pid, dlv, data in rubrics]
    results = await asyncio.gather(*tasks)
    results = [r for r in results if r]

    if results:
        summary = os.path.join(target_world, "evaluation_summary_merged.json")
        with open(summary, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        # Truth aggregate from item sums
        p = sum(sum(i.get("points_possible",0) for i in r.get("items",[])) for r in results)
        e = sum(sum(i.get("points_earned",0) for i in r.get("items",[])) for r in results)
        pct = round(100*e/p,1) if p else 0
        log(f"DONE: {len(results)} dlv, {e}/{p} = {pct}%")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rubric-source", required=True,
                    help="dir containing worlds with merged_rubric_*.json files (typically skill-worlds-v3)")
    ap.add_argument("--target", required=True,
                    help="dir whose deliverables to score (baseline-worlds or skill-worlds-v3)")
    ap.add_argument("--eval-model", default="claude-opus-4-7")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--worlds", default="")
    ap.add_argument("--prefix", default="win_world_")
    args = ap.parse_args()

    src_worlds = sorted(glob.glob(os.path.join(args.rubric_source, f"{args.prefix}*")))
    if args.worlds:
        wanted = set(args.worlds.split(","))
        src_worlds = [w for w in src_worlds if os.path.basename(w) in wanted]

    sem = asyncio.Semaphore(args.concurrency)
    print(f"Scoring {len(src_worlds)} worlds, target={args.target}, concurrency={args.concurrency}, model={args.eval_model}")

    coros = []
    for sw in src_worlds:
        wid = os.path.basename(sw)
        tw = os.path.join(args.target, wid)
        if not os.path.isdir(tw):
            print(f"[{wid}] no target counterpart in {args.target} — skipping")
            continue
        coros.append(score_world(sem, sw, tw, args.eval_model))
    await asyncio.gather(*coros)
    print("All worlds processed.")


if __name__ == "__main__":
    asyncio.run(main())

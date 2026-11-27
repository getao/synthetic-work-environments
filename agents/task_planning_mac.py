"""Task Planning agent — Step 6 + Step 6.5 (macOS flavor).

Plans the monthly work simulation:
  Step 6:   Monthly objectives, deliverables, external NPCs
  Step 6.5: Generate external NPC reference files + workspace prerequisites
"""

import os

from agents.common import (
    call_claude,
    _read_json,
    _logical_to_physical_mac,
    _build_user_summary,
    _cleanup_stray_files,
    UsageTracker,
)
from agents.task_planning_prompts_mac import (
    build_monthly_objectives_prompt,
    build_ref_files_prompt,
    build_workspace_prereqs_prompt,
)


async def run_task_planning_mac(
    world_dir: str,
    profile: dict,
    start_date: str,
    plugins: list | None,
    model: str | None,
    log_file: str,
    turn_log_file: str,
    tracker: UsageTracker,
    log_fn: callable,
    real_world_context: str = "",
) -> tuple[dict, list]:
    """Run Steps 6 and 6.5 for the macOS flavor.

    Returns:
        (objectives, npcs) — the monthly objectives dict and the list
        of external NPCs (with rubrics intact).
    """
    log = log_fn
    user_summary = _build_user_summary(profile)

    # ==================================================================
    # Step 6: Monthly Objectives + External NPCs
    # ==================================================================
    objectives_path = os.path.join(world_dir, "monthly_objectives.json")
    external_ctx_path = os.path.join(world_dir, "external_context.json")

    if os.path.exists(objectives_path) and os.path.exists(external_ctx_path):
        log("Step 6: RESUME — monthly_objectives.json and external_context.json already exist.")
        objectives = _read_json(objectives_path)
        external_context = _read_json(external_ctx_path)
    else:
        log("Step 6: Planning monthly objectives and external NPCs...")
        prompt = build_monthly_objectives_prompt(
            start_date=start_date,
            real_world_context=real_world_context,
        )
        tracker.accumulate(await call_claude(
            prompt, cwd=world_dir, max_turns=30, plugins=plugins,
            model=model, log_file=log_file, turn_log_file=turn_log_file,
            step_label="step6_monthly_objectives",
            os_flavor="macos",
        ))

        if not os.path.exists(objectives_path):
            raise RuntimeError("Step 6 failed: monthly_objectives.json was not created")
        if not os.path.exists(external_ctx_path):
            raise RuntimeError("Step 6 failed: external_context.json was not created")

        objectives = _read_json(objectives_path)
        external_context = _read_json(external_ctx_path)
        dlv_count = len(objectives.get("deliverables", []))
        npc_count = len(
            external_context.get("external_npcs", external_context.get("external_personas", []))
        )
        log(f"Step 6 done: {dlv_count} deliverables, {npc_count} external NPCs.")

    # Validate: every deliverable must have an evaluator NPC with a rubric
    deliverable_ids = {d["id"] for d in objectives.get("deliverables", [])}
    npcs = external_context.get("external_npcs", external_context.get("external_personas", []))
    # Count rubric coverage per deliverable_id (must be exactly 1 each)
    dlv_rubric_count: dict[str, list[str]] = {}
    orphan_rubrics: list[str] = []
    for p in npcs:
        rubric = p.get("rubric")
        if not rubric:
            continue
        did = rubric.get("deliverable_id")
        if not did:
            continue
        if did not in deliverable_ids:
            orphan_rubrics.append(f"{p.get('id', '?')}→{did}")
            continue
        dlv_rubric_count.setdefault(did, []).append(p.get("id", "?"))

    uncovered = sorted(deliverable_ids - set(dlv_rubric_count.keys()))
    over_covered = {did: ids for did, ids in dlv_rubric_count.items() if len(ids) > 1}

    if uncovered or over_covered or orphan_rubrics:
        msg_lines = ["Step 6 rubric coverage check FAILED:"]
        if uncovered:
            msg_lines.append(f"  Missing rubric for: {uncovered}")
        if over_covered:
            for did, ids in over_covered.items():
                msg_lines.append(f"  Duplicate rubric on {did}: NPCs {ids}")
        if orphan_rubrics:
            msg_lines.append(f"  Rubrics pointing to non-existent deliverables: {orphan_rubrics}")
        msg = "\n".join(msg_lines)
        log(msg)
        for f in ("monthly_objectives.json", "external_context.json", "context_seeds.json"):
            p = os.path.join(world_dir, f)
            if os.path.exists(p):
                os.remove(p)
                log(f"  removed {f} so next run will retry Step 6")
        raise RuntimeError(msg)

    # ==================================================================
    # Step 6.5: Generate External NPC Reference Files
    # ==================================================================
    external_refs_dir = os.path.join(world_dir, "external_refs")
    os.makedirs(external_refs_dir, exist_ok=True)

    # Safety net: if the LLM forgot to include the required `id` field on any
    # NPC, auto-assign one. Without this, multiple NPCs collide on the same
    # external_refs/unknown/ directory and ref files overwrite each other.
    _seen_ids: set[str] = set()
    for idx, npc_entry in enumerate(npcs):
        nid = npc_entry.get("id")
        if not nid or nid in _seen_ids:
            auto = f"ext_auto_{idx:03d}"
            log_fn(
                f"Step 6.5: WARNING — NPC[{idx}] "
                f"(name={npc_entry.get('name', '?')!r}) had missing/duplicate id "
                f"{nid!r}; auto-assigning {auto!r}"
            )
            npc_entry["id"] = auto
            nid = auto
        _seen_ids.add(nid)

    for npc_entry in npcs:
        npc_id = npc_entry.get("id", "unknown")
        npc_dir = os.path.join(external_refs_dir, npc_id)
        ref_files = npc_entry.get("reference_files", [])

        if not ref_files:
            continue

        expected_files = [rf.get("filename", "") for rf in ref_files]
        existing_count = sum(
            1 for fn in expected_files
            if os.path.exists(os.path.join(npc_dir, fn))
        )

        if existing_count == len(expected_files) and existing_count > 0:
            log(f"Step 6.5: RESUME — {npc_id} reference files already exist ({existing_count} files).")
            continue

        os.makedirs(npc_dir, exist_ok=True)
        log(f"Step 6.5: Generating reference files for {npc_id} ({len(ref_files)} files)...")

        prompt = build_ref_files_prompt(
            npc_entry=npc_entry,
            user_profile_summary=user_summary,
            real_world_context=real_world_context,
        )
        tracker.accumulate(await call_claude(
            prompt, cwd=world_dir, max_turns=200, plugins=plugins,
            model=model, log_file=log_file, turn_log_file=turn_log_file,
            step_label=f"step6.5_ref_{npc_id}",
            os_flavor="macos",
        ))
        _cleanup_stray_files(world_dir, log_fn=log)

        generated_count = sum(
            1 for fn in expected_files
            if os.path.exists(os.path.join(npc_dir, fn))
        )
        log(f"Step 6.5: {npc_id} done. {generated_count}/{len(expected_files)} files generated.")

    # Generate workspace prerequisites
    context_seeds_path = os.path.join(world_dir, "context_seeds.json")
    if os.path.exists(context_seeds_path):
        context_seeds = _read_json(context_seeds_path)
        prereqs = context_seeds.get("workspace_prerequisites", [])
        if prereqs:
            prereqs_done = all(
                os.path.exists(_logical_to_physical_mac(world_dir, p["path"]))
                for p in prereqs
                if _logical_to_physical_mac(world_dir, p["path"])
            )
            if prereqs_done:
                log("Step 6.5: RESUME — workspace prerequisite files already exist.")
            else:
                log(f"Step 6.5: Generating {len(prereqs)} workspace prerequisite files...")
                prompt = build_workspace_prereqs_prompt(
                    prerequisites=prereqs,
                    user_profile_summary=user_summary,
                )
                tracker.accumulate(await call_claude(
                    prompt, cwd=world_dir, max_turns=200, plugins=plugins,
                    model=model, log_file=log_file, turn_log_file=turn_log_file,
                    step_label="step6.5_workspace_prereqs",
                    os_flavor="macos",
                ))
                _cleanup_stray_files(world_dir, log_fn=log)
                log("Step 6.5: Workspace prerequisite files done.")

    log("Step 6.5 complete: all reference files and prerequisites generated.")

    return objectives, npcs

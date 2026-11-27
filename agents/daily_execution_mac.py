"""Daily Execution agent — Steps 7-9 (macOS flavor).

Executes the monthly work simulation:
  Step 7: Weekly planning (per week)
  Step 8: Daily file generation with NPC interactions (per day)
  Step 9: Deliverable evaluation
"""

import glob
import json
import os
import time
from datetime import datetime

from agents.common import (
    call_claude,
    _read_json,
    _read_jsonl,
    _ensure_dependencies,
    _build_user_summary,
    _logical_to_physical_mac,
    _verify_batch,
    _cleanup_stray_files,
    setup_world_claude_md,
    UsageTracker,
)
from agents.task_planning_mac import run_task_planning_mac
from agents.task_planning_prompts_mac import strip_npcs_for_main_agent
from agents.daily_execution_prompts_mac import (
    build_weekly_plan_prompt,
    build_daily_file_generation_prompt,
    build_evaluation_prompt,
)
from agents.npc_runner import run_npc_responses


async def daily_simulate_mac(
    world_dir: str,
    start_date: str | None = None,
    num_weeks: int = 4,
    plugins: list | None = None,
    model: str | None = None,
    eval_model: str | None = None,
    use_occupation_skills: bool = False,
    real_world_context: str = "",
    plan_only: bool = False,
) -> str:
    """Run the Daily Simulation pipeline on an existing macOS Cold Start world.

    Steps:
        6   — Monthly objectives + external NPCs planning
        6.5 — Generate external NPC reference files + workspace prerequisites
        7   — Weekly day-by-day planning (per week)
        8   — Daily file generation (per day)
        9   — Deliverable evaluation

    Returns the world directory path.
    """
    world_dir = os.path.abspath(world_dir)
    world_id = os.path.basename(world_dir)
    log_file = os.path.join(world_dir, "daily_sim_output.log")
    turn_log_file = os.path.join(world_dir, "daily_sim_turns.jsonl")

    tag = f"[{world_id}]"
    t0 = time.monotonic()

    def log(msg: str):
        elapsed = time.monotonic() - t0
        m, s = divmod(int(elapsed), 60)
        print(f"{tag} [{m:02d}:{s:02d}] {msg}", flush=True)

    # Ensure .claude/ with workspace CLAUDE.md exists (macOS variant)
    setup_world_claude_md(world_dir, os_flavor="macos")

    # Validate Cold Start is complete
    if not os.path.exists(os.path.join(world_dir, "_complete")):
        raise RuntimeError(f"World {world_dir} has not completed Cold Start.")

    profile = _read_json(os.path.join(world_dir, "user_profile.json"))
    user_summary = _build_user_summary(profile)

    # If occupation-skills hint is on, scan world's .claude/skills/
    occupation_skills_list: list[str] = []
    if use_occupation_skills:
        BASE_SKILLS = {
            "minimax-docx", "minimax-pdf", "minimax-xlsx", "pptx-generator",
        }
        skills_dir = os.path.join(world_dir, ".claude", "skills")
        if os.path.isdir(skills_dir):
            occupation_skills_list = sorted(
                d for d in os.listdir(skills_dir)
                if d not in BASE_SKILLS
                and os.path.isdir(os.path.join(skills_dir, d))
            )

    if start_date is None:
        start_date = datetime.now().strftime("%Y-%m-%d")

    log(f"Daily Simulation (macOS) started. start_date={start_date}, weeks={num_weeks}")

    await _ensure_dependencies(world_dir, log_fn=log)

    tracker = UsageTracker(world_dir, "daily_sim_usage.json", "daily_sim_", t0)

    # ==================================================================
    # Steps 6 + 6.5: Task Planning (delegated)
    # ==================================================================
    objectives, npcs = await run_task_planning_mac(
        world_dir=world_dir,
        profile=profile,
        start_date=start_date,
        plugins=plugins,
        model=model,
        log_file=log_file,
        turn_log_file=turn_log_file,
        tracker=tracker,
        log_fn=log,
        real_world_context=real_world_context,
    )

    if plan_only:
        tracker.save()
        log("--plan-only: stopping after Step 6.5.")
        return world_dir

    # ==================================================================
    # Setup shared folders
    # ==================================================================
    external_share_dir = os.path.join(world_dir, "external_share")
    drives_share_dir = os.path.join(world_dir, "drives", "share")
    os.makedirs(external_share_dir, exist_ok=True)
    os.makedirs(drives_share_dir, exist_ok=True)
    for p in npcs:
        pid = p.get("id", "unknown")
        os.makedirs(os.path.join(external_share_dir, pid), exist_ok=True)

    intlog_path = os.path.join(world_dir, "npc_interaction_logs.json")
    legacy_intlog_path = os.path.join(world_dir, "persona_interaction_logs.json")
    if os.path.exists(intlog_path):
        npc_interaction_logs: dict[str, list[dict]] = _read_json(intlog_path)
    elif os.path.exists(legacy_intlog_path):
        npc_interaction_logs: dict[str, list[dict]] = _read_json(legacy_intlog_path)
    else:
        npc_interaction_logs: dict[str, list[dict]] = {
            p.get("id", "unknown"): [] for p in npcs
        }

    def _global_day(wk: int, idx: int) -> int:
        return (wk - 1) * 5 + idx + 1

    # ==================================================================
    # Steps 7–8: Weekly Planning + Daily Execution
    # ==================================================================
    objectives_json = json.dumps(objectives, indent=2, ensure_ascii=False)
    npcs_for_main = strip_npcs_for_main_agent(npcs)

    for week_num in range(1, num_weeks + 1):
        week_plan_path = os.path.join(world_dir, f"week_{week_num}_plan.json")

        # --- Step 7: Weekly Planning ---
        if os.path.exists(week_plan_path):
            log(f"Step 7 (Week {week_num}): RESUME — plan already exists.")
            week_plan = _read_json(week_plan_path)
        else:
            log(f"Step 7 (Week {week_num}): Main agent planning week...")

            prompt = build_weekly_plan_prompt(
                objectives_json=objectives_json,
                external_npcs_json=json.dumps(
                    npcs_for_main, indent=2, ensure_ascii=False,
                ),
                week_num=week_num,
                user_profile_summary=user_summary,
                real_world_context=real_world_context,
                use_occupation_skills=use_occupation_skills,
                occupation_skills=occupation_skills_list,
            )
            tracker.accumulate(await call_claude(
                prompt, cwd=world_dir, max_turns=30, plugins=plugins,
                model=model, log_file=log_file, turn_log_file=turn_log_file,
                step_label=f"step7_week{week_num}_plan",
                os_flavor="macos",
            ))

            if not os.path.exists(week_plan_path):
                raise RuntimeError(f"Step 7 failed: week_{week_num}_plan.json was not created")

            week_plan = _read_json(week_plan_path)
            day_count = len(week_plan.get("days", []))
            log(f"Step 7 (Week {week_num}): done. {day_count} days planned.")

        # --- Step 8: Daily Execution ---
        days = week_plan.get("days", [])
        for day_idx, day_plan in enumerate(days):
            day_date = day_plan.get("date", f"week{week_num}_day{day_idx}")
            day_num = _global_day(week_num, day_idx)
            activities = day_plan.get("activities", [])

            day_marker = os.path.join(world_dir, f"_day{day_num}_complete")
            if os.path.exists(day_marker):
                log(f"Step 8 (Week {week_num}, Day {day_num}, {day_date}): RESUME — already complete.")
                continue

            file_count = sum(
                len(a.get("files_to_create", [])) + len(a.get("files_to_modify", []))
                for a in activities
            )
            log(f"Step 8 (Week {week_num}, Day {day_num}, {day_date}): "
                f"{file_count} files + {len(activities)} activities...")

            # Create directories for new files
            for act in activities:
                for path in act.get("files_to_create", []):
                    physical = _logical_to_physical_mac(world_dir, path)
                    if physical:
                        os.makedirs(os.path.dirname(physical), exist_ok=True)

            ext_npc_context = json.dumps(
                npcs_for_main, indent=2, ensure_ascii=False,
            )

            prompt = build_daily_file_generation_prompt(
                day_plan=day_plan,
                user_profile_summary=user_summary,
                world_root=world_dir,
                external_npcs_context=ext_npc_context,
                real_world_context=real_world_context,
                day_num=day_num,
                use_occupation_skills=use_occupation_skills,
                occupation_skills=occupation_skills_list,
            )

            # Clean up stale outreach files from previous failed runs
            stale_pattern = os.path.join(world_dir, f"npc_outreach_day{day_num}_*_r*.json")
            for stale in glob.glob(stale_pattern):
                os.remove(stale)

            # Phase 1: Main agent
            tracker.accumulate(await call_claude(
                prompt, cwd=world_dir, max_turns=500, plugins=plugins,
                model=model,
                log_file=log_file, turn_log_file=turn_log_file,
                step_label=f"step8_week{week_num}_day{day_idx}_{day_date}",
                os_flavor="macos",
            ))
            _cleanup_stray_files(world_dir, log_fn=log)

            # Phase 2: NPC responses
            await run_npc_responses(
                world_dir=world_dir,
                day_num=day_num,
                day_date=day_date,
                npcs=npcs,
                npc_interaction_logs=npc_interaction_logs,
                drives_share_dir=drives_share_dir,
                external_share_dir=external_share_dir,
                plugins=plugins,
                model=model,
                log_file=log_file,
                turn_log_file=turn_log_file,
                tracker=tracker,
                log_fn=log,
                os_flavor="macos",
            )

            # Post-day bookkeeping
            created_paths = []
            for act in activities:
                for path in act.get("files_to_create", []):
                    created_paths.append({"path": path})
            if created_paths:
                missing = _verify_batch(world_dir, created_paths, log_fn=log)
                if missing:
                    log(f"  WARNING: {len(missing)} files missing on {day_date}.")

            current_file_list = _read_json(os.path.join(world_dir, "file_list.json"))
            existing_paths = {e["path"] for e in current_file_list}
            for act in activities:
                for path in act.get("files_to_create", []):
                    if path not in existing_paths:
                        current_file_list.append({
                            "path": path,
                            "timestamp": f"{day_date}T{act.get('time', '09:00')}:00",
                            "origin": "user_created",
                            "description": act.get("description", ""),
                            "content_mode": "generate",
                            "content_scale": "medium",
                            "project_ids": [act["deliverable_id"]] if act.get("deliverable_id") else [],
                            "content_generated": True,
                        })
                        existing_paths.add(path)
            fl_path = os.path.join(world_dir, "file_list.json")
            with open(fl_path, "w", encoding="utf-8") as f:
                json.dump(current_file_list, f, indent=2, ensure_ascii=False)

            intlog_path = os.path.join(world_dir, "npc_interaction_logs.json")
            with open(intlog_path, "w", encoding="utf-8") as f:
                json.dump(npc_interaction_logs, f, indent=2, ensure_ascii=False)

            with open(day_marker, "w") as f:
                f.write(datetime.now().isoformat() + "\n")
            log(f"Step 8 (Week {week_num}, Day {day_num}, {day_date}): done.")

        log(f"Week {week_num} complete.")

    # ==================================================================
    # Step 9: Deliverable Evaluation
    # ==================================================================
    log("Step 9: Evaluating deliverables...")
    deliverables = objectives.get("deliverables", [])
    evaluation_results = []

    for dlv in deliverables:
        dlv_id = dlv.get("id", "unknown")

        evaluator_npc = None
        for p in npcs:
            rubric = p.get("rubric", {})
            if rubric and rubric.get("deliverable_id") == dlv_id:
                evaluator_npc = p
                break

        if not evaluator_npc:
            log(f"  Step 9: No evaluator found for {dlv_id} — skipping.")
            continue

        eval_pid = evaluator_npc.get("id", "unknown")
        eval_name = evaluator_npc.get("name", "Unknown")

        eval_file = os.path.join(world_dir, f"evaluation_{eval_pid}_{dlv_id}.json")
        if os.path.exists(eval_file):
            eval_data = _read_json(eval_file)
            evaluation_results.append(eval_data)
            pct = eval_data.get("percentage", "?")
            log(f"  Step 9: RESUME — {eval_name} already scored {dlv_id}: {pct}%")
            continue

        log(f"  Step 9: {eval_name} evaluating {dlv_id}...")

        deliv_file_paths = {}
        for path in dlv.get("output_files", []):
            physical = _logical_to_physical_mac(world_dir, path)
            if physical and os.path.exists(physical):
                rel = os.path.relpath(physical, world_dir).replace("\\", "/")
                deliv_file_paths[path] = rel

        ref_file_paths = []
        eval_ref_dir = os.path.join(world_dir, "external_refs", eval_pid)
        if os.path.isdir(eval_ref_dir):
            for fn in os.listdir(eval_ref_dir):
                fpath = os.path.join(eval_ref_dir, fn)
                if os.path.isfile(fpath):
                    rel = os.path.relpath(fpath, world_dir).replace("\\", "/")
                    ref_file_paths.append(rel)

        prompt = build_evaluation_prompt(
            npc=evaluator_npc,
            deliverable=dlv,
            interaction_history=npc_interaction_logs.get(eval_pid, []),
            deliverable_file_paths=deliv_file_paths,
            reference_file_paths=ref_file_paths,
        )
        try:
            result = await call_claude(
                prompt, cwd=world_dir, max_turns=30, plugins=plugins,
                model=(eval_model or model),
                log_file=log_file, turn_log_file=turn_log_file,
                step_label=f"step9_eval_{dlv_id}_{eval_pid}",
                os_flavor="macos",
            )
            tracker.accumulate(result)
        except Exception as e:
            log(f"  Step 9: {eval_name} FAILED on {dlv_id}: {type(e).__name__}: {e}")
            continue

        eval_file = os.path.join(world_dir, f"evaluation_{eval_pid}_{dlv_id}.json")
        if os.path.exists(eval_file):
            eval_data = _read_json(eval_file)
            evaluation_results.append(eval_data)
            pct = eval_data.get("percentage", "?")
            log(f"  Step 9: {eval_name} scored {dlv_id}: {pct}%")
        else:
            log(f"  Step 9: WARNING — evaluation file not created for {dlv_id}.")

    if evaluation_results:
        eval_summary_path = os.path.join(world_dir, "evaluation_summary.json")
        with open(eval_summary_path, "w", encoding="utf-8") as f:
            json.dump(evaluation_results, f, indent=2, ensure_ascii=False)

    tracker.save()

    final_file_list = _read_json(os.path.join(world_dir, "file_list.json"))
    activity_count = len(_read_jsonl(
        os.path.join(world_dir, "daily_activity_log.jsonl")
    ))

    with open(os.path.join(world_dir, "_daily_sim_complete"), "w") as f:
        f.write(datetime.now().isoformat() + "\n")

    log(
        f"DAILY SIM COMPLETE: {len(final_file_list)} total files, "
        f"{activity_count} activities. "
        f"Cost: ${tracker.total_cost_usd:.4f}, turns: {tracker.total_turns}, {tracker.usage_str()}"
    )

    return world_dir

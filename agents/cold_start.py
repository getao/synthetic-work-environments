"""Cold Start agent — Steps 1-5.

Generates a complete simulated PC filesystem from a persona description:
  Step 1: Persona → User Profile
  Step 2: User Profile → Filesystem Policy
  Step 3: Joint Planning (project index, file list, file graph)
  Step 4: Create directory structure
  Step 5: Generate file contents (batched)
"""

import json
import os
import random
import time
import uuid
from datetime import datetime, timedelta

from agents.common import (
    call_claude,
    _read_json,
    _ensure_dependencies,
    _build_user_summary,
    _logical_to_physical,
    _verify_batch,
    _get_relevant_edges,
    _cleanup_stray_files,
    setup_world_claude_md,
    UsageTracker,
)
from agents.cold_start_prompts import (
    build_user_profile_prompt,
    build_filesystem_policy_prompt,
    build_planning_prompt,
    build_file_generation_prompt,
)


# ---------------------------------------------------------------------------
# Cold-start-only helpers
# ---------------------------------------------------------------------------

def _validate_user_profile(world_dir: str) -> dict:
    path = os.path.join(world_dir, "user_profile.json")
    if not os.path.exists(path):
        raise RuntimeError("user_profile.json was not created")
    data = _read_json(path)
    for key in ("identity", "work_context", "filesystem_relevant_traits"):
        if key not in data:
            raise RuntimeError(f"user_profile.json missing required key: {key}")
    return data


def _validate_filesystem_policy(world_dir: str, current_ts: str) -> dict:
    path = os.path.join(world_dir, "filesystem_policy.json")
    if not os.path.exists(path):
        raise RuntimeError("filesystem_policy.json was not created")
    data = _read_json(path)
    if "system_start_timestamp" not in data:
        raise RuntimeError("filesystem_policy.json missing system_start_timestamp")
    start = data["system_start_timestamp"]
    if start >= current_ts:
        raise RuntimeError(
            f"system_start_timestamp ({start}) must be before current_timestamp ({current_ts})"
        )
    return data


def _validate_planning(world_dir: str, current_ts: str, system_start_ts: str) -> tuple[dict, list, dict]:
    # project_index.json
    pi_path = os.path.join(world_dir, "project_index.json")
    if not os.path.exists(pi_path):
        raise RuntimeError("project_index.json was not created")
    project_index = _read_json(pi_path)

    # file_list.json
    fl_path = os.path.join(world_dir, "file_list.json")
    if not os.path.exists(fl_path):
        raise RuntimeError("file_list.json was not created")
    file_list = _read_json(fl_path)

    # Validate only originally planned entries (not extracted files added at runtime)
    planned = [f for f in file_list if not f.get("derived_from")]
    if len(planned) > 100:
        raise RuntimeError(f"file_list has {len(planned)} planned files, exceeds 100 limit")

    # Soft-fix out-of-range timestamps instead of failing the whole run.
    # The LLM occasionally produces a timestamp a bit outside [system_start, current_ts];
    # clamping is cheaper than losing all of Steps 1-3.
    clamped_low = 0
    clamped_high = 0
    for entry in planned:
        ts = entry.get("timestamp", "")
        if not ts:
            continue
        if ts < system_start_ts:
            entry["timestamp"] = system_start_ts
            clamped_low += 1
        elif ts > current_ts:
            entry["timestamp"] = current_ts
            clamped_high += 1
    if clamped_low or clamped_high:
        # Persist the clamped values so downstream steps see the corrected list.
        with open(fl_path, "w", encoding="utf-8") as f:
            json.dump(file_list, f, indent=2, ensure_ascii=False)
        print(
            f"[validate_planning] clamped {clamped_low} timestamp(s) up to system_start "
            f"and {clamped_high} down to current_timestamp",
            flush=True,
        )

    # file_graph.json
    fg_path = os.path.join(world_dir, "file_graph.json")
    if not os.path.exists(fg_path):
        raise RuntimeError("file_graph.json was not created")
    file_graph = _read_json(fg_path)

    return project_index, file_list, file_graph


def _create_directories(world_dir: str, file_list: list[dict]) -> None:
    """Create all directories needed for the files in file_list."""
    drives_dir = os.path.join(world_dir, "drives")
    for entry in file_list:
        logical_path = entry["path"]  # e.g. "C:/Users/alice/Documents/file.docx"
        # Convert to physical: drives/C/Users/alice/Documents/file.docx
        parts = logical_path.split(":/", 1)
        if len(parts) != 2:
            continue
        drive_letter, rest = parts
        physical_path = os.path.join(drives_dir, drive_letter, rest)
        parent_dir = os.path.dirname(physical_path)
        os.makedirs(parent_dir, exist_ok=True)


def _batch_files(file_list: list[dict], batch_size: int = 3) -> list[list[dict]]:
    """Split sorted file list into batches."""
    sorted_files = sorted(file_list, key=lambda f: f["timestamp"])
    batches = []
    for i in range(0, len(sorted_files), batch_size):
        batches.append(sorted_files[i : i + batch_size])
    return batches


def _get_recent_activity_log(world_dir: str, n: int = 20) -> list[dict]:
    """Read the most recent n entries from activity_log.jsonl."""
    path = os.path.join(world_dir, "activity_log.jsonl")
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries[-n:]


def _mark_generated(world_dir: str, batch: list[dict]) -> None:
    """Mark files in file_list.json as content_generated=true."""
    fl_path = os.path.join(world_dir, "file_list.json")
    file_list = _read_json(fl_path)
    generated_paths = {entry["path"] for entry in batch}
    for entry in file_list:
        if entry["path"] in generated_paths:
            entry["content_generated"] = True
    with open(fl_path, "w", encoding="utf-8") as f:
        json.dump(file_list, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def cold_start(
    persona: str,
    current_timestamp: str | None = None,
    world_id: str | None = None,
    plugins: list | None = None,
    worlds_root: str = "worlds",
    max_generate: int | None = None,
    model: str | None = None,
) -> str:
    """Run the full Cold Start pipeline. Returns the world directory path.

    Args:
        max_generate: If set, only generate content for the first N files
                      (planning steps still produce the full file list).
        model: Claude model to use (e.g. "claude-sonnet-4-6"). Default: SDK default.
    """

    if current_timestamp is None:
        current_timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    if world_id is None:
        world_id = uuid.uuid4().hex[:12]

    world_dir = os.path.abspath(os.path.join(worlds_root, world_id))
    os.makedirs(world_dir, exist_ok=True)

    # Create .claude/ with workspace CLAUDE.md
    setup_world_claude_md(world_dir)

    # Save persona
    persona_path = os.path.join(world_dir, "persona.json")
    with open(persona_path, "w", encoding="utf-8") as f:
        json.dump({"persona": persona, "current_timestamp": current_timestamp}, f, indent=2, ensure_ascii=False)

    log_file = os.path.join(world_dir, "output.log")
    turn_log_file = os.path.join(world_dir, "turns.jsonl")
    tag = f"[{world_id}]"

    t0 = time.monotonic()

    def log(msg: str):
        elapsed = time.monotonic() - t0
        m, s = divmod(int(elapsed), 60)
        print(f"{tag} [{m:02d}:{s:02d}] {msg}", flush=True)

    log(f"Cold Start started. dir={world_dir} ts={current_timestamp}")

    # Pre-install common dependencies so subprocess sessions don't waste time
    await _ensure_dependencies(world_dir, log_fn=log)

    # Usage tracking
    tracker = UsageTracker(world_dir, "usage.json", "total_", t0)

    # ------------------------------------------------------------------
    # Check for resumable state
    # ------------------------------------------------------------------
    resuming = False
    planning_files = ["user_profile.json", "filesystem_policy.json",
                      "project_index.json", "file_list.json", "file_graph.json"]
    if all(os.path.exists(os.path.join(world_dir, f)) for f in planning_files):
        try:
            profile = _validate_user_profile(world_dir)
            policy = _validate_filesystem_policy(world_dir, current_timestamp)
            system_start_ts = policy["system_start_timestamp"]
            project_index, file_list, file_graph = _validate_planning(
                world_dir, current_timestamp, system_start_ts
            )
            resuming = True
            already_done = sum(1 for f in file_list if f.get("content_generated"))
            log(f"RESUME: {already_done}/{len(file_list)} files already generated.")
        except Exception as e:
            log(f"RESUME: Existing data invalid ({e}), re-running from scratch.")
            resuming = False

    if not resuming:
        # --------------------------------------------------------------
        # Step 1: Persona → User Profile
        # --------------------------------------------------------------
        log("Step 1: Generating User Profile...")
        prompt = build_user_profile_prompt(persona)
        tracker.accumulate(await call_claude(prompt, cwd=world_dir, max_turns=5, plugins=plugins, model=model, log_file=log_file, turn_log_file=turn_log_file, step_label="step1_user_profile"))
        profile = _validate_user_profile(world_dir)
        log("Step 1 done: user_profile.json created.")

        # --------------------------------------------------------------
        # Step 2: User Profile → Filesystem Policy
        # --------------------------------------------------------------
        log("Step 2: Generating Filesystem Policy...")
        profile_json = json.dumps(profile, indent=2, ensure_ascii=False)

        # Generate random system_start_timestamp in 2020-2025
        start_range = datetime(2020, 1, 1)
        end_range = datetime(2025, 12, 31)
        random_days = random.randint(0, (end_range - start_range).days)
        random_hour = random.randint(7, 20)
        random_minute = random.randint(0, 59)
        system_start = start_range + timedelta(days=random_days)
        system_start = system_start.replace(hour=random_hour, minute=random_minute, second=0)
        system_start_ts = system_start.strftime("%Y-%m-%dT%H:%M:%S")

        prompt = build_filesystem_policy_prompt(profile_json, current_timestamp, system_start_ts)
        tracker.accumulate(await call_claude(prompt, cwd=world_dir, max_turns=5, plugins=plugins, model=model, log_file=log_file, turn_log_file=turn_log_file, step_label="step2_fs_policy"))
        policy = _validate_filesystem_policy(world_dir, current_timestamp)
        log(f"Step 2 done: filesystem_policy.json created. system_start={system_start_ts}")

        # --------------------------------------------------------------
        # Step 3: Joint Planning
        # --------------------------------------------------------------
        log("Step 3: Planning Projects, Files, and File Graph...")
        policy_json = json.dumps(policy, indent=2, ensure_ascii=False)
        profile_json = json.dumps(profile, indent=2, ensure_ascii=False)
        prompt = build_planning_prompt(profile_json, policy_json, current_timestamp)
        tracker.accumulate(await call_claude(prompt, cwd=world_dir, max_turns=15, plugins=plugins, model=model, log_file=log_file, turn_log_file=turn_log_file, step_label="step3_planning"))
        system_start_ts = policy["system_start_timestamp"]
        project_index, file_list, file_graph = _validate_planning(
            world_dir, current_timestamp, system_start_ts
        )
        log(f"Step 3 done: {len(file_list)} files planned.")

    # ------------------------------------------------------------------
    # Step 4: Create Directory Structure
    # ------------------------------------------------------------------
    _create_directories(world_dir, file_list)
    log("Step 4 done: directories created.")

    # ------------------------------------------------------------------
    # Step 5: Generate File Contents (batched)
    # ------------------------------------------------------------------
    profile_json = json.dumps(profile, indent=2, ensure_ascii=False)
    user_summary = _build_user_summary(profile)

    # Filter out already-generated files
    sorted_files = sorted(file_list, key=lambda f: f["timestamp"])
    remaining_files = [f for f in sorted_files if not f.get("content_generated")]

    if remaining_files and len(remaining_files) < len(sorted_files):
        log(f"Step 5: Skipping {len(sorted_files) - len(remaining_files)} already-generated, {len(remaining_files)} remaining.")

    # Apply max_generate limit
    if max_generate is not None:
        files_to_generate = remaining_files[:max_generate]
        skipped_count = len(remaining_files) - len(files_to_generate)
        log(f"Step 5 [dry-run]: generating {len(files_to_generate)}/{len(remaining_files)} files (skipping {skipped_count})")
    else:
        files_to_generate = remaining_files

    batches = _batch_files(files_to_generate)

    for i, batch in enumerate(batches, 1):
        paths = ", ".join(os.path.basename(e["path"]) for e in batch)
        log(f"Step 5: Batch {i}/{len(batches)} ({len(batch)} files: {paths})")

        activity_log = _get_recent_activity_log(world_dir)
        batch_paths = {entry["path"] for entry in batch}
        relevant_edges = _get_relevant_edges(file_graph, batch_paths)

        prompt = build_file_generation_prompt(
            batch=batch,
            activity_log_entries=activity_log,
            file_graph_edges=relevant_edges,
            user_profile_summary=user_summary,
            world_root=world_dir,
        )
        tracker.accumulate(await call_claude(prompt, cwd=world_dir, max_turns=500, plugins=plugins, model=model, log_file=log_file, turn_log_file=turn_log_file, step_label=f"step5_batch{i}"))
        _cleanup_stray_files(world_dir, log_fn=log)
        missing = _verify_batch(world_dir, batch, log_fn=log)
        _mark_generated(world_dir, batch)
        if missing:
            log(f"Step 5: Batch {i}/{len(batches)} done. WARNING: {len(missing)} files missing.")
        else:
            log(f"Step 5: Batch {i}/{len(batches)} done. All {len(batch)} files verified.")

    # ------------------------------------------------------------------
    # Done
    # ------------------------------------------------------------------
    final_file_list = _read_json(os.path.join(world_dir, "file_list.json"))
    generated = sum(1 for f in final_file_list if f.get("content_generated"))

    # Final verification: remove missing files from file_list and file_graph
    verified = 0
    all_missing = set()
    for entry in final_file_list:
        if not entry.get("content_generated"):
            continue
        physical = _logical_to_physical(world_dir, entry["path"])
        if physical and os.path.exists(physical):
            verified += 1
        else:
            all_missing.add(entry["path"])

    if all_missing:
        log(f"PRUNE: {len(all_missing)} files missing on disk, removing from file_list/file_graph: {list(all_missing)[:10]}")

        # Prune file_list.json
        fl_path = os.path.join(world_dir, "file_list.json")
        final_file_list = [e for e in final_file_list if e["path"] not in all_missing]
        with open(fl_path, "w", encoding="utf-8") as f:
            json.dump(final_file_list, f, indent=2, ensure_ascii=False)

        # Prune file_graph.json
        fg_path = os.path.join(world_dir, "file_graph.json")
        if os.path.exists(fg_path):
            file_graph_data = _read_json(fg_path)
            file_graph_data["nodes"] = [
                n for n in file_graph_data.get("nodes", [])
                if n.get("path") not in all_missing
            ]
            file_graph_data["edges"] = [
                e for e in file_graph_data.get("edges", [])
                if e.get("from") not in all_missing and e.get("to") not in all_missing
            ]
            with open(fg_path, "w", encoding="utf-8") as f:
                json.dump(file_graph_data, f, indent=2, ensure_ascii=False)

    generated = sum(1 for f in final_file_list if f.get("content_generated"))

    activity_count = 0
    al_path = os.path.join(world_dir, "activity_log.jsonl")
    if os.path.exists(al_path):
        with open(al_path, "r", encoding="utf-8") as f:
            activity_count = sum(1 for line in f if line.strip())

    # Write completion marker and final usage
    tracker.save()
    with open(os.path.join(world_dir, "_complete"), "w") as f:
        f.write(datetime.now().isoformat() + "\n")

    log(f"COMPLETE: {generated}/{len(final_file_list)} files, {verified} verified on disk, {activity_count} activities. Cost: ${tracker.total_cost_usd:.4f}, turns: {tracker.total_turns}, {tracker.usage_str()}")

    return world_dir

"""Standalone NPC response runner (no MCP).

Runs each NPC agent as an independent call_claude session.
Called by the daily execution loop after the main agent writes
npc_outreach_day{N}_{npc_id}_r{seq}.json files.
"""

import glob
import json
import os
import re

from agents.common import (
    call_claude,
    _read_file_as_text,
    UsageTracker,
)
from agents.daily_execution_prompts import build_npc_response_prompt as _npc_prompt_windows
from agents.daily_execution_prompts_mac import build_npc_response_prompt as _npc_prompt_macos


# Pattern: npc_outreach_day3_ext_tyler_r1.json
_OUTREACH_RE = re.compile(r"^npc_outreach_day(\d+)_(.+)_r(\d+)\.json$")


async def run_npc_responses(
    world_dir: str,
    day_num: int,
    day_date: str,
    npcs: list[dict],
    npc_interaction_logs: dict[str, list[dict]],
    drives_share_dir: str,
    external_share_dir: str,
    plugins: list | None,
    model: str | None,
    log_file: str,
    turn_log_file: str,
    tracker: UsageTracker,
    log_fn: callable,
    os_flavor: str = "windows",
) -> list[dict]:
    """Process all NPC outreach requests for a given day.

    Discovers npc_outreach_day{N}_*_r*.json files, runs each NPC agent,
    records interactions, and returns a summary of responses.

    Returns:
        List of {npc_id, npc_name, seq, reply, files_shared} for each message processed.
    """
    log = log_fn

    # Discover outreach files for this day
    pattern = os.path.join(world_dir, f"npc_outreach_day{day_num}_*_r*.json")
    outreach_files = sorted(glob.glob(pattern))

    if not outreach_files:
        return []

    # Deduplicate: remove any interaction log entries for this day
    # (handles resume after partial Phase 2 failure)
    for pid_key in list(npc_interaction_logs.keys()):
        npc_interaction_logs[pid_key] = [
            entry for entry in npc_interaction_logs[pid_key]
            if entry.get("day") != day_num
        ]

    # Index NPCs by id
    npc_by_id = {p.get("id", "unknown"): p for p in npcs}

    responses: list[dict] = []

    for fpath in outreach_files:
        fname = os.path.basename(fpath)
        m = _OUTREACH_RE.match(fname)
        if not m:
            log(f"    [npc_runner] Skipping unrecognized file: {fname}")
            continue

        _file_day, pid, seq_str = m.groups()
        seq = int(seq_str)

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                req = json.load(f)
        except (json.JSONDecodeError, ValueError) as e:
            log(f"    [npc_runner] Malformed JSON in {fname}: {e} — skipping.")
            continue

        # Allow npc_id from filename or from JSON body
        pid = req.get("npc_id", pid)
        message = req.get("message", "")

        npc_entry = npc_by_id.get(pid)
        if not npc_entry:
            log(f"    [npc_runner] Unknown NPC '{pid}' — skipping.")
            continue

        pname = npc_entry.get("name", "Unknown")
        log(f"    [npc_runner] {pname} responding (day {day_num}, msg {seq})...")

        # Build interaction context
        interaction_ctx = (
            f"The main user has sent you the following message/request "
            f"on day {day_num} ({day_date}):\n\n"
            f"--- BEGIN MESSAGE ---\n{message}\n--- END MESSAGE ---"
        )

        # List shared files from main agent
        shared_files = []
        if os.path.isdir(drives_share_dir):
            for root, _dirs, files in os.walk(drives_share_dir):
                for fn in files:
                    shared_files.append(os.path.relpath(
                        os.path.join(root, fn), world_dir
                    ).replace("\\", "/"))

        # Snapshot external_share/{pid}/ before NPC runs
        pid_share_dir = os.path.join(external_share_dir, pid)
        os.makedirs(pid_share_dir, exist_ok=True)
        before_files = set()
        if os.path.isdir(pid_share_dir):
            for root, _dirs, files in os.walk(pid_share_dir):
                for fn in files:
                    before_files.add(os.path.relpath(
                        os.path.join(root, fn), world_dir
                    ).replace("\\", "/"))

        _builder = _npc_prompt_macos if os_flavor == "macos" else _npc_prompt_windows
        npc_prompt = _builder(
            npc=npc_entry,
            interaction_context=interaction_ctx,
            interaction_history=npc_interaction_logs.get(pid, []),
            shared_files_from_main=shared_files,
            current_day=day_num,
            current_date=day_date,
            response_seq=seq,
        )

        # Record the outreach immediately (before NPC runs) so it's
        # preserved even if the NPC agent crashes
        npc_interaction_logs.setdefault(pid, []).append({
            "day": day_num, "date": day_date,
            "direction": "main_to_npc",
            "type": "request",
            "content": message,
        })

        # Plain call_claude — no MCP, no ExceptionGroup risk
        try:
            result = await call_claude(
                npc_prompt, cwd=world_dir, max_turns=30,
                plugins=plugins, model=model, log_file=log_file,
                turn_log_file=turn_log_file,
                step_label=f"step8_npc_{pid}_day{day_num}_r{seq}",
                os_flavor=os_flavor,
            )
            tracker.accumulate(result)
        except Exception as e:
            log(f"    [npc_runner] {pname} FAILED: {type(e).__name__}: {e}")
            npc_interaction_logs.setdefault(pid, []).append({
                "day": day_num, "date": day_date,
                "direction": "npc_to_main",
                "type": "error",
                "content": f"(NPC failed to respond: {type(e).__name__})",
            })
            continue

        # Read NPC's reply file
        reply_path = os.path.join(
            world_dir, "external_share", pid,
            f"reply_day{day_num}_r{seq}.txt",
        )
        reply_text = _read_file_as_text(reply_path, max_chars=30000)
        if not reply_text:
            reply_text = result.get("text", "(No reply generated)")

        # Detect new files shared by NPC
        after_files = set()
        if os.path.isdir(pid_share_dir):
            for root, _dirs, files in os.walk(pid_share_dir):
                for fn in files:
                    after_files.add(os.path.relpath(
                        os.path.join(root, fn), world_dir
                    ).replace("\\", "/"))
        new_files = sorted(after_files - before_files)
        reply_relpath = f"external_share/{pid}/reply_day{day_num}_r{seq}.txt"
        new_files = [f for f in new_files if f != reply_relpath]

        # Record NPC response (outreach was already logged above)
        npc_interaction_logs.setdefault(pid, []).append({
            "day": day_num, "date": day_date,
            "direction": "npc_to_main",
            "type": "response",
            "content": reply_text,
        })

        # Persist logs after each interaction
        intlog_path = os.path.join(world_dir, "npc_interaction_logs.json")
        with open(intlog_path, "w", encoding="utf-8") as f:
            json.dump(npc_interaction_logs, f, indent=2, ensure_ascii=False)

        log(f"    [npc_runner] {pname} done (reply {len(reply_text)} chars, {len(new_files)} files shared)")

        responses.append({
            "npc_id": pid,
            "npc_name": pname,
            "seq": seq,
            "reply": reply_text,
            "files_shared": new_files,
        })

    return responses

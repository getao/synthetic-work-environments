"""Prompt templates for Daily Execution (Steps 7-9) — macOS flavor.

Includes weekly planning, daily file generation,
NPC response, and deliverable evaluation.
"""

from __future__ import annotations

import copy
import json


# ---------------------------------------------------------------------------
# GDP-val reference examples (quality floor for deep_work outputs)
# ---------------------------------------------------------------------------

_GDPVAL_EXAMPLES = """\
These GDP-val tasks represent the MINIMUM complexity for any single deep_work output:
- Auditor: Sample-size calculation at 90% confidence, variance analysis on anti-financial-crime risk metrics, multi-criteria audit sampling → xlsx with workings tab
- Warehouse Manager: Write a 5-page SOP for ESD-sensitive component handling per IPC-A-610G → professional docx
- Lawyer: Draft an 8–11 page Last Will and Testament from scratch under Texas law with trust provisions → pdf
Every deep_work file you plan must be AT LEAST this complex."""


# ---------------------------------------------------------------------------
# Occupation-specific skill hint (see sibling `daily_execution_prompts.py`)
# Gated by `use_occupation_skills`. REQUIRES agent to pick one or explicitly
# state none match — silent skipping is a hard failure.
# ---------------------------------------------------------------------------

def _make_occupation_skills_hint(occupation_skills: list[str]) -> str:
    """Same as in daily_execution_prompts.py — keep in sync."""
    if not occupation_skills:
        return ""
    skill_lines = "\n".join(f"  - `{s}`" for s in sorted(occupation_skills))
    return f"""\
## Occupation Skills — pick ONE before producing today's deliverables

Your workspace ships these occupation-specific skills under
`.claude/skills/<name>/SKILL.md`. Each contains principles, best
practices, and common pitfalls distilled from real-world professionals:

{skill_lines}

**REQUIRED first action — do this BEFORE any tool calls that produce a deliverable:**

1. From the list above, identify the **single best-matching skill** for
   the user's role. (Most personas will have exactly one strong match.)
2. **Invoke `Skill(skill="<name>")` to load its content** (or
   `Read .claude/skills/<name>/SKILL.md` if Skill tool isn't available).
   This must happen before you start producing deliverables — the
   guidance shapes how you write them.
3. Apply the loaded guidance throughout the day's work.

**Escape hatch** (use sparingly, with explicit reasoning): if NO skill
above is a defensible match for the role, you MUST state literally:

> "No occupation skill matches this role because <one-sentence reason>."

Then proceed without one. **Silent skipping is a hard failure** — only
two acceptable outcomes: (a) load a skill, or (b) say out loud no
match. Saying you "will use" a skill but never loading it counts as
silent skipping.

(The above list contains occupation skills only. The document/format
skills `minimax-docx`, `minimax-xlsx`, `pptx-generator`, `minimax-pdf`
are separate and should also be used for file
production as appropriate.)"""


# ===================================================================
# Step 7: Weekly Day-by-Day Planning
# ===================================================================

def build_weekly_plan_prompt(
    objectives_json: str,
    external_npcs_json: str,
    week_num: int,
    user_profile_summary: str,
    real_world_context: str = "",
    use_occupation_skills: bool = False,
    occupation_skills: list[str] | None = None,
) -> str:
    """Build prompt for Step 7: main agent plans its own week.

    Called 4 times (once per week).  The plan is from the main agent's
    perspective — it decides what to work on and when to reach out to
    external NPCs for help.

    Activity log and file list are NOT inlined — the agent reads them
    via tools to avoid prompt bloat.

    If `use_occupation_skills` is True AND `occupation_skills` is non-empty,
    a hint is prepended forcing the agent to either load one matching
    skill or explicitly state none match.
    """
    skills_block = ""
    if use_occupation_skills and occupation_skills:
        skills_block = "\n" + _make_occupation_skills_hint(occupation_skills) + "\n"
    return f"""\
You are the main user.  Plan **your Week {week_num}** of a 4-week work month.
{skills_block}
## Who You Are
{user_profile_summary}

## Your Monthly Objectives
{objectives_json}

## Your Collaborators
These external NPCs are available to you.  They are **purely reactive** —
they will NOT contact you on their own.  When you need data, feedback,
clarification, or approvals, you must proactively reach out to them.

{external_npcs_json}

## What You've Done So Far
Read `activity_log.jsonl` (Cold Start activities) and `daily_activity_log.jsonl`
(Daily Sim activities) in the working directory to review what's been done.
Also read any previous `week_*_plan.json` files to see what was planned.

## Files on Your Disk
Read `file_list.json` in the working directory for the complete file inventory.

## Real-World Context
{real_world_context if real_world_context else "(Use your training knowledge.)"}

─────────────────────────────────────────────────────
## YOUR TASK

Think through what you need to accomplish this week to stay on track for
your monthly milestones.  Consider:
- What deliverables need progress this week?
- What information or data do you need from collaborators?
- What drafts should you prepare for review/feedback?
- What dependencies block your work until you get answers?

Write `week_{week_num}_plan.json` **in the current working directory root** (NOT inside `drives/`). This is a simulation control file, not a user document.

**CRITICAL: valid JSON** — escape all double quotes inside string values (use `\\"` not `"`).
Use a Python or Node.js script to write the JSON to guarantee validity.

Use this structure:

```json
{{
  "week": {week_num},
  "days": [
    {{
      "date": "<YYYY-MM-DD>",
      "day_of_week": "<Monday|Tuesday|...>",
      "activities": [
        {{
          "time": "<HH:MM>",
          "type": "<deep_work|email_write|review|admin|outreach>",
          "description": "<specific description of what you do>",
          "files_to_create": ["<logical macOS path>"],
          "files_to_modify": ["<logical macOS path of existing file>"],
          "content_notes": "<detailed guidance for file generation>",
          "deliverable_id": "<if related to a multi-week deliverable>",
          "outreach_to": "<npc id, if reaching out for data/feedback/clarification>",
          "outreach_purpose": "<what you need from them>",
          "derived_from": ["<paths of files this depends on>"]
        }}
      ]
    }}
  ]
}}
```

## RULES

1. **5 working days** (Mon–Fri) for this week.
2. **3–6 activities per day**, mixing routine work with deep work.
3. **Advance deliverable milestones**: check the milestone for week {week_num}
   and plan activities that progress toward that goal.
4. **Proactive outreach**: when you need data, feedback, or approvals from a
   collaborator, schedule an `outreach` activity.  Communication is asynchronous
   (like email) — you send a message and the reply arrives before the next day.
   Make each message self-contained and informative.
   For file sharing, use `drives/share/` (outbound) and `external_share/` (inbound).
5. **Request feedback on drafts**: before finalizing a deliverable, schedule
   an outreach to the relevant reviewer/approver NPC to request feedback.
   You must complete the draft BEFORE requesting review.
6. **file content_notes must be detailed**: these will be used as instructions
   for actual file generation.  Don't be vague — specify what the file should
   contain, what data to include, what format to use.
7. **files_to_modify**: when a file is being revised (v1→v2), list the
   original file path here.  The generator will read the existing file and
   produce an updated version.
8. **Each deep_work file must be ≥ GDP-val complexity level**:
   {_GDPVAL_EXAMPLES}
9. **Realistic pacing**: not every day is equally productive.  Vary naturally.

Write the file now.
"""


# ===================================================================
# Step 8: Daily File Generation (extends Cold Start's file gen prompt)
# ===================================================================

def build_daily_file_generation_prompt(
    day_plan: dict,
    user_profile_summary: str,
    world_root: str,
    external_npcs_context: str = "",
    real_world_context: str = "",
    day_num: int = 0,
    use_occupation_skills: bool = False,
    occupation_skills: list[str] | None = None,
) -> str:
    """Build prompt for Step 8: generate files for one day's activities.

    Similar to Cold Start's build_file_generation_prompt but adds:
    - Day context (what day it is, what the user is working toward)
    - External NPC context for interactions
    - File modification support (read existing → edit → save)
    - Richer activity log entries including non-file activities

    Activity log and file graph are NOT inlined — the agent reads them
    via tools to avoid prompt bloat.

    If `use_occupation_skills` is True, an occupation-skill hint is
    prepended to nudge the agent toward reading the matching skill
    under `.claude/skills/` before producing deliverables.
    """
    day_date = day_plan.get("date", "unknown")
    day_of_week = day_plan.get("day_of_week", "unknown")
    activities = day_plan.get("activities", [])

    # Separate file-producing activities from non-file activities
    file_activities = []
    non_file_activities = []
    for act in activities:
        if act.get("files_to_create") or act.get("files_to_modify"):
            file_activities.append(act)
        else:
            non_file_activities.append(act)

    # Build file list for generation
    files_to_process = []
    for act in file_activities:
        for path in act.get("files_to_create", []):
            files_to_process.append({
                "path": path,
                "description": act.get("content_notes", act.get("description", "")),
                "activity_description": act.get("description", ""),
                "derived_from": act.get("derived_from", []),
                "is_modification": False,
            })
        for path in act.get("files_to_modify", []):
            files_to_process.append({
                "path": path,
                "description": act.get("content_notes", act.get("description", "")),
                "activity_description": act.get("description", ""),
                "derived_from": act.get("derived_from", []),
                "is_modification": True,
            })

    files_json = json.dumps(files_to_process, indent=2, ensure_ascii=False)
    non_file_json = json.dumps(non_file_activities, indent=2, ensure_ascii=False)

    skills_block = ""
    if use_occupation_skills and occupation_skills:
        skills_block = "\n" + _make_occupation_skills_hint(occupation_skills) + "\n"

    return f"""\
**Follow the PATH RULE, tool/library reference, and content_scale guidelines in CLAUDE.md.**
{skills_block}
## Today: Day {day_num}, {day_of_week}, {day_date}

## User
{user_profile_summary}

## Your Collaborators
{external_npcs_context if external_npcs_context else "(No collaborators assigned.)"}

## Real-World Context
{real_world_context if real_world_context else "(Use your training knowledge.)"}

## Context Files (read as needed)
- `daily_activity_log.jsonl` — what you've done in previous days
- `activity_log.jsonl` — Cold Start activity history
- `file_list.json` — complete file inventory
- `file_graph.json` — file dependency edges

## COMMUNICATING WITH COLLABORATORS

Communication is **asynchronous** (like email) — you send messages, and
replies arrive before your next working day.

**To contact a collaborator**: write a JSON file for each message, named
`npc_outreach_day{day_num}_<npc_id>_r<seq>.json` in the working directory root
(NOT inside `drives/`).  `<seq>` is the message sequence number for that NPC
today (start at 1).  Each file contains ONE message to ONE recipient:

```json
{{
  "npc_id": "ext_tyler",
  "message": "Hi Tyler, ..."
}}
```

To contact multiple collaborators, write separate files (one per recipient):
- `npc_outreach_day{day_num}_ext_tyler_r1.json`
- `npc_outreach_day{day_num}_ext_sandra_r1.json`

Each message should be **self-contained and informative** — include all
relevant context, specific questions, and clear requests in a single message,
since you won't get a chance to clarify until the next day.

**File sharing** (see CLAUDE.md for full details):
- Share files out: copy to `drives/share/` BEFORE writing the outreach file
- Receive files: check `external_share/<npc_id>/` for files from previous days
- You CANNOT see `external_refs/` (NPCs' private files)

**FIRST THING**: Check `external_share/` for replies and files from previous interactions.

## FILES TO CREATE OR MODIFY

{files_json}

## NON-FILE ACTIVITIES TO LOG

{non_file_json}

## INSTRUCTIONS

### For each file to CREATE:
1. Convert logical path to `drives/...`, create parent dirs with `mkdir -p`
2. Use the correct tool/library for the file type (see CLAUDE.md)
3. Content must be professional, domain-accurate, and realistic
4. Each deep_work file must be ≥ GDP-val complexity level

### For each file to MODIFY:
1. Read the existing file first
2. Make changes described in `content_notes`
3. Save as new version (e.g., `_v2`, `_revised`, `_FINAL`)
4. Substantive changes, not trivial edits

### Outreach:
When you need data, feedback, or approvals from collaborators, write one
`npc_outreach_day{day_num}_<npc_id>_r<seq>.json` file per message.
Be thorough — each message is like sending an email: include all context and
questions upfront.  To request draft review: copy the draft to `drives/share/`
first, then reference the file path in your outreach message.

### After all work:
- Append to `daily_activity_log.jsonl` (see CLAUDE.md for format). Include ALL activities.
- Update `file_graph.json` with new edges (`version_of`, `derived_from`, `references`).
"""


# ===================================================================
# Step 8 NPC Agent: External NPC Response
# ===================================================================

def build_npc_response_prompt(
    npc: dict,
    interaction_context: str,
    interaction_history: list[dict],
    shared_files_from_main: list[str],
    current_day: int,
    current_date: str,
    response_seq: int = 1,
) -> str:
    """Build prompt for an external NPC agent responding to the main agent.

    The NPC agent can:
    - Read/reference its own files in external_refs/<npc_id>/
    - See files shared by main agent in drives/share/
    - Produce responses written to external_share/<npc_id>/
    - Share files by copying from external_refs/ to external_share/

    It CANNOT see drives/Macintosh HD/ (main agent's private filesystem)
    or other NPCs' files.
    """
    npc_id = npc.get("id", "unknown")
    npc_name = npc.get("name", "Unknown")

    # Build interaction history summary
    history_json = json.dumps(interaction_history, indent=2, ensure_ascii=False) if interaction_history else "[]"

    # Shared files list
    shared_files_str = "\n".join(f"  - {f}" for f in shared_files_from_main) if shared_files_from_main else "  (none)"

    # Strip rubric from NPC context passed to NPC agent
    npc_clean = copy.deepcopy(npc)
    npc_clean.pop("rubric", None)

    return f"""\
You are **{npc_name}**, responding in a work simulation.

## Your Identity
{json.dumps(npc_clean, indent=2, ensure_ascii=False)}

## Current Date
Day {current_day} ({current_date})

## Interaction Context
{interaction_context}

## Prior Interaction History (your exchanges with the main user)
{history_json}

## Files Shared With You by the Main User
The main user has shared the following files for you to review/use.
**Read them** using the Read tool if they are relevant to the request.
{shared_files_str}

═══════════════════════════════════════════════════════════════════

## YOUR TASK

Respond to the interaction context above **in character** as {npc_name}.

**Guidelines:**
1. Stay fully in character — use your communication style, expertise level,
   and personality as described in your profile.
2. Your response should be realistic — the length, tone, and detail level
   should match what this person would actually write/say.
3. Write your text response (email/message body) to:
   `external_share/{npc_id}/reply_day{current_day}_r{response_seq}.txt`
4. If you need to share a file with the main user (data, reports, templates),
   copy it from `external_refs/{npc_id}/` to `external_share/{npc_id}/`.
5. If you need to create a new file (e.g., a corrected data export, a
   review markup, a response memo), create it in `external_share/{npc_id}/`.
6. You can read your own files in `external_refs/{npc_id}/` to inform
   your response.
7. You can read files in `drives/share/` that the main user shared with you.
8. Do NOT access `drives/Macintosh HD/...` (main user's private filesystem).
9. Do NOT access other NPCs' folders (`external_share/<other_id>/`, `external_refs/<other_id>/`).
10. Do NOT read `npc_outreach_day*.json` files — those are internal routing files.

## PATH RULES
- Your text reply: `external_share/{npc_id}/reply_day{current_day}_r{response_seq}.txt`
- Your private files: `external_refs/{npc_id}/`
- Your file share: `external_share/{npc_id}/`
- Main user's shared files: `drives/share/`
- Do NOT access: `drives/Macintosh HD/...`, `external_share/<other_id>/`, `external_refs/<other_id>/`, `npc_outreach_day*.json`

Respond now.
"""


# ===================================================================
# Step 9: Deliverable Evaluation
# ===================================================================

def build_evaluation_prompt(
    npc: dict,
    deliverable: dict,
    interaction_history: list[dict],
    deliverable_file_paths: dict[str, str],
    reference_file_paths: list[str],
) -> str:
    """Build prompt for an evaluator NPC agent to generate a GDPval-level
    granular rubric and score a deliverable.

    The evaluator receives in the prompt (for rubric generation):
    - The deliverable specification (description, milestones, expected outputs)
    - Their own preferences and priorities (high-level rubric from Step 6)
    - Full interaction history with the main agent

    The evaluator reads with tools (for rubric generation + scoring):
    - Reference files (to extract exact expected values for rubric items)
    - Deliverable files (to score against the rubric)

    Args:
        deliverable_file_paths: {logical_path: physical_path_relative_to_cwd}
        reference_file_paths: list of paths relative to cwd
    """
    npc_name = npc.get("name", "Unknown")
    npc_id = npc.get("id", "unknown")
    rubric = npc.get("rubric", {})
    rubric_json = json.dumps(rubric, indent=2, ensure_ascii=False) if rubric else "{}"

    # Build deliverable specification
    dlv_id = deliverable.get("id", "unknown")
    dlv_title = deliverable.get("title", "Unknown")
    dlv_desc = deliverable.get("description", "")
    dlv_milestones = deliverable.get("milestones", [])
    dlv_output_files = deliverable.get("output_files", [])
    milestones_text = "\n".join(
        f"  Week {m.get('week', '?')}: {m.get('goal', '')}"
        for m in dlv_milestones
    )
    output_files_text = "\n".join(f"  - {f}" for f in dlv_output_files)

    history_json = json.dumps(interaction_history, indent=2, ensure_ascii=False) if interaction_history else "[]"

    # Build deliverable file path listing
    deliv_path_lines = []
    for logical, physical in deliverable_file_paths.items():
        deliv_path_lines.append(f"  - `{physical}`  (← {logical})")
    deliv_paths_section = "\n".join(deliv_path_lines) if deliv_path_lines else "  (No deliverable files found)"

    # Build reference file path listing
    ref_path_lines = [f"  - `{p}`" for p in reference_file_paths]
    ref_paths_section = "\n".join(ref_path_lines) if ref_path_lines else "  (No reference files)"

    return f"""\
You are **{npc_name}**, evaluating a deliverable in a work simulation.

## Your Role
You are the evaluator/reviewer for this deliverable. You have worked with
the main user throughout the month — sharing data, providing feedback,
making requests, and communicating requirements. Now you must produce a
rigorous, fine-grained evaluation.

## Deliverable Specification
**ID**: {dlv_id}
**Title**: {dlv_title}
**Description**: {dlv_desc}
**Milestones**:
{milestones_text}
**Expected Output Files**:
{output_files_text}

## Your Preferences and Priorities
These are the high-level areas you care about as the evaluator. Use them
as a starting point, but your detailed rubric must go far beyond these.
{rubric_json}

## Your Full Interaction History with the Main User
This is the complete record of every message exchanged. Mine this carefully —
every correction you made, every requirement you communicated, every data
point you provided becomes a verifiable rubric item.
{history_json}

## Files You Must Read

**Your Reference Files** (data you shared, templates you provided):
{ref_paths_section}

**Deliverable Files to Evaluate**:
{deliv_paths_section}

Read ALL of these files using the Read tool before generating your rubric.
For .xlsx, .docx, and .pdf files, the Read tool will handle them correctly.

═══════════════════════════════════════════════════════════════════

## YOUR TASK

You must produce an evaluation at the granularity level of professional
benchmark rubrics (like GDPval). This means **45–65 specific, independently
verifiable items**, each with concrete expected values wherever possible.

### Phase 1: Read All Files
Read every reference file and every deliverable file listed above.
You need the reference files to know what values to expect, and the
deliverable files to verify those values.

### Phase 2: Generate Granular Rubric

Systematically derive rubric items from ALL of these sources:

**A. From the Deliverable Specification** (~5–10 items)
- Each expected output file exists and is in the correct format
- Each milestone goal is addressed in the final deliverable
- The deliverable title/scope is fully covered

**B. From Your Reference Files** (~10–15 items)
- Specific data values from your reference files are correctly used
  (e.g., "F&A rate is exactly 52.5%", "loop duration for position B-S1
  is exactly 12:00")
- Template formats and required fields are followed
- Standards and specifications from your documents are met

**C. From Interaction History** (~10–20 items)
- Every specific correction you communicated is incorporated
  (e.g., "Panel B-2 word count reduced to ≤120 words per my Feb 19 note")
- Every requirement you stated in conversation is met
- Every question you answered is reflected in the deliverable
- Agreements and decisions made during exchanges are honored
- Items you flagged as blocking or conditional are resolved

**D. From Domain Expertise** (~5–10 items)
- Professional standards for this type of deliverable
- Internal consistency (numbers add up, cross-references are correct)
- Completeness checks (all sections present, no gaps)
- Technical accuracy of claims, calculations, or data

**E. Overall Quality** (~3–5 items)
- Formatting and presentation
- Professional language and tone
- Organization and navigability

Each rubric item MUST follow this format:
```
[+N] Concrete, verifiable criterion with expected value if applicable
```

Point values:
- **+1**: Minor formatting, style, or cosmetic item
- **+2**: Substantive requirement (correct value, required section, spec compliance)
- **+5**: Critical requirement (blocking issue, major accuracy, core deliverable)

**Be specific.** BAD: "Budget is complete." GOOD: "Personnel line items include
PI (0.5 FTE), Co-PI (0.25 FTE), and Postdoc (1.0 FTE) with salary rates
matching Year 4 actuals from FARI expenditure report."

**Use exact values.** BAD: "Indirect costs are calculated correctly."
GOOD: "F&A is calculated at 52.5% of MTDC, yielding $47,250 on a $90,000
MTDC base."

### Phase 3: Score Each Item
For each rubric item:
- **Full points** if the criterion is clearly met in the deliverable
- **0 points** if not met or not present
- **Partial credit** (with explanation) only if partially addressed

Be strict. If a value is wrong, it is wrong — do not give partial credit
for "attempting" it. Partial credit is for items that are substantively
addressed but have a minor discrepancy.

### Phase 4: Write Evaluation File
Write the complete rubric and scores to `evaluation_{npc_id}_{dlv_id}.json`
**in the current working directory root** (NOT inside `drives/`):
```json
{{
  "deliverable_id": "{dlv_id}",
  "evaluator_id": "{npc_id}",
  "evaluator_name": "{npc_name}",
  "total_possible": <sum of all point values>,
  "total_earned": <sum of earned points>,
  "percentage": <round(earned/possible * 100, 1)>,
  "items": [
    {{
      "criterion": "<specific criterion text with expected value>",
      "source": "<spec|reference|interaction|expertise|quality>",
      "points_possible": N,
      "points_earned": M,
      "met": true/false/"partial",
      "notes": "<evidence from deliverable, or explanation if not met>"
    }}
  ],
  "overall_comments": "<qualitative assessment in character, 2-3 paragraphs>"
}}
```

**IMPORTANT**: You must produce at least 45 rubric items. Aim for 50–60.
Each item must be independently verifiable — no vague or subjective criteria.
Use a script to write the JSON file to ensure validity.

Generate the rubric and evaluate now.
"""

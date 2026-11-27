"""Prompt templates for Task Planning (Step 6 + 6.5).

Includes monthly objectives, external NPC construction,
reference file generation, and workspace prerequisites.
"""

from __future__ import annotations

import copy
import json


# ---------------------------------------------------------------------------
# Context filtering helpers (information isolation)
# ---------------------------------------------------------------------------

def strip_npc_for_main_agent(npc: dict) -> dict:
    """Return a copy of an NPC entry with rubric removed.

    Used when building prompts for the main agent (Steps 7/8) so it cannot
    see hidden evaluation criteria.
    """
    p = copy.deepcopy(npc)
    p.pop("rubric", None)
    return p


def strip_npcs_for_main_agent(npcs: list[dict]) -> list[dict]:
    """Convenience: strip all NPCs for main agent context."""
    return [strip_npc_for_main_agent(p) for p in npcs]


# ---------------------------------------------------------------------------
# GDP-val reference examples (quality floor for deep_work outputs)
# ---------------------------------------------------------------------------

_GDPVAL_EXAMPLES = """\
These GDP-val tasks represent the MINIMUM complexity for any single deep_work output:
- Auditor: Sample-size calculation at 90% confidence, variance analysis on anti-financial-crime risk metrics, multi-criteria audit sampling → xlsx with workings tab
- Warehouse Manager: Write a 5-page SOP for ESD-sensitive component handling per IPC-A-610G → professional docx
- Lawyer: Draft an 8–11 page Last Will and Testament from scratch under Texas law with trust provisions → pdf
Every deep_work file you plan must be AT LEAST this complex."""


# ===================================================================
# Step 6: Monthly Objectives + External Personas + Real-world Context
# ===================================================================

def build_monthly_objectives_prompt(
    start_date: str,
    real_world_context: str = "",
) -> str:
    """Build prompt for Step 6: monthly objectives + external NPCs.

    The LLM must output THREE JSON files:
      1. monthly_objectives.json
      2. external_context.json
      3. context_seeds.json (workspace prerequisite files)

    User profile, project index, and file list are NOT inlined — the agent
    reads them via tools to avoid prompt bloat.
    """
    return f"""\
You are planning a **one-month daily work simulation** for a user whose PC
filesystem has already been populated by a Cold Start process.

## Your Perspective

You are NOT the user.  You are the user's **senior manager** (or an industry
expert at the top of this profession) who deeply understands:
- What excellent work looks like in this role
- What a realistic but challenging monthly workload is
- What deliverables would demonstrate real professional competence
- Who this person interacts with and what those interactions look like

Your job is to set **month-level objectives** for this user — the kind of
KPI/OKR targets a manager would assign — that require roughly one full month
of sustained professional effort.  The final acceptance criteria are concrete
**deliverables** (work packages of 5–10 interrelated files each).

Study the user's profile, their active projects, and their existing filesystem
carefully.  Most objectives should build on what's already on their desk —
continuing in-progress work, responding to recent events, advancing existing
projects.  But new assignments (from a manager, a new client, an emerging
opportunity) are also realistic and welcome if they fit the user's role.

## Context Files (read these first)
- `user_profile.json` — the user's detailed profile (role, skills, background)
- `project_index.json` — active projects
- `file_list.json` — complete file inventory from Cold Start

## Simulation Start Date
{start_date}
(Simulation covers ~20 working days = 4 weeks from this date.)

## Real-World Context (from web search)
{real_world_context if real_world_context else "(No real-world context provided — use your training knowledge for the simulation period.)"}

## Quality Floor
{_GDPVAL_EXAMPLES}

─────────────────────────────────────────────────────────
## YOUR TASK

Produce **three JSON files** by writing them to the current directory.

### 1. `monthly_objectives.json`

Plan the user's month.  Include:

```json
{{
  "simulation_period": {{
    "start": "{start_date}",
    "end": "<4 weeks later>",
    "working_days": 20
  }},
  "deliverables": [
    {{
      "id": "dlv_001",
      "title": "<descriptive title>",
      "project_id": "<from project_index>",
      "description": "<what this deliverable is, why it matters>",
      "target_completion": "<ISO date>",
      "milestones": [
        {{"week": 1, "goal": "<concrete goal>"}},
        {{"week": 2, "goal": "..."}},
        {{"week": 3, "goal": "..."}},
        {{"week": 4, "goal": "..."}}
      ],
      "output_files": ["<filename_v1.ext>", "<filename_v2.ext>", "<filename_FINAL.ext>"]
    }}
  ],
  "recurring_activities": [
    {{"frequency": "daily|weekly|biweekly", "activity": "<description>"}}
  ],
  "weekly_focus": [
    {{"week": 1, "focus": "<theme>", "deliverable_ids": ["dlv_001"]}},
    ...
  ]
}}
```

**Rules for deliverables:**
- **Task Complexity**: Each deliverable must be a genuinely hard, long-horizon
  task — multi-hop, multi-step, NOT something completable in one sitting.
  Examples of what makes a task complex: incomplete starting information that
  forces clarification rounds with collaborators; needing to cross-reference
  and reconcile multiple sources; non-trivial intermediate steps (data
  cleaning, analysis, calculations, verification, web search) before reaching the final
  output; dependencies on information that arrives over time.  Design tasks
  that are realistic for the role but at the challenging end of the spectrum.
- Number of deliverables depends on the user's role and seniority (not fixed).
  Senior/management roles naturally juggle more concurrent work items;
  junior or focused roles may have just 1–2.  Choose what is most realistic
  for THIS user.
- Each deliverable is a **work package** (5–10 interrelated files), not a single doc.
- Each must go through ≥3 iterations (draft → revision → final).
- Milestones must be concrete and measurable.
- output_files list the key filenames that will be created (versions included).
- Deliverables should primarily build upon existing projects and files visible
  in the file list.  However, new projects or assignments that arrive during
  the month (e.g. from a manager or new client) are realistic and allowed —
  just ensure they fit naturally with the user's role and workload.
- **External Interaction Dependency (recommended)**: Prefer designing
  deliverables that cannot be completed using only prerequisite files and
  the user's existing filesystem.  Ideally the user should depend on ongoing
  external NPC interactions to succeed — e.g. data that arrives via
  external NPCs, feedback loops that require revision, approvals that
  gate progress, or information gaps that force proactive clarification.
  This multi-week, multi-person, iterative nature is what distinguishes
  Daily Sim from single-shot GDP-val tasks.
- **Realistic Cognitive Complexity**: Deliverables should reflect how this
  professional actually works.  If the role naturally involves data analysis,
  the deliverable should require real computation (not hand-waved numbers).
  If the work depends on current real-world facts (market prices, regulatory
  updates, industry benchmarks), the agent should need to look them up.  If
  findings need to be communicated visually, charts and tables with actual
  workings should be produced — not just prose descriptions.  In short:
  design deliverables that are faithful to the profession's actual workflow,
  whatever that workflow entails (research, computation, drafting, review,
  visualization, etc.).  The goal is multi-hop, long-horizon tasks that
  cannot be completed in a single step.

### 2. `external_context.json`

Design 3–5 external NPCs who will interact with the user during the month.
These are real people in the user's work life — managers, clients, colleagues,
direct reports, external partners.

**Every external NPC must include (REQUIRED fields — do NOT omit any):**
- **`id`**: unique identifier with `ext_` prefix, e.g. `ext_001`, `ext_felder`, `ext_bauer`.
  This MUST match the `requester_id` used in rubrics below and is used to
  namespace the NPC's reference files (`external_refs/<id>/...`). Missing or
  duplicate `id` fields will break downstream processing.
- **`name`**: full name of the person
- Detailed background (age, education, tenure, personality, work style)
- `key_facts` with domain-specific data (not vague — exact numbers, names, dates)
- `reference_files`: concrete files this NPC "brings" to the interaction.
  Each reference file has an `id`, `filename`, `description` (detailed enough to
  generate the actual file), `content_scale` (small/medium/large), and optionally
  `intentional_errors` (for files from junior staff that the user should catch).
- `what_they_provide`: brief description of what the main agent can get from this
  NPC (data, feedback, approvals, domain expertise, etc.)
- `communication_style` description

**External NPCs are purely reactive.** They do NOT initiate contact.
The main agent must reach out to them when it needs information, data,
feedback, or approvals.  When contacted, an NPC agent will respond
in character — sharing relevant files, answering questions, providing
feedback on submitted work, etc.  There is NO interaction_timeline.

**Types of reference files by NPC role:**
| Role | Reference Files |
|------|----------------|
| Manager/Director | Quality exemplar deliverables, review checklists, process docs, templates |
| Client | Their data files, project specs, company templates |
| Direct Report | Data exports (may contain errors), draft work products, analysis templates |
| External Party | Industry standards, regulatory templates, third-party reports |

**Hidden Rubric — MANDATORY COVERAGE RULE**

Every single `dlv_NNN` in `monthly_objectives.json → deliverables` MUST be
covered by **exactly one** NPC's `rubric.deliverable_id`:

- **Missing coverage** (a `dlv_NNN` has NO rubric) → Step 9 cannot evaluate it
  → the whole deliverable is wasted. NOT ACCEPTABLE.
- **Duplicate coverage** (two NPCs rubric-ed the same `dlv_NNN`) → Step 9
  runs twice and scores diverge. NOT ACCEPTABLE.

**Before you submit `external_context.json`**, mentally perform this check:

```
For each dlv_NNN in monthly_objectives.deliverables:
    count = number of NPCs where npc.rubric.deliverable_id == dlv_NNN
    assert count == 1   # ← every deliverable covered exactly once
```

If you have 5 deliverables, there must be **5 distinct NPCs carrying a
rubric** (one per deliverable). You may have more NPCs than deliverables
(NPCs without rubrics act as data providers / colleagues / informants).
You may NEVER have fewer rubrics than deliverables.

Assign each rubric to the NPC who is the natural requester/evaluator of
that deliverable (the manager, the client, the committee chair — whoever
would realistically judge the work).

The rubric structure:
```json
{{
  "rubric": {{
    "deliverable_id": "dlv_001",
    "requester_id": "ext_alice",
    "communication_style": "structured|scattered|minimal",
    "criteria": [
      {{"name": "...", "weight": 0.3, "description": "..."}}
    ],
    "initially_communicated": ["<criteria names told upfront>"],
    "revealed_on_ask": ["<criteria revealed when user asks>"],
    "only_at_review": ["<criteria revealed only at review time>"]
  }}
}}
```

`requester_id` MUST exactly equal the containing NPC's own `id` —
the NPC is assigning the rubric to themselves as evaluator.

### 3. `context_seeds.json`

List workspace prerequisite files that need to exist in the user's filesystem
BEFORE daily simulation starts (company policies, internal templates, etc.
that Cold Start didn't generate but the simulation needs):

```json
{{
  "workspace_prerequisites": [
    {{
      "path": "<logical Windows path, e.g. C:/Users/.../file.ext>",
      "description": "<what this file is and why it's needed>",
      "origin": "company_policy|internal_template|historical_communication",
      "content_scale": "small|medium|large",
      "needed_by": ["dlv_001"]
    }}
  ]
}}
```

## CRITICAL RULES
1. All NPCs, data, and interactions must be **internally consistent**.
2. Reference files must contain enough detail to actually generate realistic files.
3. Interaction timelines must form coherent causal chains (Week 1 data → Week 2 analysis → Week 3 review).
4. Use real-world context (market data, regulations, news) where relevant.
5. The user's daily work should reflect what someone in this exact role would actually do.
6. Do NOT be generic. Be specific: real numbers, real names, real dates, real domain terminology.

Write all three files now.
"""


# ===================================================================
# Step 6.5: External Persona Reference Files Generation
# ===================================================================

def build_ref_files_prompt(
    npc_entry: dict,
    user_profile_summary: str,
    real_world_context: str = "",
) -> str:
    """Build prompt for generating one external NPC's reference files.

    Called once per external NPC.  The LLM creates the actual files
    described in npc_entry['reference_files'].
    """
    ref_files = npc_entry.get("reference_files", [])
    npc_id = npc_entry.get("id", "unknown")
    ref_descriptions = json.dumps(ref_files, indent=2, ensure_ascii=False)

    return f"""\
You are generating **reference files** for an external NPC in a work
simulation.  These files represent documents, data, and templates that this
NPC brings to their interactions with the main user.

## Main User (for context)
{user_profile_summary}

## External NPC
{json.dumps(npc_entry, indent=2, ensure_ascii=False)}

## Real-World Context
{real_world_context if real_world_context else "(Use your training knowledge.)"}

## Files to Generate
{ref_descriptions}

─────────────────────────────────────────────────────────
## YOUR TASK

Create each file listed above in `external_refs/{npc_id}/`.

**Follow the tool/library reference and content_scale guidelines in CLAUDE.md.**

- Use the `description` to guide content generation
- If `intentional_errors` are specified, embed them naturally as genuine mistakes
- Content must be **professional, domain-accurate, and realistic** —
  these are input data and quality benchmarks for the simulation

## PATH RULE
All paths must start with `external_refs/{npc_id}/`.

Create all files now.
"""


# ===================================================================
# Step 6.5 (continued): Workspace Prerequisite Files
# ===================================================================

def build_workspace_prereqs_prompt(
    prerequisites: list[dict],
    user_profile_summary: str,
) -> str:
    """Build prompt for generating workspace prerequisite files.

    These go into the user's drives/ filesystem.
    """
    prereqs_json = json.dumps(prerequisites, indent=2, ensure_ascii=False)

    return f"""\
You are generating **workspace prerequisite files** for a work simulation.
These are company policies, internal templates, and other documents that
must exist in the user's filesystem before daily work simulation begins.

## User
{user_profile_summary}

## Files to Generate
{prereqs_json}

─────────────────────────────────────────────────────────
## YOUR TASK

Create each file listed above.

**Follow the PATH RULE, tool/library reference, and content_scale guidelines in CLAUDE.md.**
Convert logical paths (e.g. `C:/Users/alice/file.docx`) to `drives/C/Users/alice/file.docx`.

Create all files now.
"""

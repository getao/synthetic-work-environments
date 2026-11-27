"""Prompt templates for each Cold Start pipeline step (Steps 1-5) — macOS flavor."""

# ---------------------------------------------------------------------------
# Step 1: Persona → User Profile
# ---------------------------------------------------------------------------

def build_user_profile_prompt(persona: str) -> str:
    return f"""\
You are building a realistic macOS filesystem simulation for a specific user.

## Your Task

Given the user persona below, expand it into a **concrete, actionable, work-oriented user profile** and write it to `user_profile.json` in the current directory.

## User Persona

{persona}

## Output Requirements

Write a single JSON file `user_profile.json` with EXACTLY this structure (fill in all fields with realistic, specific values inferred from the persona):

```json
{{
  "identity": {{
    "full_name": "<realistic full name>",
    "username": "<lowercase first name or short alias>",
    "role": "<job title>",
    "organization": "<company/institution>",
    "location": "<city, state/country>",
    "career_stage": "<early_career | mid_career | senior | executive>"
  }},
  "biographical_summary": {{
    "short_bio": "<2-3 sentence bio covering who they are, what they do, and their work focus>"
  }},
  "career_profile": {{
    "career_summary": "<1-2 sentence career overview>",
    "experience_highlights": ["<highlight 1>", "<highlight 2>", "..."],
    "career_history": [
      {{
        "period": "<year range>",
        "role": "<title>",
        "organization": "<org>",
        "focus": "<what they focused on>",
        "notable_work": ["<item 1>", "<item 2>"]
      }}
    ],
    "notable_achievements": ["<achievement 1>", "..."]
  }},
  "historical_work_context": {{
    "historical_focus_timeline": [
      {{
        "time_range": "<YYYY-MM to YYYY-MM>",
        "focus": "<what they were working on>",
        "notes": "<brief context>"
      }}
    ]
  }},
  "work_context": {{
    "primary_responsibilities": ["<resp 1>", "..."],
    "likely_project_types": ["<type 1>", "..."],
    "current_focus_areas": ["<area 1>", "..."],
    "common_document_types": ["<type 1>", "..."]
  }},
  "current_projects_overview": [
    {{
      "project_id": "project_<short_name>",
      "name": "<descriptive project name>",
      "what_it_is": "<1-2 sentence description>",
      "user_role": "<their role in this project>",
      "why_it_matters": "<why this project is important to them>"
    }}
  ],
  "work_style": {{
    "work_patterns": ["<pattern 1>", "..."],
    "strengths": ["<strength 1>", "..."],
    "weaknesses": ["<weakness 1>", "..."],
    "preferred_inputs": ["<input type 1>", "..."],
    "preferred_outputs": ["<output type 1>", "..."]
  }},
  "document_behavior": {{
    "documents_written_well": ["<type 1>", "..."],
    "documents_written_less_well": ["<type 1>", "..."],
    "editing_habits": ["<habit 1>", "..."],
    "naming_behavior": {{
      "usually_descriptive": true,
      "sometimes_keeps_default_names": false,
      "uses_version_suffixes": true
    }}
  }},
  "collaboration_context": {{
    "manager_relationship": "<description>",
    "peer_collaboration_style": "<description>",
    "direct_report_context": "<description or 'none'>",
    "external_stakeholder_context": "<description>"
  }},
  "related_people": [
    {{
      "name": "<full name>",
      "role": "<their role>",
      "relationship": "<manager | peer | direct_report | external>",
      "context": "<how they interact>"
    }}
  ],
  "external_relationships": [
    {{
      "name": "<org/entity name>",
      "type": "<client | vendor | grant sponsor | etc.>",
      "relationship_to_user": "<description>",
      "relationship_to_projects": ["<project_id>"],
      "notes": "<context>"
    }}
  ],
  "filesystem_relevant_traits": {{
    "tech_level": "<low | intermediate | advanced>",
    "computer_usage_level": "<low | medium | high>",
    "tidiness": "<low | medium | high>"
  }}
}}
```

## Important Guidelines

- Invent realistic, specific details — real-sounding names, organizations, locations
- Create 2-5 current projects that make sense for this persona
- Create 3-6 related people with diverse relationships
- The profile should feel like a real person, not a template
- career_history should have 2-4 entries spanning several years
- historical_focus_timeline should cover the last 2-3 years
- current_projects_overview project_ids must use the format "project_<short_name>"
- Write ONLY the JSON file, no other output
"""


# ---------------------------------------------------------------------------
# Step 2: User Profile → Filesystem Policy
# ---------------------------------------------------------------------------

def build_filesystem_policy_prompt(profile_json: str, current_timestamp: str, system_start_timestamp: str) -> str:
    return f"""\
You are building a realistic macOS filesystem simulation.

## Your Task

Given the user profile below, derive the user's **filesystem behavior pattern** and write it to `filesystem_policy.json` in the current directory.

## User Profile

```json
{profile_json}
```

## Current Timestamp (upper bound for all dates)

{current_timestamp}

## System Start Timestamp (pre-determined, DO NOT change)

{system_start_timestamp}

## Output Requirements

Write a single JSON file `filesystem_policy.json` with EXACTLY this structure:

```json
{{
  "system_start_timestamp": "{system_start_timestamp}",
  "volume_layout": [
    {{"name": "Macintosh HD", "role": "primary"}}
  ],
  "default_paths": {{
    "desktop": "/Users/<username>/Desktop",
    "documents": "/Users/<username>/Documents",
    "downloads": "/Users/<username>/Downloads",
    "pictures": "/Users/<username>/Pictures",
    "music": "/Users/<username>/Music",
    "movies": "/Users/<username>/Movies",
    "library": "/Users/<username>/Library",
    "icloud_drive": "/Users/<username>/Library/Mobile Documents/com~apple~CloudDocs",
    "applications": "/Applications"
  }},
  "storage_patterns": {{
    "office_files_usually_go_to": ["<path or alias>"],
    "downloads_usually_go_to": ["<path or alias>"],
    "screenshots_usually_go_to": ["<path or alias>"],
    "project_files_usually_go_to": ["<path or alias>"],
    "temporary_files_often_end_up_in": ["<path or alias>"]
  }},
  "organization_style": {{
    "tidiness": "<low | medium | high>",
    "uses_project_folders": true,
    "default_folder_piling": true,
    "desktop_clutter_likelihood": "<low | medium | high>",
    "download_clutter_likelihood": "<low | medium | high>",
    "uses_icloud_drive": true,
    "uses_stacks_on_desktop": false
  }},
  "naming_style": {{
    "is_consistent": false,
    "uses_version_suffixes": true,
    "keeps_default_filenames": true,
    "common_default_names": ["<name 1>", "..."]
  }},
  "usage_patterns": {{
    "computer_usage_level": "<low | medium | high>",
    "frequently_downloads_files": true,
    "frequently_creates_documents": true,
    "frequently_edits_existing_files": true,
    "frequently_switches_between_projects": true,
    "frequently_takes_screenshots": false
  }}
}}
```

## Important Guidelines

- `system_start_timestamp` is pre-determined and provided above. Use it EXACTLY as given — do NOT change it.
- The `username` in paths must match the `identity.username` from the user profile. macOS usernames are lowercase, typically the short-name.
- `volume_layout`: most ordinary users have only `Macintosh HD` (the default primary boot volume name on macOS). Power users, videographers, or photographers may have additional external volumes (e.g. `{{"name": "ExternalBackup", "role": "external"}}`). Decide based on tech_level and role.
- Screenshots on macOS default to Desktop (unless the user changed it via `screencapture` settings).
- Many users store their work in iCloud Drive (`~/Library/Mobile Documents/com~apple~CloudDocs/`) instead of local `Documents`. Decide based on the user.
- `storage_patterns`, `organization_style`, `naming_style`, and `usage_patterns` should all be consistent with the user profile's `filesystem_relevant_traits`, `work_style`, and `document_behavior`.
- Be diverse — not every user is tidy, not every user is messy. Reflect THIS specific user.
- Write ONLY the JSON file, no other output.
"""


# ---------------------------------------------------------------------------
# Step 3: Joint Planning (Project Index + File List + File Graph)
# ---------------------------------------------------------------------------

def build_planning_prompt(
    profile_json: str,
    policy_json: str,
    current_timestamp: str,
) -> str:
    return f"""\
You are building a realistic macOS filesystem simulation.

## Your Task

Given the user profile and filesystem policy below, jointly plan:
1. `project_index.json` — the project semantic layer
2. `file_list.json` — what files exist on this user's Mac
3. `file_graph.json` — relationships between files

Write ALL THREE files to the current directory.

## User Profile

```json
{profile_json}
```

## Filesystem Policy

```json
{policy_json}
```

## Current Timestamp (upper bound)

{current_timestamp}

## Schema for project_index.json

```json
{{
  "projects": [
    {{
      "project_id": "project_<short_name>",
      "name": "<descriptive name>",
      "description": "<what the project is about>",
      "tags": ["<tag1>", "..."],
      "related_people": ["<person name>"],
      "related_projects": ["<other project_id>"],
      "activity_timeline": [
        {{
          "start": "<YYYY-MM-DD>",
          "end": "<YYYY-MM-DD>",
          "level": "<very_active | active | low_activity | inactive | completed>"
        }}
      ]
    }}
  ]
}}
```

## Schema for file_list.json

An array of file entries:

```json
[
  {{
    "path": "<macOS logical path like /Users/username/Documents/file.docx>",
    "timestamp": "<ISO datetime>",
    "origin": "<user_created | web_download | shared | system_generated>",
    "description": "<what this file is and what it contains>",
    "content_mode": "<generate | download | skip>",
    "download_hint": "<URL or search query for download files, omit for non-download files>",
    "extract": false,
    "content_scale": "<small | medium | large — only for content_mode 'generate'>",
    "project_ids": ["<project_id or empty array>"],
    "derived_from": ["<path of source file, or empty array>"],
    "content_generated": false
  }}
]
```

## Schema for file_graph.json

```json
{{
  "nodes": [
    {{
      "path": "<file path>",
      "project_ids": ["<project_id>"]
    }}
  ],
  "edges": [
    {{
      "from": "<source file path>",
      "to": "<derived file path>",
      "type": "<derived_from | version_of | extracted_from | references>"
    }}
  ]
}}
```

## CRITICAL CONSTRAINTS

### File Count
- Target: 50-100 files total
- This includes ALL files: user-created, downloads, shared, system-generated

### Time Constraints
- system_start_timestamp (from filesystem_policy) is the LOWER BOUND for all timestamps
- current_timestamp ({current_timestamp}) is the UPPER BOUND for all timestamps
- Every file timestamp must satisfy: system_start_timestamp <= timestamp <= current_timestamp
- Child files must have later timestamps than parent files
- Newer versions must have later timestamps than older versions

### File Origins — Proportions Must Be Inferred From User Profile
- Do NOT use fixed percentages
- An office worker should have more documents and downloads
- A developer should have more code files and configs
- A researcher should have more PDFs and notes
- The mix must feel realistic for THIS specific user

### Content Modes
- `generate`: for files whose content should be created by AI (documents, code, notes, images, charts, etc.). This includes `.docx`, `.xlsx`, `.pptx`, `.pdf`, `.png`, `.jpg` — all of these CAN be generated. Charts and data visualizations should use matplotlib/plotly.
- `download`: for files obtained from the internet (PDFs, forms, templates, archives)
- `skip`: for installers (.dmg, .pkg), `.app` bundles from the App Store, large archives that won't be extracted, and other files that cannot be meaningfully generated — only a placeholder will be created. Do NOT use `skip` for images, Office documents, or PDFs.

### CRITICAL: Download Files Must Be Real and Downloadable
When planning files with `content_mode: "download"`, you MUST prefer documents that **actually exist on the public internet as free, direct-download PDFs or files**. Do NOT invent fictional document names for downloads.

Good examples of real, publicly downloadable files:
- IRS forms: Form W-4, Form W-9, Form 1099, Form 970 (irs.gov)
- SEC filings: 10-K, 10-Q annual reports (sec.gov/edgar)
- Government forms: I-9, SF-86, state tax forms
- Open-access academic papers (arxiv.org, SSRN)
- Software documentation PDFs (official docs from Apple, Oracle, Microsoft, SAP, etc.)
- Public standards documents (ISO previews, NIST publications)
- Open-source project archives from GitHub (.zip releases)
- Public dataset CSV/Excel files (data.gov, census.gov, WHO, World Bank)

Bad examples (will fail to download):
- "ASC330_Inventory_FASB.pdf" — FASB standards are behind a paywall
- "IMA_InventoryCosting_PracticeGuide.pdf" — IMA guides require membership
- "NetSuite_CostAccounting_UserGuide_2024.pdf" — vendor docs are login-gated
- Any fictional document with a made-up name

For each download file, include a `download_hint` field with either:
- A known direct URL, OR
- A search query that will find the real file (e.g., "IRS Form W-4 site:irs.gov filetype:pdf")

If the user's work context requires reference to paywalled/gated content (e.g., FASB standards, vendor manuals), mark those as `content_mode: "generate"` with `origin: "shared"` or `origin: "web_download"` instead — they will be realistically generated rather than downloaded.

### File Graph Constraints
- Must be a DAG (no cycles)
- Edges represent real relationships: derived_from, version_of, extracted_from, references
- All file paths in edges must exist in file_list

### Diversity Requirements
- Files must span across different directories (Desktop, Documents, Downloads, project folders, iCloud Drive, Library, etc.)
- Include files from MULTIPLE time periods (not all clustered at one date)
- Include MULTIPLE projects at different activity levels
- Include non-project files (admin docs, downloads, screenshots, personal files, tax forms, etc.)
- Include some messy/disorganized elements realistic for this user's tidiness level
- Projects should have interleaved timelines (user works on multiple things over time)

### Path Requirements
- All paths must use macOS logical paths starting with `/Users/<username>/`, `/Applications/`, or `/Volumes/<VolumeName>/`.
- Do NOT use Windows drive letters (no `C:/`, `D:/`).
- The primary volume's files are under `/Users/<username>/...`, `/Applications/...`, etc. External-volume files are under `/Volumes/<VolumeName>/...`.
- All volumes referenced must appear in `volume_layout` from the filesystem_policy.
- Use the username from the user profile.
- Common macOS-specific locations to consider (as appropriate for the user):
  - `/Users/<u>/Desktop`, `/Users/<u>/Documents`, `/Users/<u>/Downloads`, `/Users/<u>/Pictures`, `/Users/<u>/Music`, `/Users/<u>/Movies`, `/Users/<u>/Public`
  - `/Users/<u>/Library/Mobile Documents/com~apple~CloudDocs/` — iCloud Drive
  - `/Users/<u>/Library/Application Support/<AppName>` — some app-private user data leaks here
  - Project folders under `/Users/<u>/Code`, `/Users/<u>/Projects`, `/Users/<u>/Work` (user-chosen conventions vary)

### Archive Patterns
- Downloaded archives (.zip, .tar.gz, .dmg, etc.) should be listed as a SINGLE entry with `content_mode: "download"`
- Decide whether the user would extract the archive: set `"extract": true` if yes, `"extract": false` if not
- Do NOT list the extracted contents as separate entries in file_list — the actual extracted files are unknown until extraction happens at generation time
- Do NOT add extracted file paths to file_graph nodes/edges at planning time — those will be added after real extraction
- CRITICAL: Archive download_hints must point to **real, publicly available archives** (e.g., GitHub release .zip files, open dataset archives, government data packages). Archives cannot be fallback-generated, so they MUST be downloadable.

### Content Scale — Realistic File Sizes
Every file with `content_mode: "generate"` must have a `content_scale` field. Files with `content_mode: "download"` do NOT need `content_scale` (downloaded files are whatever size they are).

- `small`: a quick note, short memo, simple spreadsheet (~10-30 rows), 1-page doc, brief script
- `medium`: a typical working document (3-8 pages), a data sheet (50-200 rows), a multi-section report, a moderate codebase file
- `large`: a major deliverable (15+ pages), a substantial dataset (500-2000+ rows), a comprehensive report, a long analysis notebook

**Distribution should adapt to THIS user — do NOT use fixed percentages.**
- A data analyst may have many `large` Excel datasets but `small` notes
- A manager may have several `large` reports and presentations
- A developer may have mostly `medium` code files with few `large` ones
- A student may have mostly `small` files with one or two `large` papers
- Think about what THIS user's key deliverables are — those should be `large`
- Everyday notes, quick memos, and scratch files should be `small`
- The distribution should feel natural for the user's role and work patterns

### Version Chains
- Some documents should have version chains (v1 → v2 → final)
- Use "version_of" edge type in file_graph
- Timestamps must be chronologically ordered

## Important Guidelines

- Think of this as planning the "skeleton" of a real person's Mac
- The file list should tell a story of someone working over time
- Include a mix of organized project work AND scattered miscellaneous files
- Write ALL THREE JSON files to the current directory
- Do NOT create any actual file content yet — only the metadata
"""


# ---------------------------------------------------------------------------
# Step 5: File Content Generation (batched)
# ---------------------------------------------------------------------------

def build_file_generation_prompt(
    batch: list[dict],
    activity_log_entries: list[dict],
    file_graph_edges: list[dict],
    user_profile_summary: str,
    world_root: str,
) -> str:
    import json

    batch_json = json.dumps(batch, indent=2, ensure_ascii=False)
    activity_json = json.dumps(activity_log_entries, indent=2, ensure_ascii=False) if activity_log_entries else "[]"
    edges_json = json.dumps(file_graph_edges, indent=2, ensure_ascii=False) if file_graph_edges else "[]"

    return f"""\
You are generating realistic file contents for a simulated macOS environment.

**Follow the PATH RULE, tool/library reference, and content_scale guidelines in CLAUDE.md.**

## User Context

{user_profile_summary}

## Recent Activity Log

```json
{activity_json}
```

## Relevant File Graph Edges

```json
{edges_json}
```

## Files to Process (in chronological order)

```json
{batch_json}
```

## Instructions

Process EACH file in the batch above, in order. For each file:

### If content_mode = "generate"
- Convert logical path to `drives/...` format (e.g. `/Users/alice/Documents/x.docx` → `drives/Macintosh HD/Users/alice/Documents/x.docx`; `/Volumes/ExtDrive/y` → `drives/ExtDrive/y`). Create parent dirs with `mkdir -p`.
- Generate realistic, contextually appropriate content matching the description
- Use the correct tool/library for the file type (see CLAUDE.md)
- Respect `content_scale` (see CLAUDE.md) — `large` files are key deliverables
- If derived_from another file, content should build on or reference the source
- Version chains: later versions should show evolution from earlier versions

### If content_mode = "download"
1. Download using `download_hint` (URL or search query) → save to correct `drives/...` path
2. If download fails, generate a realistic fallback using the correct tool (see CLAUDE.md). Archives cannot be fallback-generated — remove from file_list.json and file_graph.json.
3. If archive with `"extract": true`, extract after downloading. Update file_list.json, file_graph.json, and activity_log.jsonl with extracted files.

### If content_mode = "skip"
- Create the file with a single line: "[placeholder]"

## After Processing Each File

Append an activity log entry to `activity_log.jsonl` (see CLAUDE.md for format).
The activity must explain what task, what file, what it contains, how it connects to projects.

## Reminders
- Paths with spaces (like `Macintosh HD`) MUST be quoted in bash: `mkdir -p "drives/Macintosh HD/Users/..."`
- Process files in chronological order
- Append to activity_log.jsonl, do not overwrite
"""

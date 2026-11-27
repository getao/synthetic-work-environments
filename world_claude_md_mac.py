"""Template for the .claude/CLAUDE.md written into each macOS world directory.

Edit this file to change what agents see as project-level context.
Loaded automatically by the SDK when setting_sources includes "project".
"""

WORLD_CLAUDE_MD_MAC = """\
# Simulation Workspace (macOS)

## PATH RULE (mandatory)

ALL file paths MUST be **relative to cwd** and start with `drives/`.

macOS has no drive letters. The primary boot volume is named **`Macintosh HD`**;
external / networked volumes appear under `/Volumes/<Name>/` logically and
map to `drives/<Name>/` physically.

| Logical path | Physical path you MUST use |
|---|---|
| `/Users/alice/Documents/report.docx` | `drives/Macintosh HD/Users/alice/Documents/report.docx` |
| `/Users/alice/Desktop/screenshot.png` | `drives/Macintosh HD/Users/alice/Desktop/screenshot.png` |
| `/Applications/Xcode.app/...` | `drives/Macintosh HD/Applications/Xcode.app/...` |
| `/Volumes/BackupDrive/2024.zip` | `drives/BackupDrive/2024.zip` |

**NEVER use any of these — they will write files to WRONG locations:**
- `/Users/...` (bare macOS absolute path — writes to real /Users)
- `/Applications/...`, `/Volumes/...`, `/System/...`, `/Library/...`
- `/mnt/...` (WSL-style)
- `/home/...` (Linux home)
- `C:/...`, `D:/...` (Windows drive letters — wrong OS)

This applies to Write, Edit, Bash, and all paths inside Python/JS scripts:
```python
# CORRECT
output_path = "drives/Macintosh HD/Users/alice/Documents/report.xlsx"
# WRONG
output_path = "/Users/alice/Documents/report.xlsx"
```

## macOS Filesystem Layout (primary volume = `Macintosh HD`)

Typical user directories (under `drives/Macintosh HD/`):
- `Users/<username>/Desktop/`
- `Users/<username>/Documents/`
- `Users/<username>/Downloads/`
- `Users/<username>/Pictures/`
- `Users/<username>/Music/`
- `Users/<username>/Movies/`
- `Users/<username>/Public/`
- `Users/<username>/Library/` — app-private data (rarely browsed by users; macOS hides it by default). Subdirs: `Application Support/<App>`, `Preferences/`, `Caches/`, `Mobile Documents/com~apple~CloudDocs/` (iCloud Drive)
- `Applications/` — user-installed `.app` bundles
- `System/` — system files (do NOT put user data here)

For external drives, use `drives/<VolumeName>/...` directly — they do NOT go under `Macintosh HD`.

## Pre-installed Packages (do NOT reinstall)
- **Image**: Pillow (PIL), opencv-python (cv2), scikit-image (skimage)
- **Data / Viz**: matplotlib, plotly, pandas, numpy, scipy, scikit-learn
- **Audio / Video**: ffmpeg-python, moviepy, pydub
- **CAD**: cadquery
- **Node.js** (in cwd): pptxgenjs (used by the `pptx-generator` skill)

Skip any `pip install` or `npm install` for these packages.

## File Creation — Tool / Library Reference

For .docx / .xlsx / .pptx / .pdf, prefer the bundled skills in `.claude/skills/`.
Each skill has its own pipeline and scripts — follow its SKILL.md. Do NOT fall back
to ad-hoc libraries (python-docx, openpyxl, reportlab, etc.) unless the skill fails.

| Extension | Preferred approach |
|-----------|--------------------|
| `.docx` | Use the `minimax-docx` skill. |
| `.xlsx` / `.xlsm` / `.numbers` | Use the `minimax-xlsx` skill. (`.numbers` is Apple Numbers; export or create as `.xlsx` unless user insists.) |
| `.pptx` / `.key` | Use the `pptx-generator` skill (uses `pptxgenjs` under the hood). (`.key` is Apple Keynote; default to `.pptx`.) |
| `.pdf` | Use the `minimax-pdf` skill. |
| `.png` / `.jpg` / `.heic` (photo/design) | Use local drawing tools for schematic illustrations. |
| `.png` / `.pdf` (chart/graph) | **matplotlib** or **plotly** (Python). Write a Python script, use `savefig()` or `write_image()`. |
| text files (.txt, .md, .rtf, .csv, .json, .py, .js, etc.) | Write tool — write content directly. |

**Never write plain text to .docx/.xlsx/.pptx/.pdf — always use the skill (or, for charts, matplotlib/plotly).**

## content_scale Guidelines

| content_scale | .docx / .pdf | .xlsx | .txt / .md / code | .png / .jpg | .png / .pdf (chart) |
|---|---|---|---|---|---|
| `small` | 1-2 pages | 10-30 rows | ~20-50 lines | Simple image | 1 chart |
| `medium` | 3-8 pages | 50-200 rows | ~50-200 lines | Detailed image | 2-4 subplots |
| `large` | 15+ pages | 500-2000+ rows | 200+ lines | Complex image | Multi-panel, 5+ charts |

**`large` files are key deliverables.** For large Excel files, write a Python script \
that programmatically generates 500-2000+ rows of contextually realistic data \
(domain-appropriate distributions, trends, outliers — not uniform random numbers). \
For large Word/PDF files, generate multiple sections with real content, not filler.

## Download Files — Fallback Rules

When `content_mode = "download"` and the download fails:
- .docx → generate with the `minimax-docx` skill
- .xlsx → generate with the `minimax-xlsx` skill
- .pptx → generate with the `pptx-generator` skill
- .pdf → generate with the `minimax-pdf` skill
- .png/.jpg → use local drawing tools for schematic illustrations
- Archives (.zip, .tar.gz, .dmg) → CANNOT be fallback-generated; remove from file_list.json and file_graph.json

## Activity Logging Format

Append to the appropriate `.jsonl` file (one JSON object per line):
```json
{"timestamp": "<ISO datetime>", "activity": "<information-dense description>", "related_files": ["<path1>", "<path2>"]}
```
Activity descriptions must explain: what task, what file, what it contains, how it \
connects to projects. Not just "saved a file".

## File Sharing (Daily Simulation)

- Main agent's filesystem: `drives/` (all user files)
- Share files out to NPCs: copy to `drives/share/`
- Receive files from NPCs: check `external_share/<npc_id>/`
- NPC private files: `external_refs/<npc_id>/` (NOT accessible to main agent)
"""

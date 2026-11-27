"""Shared utilities for all pipeline agents.

Contains the core SDK wrapper (call_claude), dependency pre-installation,
path guards, file helpers, and usage tracking.
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import time

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    UserMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    ThinkingBlock,
    ResultMessage,
    PermissionResultAllow,
    PermissionResultDeny,
)

from system_prompt import SYSTEM_PROMPT_APPEND
from world_claude_md import WORLD_CLAUDE_MD


# ---------------------------------------------------------------------------
# PATH fix: ensure modern node (installed under /usr/local/bin by `n`) wins
# over the system node in /usr/bin. Some skill scripts (pptx-generator,
# minimax-pdf) need Node 16+.
# ---------------------------------------------------------------------------
_PATH_PRIORITY_DIRS = ["/usr/local/bin"]
_current_path = os.environ.get("PATH", "")
_path_entries = _current_path.split(os.pathsep) if _current_path else []
_reordered = [p for p in _PATH_PRIORITY_DIRS if p not in _path_entries[: len(_PATH_PRIORITY_DIRS)]]
if _reordered:
    remaining = [p for p in _path_entries if p not in _PATH_PRIORITY_DIRS]
    os.environ["PATH"] = os.pathsep.join(_PATH_PRIORITY_DIRS + remaining)


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def _build_system_prompt(cwd: str, os_flavor: str = "windows") -> dict:
    """Build system prompt from template — identity + path hard-rule only.

    Detailed guidance (packages, file-type tools, examples) lives in
    <world_dir>/.claude/CLAUDE.md and is loaded automatically by the SDK.
    """
    abs_cwd = os.path.abspath(cwd).replace("\\", "/")
    if os_flavor == "macos":
        from system_prompt_mac import SYSTEM_PROMPT_APPEND_MAC
        template = SYSTEM_PROMPT_APPEND_MAC
    else:
        template = SYSTEM_PROMPT_APPEND
    return {
        "type": "preset",
        "preset": "claude_code",
        "append": template.format(cwd=abs_cwd),
    }


# ---------------------------------------------------------------------------
# Path guard
# ---------------------------------------------------------------------------

# Regex: bare Windows drive letter path (C:/ D:/ etc.) NOT preceded by "drives/"
_BARE_DRIVE_RE = re.compile(r'(?<!/)\b[A-Z]:[/\\]')

# Regex: bare macOS user-data path (/Users/, /Volumes/, /Applications/)
# NOT preceded by "drives/" (or part of a longer path like "foo/Users/bar").
_BARE_MAC_PATH_RE = re.compile(r'(?<![\w/])/(?:Users|Volumes|Applications)(?=/)')


def _make_path_guard(allowed_dir: str, os_flavor: str = "windows"):
    """Return a can_use_tool callback that blocks writes outside allowed_dir.

    os_flavor: "windows" blocks bare drive letters (C:/, D:/), "macos" blocks
    bare macOS user-data paths (/Users/, /Volumes/, /Applications/).
    """
    allowed_prefix = os.path.normcase(os.path.abspath(allowed_dir)) + os.sep

    async def _guard(tool_name, tool_input, _context):
        # Guard Write / Edit — check file_path
        if tool_name in ("Write", "Edit", "NotebookEdit"):
            file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
            abs_path = os.path.normcase(os.path.abspath(file_path))
            if not abs_path.startswith(allowed_prefix):
                return PermissionResultDeny(
                    message=f"BLOCKED: path {file_path} is outside allowed directory {allowed_dir}"
                )

        # Guard Bash — reject commands containing bare logical paths
        if tool_name == "Bash":
            command = tool_input.get("command", "")
            if os_flavor == "windows":
                if _BARE_DRIVE_RE.search(command):
                    return PermissionResultDeny(
                        message=f"BLOCKED: command contains a bare Windows drive path. "
                                f"Use drives/C/ or drives/D/ instead."
                    )
            elif os_flavor == "macos":
                if _BARE_MAC_PATH_RE.search(command):
                    return PermissionResultDeny(
                        message=f"BLOCKED: command contains a bare macOS logical path "
                                f"(/Users/, /Volumes/, /Applications/). "
                                f"Use drives/Macintosh HD/Users/... instead."
                    )

        return PermissionResultAllow()

    return _guard


# ---------------------------------------------------------------------------
# Stray file cleanup
# ---------------------------------------------------------------------------

_STRAY_DIRS = ["mnt", "d", "home"]

import shutil


def _cleanup_stray_files(world_dir: str, log_fn=None):
    """Remove stray directories created by Git Bash path confusion.

    Claude Code on Git Bash sometimes writes to /mnt/d/..., /d/..., /home/...
    which end up as D:\\mnt, D:\\d, D:\\home on Windows.
    Only runs on Windows — on macOS/Linux these are real system directories.
    """
    drive = os.path.splitdrive(os.path.abspath(world_dir))[0]  # e.g. "D:"
    if not drive:
        # Not on Windows (no drive letter) — skip to avoid deleting real dirs
        return 0
    removed = 0
    for dirname in _STRAY_DIRS:
        stray = os.path.join(drive + os.sep, dirname)
        if os.path.isdir(stray):
            try:
                count = sum(len(files) for _, _, files in os.walk(stray))
                shutil.rmtree(stray)
                removed += count
                if log_fn:
                    log_fn(f"CLEANUP: removed {stray} ({count} files)")
            except Exception as e:
                if log_fn:
                    log_fn(f"CLEANUP: failed to remove {stray}: {e}")
    return removed


# ---------------------------------------------------------------------------
# SDK helpers
# ---------------------------------------------------------------------------

async def _as_stream(text: str):
    """Wrap a string prompt as an async iterable (required for can_use_tool)."""
    yield {"type": "user", "message": {"role": "user", "content": text}}


def _truncate(s: str, max_len: int = 200) -> str:
    """Truncate a string for logging."""
    if len(s) <= max_len:
        return s
    return s[:max_len] + f"...({len(s)} chars)"


# ---------------------------------------------------------------------------
# Core SDK wrapper
# ---------------------------------------------------------------------------

async def call_claude(
    prompt: str,
    cwd: str,
    max_turns: int = 10,
    plugins: list | None = None,
    model: str | None = None,
    mcp_servers: dict | None = None,
    log_file: str | None = None,
    turn_log_file: str | None = None,
    step_label: str = "",
    os_flavor: str = "windows",
) -> dict:
    """Call Claude Code CLI via the SDK and return result info.

    Returns a dict with keys: text, cost_usd, usage, duration_ms, num_turns.

    Args:
        mcp_servers: Optional MCP server configs to register with the agent.
        log_file: If set, stream Claude Code output to this file instead of stdout.
        turn_log_file: If set, write per-turn diagnostic JSONL to this file.
        step_label: Label for this session in the turn log.
        os_flavor: "windows" or "macos" — selects which system prompt and
            path guard to apply. Defaults to "windows" for backward compat.
    """
    options = ClaudeAgentOptions(
        system_prompt=_build_system_prompt(cwd, os_flavor=os_flavor),
        permission_mode="bypassPermissions",
        cwd=cwd,
        max_turns=max_turns,
        can_use_tool=_make_path_guard(cwd, os_flavor=os_flavor),
        # Load project .claude/CLAUDE.md + .claude/settings.json (no "user" for reproducibility)
        setting_sources=["project"],
    )
    if plugins:
        options.plugins = plugins
    if model:
        options.model = model
    if mcp_servers:
        options.mcp_servers = mcp_servers

    output_parts: list[str] = []
    result_info: dict = {}
    fh = open(log_file, "a", encoding="utf-8") if log_file else None
    turn_fh = open(turn_log_file, "a", encoding="utf-8") if turn_log_file else None
    if turn_fh and step_label:
        turn_fh.write(json.dumps({"type": "session_start", "step": step_label, "max_turns": max_turns}) + "\n")
        turn_fh.flush()

    turn_num = 0
    turn_t0 = time.monotonic()

    try:
        async for message in query(prompt=_as_stream(prompt), options=options):
            if isinstance(message, AssistantMessage):
                turn_num += 1
                now = time.monotonic()
                turn_elapsed = round(now - turn_t0, 1)
                turn_t0 = now

                # Collect block summaries
                tool_calls = []
                text_len = 0
                thinking_len = 0
                for block in message.content:
                    if isinstance(block, TextBlock):
                        if fh:
                            fh.write(block.text)
                            fh.flush()
                        else:
                            print(block.text, end="", flush=True)
                        output_parts.append(block.text)
                        text_len += len(block.text)
                    elif isinstance(block, ToolUseBlock):
                        tool_input = block.input or {}
                        # Summarize tool input
                        if block.name in ("Write", "Edit"):
                            summary = {
                                "file_path": tool_input.get("file_path", ""),
                                "content_len": len(tool_input.get("content", "")),
                            }
                        elif block.name == "Read":
                            summary = {"file_path": tool_input.get("file_path", "")}
                        elif block.name == "Bash":
                            summary = {"command": _truncate(tool_input.get("command", ""), 300)}
                        elif block.name == "Glob":
                            summary = {"pattern": tool_input.get("pattern", "")}
                        elif block.name == "Grep":
                            summary = {
                                "pattern": tool_input.get("pattern", ""),
                                "path": tool_input.get("path", ""),
                            }
                        elif block.name == "WebSearch":
                            summary = {"query": tool_input.get("query", "")}
                        else:
                            summary = {k: _truncate(str(v)) for k, v in list(tool_input.items())[:3]}
                        tool_calls.append({"tool": block.name, **summary})
                    elif isinstance(block, ThinkingBlock):
                        thinking_len += len(block.thinking or "")

                # Write turn log entry
                if turn_fh:
                    entry = {
                        "turn": turn_num,
                        "elapsed_s": turn_elapsed,
                        "model": message.model,
                        "tool_calls": tool_calls,
                        "text_len": text_len,
                        "thinking_len": thinking_len,
                    }
                    turn_fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    turn_fh.flush()

            elif isinstance(message, UserMessage):
                # Log tool results for detailed replay
                if turn_fh and message.content:
                    tool_results = []
                    blocks = message.content if isinstance(message.content, list) else []
                    for block in blocks:
                        if isinstance(block, ToolResultBlock):
                            content = block.content
                            # Only truncate very long results (>10KB)
                            if isinstance(content, str):
                                content_summary = _truncate(content, 10000)
                            elif isinstance(content, list):
                                parts = []
                                for item in content:
                                    if isinstance(item, dict) and item.get("type") == "text":
                                        parts.append(_truncate(item.get("text", ""), 10000))
                                    else:
                                        parts.append(str(type(item).__name__))
                                content_summary = "; ".join(parts) if parts else "(empty)"
                            else:
                                content_summary = "(none)"
                            tool_results.append({
                                "tool_use_id": block.tool_use_id,
                                "is_error": block.is_error,
                                "content": content_summary,
                            })
                    if tool_results:
                        turn_fh.write(json.dumps({
                            "type": "tool_results",
                            "results": tool_results,
                        }, ensure_ascii=False) + "\n")
                        turn_fh.flush()

            elif isinstance(message, ResultMessage):
                result_info = {
                    "cost_usd": message.total_cost_usd or 0.0,
                    "usage": message.usage or {},
                    "duration_ms": message.duration_ms,
                    "duration_api_ms": message.duration_api_ms,
                    "num_turns": message.num_turns,
                    "session_id": message.session_id,
                }
                if turn_fh:
                    turn_fh.write(json.dumps({
                        "type": "result",
                        "num_turns": message.num_turns,
                        "cost_usd": message.total_cost_usd,
                        "duration_ms": message.duration_ms,
                        "duration_api_ms": message.duration_api_ms,
                        "usage": message.usage,
                    }, ensure_ascii=False) + "\n")
                    turn_fh.flush()
    finally:
        if fh:
            fh.write("\n")
            fh.close()
        if turn_fh:
            turn_fh.close()

    if not fh:
        print()  # newline after streamed output
    result_info["text"] = "".join(output_parts)
    return result_info


# ---------------------------------------------------------------------------
# Dependency pre-installation
# ---------------------------------------------------------------------------

# (pip_name, import_name)
_PYTHON_PACKAGES = [
    # --- Office documents ---
    ("openpyxl", "openpyxl"),           # .xlsx generation (legacy)
    ("reportlab", "reportlab"),         # .pdf generation (legacy + used by minimax-pdf fallback)
    ("python-docx", "docx"),            # .docx generation (legacy)
    ("python-pptx", "pptx"),            # .pptx generation (legacy)
    ("pymupdf", "fitz"),                # .pdf read/edit/merge (PyMuPDF)
    ("pypdf", "pypdf"),                 # .pdf form fill + merge (used by minimax-pdf skill)
    ("markitdown", "markitdown"),       # extract text from pptx/docx/pdf (used by pptx-generator skill)
    # --- Image ---
    ("Pillow", "PIL"),                  # image creation/editing
    ("opencv-python-headless", "cv2"),  # image processing
    ("scikit-image", "skimage"),        # advanced image algorithms
    # --- Data visualisation / scientific ---
    ("matplotlib", "matplotlib"),       # charts, plots, diagrams
    ("plotly", "plotly"),               # interactive charts (export to png/html)
    ("scipy", "scipy"),                 # scientific computing
    ("scikit-learn", "sklearn"),        # ML & data analysis
    ("pandas", "pandas"),               # dataframes
    ("numpy", "numpy"),                 # numerical arrays
    # --- Audio / Video ---
    ("ffmpeg-python", "ffmpeg"),        # FFmpeg wrapper for audio/video
    ("moviepy", "moviepy"),             # video editing
    ("pydub", "pydub"),                 # audio editing
    ("librosa", "librosa"),             # audio analysis
    ("soundfile", "soundfile"),         # audio I/O
    # --- CAD ---
    ("cadquery", "cadquery"),           # parametric 3D CAD modelling
    # --- Extra data/stats for realistic agent tasks ---
    ("seaborn", "seaborn"),             # statistical viz on top of matplotlib
    ("statsmodels", "statsmodels"),     # regression / time series / A-B tests
    ("xgboost", "xgboost"),             # gradient boosting
    ("lightgbm", "lightgbm"),           # gradient boosting
    ("shap", "shap"),                   # model explanation
    # --- Extra viz ---
    ("wordcloud", "wordcloud"),         # word cloud images
    ("bokeh", "bokeh"),                 # interactive charts
    ("plotnine", "plotnine"),           # ggplot-style grammar of graphics
    # --- File readers / format support ---
    ("xlrd", "xlrd"),                   # read legacy .xls
    ("pyxlsb", "pyxlsb"),               # read .xlsb
    ("odfpy", "odf"),                   # read/write OpenDocument .ods / .odt
    ("pdfplumber", "pdfplumber"),       # extract text/tables from pdf
    ("docx2txt", "docx2txt"),           # quick text extract from docx
    ("fpdf2", "fpdf"),                  # lightweight pdf generation
    # --- Text / NLP ---
    ("nltk", "nltk"),                   # tokenize / stopwords / basic NLP
    ("chardet", "chardet"),             # encoding detection
    ("markdownify", "markdownify"),     # HTML → Markdown
    ("rapidfuzz", "rapidfuzz"),         # fast fuzzy string matching
    ("beautifulsoup4", "bs4"),          # HTML/XML parsing
    # --- Utilities ---
    ("requests", "requests"),           # HTTP client
    ("faker", "faker"),                 # synthetic data generation
    ("tabulate", "tabulate"),           # pretty-print tables
    ("networkx", "networkx"),           # graph structures / algorithms
    ("sympy", "sympy"),                 # symbolic math
    ("pycountry", "pycountry"),         # ISO country / currency / language codes
]

_NPM_PACKAGES = {
    "docx": "^9.6.1",        # .docx generation (Node, legacy)
    "pptxgenjs": "^4.0.1",   # .pptx generation (Node, used by pptx-generator skill)
    "playwright": "^1.48.0", # headless browser for PDF cover rendering (used by minimax-pdf skill)
}


# Lock + flag for one-time Python package installation across concurrent worlds
_py_deps_lock = asyncio.Lock()
_py_deps_installed = False


async def _ensure_dependencies(world_dir: str, log_fn=None):
    """Pre-install Python and Node.js packages into the world directory.

    - Python packages: installed once per process (guarded by asyncio.Lock).
    - Node packages: installed per world_dir into node_modules via package.json.

    Safe for cross-world concurrent calls.
    """
    global _py_deps_installed
    log = log_fn or (lambda msg: print(msg, flush=True))

    # --- Python packages (process-wide, install once) ---
    async with _py_deps_lock:
        if not _py_deps_installed:
            missing_py = []
            for pip_name, import_name in _PYTHON_PACKAGES:
                try:
                    __import__(import_name)
                except ImportError:
                    missing_py.append(pip_name)

            if missing_py:
                log(f"Pre-installing Python packages: {', '.join(missing_py)}")
                pip_cmd = [shutil.which("uv"), "pip", "install", "--quiet"] if shutil.which("uv") else [sys.executable, "-m", "pip", "install", "--quiet"]
                proc = await asyncio.create_subprocess_exec(
                    *pip_cmd, *missing_py,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.wait()
                if proc.returncode != 0:
                    stderr = await proc.stderr.read()
                    raise RuntimeError(f"uv pip install failed: {stderr.decode()}")
            else:
                log("Python packages already installed.")
            _py_deps_installed = True

    # --- Node.js packages (per-world, can run concurrently) ---
    pkg_json_path = os.path.join(world_dir, "package.json")
    node_modules = os.path.join(world_dir, "node_modules")

    # Write package.json if missing or outdated
    need_npm = False
    if os.path.exists(pkg_json_path):
        existing = json.loads(open(pkg_json_path, "r").read())
        existing_deps = existing.get("dependencies", {})
        if all(k in existing_deps for k in _NPM_PACKAGES):
            # Check node_modules exists
            if os.path.isdir(node_modules):
                log("Node packages already installed.")
            else:
                need_npm = True
        else:
            # Merge in any missing packages
            existing_deps.update(_NPM_PACKAGES)
            existing["dependencies"] = existing_deps
            with open(pkg_json_path, "w") as f:
                json.dump(existing, f, indent=2)
            need_npm = True
    else:
        with open(pkg_json_path, "w") as f:
            json.dump({"dependencies": _NPM_PACKAGES}, f, indent=2)
        need_npm = True

    if need_npm:
        log(f"Pre-installing Node packages: {', '.join(_NPM_PACKAGES.keys())}")
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        proc = await asyncio.create_subprocess_exec(
            npm_cmd, "install",
            cwd=world_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.wait()
        if proc.returncode != 0:
            stderr = await proc.stderr.read()
            raise RuntimeError(f"npm install failed: {stderr.decode()}")
    log("Dependency pre-installation complete.")


# ---------------------------------------------------------------------------
# JSON / JSONL helpers
# ---------------------------------------------------------------------------

def _read_json(path: str) -> dict | list:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        if "Extra data" in str(e):
            # Agent appended multiple JSON objects — parse just the first one
            decoder = json.JSONDecoder()
            result, _ = decoder.raw_decode(raw)
            # Re-write the file with only the valid first object to prevent
            # the same error on subsequent reads
            with open(path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            return result
        raise


def _read_jsonl(path: str) -> list[dict]:
    """Read all entries from a JSONL file."""
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
    return entries


# ---------------------------------------------------------------------------
# File & path helpers
# ---------------------------------------------------------------------------

def _build_user_summary(profile: dict) -> str:
    """Build a concise user summary for file generation context."""
    identity = profile.get("identity", {})
    bio = profile.get("biographical_summary", {}).get("short_bio", "")
    return (
        f"{identity.get('full_name', 'Unknown')} — "
        f"{identity.get('role', 'Unknown role')} at "
        f"{identity.get('organization', 'Unknown org')}. {bio}"
    )


def _logical_to_physical(world_dir: str, logical_path: str) -> str:
    """Convert logical path (C:/Users/...) to physical path (world_dir/drives/C/Users/...)."""
    parts = logical_path.split(":/", 1)
    if len(parts) != 2:
        return ""
    drive, rest = parts
    return os.path.join(world_dir, "drives", drive, rest)


_MAC_PRIMARY_VOLUME = "Macintosh HD"


def _logical_to_physical_mac(world_dir: str, logical_path: str) -> str:
    """Convert macOS logical path to physical path.

    Primary volume: "/Users/alice/file.txt" -> world_dir/drives/Macintosh HD/Users/alice/file.txt
    External volume: "/Volumes/External/x"  -> world_dir/drives/External/x
    """
    if not logical_path.startswith("/"):
        return ""
    drives_dir = os.path.join(world_dir, "drives")
    if logical_path.startswith("/Volumes/"):
        rest = logical_path[len("/Volumes/"):]
        return os.path.join(drives_dir, rest)
    rest = logical_path.lstrip("/")
    return os.path.join(drives_dir, _MAC_PRIMARY_VOLUME, rest)


def _verify_batch(world_dir: str, batch: list[dict], log_fn=None) -> list[str]:
    """Check that batch files exist at their expected physical paths.

    Returns list of logical paths that are missing.
    """
    missing = []
    for entry in batch:
        logical = entry["path"]
        physical = _logical_to_physical(world_dir, logical)
        if not physical:
            continue
        if os.path.exists(physical):
            if log_fn:
                log_fn(f"  OK: {logical}")
        else:
            missing.append(logical)
            if log_fn:
                log_fn(f"  MISSING: {logical}")
    return missing


def _get_relevant_edges(file_graph: dict, batch_paths: set[str]) -> list[dict]:
    """Get file_graph edges relevant to the current batch of files."""
    edges = file_graph.get("edges", [])
    return [
        e for e in edges
        if e.get("from") in batch_paths or e.get("to") in batch_paths
    ]


def _read_file_as_text(filepath: str, max_chars: int = 10000) -> str:
    """Read a file as text, returning empty string on failure."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars)
        return content
    except Exception:
        return ""


def _get_all_activity_log(world_dir: str) -> list[dict]:
    """Read ALL entries from activity_log.jsonl (Cold Start only)."""
    return _read_jsonl(os.path.join(world_dir, "activity_log.jsonl"))


def _get_all_daily_activity_log(world_dir: str) -> list[dict]:
    """Read ALL entries from both activity logs (Cold Start + Daily Sim)."""
    cs = _read_jsonl(os.path.join(world_dir, "activity_log.jsonl"))
    ds = _read_jsonl(os.path.join(world_dir, "daily_activity_log.jsonl"))
    return cs + ds


# ---------------------------------------------------------------------------
# Usage tracker
# ---------------------------------------------------------------------------

class UsageTracker:
    """Accumulate cost/turn/token usage across multiple call_claude() calls."""

    def __init__(self, world_dir: str, filename: str, prefix: str, t0: float):
        self.world_dir = world_dir
        self.filename = filename
        self.prefix = prefix
        self.t0 = t0
        self.total_cost_usd = 0.0
        self.total_turns = 0
        self.total_usage: dict = {}

    def accumulate(self, result: dict):
        self.total_cost_usd += result.get("cost_usd", 0.0)
        self.total_turns += result.get("num_turns", 0)
        usage = result.get("usage", {})
        for k, v in usage.items():
            if isinstance(v, (int, float)):
                self.total_usage[k] = self.total_usage.get(k, 0) + v
        self.save()

    def save(self):
        elapsed_s = time.monotonic() - self.t0
        summary = {
            f"{self.prefix}cost_usd": round(self.total_cost_usd, 4),
            f"{self.prefix}turns": self.total_turns,
            f"{self.prefix}duration_s": round(elapsed_s, 1),
            f"{self.prefix}usage": self.total_usage,
        }
        path = os.path.join(self.world_dir, self.filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

    def usage_str(self) -> str:
        return ", ".join(f"{k}={v}" for k, v in self.total_usage.items())


# ---------------------------------------------------------------------------
# World setup helpers
# ---------------------------------------------------------------------------

def setup_world_claude_md(world_dir: str, os_flavor: str = "windows"):
    """Create .claude/CLAUDE.md and symlink skills into the world directory.

    Skills are symlinked from the project root's .claude/skills/ so all
    worlds share the same skill definitions without copying.
    """
    if os_flavor == "macos":
        from world_claude_md_mac import WORLD_CLAUDE_MD_MAC as _body
    else:
        _body = WORLD_CLAUDE_MD
    # CLAUDE.md goes in the world root (SDK looks for <cwd>/CLAUDE.md)
    with open(os.path.join(world_dir, "CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write(_body)

    # .claude/ dir for settings and skills
    claude_dir = os.path.join(world_dir, ".claude")
    os.makedirs(claude_dir, exist_ok=True)

    # Copy project-root .claude/skills/ into the world
    # (copy instead of symlink for Windows compatibility)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_skills = os.path.join(project_root, ".claude", "skills")
    dst_skills = os.path.join(claude_dir, "skills")

    if os.path.isdir(src_skills) and not os.path.exists(dst_skills):
        shutil.copytree(src_skills, dst_skills)

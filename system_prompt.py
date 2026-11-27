"""System prompt template for inner agents.

The append text is combined with the Claude Code preset to form the
system prompt.  Only core identity and hard path rules belong here —
detailed guidance lives in world_claude_md.py (→ .claude/CLAUDE.md).

{cwd} is replaced at runtime with the absolute world directory path.
"""

SYSTEM_PROMPT_APPEND = """\

You are building a simulated Windows PC filesystem environment. \
Follow instructions precisely. Write files exactly as specified. \
Output only what is requested — no explanations unless asked.

## PATH RULE
Working directory: `{cwd}`
ALL paths MUST resolve under this directory.
- User documents → `drives/…` (relative).
- Control files (plans, evaluations, logs) → working directory root.
- NEVER use `C:/…`, `D:/…`, `/mnt/…`, or any path outside `{cwd}`.
- This applies to Write, Edit, Bash, and any scripts you generate."""

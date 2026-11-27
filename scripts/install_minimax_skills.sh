#!/usr/bin/env bash
# Install only the four document skills used by the public configuration.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
rev=$(<"$root/.minimax-revision")
stage=$(mktemp -d)
trap 'rm -r -- "$stage" </dev/null' EXIT
git -C "$stage" init -q
git -C "$stage" fetch -q --depth=1 https://github.com/MiniMax-AI/skills.git "$rev"
test "$(git -C "$stage" rev-parse FETCH_HEAD)" = "$rev"
names=(minimax-docx minimax-pdf minimax-xlsx pptx-generator)
mkdir -p "$root/.claude/skills"
for name in "${names[@]}"; do
  test ! -e "$root/.claude/skills/$name" || { echo "$name already exists; keep or move it before installing." >&2; exit 1; }
  git -C "$stage" cat-file -e "FETCH_HEAD:skills/$name/SKILL.md"
done
for name in "${names[@]}"; do
  git -C "$stage" archive FETCH_HEAD "skills/$name" | tar -x -C "$stage"
  cp -R "$stage/skills/$name" "$root/.claude/skills/"
done
printf 'Installed four MiniMax skills at %s\n' "$rev"

# Synthetic Work Environments at Scale for Long-Horizon Productivity Agents

Generate a persona-conditioned Windows- or macOS-style filesystem, simulate a month of professional tasks, evaluate deliverables, and write a retrospective report. Filesystems are represented as directories on disk. The runtime is the Claude Agent SDK. This release uses four document skills from [MiniMax](https://github.com/MiniMax-AI/skills): minimax-docx, minimax-xlsx, pptx-generator, and minimax-pdf. The paper's original configuration also used additional skills for non-Office artifacts.

## Quick start

Use an isolated Linux environment, Python 3.11 or later, uv, Git, and a configured Claude Code CLI. Provide your own model access through the CLI. Simulation commands make paid model calls and allow agent tools to operate inside the environment. Use a disposable workspace with no unrelated credentials or files.

```bash
uv sync --frozen
bash scripts/install_minimax_skills.sh
uv run python cold_start.py --persona "A logistics coordinator at a fictional regional food cooperative" --world-id demo
uv run python daily_sim.py --world-id demo --weeks 1
uv run python analyze_world.py --world worlds/demo
```

Follow the installed skills' setup instructions for document tooling, including Node and .NET for their respective workflows. For macOS-style worlds use cold_start_mac.py and daily_sim_mac.py. Batch entry points accept user-supplied inputs. Generated work products and reports stay in the world's output directory. Under scripts/ are utilities for merging rubrics and rescoring existing deliverables. The repository contains the simulation and analysis implementation. Aggregation of reports into an occupation skill library is described in the paper.

## Artifacts and third-party software

[Released synthetic computers and simulation reports](https://huggingface.co/datasets/microsoft/synthetic-computers-at-scale). Supply your own persona or use a persona collection under its terms. The optional installer fetches a pinned MiniMax revision directly from the upstream repository. Consult its license, credits, and the licenses of individual dependencies there.

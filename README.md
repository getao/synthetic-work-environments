# Synthetic Work Environments at Scale for Long-Horizon Productivity Agents

**Paper.** This work has been accepted for publication in **Findings of EACL 2027**. The conference will publish the camera-ready version under the title shown above. The [original arXiv preprint](https://arxiv.org/pdf/2604.28181) is available under its earlier title, *Synthetic Computers at Scale for Long-Horizon Productivity Simulation*.

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

## Persona input

Use a synthetic description of your own or choose an entry from [PersonaHub](https://huggingface.co/datasets/proj-persona/PersonaHub), for example its [Elite Personas subset](https://huggingface.co/datasets/proj-persona/PersonaHub/viewer/elite_persona). See the [upstream project](https://github.com/tencent-ailab/persona-hub) for provenance and the dataset card for terms. No persona download is required by the pipeline.

For a single world, save just the `persona` field (plain UTF-8 text, not the JSON object) to `.local-inputs/persona.txt`. Create the directory first; it is ignored by Git. Then run:

```bash
uv run python cold_start.py --persona-file .local-inputs/persona.txt --world-id persona-demo --model sonnet
uv run python daily_sim.py --world-id persona-demo --weeks 1 --model sonnet --eval-model sonnet
```

## Calling models

**Full simulation.** The commands above use the Claude Agent SDK and an already configured Claude Code runtime. `--model` selects a model supported by that runtime; it does not switch providers. The shared simulation call is [`call_claude`](agents/common.py); [retrospective analysis](analyze_world.py) has a separate SDK call. Both can run tools without interactive permission prompts. Run them only in a disposable environment: do not mount a real home directory, production credentials, or other repositories. Keep authentication in the runtime, never in persona files, prompts, logs or Git.

**One prompt, two backends.** [The minimal Python adapter](examples/invoke_model.py) passes a prompt on stdin and returns stdout, using either [Claude Code](https://code.claude.com/docs/en/cli-reference) with tools disabled or [Ollama](https://docs.ollama.com/cli) with a locally installed model. With Claude Code already configured, or a local Ollama server running and the chosen model installed:

```bash
echo 'Suggest one fictional procurement task.' | python3 examples/invoke_model.py claude sonnet
echo 'Suggest one fictional procurement task.' | python3 examples/invoke_model.py ollama YOUR_INSTALLED_MODEL
```

The adapter is a text-only example, not a drop-in backend for a simulated workday. To port the full pipeline, the new agent runtime must execute file and document tools inside the world, enforce workspace boundaries, support the collaborator tools used by the simulation, and return the text, turn, usage and error information consumed by the callers. Port the separate retrospective judge if needed. No provider credentials or deployment configuration are included.

## Artifacts and third-party software

[Released synthetic computers and simulation reports](https://huggingface.co/datasets/microsoft/synthetic-computers-at-scale). Supply your own persona or use a persona collection under its terms. The optional installer fetches a pinned MiniMax revision directly from the upstream repository. Consult its license, credits, and the licenses of individual dependencies there.

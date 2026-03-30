# learning-agent

`learning-agent` is a curriculum-driven CLI and local web UI for running a structured technical learning loop against a separate target repository.

The current implementation is a Phase 1 single-controller system. It reads a roadmap markdown file, exposes only the current unlocked week, generates learning material and implementation tasks with an OpenAI-backed provider, records verification and observations, and blocks progression until the current week's gates are satisfied.

## What It Does

- Parses a roadmap markdown file into week-level learning and delivery requirements.
- Persists progress outside model context in `state/`.
- Generates Learning Assist content for the current week:
  - blog-style reading sections
  - concept cards
  - typed question banks
  - evidence-based follow-up questions after valid observations
- Generates a scoped Junior SWE task for the active week.
- Tracks required artifacts, metrics, verification, observations, and reflection.
- Exposes the workflow through both a CLI and a local web UI.
- Includes a week-scoped topic chat surface in the UI.

## Repository Layout

```text
.
├── learning_agent/            # Core package
│   ├── providers/             # LLM provider abstraction + OpenAI implementation
│   ├── prompts/               # Mentor and Junior prompt templates
│   ├── assets/                # UI assets and illustrations
│   ├── cli.py                 # Typer CLI
│   ├── controller.py          # Main workflow/state machine
│   ├── curriculum.py          # Roadmap markdown parser
│   ├── models.py              # Pydantic models
│   ├── state.py               # Persistent and working state storage
│   └── ui.py                  # Local web UI
├── docs/                      # Product and implementation docs
├── curriculum_generation/     # Prompt assets for standalone roadmap/workspace generation
├── tests/                     # Unit tests
├── learning_agent.config.json # Repo-local runtime config
└── pyproject.toml
```

## Requirements

- Python 3.9+
- An OpenAI API key exposed as `OPENAI_API_KEY`
- A target repository on disk
- A roadmap markdown file that matches the parser's expected week structure

## Configuration

The app discovers its repo root by locating `learning_agent.config.json` in the current directory or a parent directory.

Current config shape:

```json
{
  "provider": "openai",
  "model": "gpt-4o",
  "roadmap_path": "ai_inference_engineering/docs/inference_engineering_8_week_plan.md",
  "target_repo_path": "ai_inference_engineering",
  "state_dir": "state"
}
```

Fields:

- `provider`: currently only `openai`
- `model`: chat-completions model name used by the provider
- `roadmap_path`: markdown roadmap path, relative to this repo root
- `target_repo_path`: target repository path, relative to this repo root
- `state_dir`: where ledger and working-state files are written

You can keep `OPENAI_API_KEY` in a repo-local `.env`. The loader reads `.env` automatically and does not override an already-set environment variable.

## Quick Start

Create a virtual environment, install the package, set your API key, and point the config at the roadmap and target repo you want to drive.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
export OPENAI_API_KEY=your_key_here
```

If you prefer a repo-local `.env`:

```bash
echo 'OPENAI_API_KEY=your_key_here' >> .env
```

Initialize the first week:

```bash
.venv/bin/python -m learning_agent init
.venv/bin/python -m learning_agent status
```

Start the local UI:

```bash
.venv/bin/python -m learning_agent serve
```

By default the UI runs at `http://127.0.0.1:4010` with file-watch reload enabled.

## CLI Workflow

Typical week flow:

```bash
.venv/bin/python -m learning_agent init
.venv/bin/python -m learning_agent learn generate
.venv/bin/python -m learning_agent learn answer --question-id <id> --answer "..."
.venv/bin/python -m learning_agent task generate
.venv/bin/python -m learning_agent record sync
.venv/bin/python -m learning_agent record metric --key latency_p95 --value 420
.venv/bin/python -m learning_agent record metric --key tokens_per_sec --value 31.7
.venv/bin/python -m learning_agent record observation \
  --command ".venv/bin/python simple_server/benchmark.py" \
  --artifact-path docs/baseline_results.md \
  --reliability valid \
  --latency-p95-ms 420 \
  --tokens-per-sec 31.7
.venv/bin/python -m learning_agent record reflection \
  --text "Results were stable after warm-up and match expectations." \
  --trustworthy
.venv/bin/python -m learning_agent record verify --passed --summary "Local verification passed."
.venv/bin/python -m learning_agent approve
.venv/bin/python -m learning_agent advance
```

Other useful commands:

```bash
.venv/bin/python -m learning_agent gate ask
.venv/bin/python -m learning_agent gate submit --answer "..."
.venv/bin/python -m learning_agent learn assist --enabled
.venv/bin/python -m learning_agent status
```

Bootstrap a fresh standalone curriculum workspace with Anthropic:

```bash
export ANTHROPIC_API_KEY=your_key_here
.venv/bin/python -m learning_agent curriculum bootstrap \
  --prompt-path curriculum_generation/prompts/ai_inference_engineering_8_week_plan.md \
  --output-repo-path ai_inference_engineering
```

This sends the prompt file to Anthropic as-is, writes the returned markdown to `docs/8_week_plan.md` inside the target repo path, and initializes the target repo locally without precreating scaffold directories from the plan.

## State Files

Runtime state is written under `state/` by default:

```text
state/
├── progress_ledger.json
├── current_gate.json
├── current_learning.json
└── current_task.json
```

- `progress_ledger.json` is the durable source of runtime state.
- The other files are replaceable working-state snapshots for the active week.

## Approval Rules

A week cannot be approved until the controller clears all blockers for the current week. In the current implementation that means:

- concept coverage has passed
- required files are present in the target repo
- verification passed
- all required metrics were recorded
- if the week requires evidence, an observation was recorded
- if the week requires evidence, the evidence is marked reliable
- if the week requires evidence, a reflection was recorded

## Development

Run tests with:

```bash
.venv/bin/python -m pytest
```

Key implementation docs:

- `docs/001_prd.md`
- `docs/002_phase_1_implementation.md`
- `docs/003_in_context_learning_loop_design.md`
- `docs/004_in_context_learning_loop_implementation.md`

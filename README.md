# coach

`coach` is a curriculum-paced learning workspace for senior engineers. It runs a structured Learn → Build → Verify → Approve loop against a separate target repository, exposing only the currently unlocked week and blocking progression until each week's gates are satisfied.

The platform is structured as a stage-driven workflow rather than a multi-agent system. There is one orchestrator and three stage controllers (Learn, Build, Verify), plus a topic-chat service for ad-hoc questions and a separate `curriculum` package that owns curriculum reads and bootstrapping.

## What It Does

- Parses a roadmap markdown file into week-level learning and delivery requirements.
- Persists progress in a durable ledger outside model context.
- Generates Learning Assist content for the current week (reading material, concept cards, typed question bank).
- Generates a scoped implementation brief for the active week (today via the provider; the autonomous BuildAgent is the next major work item).
- Tracks required artifacts, metrics, verification, observations, and reflection.
- Exposes the workflow through both a CLI and a local web UI.
- Provides a week-scoped topic chat surface for grounded questions during any stage.

## Repository Layout

```text
.
├── coach/                     # Runtime: orchestrator, stages, providers, CLI, UI
│   ├── stages/                # Learn / Build / Verify stage controllers
│   ├── providers/             # LLM provider abstraction + concrete adapters
│   ├── prompts/               # System prompts used by provider calls
│   ├── assets/                # UI assets
│   ├── tests/                 # Orchestrator / CLI / UI / topic-chat tests
│   ├── orchestrator.py        # WeekOrchestrator (status, gates, week transitions)
│   ├── topic_chat.py          # Standalone chat service
│   ├── cli.py                 # Typer CLI
│   ├── ui.py                  # Local web UI
│   ├── models.py              # Pydantic models (ledger, sessions, payloads)
│   ├── state.py               # Persistent + ephemeral state storage
│   ├── config.py              # Config + repo-root discovery
│   └── errors.py              # CoachError
├── curriculum/                # Curriculum reads, parsing, bootstrapping
│   ├── access.py              # CurriculumAccess (cached roadmap reader)
│   ├── parser.py              # Roadmap markdown → dict
│   ├── bootstrap.py           # `coach curriculum bootstrap` implementation
│   ├── prompts/               # Curriculum-generation prompt assets
│   └── tests/
├── docs/                      # Product + implementation docs
├── coach.config.json          # Repo-local runtime config
└── pyproject.toml
```

Tests live next to the code they cover (`coach/tests/`, `coach/stages/tests/`, `coach/providers/tests/`, `curriculum/tests/`).

## Requirements

- Python 3.9+
- An LLM API key as `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`, depending on provider
- A target repository on disk
- A roadmap markdown file matching the parser's expected week structure (see `curriculum/parser.py`)

## Configuration

The app discovers its repo root by locating `coach.config.json` in the current directory or a parent directory.

```json
{
  "provider": "anthropic",
  "model": "claude-sonnet-4-0",
  "roadmap_path": "ai_inference_engineering/docs/inference_engineering_8_week_plan.md",
  "target_repo_path": "ai_inference_engineering",
  "state_dir": "state"
}
```

Fields:

- `provider`: `openai` or `anthropic`
- `model`: model name used by the selected provider
- `roadmap_path`: roadmap markdown path, relative to this repo root
- `target_repo_path`: target repository path, relative to this repo root
- `state_dir`: where ledger and working-state files are written

API keys can live in a repo-local `.env`. The loader reads `.env` automatically and does not override an already-set environment variable.

## Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
export ANTHROPIC_API_KEY=your_key_here

.venv/bin/python -m coach init
.venv/bin/python -m coach status
```

Start the local UI:

```bash
.venv/bin/python -m coach serve
```

UI defaults to `http://127.0.0.1:4010` with file-watch reload enabled.

## CLI Workflow

Typical week:

```bash
.venv/bin/python -m coach init
.venv/bin/python -m coach learn generate
.venv/bin/python -m coach learn answer --question-id <id> --answer "..."
.venv/bin/python -m coach task generate
.venv/bin/python -m coach record sync
.venv/bin/python -m coach record metric --key latency_p95 --value 420
.venv/bin/python -m coach record metric --key tokens_per_sec --value 31.7
.venv/bin/python -m coach record observation \
  --command ".venv/bin/python simple_server/benchmark.py" \
  --artifact-path docs/baseline_results.md \
  --reliability valid \
  --latency-p95-ms 420 \
  --tokens-per-sec 31.7
.venv/bin/python -m coach record reflection \
  --text "Results were stable after warm-up and match expectations." \
  --trustworthy
.venv/bin/python -m coach record verify --passed --summary "Local verification passed."
.venv/bin/python -m coach approve
.venv/bin/python -m coach advance
```

Bootstrap a fresh standalone curriculum workspace:

```bash
export ANTHROPIC_API_KEY=your_key_here
.venv/bin/python -m coach curriculum bootstrap \
  --prompt-path curriculum/prompts/ai_inference_engineering_8_week_plan.md \
  --output-repo-path ai_inference_engineering
```

## State Files

Runtime state is written under `state/` by default:

```text
state/
├── progress_ledger.json      # Durable source of truth
├── current_learning.json     # Replaceable working state for the active week
└── current_task.json         # Replaceable working state for the active week
```

The ledger is the only durable state. Ephemeral files are reset when the week advances.

## Approval Rules

A week cannot be approved until every blocker clears:

- concept coverage has passed (`learning_check_passed`)
- required files are present in the target repo (`implementation_complete`)
- verification passed (`verification_passed`)
- all required metrics were recorded
- if the week requires evidence: an observation was recorded, evidence is marked reliable, a reflection was recorded (`evidence_reliable`)

## Development

```bash
.venv/bin/python -m pytest
```

Key implementation docs:

- `docs/001_prd.md`
- `docs/002_phase_1_implementation.md`
- `docs/003_in_context_learning_loop_design.md`
- `docs/004_in_context_learning_loop_implementation.md`

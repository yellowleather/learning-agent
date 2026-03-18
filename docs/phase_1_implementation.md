# Phase 1 Implementation Guide

## 1. Purpose

This document describes the **actual Phase 1 implementation** of the learning agent platform.

It complements [prd.md](/Users/prakhar/learning_agent/docs/prd.md):

- `prd.md` explains the ideal system and the phased architecture,
- this document explains what has been built so far in Phase 1, how it works, and how to use it.

For the concrete implementation of the Learning Assist / In-Context Learning Loop feature, see:

- [in_context_learning_loop_implementation.md](/Users/prakhar/learning_agent/docs/in_context_learning_loop_implementation.md)

Phase 1 is a **guided single-controller MVP**. It is intentionally lighter than the ideal design:

- there is one controller,
- Mentor and Junior SWE are implemented as logical roles,
- state is persisted on disk,
- future weeks are hidden by the controller,
- strict path/tool isolation is deferred,
- the system can be driven by CLI or a local web UI.

## 2. What Exists Today

The current implementation provides:

- markdown roadmap parsing,
- Week 1 initialization,
- persistent ledger state,
- concept gate generation and scoring,
- structured Junior SWE task generation,
- artifact syncing against the target repo,
- metric recording,
- verification recording,
- explicit week approval and advancement,
- a local web UI layered on top of the same controller.

The implementation targets the current roadmap in:

- [ai_inference_engineering/docs/inference_engineering_8_week_plan.md](/Users/prakhar/learning_agent/ai_inference_engineering/docs/inference_engineering_8_week_plan.md)

## 3. Repository Layout

Phase 1 code lives in:

```text
learning_agent/
├── assets/
│   └── icon.png
├── providers/
│   ├── base.py
│   ├── factory.py
│   └── openai_provider.py
├── prompts/
│   ├── junior.md
│   └── mentor.md
├── cli.py
├── config.py
├── controller.py
├── curriculum.py
├── errors.py
├── models.py
├── state.py
└── ui.py
```

Supporting project files:

- [learning_agent.config.json](/Users/prakhar/learning_agent/learning_agent.config.json)
- [pyproject.toml](/Users/prakhar/learning_agent/pyproject.toml)
- [tests/](/Users/prakhar/learning_agent/tests)

Runtime state is written to:

```text
state/
├── progress_ledger.json
├── current_gate.json
└── current_task.json
```

Only `progress_ledger.json` is durable state. The gate/task files are replaceable working state for the current week.

## 4. Core Architecture

### 4.1 Controller

The main orchestration entrypoint is:

- [learning_agent/controller.py](/Users/prakhar/learning_agent/learning_agent/controller.py)

It is responsible for:

- loading the current ledger,
- parsing the roadmap,
- resolving the current week,
- enforcing command preconditions,
- updating the ledger,
- generating gate/task content through the configured provider.

### 4.2 Curriculum Parser

The roadmap parser lives in:

- [learning_agent/curriculum.py](/Users/prakhar/learning_agent/learning_agent/curriculum.py)

It is intentionally tailored to the current roadmap shape. It derives:

- current week number and title,
- goal,
- concepts,
- task bullets,
- deliverable paths,
- required files,
- active functional directories,
- required metrics.

The parser only exposes the **current unlocked week** to downstream flows.

### 4.3 State Store

Persistent state management lives in:

- [learning_agent/state.py](/Users/prakhar/learning_agent/learning_agent/state.py)

It reads and writes:

- `progress_ledger.json`
- `current_gate.json`
- `current_task.json`

### 4.4 Provider Layer

The provider abstraction lives in:

- [learning_agent/providers/base.py](/Users/prakhar/learning_agent/learning_agent/providers/base.py)

The current concrete implementation is:

- [learning_agent/providers/openai_provider.py](/Users/prakhar/learning_agent/learning_agent/providers/openai_provider.py)

Phase 1 uses the provider for three operations:

1. generate a concept gate question,
2. score the user’s answer,
3. generate the current-week Junior SWE task.

### 4.5 Interfaces

There are two user-facing interfaces:

- CLI in [learning_agent/cli.py](/Users/prakhar/learning_agent/learning_agent/cli.py)
- local web UI in [learning_agent/ui.py](/Users/prakhar/learning_agent/learning_agent/ui.py)

Both interfaces call the same controller and therefore use the same state machine.

## 5. State Model

The ledger shape in Phase 1 is:

```json
{
  "curriculum_metadata": {
    "title": "AI Inference Engineering",
    "total_weeks": 8,
    "target_repo": "ai_inference_engineering"
  },
  "state": {
    "current_week": 1,
    "active_functional_dirs": ["simple_server", "docs"],
    "gates": {
      "socratic_check_passed": false,
      "implementation_complete": false,
      "verification_passed": false,
      "week_approved": false
    },
    "artifacts": {
      "required_files": [
        "simple_server/server.py",
        "simple_server/benchmark.py",
        "docs/baseline_results.md"
      ],
      "completed_files": []
    },
    "metrics": {
      "required": ["latency_p95", "tokens_per_sec"],
      "recorded": {}
    },
    "verification": null
  }
}
```

### State evolution

Within a week:

1. `init` creates the week state.
2. `gate ask` creates the current gate prompt.
3. `gate submit` may set `socratic_check_passed = true`.
4. `task generate` creates the current task payload.
5. `record sync` updates completed files and may set `implementation_complete = true`.
6. `record verify` may set `verification_passed = true`.
7. `approve` sets `week_approved = true`.
8. `advance` increments the week and resets week-local state.

## 6. CLI Usage

The CLI is currently run with:

```bash
.venv/bin/python -m learning_agent <command>
```

Core commands:

```bash
.venv/bin/python -m learning_agent init
.venv/bin/python -m learning_agent status
.venv/bin/python -m learning_agent gate ask
.venv/bin/python -m learning_agent gate submit --answer "..."
.venv/bin/python -m learning_agent task generate
.venv/bin/python -m learning_agent record sync
.venv/bin/python -m learning_agent record metric --key latency_p95 --value 420
.venv/bin/python -m learning_agent record metric --key tokens_per_sec --value 31.7
.venv/bin/python -m learning_agent record verify --passed --summary "Local verification passed."
.venv/bin/python -m learning_agent approve
.venv/bin/python -m learning_agent advance
```

Behavioral rules:

- `task generate` is blocked until the concept gate passes,
- `approve` is blocked until files, verification, and metrics are complete,
- `advance` is blocked until the current week is approved.

## 7. UI Usage

The local web UI is started with:

```bash
.venv/bin/python -m learning_agent serve
```

Defaults:

- host: `127.0.0.1`
- port: `4010`

The UI supports:

- initializing Week 1,
- explaining what the platform is for and how to use it,
- generating and answering the concept gate,
- generating the Junior SWE task,
- syncing artifacts,
- recording metrics,
- recording verification,
- approving the week,
- advancing to the next week.

The UI serves branding assets from:

- `/assets/icon.png`
- `/favicon.ico`

The `serve` command now defaults to an app/config reload loop. Changes under `learning_agent/`, `learning_agent.config.json`, `pyproject.toml`, and `.env` cause the UI server to restart automatically. Runtime state under `state/` is intentionally excluded from reload watching.

## 8. Configuration

Tracked configuration lives in:

- [learning_agent.config.json](/Users/prakhar/learning_agent/learning_agent.config.json)

Current fields:

```json
{
  "provider": "openai",
  "model": "",
  "roadmap_path": "ai_inference_engineering/docs/inference_engineering_8_week_plan.md",
  "target_repo_path": "ai_inference_engineering",
  "state_dir": "state"
}
```

Secrets are expected via:

- `.env`

Example:

```dotenv
OPENAI_API_KEY=...
```

`.env` is loaded automatically by [learning_agent/config.py](/Users/prakhar/learning_agent/learning_agent/config.py) and is git-ignored.

## 9. Testing

Tests currently cover:

- roadmap parsing,
- ledger initialization,
- state transitions,
- CLI flows,
- CLI reload watch behavior,
- `.env` config loading,
- UI rendering and UI action routing.

Run the suite with:

```bash
.venv/bin/python -m pytest
```

## 10. Current Limitations

Phase 1 intentionally does **not** implement:

- strict write-path enforcement,
- sandboxed execution boundaries between Mentor and Junior SWE,
- curriculum change detection,
- remote or GPU execution profiles,
- auth for the local UI,
- automatic code execution after task generation.

Additional limitations of the current implementation:

- the parser is specialized to the current roadmap format,
- the provider layer currently has only one concrete implementation,
- the local UI is intended for localhost use only,
- the app records verification status but does not run verification itself.

## 11. Expected Operator Flow

A normal Phase 1 operator flow is:

1. initialize Week 1,
2. ask the concept gate question,
3. answer the concept gate,
4. generate the Junior SWE task,
5. implement the task in the target repo,
6. sync files,
7. record metrics,
8. record verification,
9. approve the week,
10. advance to the next week.

The controller is the source of truth for whether each transition is allowed.

## 12. Next Likely Improvements

Reasonable next steps after Phase 1 are:

- execute verification commands directly instead of recording them manually,
- add stronger file-scope validation,
- add history/audit output to the UI,
- add provider-independent mocks or offline task generation modes,
- move from “logical personas” toward stronger role isolation.

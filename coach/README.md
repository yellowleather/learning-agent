# coach/

The runtime package. Wires the orchestrator, three stage controllers, the topic-chat service, providers, CLI, and UI together.

## Layout

```
coach/
├── orchestrator.py       # WeekOrchestrator: week-level state machine
├── topic_chat.py         # TopicChat service (ad-hoc grounded chat)
├── stages/               # Stage controllers (learn, build, verify)
├── providers/            # LLM provider abstraction + adapters
├── prompts/              # System prompts loaded by provider calls
├── cli.py                # Typer CLI entrypoint
├── ui.py                 # Local web UI
├── models.py             # Pydantic models (ledger, sessions, payloads)
├── state.py              # StateStore — durable ledger + ephemeral files
├── config.py             # Config loading + repo-root discovery
├── errors.py             # CoachError
└── tests/                # Tests for orchestrator, CLI, UI, topic_chat, config
```

## Mental model

The product is a **4-stage weekly workflow**, not a multi-agent system. Each week the user moves through:

1. **Learn** — concept coverage via reading + question bank (`stages/learn.py`)
2. **Build** — implementation against a scoped brief (`stages/build.py`)
3. **Verify** — observation, metrics, reflection, verification record (`stages/verify.py`)
4. **Approve** — gate progression to the next week (on the orchestrator)

The orchestrator owns the week-level state machine: `initialize`, `status`, `approve_week`, `advance_week`. It does **not** own per-stage business logic. Stages own their slice of the ledger; the orchestrator aggregates.

The single source of truth is `state/progress_ledger.json`. Stages communicate through the ledger, not by calling each other.

## Stage interface

Each stage class is constructed with the dependencies it needs (`StateStore`, `CurriculumAccess`, `provider_factory`, plus stage-specific paths) and exposes:

- **Public actions** the CLI/UI invoke (`generate_assist`, `generate_task`, `record_observation`, etc.)
- **Read-only introspection** the orchestrator asks for (`build_checkpoint`, `requires_evidence`, `question_progress`, …)
- **Private helpers** for the stage's own implementation

The orchestrator holds `self.learn`, `self.build`, `self.verify` and the CLI/UI call them directly (no facade).

## TopicChat

A standalone chat surface that the orchestrator wires up. It owns chat-internal transformations (reply normalisation, JSON-wrapped reply unwrapping, selection-context truncation, system-context formatting) and the streaming handshake with the provider. It receives cross-stage facts (blockers, question progress, default-step fallback) from the orchestrator rather than reaching into stages.

## Providers

Provider methods are one-shot LLM calls with structured output (`generate_question_bank`, `score_learning_question`, `generate_task`, …). Add a new provider by implementing `providers/base.py:LLMProvider` and wiring it into `providers/factory.py`.

## CLI

`coach.cli:app` is a Typer app. Commands map directly to stage methods — e.g. `coach learn generate` → `controller.learn.generate_assist()`.

## UI

`coach.ui` exposes the same workflow over a local web server, defaulting to `127.0.0.1:4010`. Reload-on-change is enabled by default via `coach serve`.

## Tests

Tests live in `coach/tests/` for top-level modules, and in `coach/stages/tests/` and `coach/providers/tests/` for subpackages. Each test has a 1–2 line comment describing the behaviour under test.

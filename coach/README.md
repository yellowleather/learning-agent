# coach/

Cross-stage scaffolding for the weekly workflow. This package owns the
orchestrator, the ledger and state store, the provider interface, and the
CLI. Stage-specific code lives in sibling top-level packages: `learn/`,
`build/`, `verify/`. The local web UI lives in `ui/`. The week-scoped
chat service lives in `topic_chat/`. Curriculum reads live in `curriculum/`.

## Layout

```
coach/
├── orchestrator.py       # WeekOrchestrator: week-level state machine
├── providers/            # LLM provider abstraction + adapters
├── prompts/              # Cross-stage prompts (mentor.md, junior.md)
├── cli.py                # Typer CLI entrypoint (spawns the UI in ui/)
├── models.py             # Cross-stage models (Ledger, ProgressState, Gates,
│                         #   CurriculumMetadata, CheckpointState,
│                         #   GeneratedTask, TaskSession). Re-exports VerifyRecord
│                         #   types from verify.models for callers that still
│                         #   import them from coach.models.
├── _base.py              # StrictModel base class (imported by every domain
│                         #   package to avoid circular imports through coach.models)
├── state.py              # StateStore — durable ledger + ephemeral files +
│                         #   archive lifecycle (cross-stage state surface)
├── config.py             # Config loading + repo-root discovery
├── errors.py             # CoachError
└── tests/                # Tests for orchestrator, CLI, config
```

## What lives here vs in step packages

Anything that's **specific to a stage** lives in the corresponding sibling
package, not here:

- `LearnStage`, learning models, learning prompts → `learn/`
- `BuildStage`, build-agent models, build prompts → `build/`
- `VerifyStage`, evidence models → `verify/`
- `TopicChat`, chat history model, chat prompt → `topic_chat/`
- HTTP server, HTML rendering, assets → `ui/`

Anything that's **cross-stage scaffolding** stays in coach:

- The orchestrator and the week state machine
- The persistence layer (`StateStore`) — file paths, archive lifecycle,
  `clear_ephemeral_state`. Each stage uses these methods to read/write its
  slice of the ledger; the file paths themselves are owned here because
  `archive_week_state` moves all four ephemeral files at once and
  shouldn't fragment across packages.
- The ledger root and its sub-models (`Ledger`, `ProgressState`, `Gates`,
  `ArtifactState`, `MetricsState`, `CurriculumMetadata`,
  `CheckpointState`).
- `TaskSession` and `GeneratedTask` — these cross build (which produces
  the brief) and verify (which writes verification into the same session
  via `update_task_verification`), so they live in coach as the
  cross-stage contract.
- Provider interface and adapters — providers implement methods that span
  every stage; the abstraction belongs to coach.
- CLI, UI, topic chat, config, errors — all cross-stage.

## Mental model

The product is a **4-stage weekly workflow**, not a multi-agent system.
Each week the user moves through Learn → Build → Verify → Approve. The
orchestrator owns the state machine (`initialize`, `status`,
`approve_week`, `advance_week`). It does *not* own per-stage business
logic — it holds `self.learn`, `self.build`, `self.verify` (instances of
the stage classes from their respective packages) and the CLI/UI call
those stages directly.

The single source of truth is `state/progress_ledger.json`. Stages
communicate through the ledger, not by calling each other.

## TopicChat wiring

The chat service itself lives in the sibling `topic_chat/` package. The
orchestrator owns the wiring: `WeekOrchestrator.answer_topic_chat`,
`stream_topic_chat`, and `_topic_chat_inputs` gather the cross-stage facts
(blockers, question progress, default-step fallback) and hand them to
`TopicChat`. The service never reaches into stages — the orchestrator is
the one place that aggregates across them.

## Tests

Tests in `coach/tests/` cover the orchestrator, CLI, and config. Tests
for the UI, chat service, and each stage live with their respective
packages.

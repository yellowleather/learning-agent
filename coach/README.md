# coach/

Cross-stage scaffolding for the weekly workflow. This package owns the
orchestrator, the ledger and state store, the topic-chat service, the
provider interface, the CLI, and the UI. Stage-specific code lives in
sibling top-level packages: `learn/`, `build/`, `verify/`. Curriculum
reads live in `curriculum/`.

## Layout

```
coach/
├── orchestrator.py       # WeekOrchestrator: week-level state machine
├── topic_chat.py         # TopicChat service (ad-hoc grounded chat)
├── providers/            # LLM provider abstraction + adapters
├── prompts/              # Cross-stage prompts (mentor.md, junior.md, topic_chat.md)
├── cli.py                # Typer CLI entrypoint
├── ui.py                 # Local web UI
├── models.py             # Cross-stage models (Ledger, ProgressState, Gates,
│                         #   CurriculumMetadata, TopicChatTurn, CheckpointState,
│                         #   GeneratedTask, TaskSession). Re-exports VerifyRecord
│                         #   types from verify.models for callers that still
│                         #   import them from coach.models.
├── _base.py              # StrictModel base class (imported by every domain
│                         #   package to avoid circular imports through coach.models)
├── state.py              # StateStore — durable ledger + ephemeral files +
│                         #   archive lifecycle (cross-stage state surface)
├── config.py             # Config loading + repo-root discovery
├── errors.py             # CoachError
└── tests/                # Tests for orchestrator, CLI, UI, topic_chat, config
```

## What lives here vs in step packages

Anything that's **specific to a stage** lives in the corresponding sibling
package, not here:

- `LearnStage`, learning models, learning prompts → `learn/`
- `BuildStage`, build-agent models, build prompts → `build/`
- `VerifyStage`, evidence models → `verify/`

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

## TopicChat

A standalone chat surface that the orchestrator wires up. It owns chat-
internal transformations (reply normalisation, JSON-wrapped reply
unwrapping, selection-context truncation, system-context formatting) and
the streaming handshake with the provider. It receives cross-stage facts
(blockers, question progress, default-step fallback) from the orchestrator
rather than reaching into stages.

## Tests

Tests in `coach/tests/` cover the orchestrator, CLI, UI, topic_chat, and
config. Stage-specific tests live with their stage packages.

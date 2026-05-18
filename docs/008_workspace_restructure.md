# Workspace Restructure (May 2026)

## 1. Purpose

This document captures the architectural restructure that took the codebase
from a single `learning_agent/` package with a 869-line `LearningController`
into a stage-driven layout with seven top-level packages.

It supersedes the *layout* portions of [001_prd.md](001_prd.md) and
[002_phase_1_implementation.md](002_phase_1_implementation.md) — the
pedagogy, ledger model, and gate discipline from those documents still
hold, but the package structure they describe no longer matches the code.

## 2. Final layout

```
.
├── engine/          Orchestration kernel — cross-stage scaffolding
├── learn/           Learn step (LearnStage + learning models + prompts)
├── build/           Build step (BuildStage + build-agent models + prompts)
├── verify/          Verify step (VerifyStage + evidence models)
├── ui/              Local web UI (HTTP server + assets)
├── topic_chat/      Week-scoped chat service (TopicChat + chat models + prompt)
├── curriculum/      Curriculum reads, parsing, bootstrap
├── docs/            Product + implementation docs
├── coach.config.json   Runtime config (user-facing filename)
└── pyproject.toml
```

Tests are co-located with the code they cover (`engine/tests/`,
`engine/providers/tests/`, `learn/tests/`, `build/tests/`, `verify/tests/`,
`ui/tests/`, `topic_chat/tests/`, `curriculum/tests/`). There is no
top-level `tests/` directory.

## 3. The principle

**Anything specific to a stage lives in that stage's package. Cross-stage
scaffolding lives in `engine/`.**

Concretely, each step package owns:

- Its stage controller (`LearnStage`, `BuildStage`, `VerifyStage`).
- Its domain models (the Pydantic types it produces or consumes).
- Its prompt assets and a `prompts.py` loader so prompts and the calls
  that use them stay co-located.
- Its tests.

`engine/` owns:

- `WeekOrchestrator` — the week-level state machine (initialize, status,
  approve_week, advance_week).
- `StateStore` — every persistence path, the durable ledger writer, and
  the archive lifecycle. Stages use this; they do not own their own
  state store.
- The cross-stage models (`Ledger`, `ProgressState`, `Gates`,
  `ArtifactState`, `MetricsState`, `CurriculumMetadata`,
  `CheckpointState`, `GeneratedTask`, `TaskSession`).
- The provider interface and concrete adapters.
- The CLI, config loader, error type.
- Cross-stage prompts (`mentor.md`, `junior.md`).

`topic_chat/` is a service that any stage can use; it lives at the top
level because it's not bound to a single step, but it's also not
cross-stage scaffolding — the orchestrator gathers facts and hands them
to the service.

`ui/` is the local web UI. It depends on the orchestrator and stage
classes the way any other caller does.

`curriculum/` predates this restructure (it was extracted earlier) — it
owns roadmap reads (`CurriculumAccess`), the parser, and the bootstrap
command for generating new curricula.

## 4. Brand / code split

The CLI binary is `coach`. The config file is `coach.config.json`. The
README's product name is Coach. These are the user-facing brand and they
have not changed.

The Python package the CLI dispatches into is `engine/`. The entry point
in `pyproject.toml` reads `coach = "engine.cli:app"`. This split is
deliberate:

- The product is a curriculum-paced learning workspace — a Coach.
- The package is the kernel that runs the workflow — an Engine.
- Naming the kernel after the product overclaimed once stage-specific
  code moved out into the step packages.

The split lives in exactly one place: `pyproject.toml`'s console script
entry. Everything else (imports, module names, error types) uses the
package name `engine`.

## 5. What lives where, briefly

### engine/

- `orchestrator.py` — `WeekOrchestrator`. Initialize, status, approve,
  advance. Holds `self.learn`, `self.build`, `self.verify`. Aggregates
  status and checkpoints from the stages. Wires up `TopicChat` with
  cross-stage facts.
- `state.py` — `StateStore`. All file paths
  (`progress_ledger.json`, `current_learning.json`, `current_task.json`,
  `current_build.json`, `current_build.transcript.jsonl`). Save/load for
  ledger, task, learning, build session. Transcript append and replay.
  `archive_week_state(N)` moves the outgoing week's ephemeral files into
  `state/archive/week_N/`. `clear_ephemeral_state()` is the
  no-archive variant used by `reset_pipeline` and `initialize_ledger`.
- `models.py` — cross-stage Pydantic types. Re-exports `VerificationRecord`
  etc. from `verify.models` for legacy callers.
- `_base.py` — `StrictModel` base class. Lives here to break the circular
  import that would otherwise arise: `engine.models` needs `verify.models`
  types for `ProgressState`, and `verify.models` needs `StrictModel`.
  Every domain package imports `StrictModel` from `engine._base`.
- `providers/` — the `LLMProvider` abstract interface and concrete
  adapters (OpenAI, Anthropic). One-shot calls with structured output.
- `prompts/` — `mentor.md`, `junior.md`. The cross-stage system prompts
  used by many provider calls.
- `cli.py` — Typer CLI. `coach init`, `coach serve`, `coach learn …`,
  `coach record …`, `coach approve`, `coach advance`,
  `coach curriculum bootstrap`. The reload watcher watches every
  top-level package directory plus `coach.config.json`, `pyproject.toml`,
  `.env`.
- `config.py` — `load_config()` walks up from cwd looking for
  `coach.config.json`. Discovers repo root.
- `errors.py` — `EngineError`. Raised when a command can't be completed.

### learn/

- `stage.py` — `LearnStage`. Owns the learning pipeline
  (prior-knowledge summary → question bank → reading → concept cards),
  the answer-scoring loop, and the `learning_check_passed` gate.
- `models.py` — `ConceptCard`, `LearningQuestion`, `QuestionScore`,
  `QuestionAttempt`, `LearningSession`, `LearningBundle`, the four
  provider-payload models.
- `prompts.py` + `prompts/` — five prompt templates:
  `prior_knowledge_summary`, `question_bank`, `reading_material`,
  `concept_cards_from_reading`, `score_learning_question`.

### build/

- `stage.py` — `BuildStage`. Owns the brief lifecycle, the artifact scan
  (`sync_artifacts`), the `implementation_complete` gate. This is where
  `BuildAgent` will land when it ships (see
  [009_build_agent_design.md](009_build_agent_design.md)).
- `models.py` — `CommandRun`, `FileTouched`, `BuildReport`,
  `BuildSession`, `TranscriptEvent`. The terminal-report shape the
  BuildAgent will emit. Already in place, shape locked.
- `prompts.py` + `prompts/` — `generate_task.md` (used by
  `provider.generate_task` to produce a brief). Future
  `build_agent_system.md` + `build_agent_user.md` will live here too.

### verify/

- `stage.py` — `VerifyStage`. Observation / reflection / verification
  ledger writes, the evidence-required policy, the Evidence Reliability
  checkpoint card.
- `models.py` — `VerificationRecord`, `ObservationRecord`,
  `ReflectionRecord`.

### ui/

- `server.py` — the HTTP server, request routing, HTML rendering. Plain
  `http.server` based — no Flask / FastAPI dependency.
- `assets/` — icon, illustrations.

### topic_chat/

- `service.py` — `TopicChat`. Owns reply normalisation, JSON-wrapped
  reply unwrapping, fenced-block parsing, selection-context truncation,
  system-context formatting, and the streaming handshake.
- `models.py` — `TopicChatTurn`.
- `prompts.py` + `prompts/topic_chat.md` — the chat user-prompt template.

### curriculum/

- `access.py` — `CurriculumAccess`. Cached read API over the roadmap.
- `parser.py` — `load_roadmap_dict(path)`.
- `bootstrap.py` — `coach curriculum bootstrap` implementation.
- `prompts/` — curriculum-generation prompt templates.

## 6. Cross-cutting decisions worth recording

**Ledger as single source of truth.** Stages own their slice of the
ledger and don't write to gates that belong to other stages. The
orchestrator never reaches into stages for state — it reads the ledger
directly and asks stages narrow questions
(`learn.question_progress(session)`, `verify.requires_evidence(ledger)`,
`build.build_checkpoint(ledger)`). Stages communicate through the ledger,
not by calling each other. This is enforced by convention, not
mechanically — see [001_prd.md §4.5](001_prd.md) for the long-term hard
enforcement intent.

**`archive_week_state` is monolithic.** When `WeekOrchestrator.advance_week`
runs, it moves all four ephemeral files
(`current_learning.json`, `current_task.json`, `current_build.json`,
`current_build.transcript.jsonl`) into `state/archive/week_N/` in one
call on `StateStore`. The archive lifecycle stays in `engine/` rather
than fragmenting across packages, because the four files have to move as
a set or not at all.

**`StrictModel` lives in `engine/_base.py`** (not `engine/models.py`) to
break a circular import. Every domain package imports `StrictModel` from
there. Anyone re-exporting from `engine.models` should re-export from the
base module to avoid recreating the cycle.

**The dual-persona framing is retired** as the organising abstraction
(see the header note on [001_prd.md](001_prd.md)). Only one runtime agent
will exist — the BuildAgent. Everything else is single-call provider work
or stage logic. `mentor.md` and `junior.md` remain as prompt-flavour
strings on those calls; they are not load-bearing.

**Tests are co-located.** No top-level `tests/`. Each package owns its
tests in a sibling `tests/` directory. New test files should match the
module name (e.g. `coach/orchestrator.py` ↔ `engine/tests/test_orchestrator.py`).

**Sandbox-deleted files.** During the restructure the working bash
sandbox could rename but not unlink files. Removed files were moved into
a `.scratch_deleted/` directory at the repo root. That directory is in
`.gitignore`. A `rm -rf .scratch_deleted/` from a real terminal finishes
the cleanup.

## 7. Commit list

The restructure landed across ten commits on `main`:

```
3247c5c  refactor: rename coach/ package to engine/
923ccff  refactor: extract topic_chat into top-level topic_chat/ package
59049a3  refactor: extract UI into top-level ui/ package
21c9531  refactor: split each step into its own top-level package
4a63d3f  feat(build): add BuildReport / BuildSession / TranscriptEvent models
ec13a07  docs: rewrite root README for coach/curriculum layout
437f5b2  refactor: stage-driven coach package replacing single LearningController
b593414  refactor: extract curriculum into top-level package
51a31df  chore: ignore .scratch_deleted holding directory
```

Each commit is a coherent unit. The test suite passes at every commit
boundary (131 tests at the head of the series).

## 8. What this restructure does NOT include

- The autonomous `BuildAgent`. The data foundation (models, persistence,
  archive flow) is in place. The agent loop, tools, executor, and
  provider abstraction for tool use are designed but not built — see
  [009_build_agent_design.md](009_build_agent_design.md).
- `review_build` — Mentor's structured verdict over a `BuildReport`.
- Verify-stage UI redesign that will surface agent diffs, captured
  output, and the verdict.
- Post-failure UX (re-evaluate, reset-build, per-facet verdict panel).

Those are forward-looking work; this document is the snapshot of what
exists today.

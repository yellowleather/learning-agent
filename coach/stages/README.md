# coach/stages/

Stage controllers for the weekly workflow. Each stage owns its slice of the ledger and its own work; stages do not call into each other.

## Layout

```
stages/
├── learn.py          # LearnStage
├── build.py          # BuildStage  (future home of BuildAgent)
├── verify.py         # VerifyStage
└── tests/            # Per-stage tests
```

## LearnStage (`learn.py`)

Owns the learning pipeline and the `learning_check_passed` gate.

Public actions:

- `generate_assist()` — runs the pipeline (prior-knowledge summary → question bank → reading → concept cards) and persists a `LearningSession`.
- `answer_question(question_id, answer)` — scores via the provider, appends the attempt, flips the gate when all required baseline questions pass.
- `reset_pipeline()` — clears *all* downstream gates and ephemeral state so the week can be re-run cleanly.
- `compare_providers(providers, output_dir)` — offline eval that runs the pipeline against multiple providers and writes per-provider artefacts.
- `ensure_assist()`, `get_session()`, `get_bundle()` — accessors.

Cross-stage introspection (read-only, the orchestrator calls these):

- `question_progress(session)`
- `required_questions_passed(session)`
- `build_checkpoint(ledger, session)`

## BuildStage (`build.py`)

Owns the implementation brief, the artifact-completion scan, and the `implementation_complete` gate.

Public actions:

- `generate_task()` — generates the structured brief via the provider. Gated on `learning_check_passed`.
- `sync_artifacts()` — scans `target_repo_path` for the brief's required files and flips `implementation_complete` when every file is present.
- `get_task_session()` — accessor.

Cross-stage introspection:

- `build_checkpoint(ledger)`

This module is where the **BuildAgent** (multi-turn loop with tools, subprocess executor, 30-min wall-clock budget) will land. See `docs/001_prd.md` for the design.

## VerifyStage (`verify.py`)

Owns evidence-side ledger writes and the `verification_passed` / `evidence_reliable` gates.

Public actions:

- `record_metric(key, value)`
- `record_observation(observation)` — rolls latency / tokens into recorded metrics, flips `evidence_reliable` based on reliability label.
- `record_reflection(reflection)` — buggy / untrustworthy reflection clears `evidence_reliable`.
- `record_verification(passed, summary)` — requires a task session to exist; writes through to the task session and flips `verification_passed`.

Cross-stage introspection:

- `requires_evidence(ledger)` — true iff the week declares required metrics
- `build_checkpoint(ledger, session)` — five-branch render of the Evidence Reliability card

## Constraints (apply to every stage)

- The ledger is the single source of truth. Stages own their slice and don't write to gates that belong to other stages.
- Stages don't call into each other. Cross-stage preconditions are checked by reading the ledger.
- Stages depend on `StateStore`, `CurriculumAccess`, and a provider factory — never on the orchestrator.

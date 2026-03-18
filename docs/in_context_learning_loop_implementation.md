# In-Context Learning Loop Implementation Guide

## 1. Purpose

This document describes the **actual implementation** of the In-Context Learning Loop in the current repository.

It complements:

- [in_context_learning_loop_design.md](/Users/prakhar/learning_agent/docs/in_context_learning_loop_design.md), which describes the feature design and target behavior,
- [phase_1_implementation.md](/Users/prakhar/learning_agent/docs/phase_1_implementation.md), which describes the broader Phase 1 platform.

This guide explains what has actually been built, how it works in code, how the LLM is used, how state is stored, and how to run the flow through the CLI or UI.

## 2. What Exists Today

The current implementation provides:

- Learning Assist generation for the current unlocked week,
- concept cards,
- typed question banks with `type`, `scope`, `depth`, and rubric metadata,
- free-text question answering and scoring,
- structured observation capture,
- reflection capture,
- evidence-based follow-up question generation after a valid observation,
- checkpoint derivation for the current week,
- explicit `evidence_reliable` gating,
- approval blocking when evidence is missing or unreliable.

The current implementation is still a **Phase 1 single-controller system**:

- there is one controller,
- content generation is constrained to the current unlocked week,
- the provider is called directly for generation and scoring,
- strict hard-enforced subgate execution is not implemented,
- question coverage rules are heuristic rather than curriculum-authored.

## 3. Repository Layout

The main implementation lives in:

```text
learning_agent/
├── providers/
│   ├── base.py
│   └── openai_provider.py
├── prompts/
│   ├── junior.md
│   └── mentor.md
├── cli.py
├── controller.py
├── curriculum.py
├── models.py
├── state.py
└── ui.py
```

The most relevant files are:

- [learning_agent/models.py](/Users/prakhar/learning_agent/learning_agent/models.py)
- [learning_agent/state.py](/Users/prakhar/learning_agent/learning_agent/state.py)
- [learning_agent/controller.py](/Users/prakhar/learning_agent/learning_agent/controller.py)
- [learning_agent/providers/base.py](/Users/prakhar/learning_agent/learning_agent/providers/base.py)
- [learning_agent/providers/openai_provider.py](/Users/prakhar/learning_agent/learning_agent/providers/openai_provider.py)
- [learning_agent/cli.py](/Users/prakhar/learning_agent/learning_agent/cli.py)
- [learning_agent/ui.py](/Users/prakhar/learning_agent/learning_agent/ui.py)

## 4. Core Data Model

### 4.1 New Models

The implementation adds these main data structures in [learning_agent/models.py](/Users/prakhar/learning_agent/learning_agent/models.py):

- `ConceptCard`
- `LearningQuestion`
- `QuestionScore`
- `QuestionAttempt`
- `LearningAssistPayload`
- `EvidenceQuestionPayload`
- `LearningSession`
- `ObservationRecord`
- `ReflectionRecord`
- `CheckpointState`

The week-level ledger state also now includes:

- `learning_assist_enabled`
- `observation`
- `reflection`
- `gates.evidence_reliable`

### 4.2 Gates

The implemented week gates are:

- `socratic_check_passed`
- `implementation_complete`
- `verification_passed`
- `evidence_reliable`
- `week_approved`

The code still uses the older field name `socratic_check_passed`, but in practice it now covers:

- the legacy single gate question, or
- the Learning Assist required baseline core-question coverage.

### 4.3 Checkpoints

The controller derives lightweight linear checkpoints at runtime in [learning_agent/controller.py](/Users/prakhar/learning_agent/learning_agent/controller.py):

- `core_concepts`
- `implementation`
- `evidence_reliability`

These are not curriculum-authored objects. They are computed from current ledger state, learning session state, verification state, and evidence state.

## 5. Runtime State Files

Runtime state is currently written into:

```text
state/
├── progress_ledger.json
├── current_gate.json
├── current_learning.json
└── current_task.json
```

State management lives in:

- [learning_agent/state.py](/Users/prakhar/learning_agent/learning_agent/state.py)

`progress_ledger.json` remains the durable week-state file.

`current_gate.json`, `current_learning.json`, and `current_task.json` are replaceable working-state files for the active week.

### 5.1 Ledger Shape

The ledger now looks roughly like this:

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
    "learning_assist_enabled": true,
    "gates": {
      "socratic_check_passed": false,
      "implementation_complete": false,
      "verification_passed": false,
      "evidence_reliable": false,
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
    "verification": null,
    "observation": null,
    "reflection": null
  }
}
```

## 6. Controller Flow

The orchestration entrypoint is:

- [learning_agent/controller.py](/Users/prakhar/learning_agent/learning_agent/controller.py)

### 6.1 Main Operations

The controller now supports:

1. `initialize()`
2. `generate_learning_assist()`
3. `answer_learning_question()`
4. `generate_task()`
5. `sync_artifacts()`
6. `record_metric()`
7. `record_observation()`
8. `record_reflection()`
9. `record_verification()`
10. `approve_week()`
11. `advance_week()`

### 6.2 Actual Week Flow

The implemented flow for a week is:

1. initialize the week ledger from the roadmap,
2. generate Learning Assist content,
3. answer the required baseline core questions,
4. mark conceptual coverage complete once required questions pass,
5. generate the Junior SWE task,
6. build the required files in the target repo,
7. sync artifacts and record verification,
8. record a structured observation,
9. if the observation is `valid`, generate evidence-based follow-up questions,
10. answer evidence-based questions if desired,
11. record a reflection,
12. approve the week only after all blockers are cleared.

### 6.3 Approval Rules

Week approval is blocked if any of the following remain incomplete:

- concept coverage not passed,
- required files incomplete,
- verification not passed,
- required metrics missing,
- observation missing for a metrics-based week,
- evidence marked unreliable,
- reflection missing.

This logic is enforced in `_approval_blockers()` in [learning_agent/controller.py](/Users/prakhar/learning_agent/learning_agent/controller.py).

## 7. LLM Usage

The provider abstraction lives in:

- [learning_agent/providers/base.py](/Users/prakhar/learning_agent/learning_agent/providers/base.py)

The current implementation is:

- [learning_agent/providers/openai_provider.py](/Users/prakhar/learning_agent/learning_agent/providers/openai_provider.py)

### 7.1 Prompt Sources

The two prompt files are:

- [learning_agent/prompts/mentor.md](/Users/prakhar/learning_agent/learning_agent/prompts/mentor.md)
- [learning_agent/prompts/junior.md](/Users/prakhar/learning_agent/learning_agent/prompts/junior.md)

The Mentor prompt is used for:

- Learning Assist generation,
- legacy concept-gate generation,
- gate scoring,
- per-question scoring,
- evidence-based follow-up question generation.

The Junior prompt is used for:

- current-week implementation task generation.

### 7.2 Generation Strategy

The implementation uses **one-shot generation per feature**, not a multi-step planner.

Specifically:

1. `generate_learning_assist()` makes one LLM call that returns both:
   - concept cards
   - the initial question bank
2. `generate_task()` makes a separate LLM call for the implementation brief.
3. `record_observation()` may trigger one additional LLM call to generate evidence-based questions after a `valid` observation.
4. `answer_learning_question()` makes one LLM call per submitted answer to score it against the rubric.
5. the older `gate ask` and `gate submit` flow remains available as a separate legacy path.

### 7.3 Current Learning Assist Prompt

The Learning Assist prompt is built in [learning_agent/providers/openai_provider.py](/Users/prakhar/learning_agent/learning_agent/providers/openai_provider.py).

Its current structure is:

```text
Create the current week's Learning Assist content.
Use only the provided current-week context and ledger state. Output JSON only.
Return 3-6 concept cards and a sizable question bank. Include core baseline questions that cover the week,
plus some deeper or adjacent questions. Evidence-based questions should be marked with observation_required=true.
Current week context:
{week_spec JSON}
Current ledger state:
{ledger_state JSON}
Required JSON shape: {"week": 1, "concept_cards": [...], "questions": [...]}
```

The important implementation detail is that generation is constrained by:

- current `WeekSpec`
- current `ProgressState`
- fixed response schema

The provider does not have access to future weeks if the controller does not pass them in.

## 8. CLI Usage

The CLI entrypoint is:

```bash
.venv/bin/python -m learning_agent <command>
```

The current In-Context Learning Loop commands are:

```bash
.venv/bin/python -m learning_agent init
.venv/bin/python -m learning_agent status
.venv/bin/python -m learning_agent learn generate
.venv/bin/python -m learning_agent learn answer --question-id core_prefill --answer "..."
.venv/bin/python -m learning_agent learn assist --enabled
.venv/bin/python -m learning_agent task generate
.venv/bin/python -m learning_agent record sync
.venv/bin/python -m learning_agent record metric --key latency_p95 --value 420
.venv/bin/python -m learning_agent record observation --command ".venv/bin/python simple_server/benchmark.py" --artifact-path docs/baseline_results.md --reliability valid --prompt-tokens 512 --output-tokens 128 --latency-p95-ms 840 --tokens-per-sec 32.4
.venv/bin/python -m learning_agent record reflection --text "The result looks stable." --trustworthy
.venv/bin/python -m learning_agent record verify --passed --summary "Local verification passed."
.venv/bin/python -m learning_agent approve
.venv/bin/python -m learning_agent advance
```

The older gate commands also still exist:

```bash
.venv/bin/python -m learning_agent gate ask
.venv/bin/python -m learning_agent gate submit --answer "..."
```

## 9. UI Usage

The local web UI is started with:

```bash
.venv/bin/python -m learning_agent serve
```

Defaults:

- host: `127.0.0.1`
- port: `4010`

### 9.1 Current UI Flow

In the current UI, the intended order is:

1. `Initialize Week 1`
2. `Generate Learning Assist`
3. answer Learning Assist questions
4. `Generate Task`
5. build artifacts in the target repo
6. `Sync Artifacts`
7. `Record Observation`
8. `Record Reflection`
9. `Record Verification`
10. `Approve Week`
11. `Advance Week`

The current UI supports:

- Learning Assist visibility toggle,
- concept card display,
- question bank display,
- question answering,
- task generation,
- artifact sync,
- metric recording,
- structured observation entry,
- reflection entry,
- verification entry,
- checkpoint rendering,
- approval blocker rendering.

## 10. Current Limitations

The implementation is useful, but it is still intentionally lightweight.

### 10.1 Coverage Logic

Required question coverage is currently derived by controller heuristics:

- `scope == "core"`
- `depth == "baseline"`
- `observation_required == false`

There is not yet a curriculum-authored quota such as "must pass 8 of 12 core questions."

### 10.2 Evidence Logic

Evidence reliability is currently set from the observation and may be overridden by reflection:

- observation reliability `valid` sets `gates.evidence_reliable = true`
- reflection marked buggy or untrustworthy sets it back to `false`

This is intentionally conservative, but it is not a full measurement-validation engine.

### 10.3 Question Generation

Initial cards and questions are generated in one shot.

That keeps the implementation simple, but it also means:

- question count is model-driven,
- card quality is model-driven,
- deduplication and balancing are limited,
- there is no deterministic quota expansion step yet.

### 10.4 Checkpoints

Checkpoints are currently derived and displayed, but they are not enforced as fully separate executable subflows with their own isolated working state.

## 11. Recommended Next Steps

The most sensible next improvements are:

1. add deterministic quotas for required question coverage,
2. validate generated question banks for duplicates and scope leakage before saving,
3. auto-generate Learning Assist immediately after week initialization,
4. add stronger structured validation for observations,
5. allow curriculum-authored checkpoint hints when heuristic derivation is insufficient.

## 12. Summary

The In-Context Learning Loop is now implemented as a real Phase 1 feature, not just a design note.

The current implementation adds:

- on-platform concept cards,
- question-bank generation,
- free-text answer scoring,
- structured observation and reflection capture,
- evidence-based follow-up questioning,
- explicit evidence-reliability gating,
- CLI and UI support for the full loop.

The implementation remains intentionally simple:

- one controller,
- one-shot generation per feature,
- JSON-shaped provider outputs,
- runtime-derived checkpoints,
- explicit approval blockers instead of hidden progression logic.

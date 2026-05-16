# In-Context Learning Loop Implementation Guide

## 1. Purpose

This document describes the **actual implementation** of the In-Context Learning Loop in the current repository.

It complements:

- [003_in_context_learning_loop_design.md](/Users/prakhar/learning_agent/docs/003_in_context_learning_loop_design.md), which describes the feature design and target behavior,
- [002_phase_1_implementation.md](/Users/prakhar/learning_agent/docs/002_phase_1_implementation.md), which describes the broader Phase 1 platform.

This guide explains what has actually been built, how it works in code, how the LLM is used, how state is stored, and how to run the flow through the CLI or UI.

## 2. What Exists Today

The current implementation provides:

- Learning Assist generation for the current unlocked week,
- a multi-stage learning pipeline built from question banks, reading material, and concept cards,
- question banks with `depth` and rubric metadata,
- free-text question answering and scoring,
- structured observation capture,
- reflection capture,
- checkpoint derivation for the current week,
- explicit `evidence_reliable` gating,
- approval blocking when evidence is missing or unreliable for evidence-requiring weeks,
- a week-scoped Assistant/topic-chat surface in the UI.

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
├── assets/
├── providers/
│   ├── base.py
│   ├── factory.py
│   └── openai_provider.py
├── prompts/
│   ├── concept_cards_from_reading.md
│   ├── generate_task.md
│   ├── junior.md
│   ├── prior_knowledge_summary.md
│   ├── question_bank.md
│   ├── reading_material.md
│   ├── score_learning_question.md
│   ├── mentor.md
│   └── topic_chat.md
├── cli.py
├── controller.py
├── models.py
├── prompts.py
├── state.py
└── ui.py
```

The most relevant files are:

- [learning_agent/models.py](/Users/prakhar/learning_agent/learning_agent/models.py)
- [learning_agent/state.py](/Users/prakhar/learning_agent/learning_agent/state.py)
- [learning_agent/controller.py](/Users/prakhar/learning_agent/learning_agent/controller.py)
- [learning_agent/providers/base.py](/Users/prakhar/learning_agent/learning_agent/providers/base.py)
- [learning_agent/providers/openai_provider.py](/Users/prakhar/learning_agent/learning_agent/providers/openai_provider.py)
- [learning_agent/prompts/](/Users/prakhar/learning_agent/learning_agent/prompts)
- [learning_agent/prompts.py](/Users/prakhar/learning_agent/learning_agent/prompts.py)
- [learning_agent/cli.py](/Users/prakhar/learning_agent/learning_agent/cli.py)
- [learning_agent/ui.py](/Users/prakhar/learning_agent/learning_agent/ui.py)

## 4. Core Data Model

### 4.1 Main Models

The implementation uses these main data structures in [learning_agent/models.py](/Users/prakhar/learning_agent/learning_agent/models.py):

- `ProgressState`
- `Ledger`
- `LearningQuestion`
- `LearningQuestionBankPayload`
- `QuestionScore`
- `QuestionAttempt`
- `ReadingMaterialPayload`
- `ConceptCard`
- `ConceptCardPayload`
- `LearningSession`
- `LearningBundle`
- `TopicChatTurn`
- `ObservationRecord`
- `ReflectionRecord`
- `CheckpointState`
- `GeneratedTask`
- `TaskSession`

Important relationships in the current implementation:

- `LearningSession` stores the current week's concept cards, reading material, questions, and attempts.
- `ProgressState.active_dirs` stores the persisted week scope copied from the roadmap.
- `GeneratedTask.allowed_dirs` is returned by task generation and surfaced in the UI as implementation guidance.

The week-level ledger state also includes:

- `observation`
- `reflection`
- `gates.evidence_reliable`

### 4.2 Gates

The implemented week gates are:

- `learning_check_passed`
- `implementation_complete`
- `verification_passed`
- `evidence_reliable`
- `week_approved`

The `learning_check_passed` gate is satisfied by passing all required Learning Assist baseline questions.

In the current code, the required Learning Assist questions are those with:

- `depth == "baseline"`

### 4.3 Checkpoints

The controller derives lightweight runtime checkpoints in [learning_agent/controller.py](/Users/prakhar/learning_agent/learning_agent/controller.py):

- `learning_questions`
- `implementation`
- `evidence_reliability`

These are not curriculum-authored objects. They are computed from ledger state, learning-session state, verification state, and evidence state.

## 5. Runtime State Files

Runtime state is currently written into:

```text
state/
├── progress_ledger.json
├── current_learning.json
└── current_task.json
```

State management lives in:

- [learning_agent/state.py](/Users/prakhar/learning_agent/learning_agent/state.py)

`progress_ledger.json` remains the durable week-state file.

`current_learning.json` and `current_task.json` are replaceable working-state files for the active week.

### 5.1 Ledger Shape

The ledger looks roughly like this:

```json
{
  "curriculum_metadata": {
    "title": "AI Inference Engineering",
    "total_weeks": 8,
    "target_repo": "ai_inference_engineering"
  },
  "state": {
    "current_week": 1,
    "active_dirs": ["simple_server", "docs"],
    "gates": {
      "learning_check_passed": false,
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

Important note about `active_dirs`:

- it is derived from the current week's roadmap deliverable paths and persisted in the ledger,
- it is surfaced through `status()` and passed into task-generation context,
- it is not currently enforced as a hard path-level write guard by the controller.

## 6. Controller Flow

The orchestration entrypoint is:

- [learning_agent/controller.py](/Users/prakhar/learning_agent/learning_agent/controller.py)

### 6.1 Main Operations

The controller currently supports:

1. `initialize()`
2. `status()`
3. `generate_learning_assist()`
4. `answer_learning_question()`
5. `generate_task()`
6. `sync_artifacts()`
7. `record_metric()`
8. `record_observation()`
9. `record_reflection()`
10. `record_verification()`
11. `approve_week()`
12. `advance_week()`
13. `ensure_learning_assist()`
14. `get_learning_bundle()`
15. `answer_topic_chat()`
16. `stream_topic_chat()`

### 6.2 Actual Learning Assist Flow

The implemented Learning Assist pipeline is **questions first**, but it is now explicitly multi-stage:

1. generate a current-week question bank directly in the final `LearningQuestion` schema,
2. validate the generated questions in the controller,
3. generate one learner-facing reading document from the question bank,
4. validate and normalize the reading document,
5. generate concept cards from the reading document,
6. validate and normalize concept cards,
7. save the assembled `LearningSession`.

The current `LearningSession` contains:

- `concept_cards`
- `reading_material`
- `questions`
- `attempts`

### 6.3 Actual Week Flow

The implemented week flow is:

1. initialize the week ledger from the roadmap,
2. generate Learning Assist content through the pipeline above,
3. answer the required baseline questions,
4. automatically mark conceptual coverage complete once all required questions pass,
5. generate the Junior SWE task,
6. build the required files in the target repo,
7. sync artifacts and record verification,
8. record required metrics directly or populate `latency_p95` / `tokens_per_sec` through structured observation,
9. record a structured observation,
10. record a reflection,
11. approve the week only after all blockers are cleared,
12. advance to the next week after approval.

### 6.4 Approval Rules

Week approval is blocked if any of the following remain incomplete:

- concept coverage not passed,
- required files incomplete,
- verification not passed,
- required metrics missing,
- observation missing for an evidence-requiring week,
- evidence marked unreliable for an evidence-requiring week,
- reflection missing for an evidence-requiring week.

Evidence is currently considered required when the week has one or more required metrics.

This logic is enforced in `_approval_blockers()` in [learning_agent/controller.py](/Users/prakhar/learning_agent/learning_agent/controller.py).

## 7. LLM Usage

The provider abstraction lives in:

- [learning_agent/providers/base.py](/Users/prakhar/learning_agent/learning_agent/providers/base.py)

The current implementation is:

- [learning_agent/providers/openai_provider.py](/Users/prakhar/learning_agent/learning_agent/providers/openai_provider.py)

### 7.1 Prompt Sources

Learning-loop prompt assets now live under:

- [learning_agent/prompts/](/Users/prakhar/learning_agent/learning_agent/prompts)

The current prompt files are:

- [learning_agent/prompts/mentor.md](/Users/prakhar/learning_agent/learning_agent/prompts/mentor.md)
- [learning_agent/prompts/junior.md](/Users/prakhar/learning_agent/learning_agent/prompts/junior.md)
- [learning_agent/prompts/question_bank.md](/Users/prakhar/learning_agent/learning_agent/prompts/question_bank.md)
- [learning_agent/prompts/reading_material.md](/Users/prakhar/learning_agent/learning_agent/prompts/reading_material.md)
- [learning_agent/prompts/concept_cards_from_reading.md](/Users/prakhar/learning_agent/learning_agent/prompts/concept_cards_from_reading.md)
- [learning_agent/prompts/generate_task.md](/Users/prakhar/learning_agent/learning_agent/prompts/generate_task.md)
- [learning_agent/prompts/score_learning_question.md](/Users/prakhar/learning_agent/learning_agent/prompts/score_learning_question.md)
- [learning_agent/prompts/topic_chat.md](/Users/prakhar/learning_agent/learning_agent/prompts/topic_chat.md)

Prompt loading and placeholder rendering live in:

- [learning_agent/prompts.py](/Users/prakhar/learning_agent/learning_agent/prompts.py)

The prompt split is:

- `mentor.md` for the Mentor system persona,
- `junior.md` for the Junior SWE system persona,
- file-backed user/task templates for question-bank generation, reading generation, concept-card generation, task generation, answer scoring, and topic chat.

The curriculum bootstrap prompt remains separate under:

- [curriculum/prompts/ai_inference_engineering_8_week_plan.md](/Users/prakhar/learning_agent/curriculum/prompts/ai_inference_engineering_8_week_plan.md)

That prompt is not part of the runtime learning loop itself.

### 7.2 Generation Strategy

The current implementation uses a **questions-first, validated pipeline**.

Specifically:

1. `generate_learning_assist()` asks the provider for a large current-week question bank.
2. The provider targets at least 50 concept questions across `baseline`, `deep`, and `stretch` in a single generation call.
3. The controller validates counts, uniqueness, depth coverage, and schema shape before continuing.
4. The provider writes one blog-style reading document designed to make the question bank answerable.
5. The provider generates concept cards from the reading material, not directly from the question bank.
6. The controller normalizes the reading material and concept cards.
7. `answer_learning_question()` makes one LLM call per submitted answer to score it against the question rubric and current observation context, if any.

The important implementation detail is that generation is constrained by:

- the current week roadmap dict loaded by the controller (`week_spec` at runtime),
- current `ProgressState`
- fixed response schemas
- controller-side validation and normalization

The provider does not receive future weeks unless the controller passes them in. In the current implementation, `_load_current_week()` loads exactly one week from the roadmap before each generation or scoring call.

### 7.3 Current Prompting Shape

The implementation no longer uses a single generic Learning Assist prompt. It now uses separate prompt families for:

1. question generation,
2. reading generation,
3. concept-card generation,
4. answer scoring,
5. topic chat.

These are now file-backed prompt templates rendered through `render_prompt()` rather than long inline strings in `openai_provider.py`.

The question-generation prompt currently looks roughly like:

```text
Generate a comprehensive current-week concept question bank in the application's final schema. Output JSON only.
Do not generate concept cards in this step.
Generate at least 50 questions total across baseline, deep, and stretch depths.
Stay fully scoped to this week only.
Return each question with only: id, depth, prompt_text, scoring_rubric.
```

The reading prompt then generates one reading document and requires:

- `body_markdown` to contain a `## How This Week Works` heading,
- additional `##` headings for the major themes of the week,
- a blog-style explainer tone rather than UI or product language.

The concept-card prompt then derives cards from the reading material and requires:

- 5-10 concept cards,
- learner-facing technical explanations rather than UI copy.

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
.venv/bin/python -m learning_agent learn answer --question-id prefill_decode_baseline --answer "..."
.venv/bin/python -m learning_agent task generate
.venv/bin/python -m learning_agent record sync
.venv/bin/python -m learning_agent record metric --key latency_p95 --value 420
.venv/bin/python -m learning_agent record observation --command ".venv/bin/python simple_server/benchmark.py" --artifact-path docs/baseline_results.md --reliability valid --prompt-tokens 512 --output-tokens 128 --latency-p95-ms 840 --tokens-per-sec 32.4
.venv/bin/python -m learning_agent record reflection --text "The result looks stable." --trustworthy
.venv/bin/python -m learning_agent record verify --passed --summary "Local verification passed."
.venv/bin/python -m learning_agent approve
.venv/bin/python -m learning_agent advance
```

Other currently implemented commands that matter to the same workflow surface are:

```bash
.venv/bin/python -m learning_agent serve
.venv/bin/python -m learning_agent curriculum bootstrap --output-repo-path <path>
```

`status` reports:

- current week metadata,
- required and completed files,
- required and recorded metrics,
- gate state,
- verification, observation, and reflection state,
- derived checkpoints,
- question progress,
- approval blockers,
- current task and learning sessions when present.

## 9. UI Usage

The local web UI is started with:

```bash
.venv/bin/python -m learning_agent serve
```

Defaults:

- host: `127.0.0.1`
- port: `4010`
- reload: enabled by default from the CLI wrapper

### 9.1 Current UI Behavior

In the current UI:

1. Week state is loaded from the ledger.
2. If the week is initialized but no learning session exists yet, the UI tries to auto-load Learning Assist.
3. The learner answers current-week questions and progresses through the build, verify, and approve steps.
4. The Assistant panel can answer week-scoped questions using current progress, artifacts, metrics, and learning context.

The current UI supports:

- automatic Learning Assist loading through `ensure_learning_assist()` when possible,
- reading material display,
- concept-card display,
- question answering,
- question navigation with a full-question-list modal,
- task generation,
- artifact sync,
- metric recording,
- structured observation entry,
- reflection entry,
- verification entry,
- checkpoint rendering,
- approval blocker rendering,
- browser-local multi-session week-scoped topic chat through `/api/topic-chat`.

The current UI does **not** persist chat server-side. Chat sessions stay local to the browser for the active week.

## 10. Current Limitations

The implementation is useful, but it is still intentionally lightweight.

### 10.1 Coverage Logic

Required question coverage is currently derived by controller heuristics:

- `depth == "baseline"`

The learner must currently pass **all** such questions to satisfy the Learning Assist path for `learning_check_passed`.

There is not yet a curriculum-authored quota such as "must pass 8 of 12 baseline questions."

### 10.2 Evidence Logic

Evidence reliability is currently set from the observation and may be overridden by reflection:

- observation reliability `valid` sets `gates.evidence_reliable = true`
- reflection marked buggy or untrustworthy sets it back to `false`

There are no separate evidence-question follow-ups in the current implementation. Evidence is handled through observation capture, metric recording, and reflection.

This is intentionally conservative, but it is not a full measurement-validation engine.

### 10.3 Generation Pipeline

Learning Assist generation is now multi-stage and validated, but it is still heavily model-driven.

That means:

- question-bank quality is still model-driven,
- reading and card quality are still model-driven,
- depth balancing is validated against heuristics rather than curriculum-authored quotas,
- reading-material and concept-card validation are mostly structural and stylistic, not deep semantic verification,
- the assembled learning bundle is not fully deterministic.

### 10.4 UI / CLI Parity

The UI auto-loads Learning Assist when possible, but CLI `init` still only initializes the ledger.

That means:

- UI users may see Learning Assist appear automatically,
- CLI users still need to run `learn generate` explicitly,
- the two entry experiences are not fully symmetric.

### 10.5 Checkpoints

Checkpoints are currently derived and displayed, but they are not enforced as fully separate executable subflows with their own isolated working state.

### 10.6 Topic Chat

Topic chat is grounded in current week context and app state, but it is still a lightweight prompting layer:

- it is not a general code-execution agent,
- it does not persist server-side chat history,
- it does not replace the explicit learning-check and approval logic.

## 11. Recommended Next Steps

The most sensible next improvements are:

1. add curriculum-authored quotas or requirements for conceptual coverage instead of the current all-baseline heuristic,
2. decide whether evidence-question answering should remain optional or become part of approval,
3. strengthen structured observation validation and artifact existence checks,
4. decide whether `active_dirs` should remain guidance-only or become hard path-level enforcement,
5. align CLI `init` behavior with the UI's Learning Assist auto-load behavior,
6. allow curriculum-authored checkpoint hints when heuristic derivation is insufficient,
7. decide whether topic-chat state should remain browser-local or become durable app state.

## 12. Summary

The In-Context Learning Loop is implemented as a real Phase 1 feature, not just a design note.

The current implementation adds:

- multi-stage Learning Assist generation,
- on-platform reading material and concept cards,
- typed question-bank generation and scoring,
- structured observation and reflection capture,
- explicit evidence-reliability gating,
- CLI and UI support for the full loop,
- a week-scoped Assistant/topic-chat surface in the UI.

The implementation remains intentionally simple:

- one controller,
- provider-backed structured generation/scoring outputs plus topic-chat text,
- controller-side validation and normalization,
- runtime-derived checkpoints,
- explicit approval blockers instead of hidden progression logic.

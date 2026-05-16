# learn/

Everything that's specific to the **Learn** step of the weekly workflow.
The package owns the stage controller, the learning-domain Pydantic
models, the prompts that shape learning content, and the tests for all of it.

## Layout

```
learn/
├── stage.py             # LearnStage — runs the question-bank + reading +
│                        #   concept-card pipeline, scores answers, owns
│                        #   the learning_check_passed gate
├── models.py            # ConceptCard, LearningQuestion, QuestionScore,
│                        #   QuestionAttempt, LearningAssistPayload,
│                        #   LearningQuestionBankPayload, ReadingMaterialPayload,
│                        #   ConceptCardPayload, LearningSession, LearningBundle
├── prompts.py           # load_prompt / render_prompt for learn/prompts/
├── prompts/             # learn-domain prompt assets
│   ├── prior_knowledge_summary.md
│   ├── question_bank.md
│   ├── reading_material.md
│   ├── concept_cards_from_reading.md
│   └── score_learning_question.md
└── tests/               # stage tests
```

## What lives here vs in coach/

The same rule as build/ and curriculum/: anything specific to the **Learn**
step lives in this package. Cross-stage workflow scaffolding stays in
`coach/`.

Concretely in this package:

- `LearnStage` — the orchestrator-mounted handle that runs the learning
  pipeline and flips `learning_check_passed` on the ledger.
- The learning-domain models — concept cards, questions, scoring results,
  attempts, and the persisted `LearningSession` / user-facing
  `LearningBundle`.
- The five learn-specific prompt templates and the matching `prompts.py`
  loader. Providers that implement learn-specific calls
  (`generate_prior_knowledge_summary`, `generate_question_bank`,
  `generate_reading_material`, `generate_concept_cards_from_reading`,
  `score_learning_question`) import `render_prompt` from `learn.prompts`.

What stays in `coach/`:

- The persistence paths for `current_learning.json` and the
  `archive_week_state` lifecycle (cross-stage state surface).
- The cross-stage models — `Ledger`, `Gates`, `ProgressState`,
  `CurriculumMetadata`, `TopicChatTurn`, `CheckpointState`.
- Cross-stage prompt assets — `mentor.md` (the system prompt used for every
  Mentor-flavored call) and `topic_chat.md` (used by `TopicChat`).

## The pipeline at a glance

`LearnStage.generate_assist()` runs four provider calls in sequence:

1. `generate_prior_knowledge_summary` — distils the full roadmap into a
   target-week brief so downstream calls don't have to re-read everything.
2. `generate_question_bank` — produces ≥50 questions across baseline/deep/
   stretch depths, validated for shape and coverage.
3. `generate_reading_material` — a blog-style "How This Week Works" reading.
4. `generate_concept_cards_from_reading` — distils the reading into 3+
   normalised concept cards (ids deduped, fields stripped).

Each step's output is validated; a failure raises `CoachError` rather than
persisting half-baked content.

`LearnStage.answer_question(qid, answer)` scores a single answer through
`score_learning_question` and flips `learning_check_passed` on the ledger
when every required baseline question has a passing latest attempt.

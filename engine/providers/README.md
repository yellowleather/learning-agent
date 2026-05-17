# coach/providers/

LLM provider abstraction and concrete adapters. The rest of the codebase talks to an `LLMProvider` interface; this folder is the only place that knows about specific vendors.

## Layout

```
providers/
├── base.py                  # LLMProvider abstract interface
├── factory.py               # get_provider(config) — returns the configured implementation
├── anthropic_provider.py    # Claude / Anthropic Messages API
├── openai_provider.py       # OpenAI Chat Completions / Responses API
└── tests/                   # Tests per provider + factory contract
```

## The interface (`base.py`)

`LLMProvider` is the contract every adapter implements. All methods are one-shot calls with structured (Pydantic) inputs and outputs:

- `generate_prior_knowledge_summary(full_plan, target_week_number)` — pre-pipeline summary used by question/reading generation.
- `generate_question_bank(week_spec, prior_knowledge_summary, ledger_state)` — typed `LearningQuestionBankPayload`.
- `generate_reading_material(week_spec, prior_knowledge_summary, ledger_state, questions)` — typed `ReadingMaterialPayload`.
- `generate_concept_cards_from_reading(week_spec, ledger_state, reading_material)` — typed `ConceptCardPayload`.
- `generate_task(week_spec, ledger_state)` — the build brief (`GeneratedTask`).
- `score_learning_question(week_spec, question, answer, observation)` — `QuestionScore`.
- `answer_topic_chat(week_spec, context, history, message)` — chat reply string.
- `stream_topic_chat(...)` — optional; default falls back to `answer_topic_chat`.

System prompts live in `coach/prompts/` (e.g. `mentor.md`, `junior.md`, `score_learning_question.md`). Adapters load them via `coach.prompts.load_prompt`.

## Adding a provider

1. Add `your_provider.py` implementing `LLMProvider`.
2. Add it to `factory.py`'s switch on `config.provider`.
3. Add tests under `providers/tests/`.

## Notes for the upcoming BuildAgent

The BuildAgent will be the first piece of the system that uses **multi-turn tool calling**. That's a different shape than the one-shot methods in this interface, and v1 will be Anthropic-only (per the decision in `docs/`). The agent loop will live in `coach/stages/build_agent/` rather than being shoehorned into `LLMProvider`. The provider abstraction here stays focused on structured single-call generation.

Generate learner-facing concept cards derived from the provided current-week reading material. Output JSON only.
Use the reading material as the source of truth. Do not generate cards directly from a question bank.
The cards should anchor the important ideas in the reading without duplicating the reading verbatim.

Card requirements:
- Generate 5-10 concept cards.
- Every card must include id, concept, title, explanation, why_it_matters, common_mistake, and quick_check_question.
- id should be stable kebab-case.
- concept should be a stable snake_case label.
- Prefer cards built around major technical distinctions, system boundaries, metrics, and implementation concepts present in the reading.
- Do not create cards for future-week topics.
- Do not mention the words chapter, section, question bank, rubric, or UI in the card body text.
- Do not refer to the platform or to what the learner is clicking.

Current week context:
{{WEEK_CONTEXT_JSON}}
Current ledger state:
{{LEDGER_STATE_JSON}}
Reading material:
{{READING_MATERIAL_JSON}}
Required JSON shape: {"week": 1, "concept_cards": [{"id": "prefill-vs-decode", "concept": "prefill_vs_decode", "title": "Prefill vs Decode", "explanation": "...", "why_it_matters": "...", "common_mistake": "...", "quick_check_question": "..."}]}

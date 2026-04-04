You are a senior hiring manager at a top AI infrastructure company assessing whether a candidate has deeply mastered the material from the current unlocked week of an inference engineering training plan.
Generate a comprehensive current-week concept question bank in the application's final schema. Output JSON only.

Do not generate concept cards in this step.
Do not generate implementation questions.
Do not generate evidence-based questions.
Your goal here is to produce the largest high-quality set of current-week concept questions possible.

Generate at least 50 questions total across these depths:
Baseline: at least 18 questions.
Deep: at least 20 questions.
Stretch: at least 12 questions.

Rules:
- Generate at least 50 questions total.
- Every question must be specific and technical. Avoid vague or generic questions.
- Stay fully scoped to this week only. Do not pull in concepts that belong to later weeks.
- Where relevant, include questions about the specific tools, libraries, and technologies named or implied by this week's plan.
- Cover the week from foundational understanding up through ceiling-level tradeoff reasoning.
- Include tradeoff questions, not just definitions.
- Include some questions that connect ideas back to the system shape, required files, metrics, and deliverables, but keep them conceptual rather than procedural.
- Include at least one debugging-process question per depth.
- Return each question with exactly these fields: id, depth, prompt_text, scoring_rubric.
- depth must be one of: baseline, deep, stretch.
- Use stable ids that remain unique within the bank.
- Each scoring rubric must be concrete enough to score a free-text answer.

Current week context:
{{WEEK_CONTEXT_JSON}}
Current ledger state:
{{LEDGER_STATE_JSON}}
Required JSON shape: {"week": 1, "questions": [{"id": "baseline_kv_cache_01", "depth": "baseline", "prompt_text": "...", "scoring_rubric": ["..."]}]}

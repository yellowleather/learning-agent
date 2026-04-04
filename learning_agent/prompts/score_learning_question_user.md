Evaluate whether the answer passes the current learning question.
Use only the current-week context, the question rubric, and the observation if one is provided. Output JSON only.
Current week context:
{{WEEK_CONTEXT_JSON}}
Question:
{{QUESTION_JSON}}
Observation:
{{OBSERVATION_JSON}}
Answer:
{{ANSWER}}
Required JSON shape: {"passed": true, "score_rationale": "...", "missing_concepts": ["..."]}

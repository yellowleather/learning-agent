Evaluate whether the learner's answer passes the current 
concept question. Output JSON only.

Use the week plan, question, scoring rubric, and observation 
if provided. Do not use any other knowledge to infer 
understanding — evaluate only what the learner explicitly 
stated.

## Scoring rules

- An answer passes if it demonstrates understanding of all 
  required rubric points. Exact terminology is not required 
  but the underlying mechanism must be correct.
- Treat semantically equivalent paraphrases as satisfying a 
  rubric point when the meaning is clearly the same.
- A single concise statement may satisfy multiple rubric 
  points if it clearly covers them. Do not require the learner 
  to restate the same idea in separate wording just because 
  the rubric split it into multiple bullets.
- Do not fail an answer solely for minor spelling mistakes, 
  grammar issues, or typos when the intended concept is still 
  clear from context.
- An answer fails if it is missing one or more required 
  rubric points, is factually incorrect on a required point, 
  or demonstrates a fundamental misconception.
- Do not reward length. A concise answer that covers all 
  rubric points passes.
- Do not penalize correct information beyond the rubric.
- Do not infer understanding from vague or ambiguous 
  statements. If a required point is unclear or absent, 
  it is missing.

## Depth calibration

Use the question's declared depth to set the bar:

- `baseline`: basic accurate understanding of the concept 
  must be present. Precise terminology not required.
- `deep`: the answer must explain why, not just what. 
  Surface recall without mechanistic explanation fails.
- `stretch`: the answer must show synthesis or higher-order 
  reasoning. Restating the concept correctly is insufficient.

## Inputs

### Current week plan
{{WEEK_PLAN}}

### Question
{{QUESTION_JSON}}

### Observation
{{OBSERVATION_JSON}}

### Learner's answer
{{ANSWER}}

## Output format

Return JSON only. No preamble. No meta-commentary.

{
  "passed": true | false,
  "score_rationale": "...",
  "missing_concepts": ["..."]
}

- `score_rationale`: 1-3 sentences explaining the decision. 
  Present on both pass and fail.
- `missing_concepts`: array of specific concepts the answer 
  failed to demonstrate. Empty array on pass.

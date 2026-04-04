Generate learner-facing concept cards derived from the 
provided current-week reading material. Output JSON only.

Use the reading material as the source of truth. Do not 
generate cards directly from the question bank. Cards must 
anchor the important ideas in the reading without duplicating 
the reading verbatim.

## What a concept card is

A concept card covers exactly one discrete concept — a single 
mechanism, distinction, formula, or principle that can be 
understood independently.

Examples of card-worthy concepts:
- prefill vs decode phase distinction
- KV cache memory footprint calculation
- why decode is memory-bandwidth-bound
- the role of temperature in token sampling

Examples of things that are not card-worthy:
- an entire section of the reading bundled into one card
- a procedural step or implementation instruction
- a vague theme like "performance" or "memory"

## Card requirements

- Generate between 8 and 15 cards. Calibrate to the 
  conceptual density of the reading — lighter weeks may 
  produce fewer cards, heavier weeks more.
- Prefer cards built around major technical distinctions, 
  system boundaries, metrics, and mechanisms present in 
  the reading.
- Do not create cards for future-week topics.
- Do not mention the words chapter, section, question bank, 
  rubric, or UI in card body text.
- Do not refer to the platform or to what the learner 
  is clicking.

## Card fields

Every card must include:

- `id`: stable kebab-case identifier, unique within the week.
  Example: `prefill-vs-decode`
- `concept`: stable snake_case label for the concept.
  Example: `prefill_vs_decode`
- `title`: short display name shown to the learner, 2-5 words.
  Example: "Prefill vs Decode"
- `explanation`: precise technical explanation, 2-4 sentences. 
  No padding. Do not substitute analogies for mechanisms — 
  if the concept has mathematical or mechanical structure, 
  state it directly.
- `why_it_matters`: one sentence grounding the concept in 
  the current week's goals and system shape.
- `common_mistake`: the most likely specific misconception 
  a learner makes about this concept. One sentence, 
  concrete and technical. Avoid vague mistakes like 
  "not fully understanding the concept."
- `quick_check_question`: one short question whose answer 
  requires genuine understanding of the concept. Include 
  for every card — only omit if no natural check question 
  exists.

## Inputs

### Current week plan
{{WEEK_PLAN}}

### Current ledger state
{{LEDGER_STATE_JSON}}

### Reading material
{{READING_MATERIAL_JSON}}

## Output format

Return JSON only. No preamble. No meta-commentary.

{
  "week": 1,
  "concept_cards": [
    {
      "id": "prefill-vs-decode",
      "concept": "prefill_vs_decode",
      "title": "Prefill vs Decode",
      "explanation": "...",
      "why_it_matters": "...",
      "common_mistake": "...",
      "quick_check_question": "..."
    }
  ]
}

Write the learner-facing reading material for the current week. Output JSON only.
The reading must feel like a concise technical blog post or explainer written for an engineer, not like a textbook chapter, lesson plan, UI walkthrough, or internal product artifact.
The learner should be able to read it and then answer the provided current-week questions well.

Writing rules:
- Do not mention the words chapter, section, concept card, concept cards, question bank, rubric, or UI.
- Do not talk about what the platform is doing. Teach the technical ideas directly.
- Use a clear, blog-like voice: concrete, explanatory, and grounded in the week's system.
- Make the prose sufficient to answer the question set, not just a summary.
- Keep the reading tightly scoped to the current week. Do not leak future-week topics.
- Use markdown paragraphs and short bullet lists where they genuinely help.
- Return one reading document with fields: week, title, body_markdown.
- body_markdown must begin with a markdown heading exactly equal to `## How This Week Works`.
- After that opening section, include additional `##` headings generated dynamically from the question bank.
- Do not assume Week 1 topics such as prefill/decode unless they are clearly supported by the provided questions.
- Name the additional sections after the actual technical themes that recur in the questions.
- Do not attach subsections to individual questions.

Required opening heading:
{
  "heading": "How This Week Works",
  "purpose": "Orient the learner to the week's goal, system shape, and why the work matters before implementation."
}

{{THEME_HINTS_BLOCK}}Current week context:
{{WEEK_CONTEXT_JSON}}
Current ledger state:
{{LEDGER_STATE_JSON}}
Question bank:
{{QUESTION_BANK_JSON}}
Required JSON shape: {"week": 1, "title": "Week 1 Reading", "body_markdown": "## How This Week Works\n\n..."}

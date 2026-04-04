from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any, Type, TypeVar

from pydantic import BaseModel

from learning_agent.errors import LearningAgentError
from learning_agent.models import (
    ConceptCardPayload,
    GeneratedTask,
    LearningQuestion,
    LearningQuestionBankPayload,
    ObservationRecord,
    ProgressState,
    QuestionScore,
    ReadingMaterialPayload,
    TopicChatTurn,
)
from learning_agent.prompts import load_prompt
from learning_agent.providers.base import LLMProvider


ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str):
        self.model = model.strip()

    def _week_context_json(self, week_spec: dict[str, Any]) -> str:
        return json.dumps(week_spec, indent=2, sort_keys=True)

    def generate_question_bank(self, week_spec: dict[str, Any], ledger_state: ProgressState) -> LearningQuestionBankPayload:
        system_prompt = load_prompt("mentor.md")
        base_user_prompt = (
            "You are a senior hiring manager at a top AI infrastructure company assessing whether a candidate has "
            "deeply mastered the material from the current unlocked week of an inference engineering training plan.\n"
            "Generate a comprehensive current-week concept question bank in the application's final schema. Output JSON only.\n\n"
            "Do not generate concept cards in this step.\n"
            "Do not generate implementation questions.\n"
            "Do not generate evidence-based questions.\n"
            "Your goal here is to produce the largest high-quality set of current-week concept questions possible.\n\n"
            "Generate at least 50 questions total across these depths:\n"
            "Baseline: at least 18 questions.\n"
            "Deep: at least 20 questions.\n"
            "Stretch: at least 12 questions.\n\n"
            "Rules:\n"
            "- Generate at least 50 questions total.\n"
            "- Every question must be specific and technical. Avoid vague or generic questions.\n"
            "- Stay fully scoped to this week only. Do not pull in concepts that belong to later weeks.\n"
            "- Where relevant, include questions about the specific tools, libraries, and technologies named or implied by this week's plan.\n"
            "- Cover the week from foundational understanding up through ceiling-level tradeoff reasoning.\n"
            "- Include tradeoff questions, not just definitions.\n"
            "- Include some questions that connect ideas back to the system shape, required files, metrics, and deliverables, but keep them conceptual rather than procedural.\n"
            "- Include at least one debugging-process question per depth.\n"
            "- Return each question with exactly these fields: id, depth, prompt_text, scoring_rubric.\n"
            "- depth must be one of: baseline, deep, stretch.\n"
            "- Use stable ids that remain unique within the bank.\n"
            "- Each scoring rubric must be concrete enough to score a free-text answer.\n\n"
            f"Current week context:\n{self._week_context_json(week_spec)}\n"
            f"Current ledger state:\n{ledger_state.model_dump_json(indent=2)}\n"
            'Required JSON shape: {"week": 1, "questions": [{"id": "baseline_kv_cache_01", '
            '"depth": "baseline", "prompt_text": "...", "scoring_rubric": ["..."]}]}'
        )
        return self._completion_as_model(system_prompt, base_user_prompt, LearningQuestionBankPayload)

    def generate_reading_material(
        self,
        week_spec: dict[str, Any],
        ledger_state: ProgressState,
        questions: list[LearningQuestion],
    ) -> ReadingMaterialPayload:
        system_prompt = load_prompt("mentor.md")
        theme_hints = self._reading_theme_hints(questions)

        user_prompt = (
            "Write the learner-facing reading material for the current week. Output JSON only.\n"
            "The reading must feel like a concise technical blog post or explainer written for an engineer, not like a textbook chapter, "
            "lesson plan, UI walkthrough, or internal product artifact.\n"
            "The learner should be able to read it and then answer the provided current-week questions well.\n\n"
            "Writing rules:\n"
            "- Do not mention the words chapter, section, concept card, concept cards, question bank, rubric, or UI.\n"
            "- Do not talk about what the platform is doing. Teach the technical ideas directly.\n"
            "- Use a clear, blog-like voice: concrete, explanatory, and grounded in the week's system.\n"
            "- Make the prose sufficient to answer the question set, not just a summary.\n"
            "- Keep the reading tightly scoped to the current week. Do not leak future-week topics.\n"
            "- Use markdown paragraphs and short bullet lists where they genuinely help.\n"
            "- Return one reading document with fields: week, title, body_markdown.\n"
            "- body_markdown must begin with a markdown heading exactly equal to `## How This Week Works`.\n"
            "- After that opening section, include additional `##` headings generated dynamically from the question bank.\n"
            "- Do not assume Week 1 topics such as prefill/decode unless they are clearly supported by the provided questions.\n"
            "- Name the additional sections after the actual technical themes that recur in the questions.\n"
            "- Do not attach subsections to individual questions.\n\n"
            "Required opening heading:\n"
            + json.dumps(
                {
                    "heading": "How This Week Works",
                    "purpose": "Orient the learner to the week's goal, system shape, and why the work matters before implementation.",
                },
                indent=2,
            )
            + "\n\n"
            + (
                f"Recurring question themes to consider when naming the remaining markdown sections:\n{json.dumps(theme_hints, indent=2)}\n\n"
                if theme_hints
                else ""
            )
            +
            f"Current week context:\n{self._week_context_json(week_spec)}\n"
            f"Current ledger state:\n{ledger_state.model_dump_json(indent=2)}\n"
            f"Question bank:\n{json.dumps([question.model_dump(mode='json') for question in questions], indent=2)}\n"
            'Required JSON shape: {"week": 1, "title": "Week 1 Reading", "body_markdown": "## How This Week Works\\n\\n..."}'
        )
        return self._completion_as_model(system_prompt, user_prompt, ReadingMaterialPayload)

    def generate_concept_cards_from_reading(
        self,
        week_spec: dict[str, Any],
        ledger_state: ProgressState,
        reading_material: ReadingMaterialPayload,
    ) -> ConceptCardPayload:
        system_prompt = load_prompt("mentor.md")
        user_prompt = (
            "Generate learner-facing concept cards derived from the provided current-week reading material. Output JSON only.\n"
            "Use the reading material as the source of truth. Do not generate cards directly from a question bank.\n"
            "The cards should anchor the important ideas in the reading without duplicating the reading verbatim.\n\n"
            "Card requirements:\n"
            "- Generate 5-10 concept cards.\n"
            "- Every card must include id, concept, title, explanation, why_it_matters, common_mistake, and quick_check_question.\n"
            "- id should be stable kebab-case.\n"
            "- concept should be a stable snake_case label.\n"
            "- Prefer cards built around major technical distinctions, system boundaries, metrics, and implementation concepts present in the reading.\n"
            "- Do not create cards for future-week topics.\n"
            "- Do not mention the words chapter, section, question bank, rubric, or UI in the card body text.\n"
            "- Do not refer to the platform or to what the learner is clicking.\n\n"
            f"Current week context:\n{self._week_context_json(week_spec)}\n"
            f"Current ledger state:\n{ledger_state.model_dump_json(indent=2)}\n"
            f"Reading material:\n{reading_material.model_dump_json(indent=2)}\n"
            'Required JSON shape: {"week": 1, "concept_cards": [{"id": "prefill-vs-decode", "concept": "prefill_vs_decode", '
            '"title": "Prefill vs Decode", "explanation": "...", "why_it_matters": "...", "common_mistake": "...", '
            '"quick_check_question": "..."}]}'
        )
        return self._completion_as_model(system_prompt, user_prompt, ConceptCardPayload)

    def generate_task(self, week_spec: dict[str, Any], ledger_state: ProgressState) -> GeneratedTask:
        system_prompt = load_prompt("junior.md")
        user_prompt = (
            "Generate the current-week implementation task for the Junior SWE.\n"
            "Use only the provided current-week context and ledger state. Output JSON only.\n"
            f"Current week context:\n{self._week_context_json(week_spec)}\n"
            f"Current ledger state:\n{ledger_state.model_dump_json(indent=2)}\n"
            'Required JSON shape: {"week": 1, "title": "...", "objective": "...", "allowed_dirs": ["..."], '
            '"required_files": ["..."], "implementation_steps": ["..."], "acceptance_checks": ["..."], '
            '"verification_expectations": ["..."], "summary": "..."}'
        )
        return self._completion_as_model(system_prompt, user_prompt, GeneratedTask)

    def score_learning_question(
        self,
        week_spec: dict[str, Any],
        question: LearningQuestion,
        answer: str,
        observation: ObservationRecord | None,
    ) -> QuestionScore:
        system_prompt = load_prompt("mentor.md")
        observation_json = observation.model_dump_json(indent=2) if observation is not None else "null"
        user_prompt = (
            "Evaluate whether the answer passes the current learning question.\n"
            "Use only the current-week context, the question rubric, and the observation if one is provided. Output JSON only.\n"
            f"Current week context:\n{self._week_context_json(week_spec)}\n"
            f"Question:\n{question.model_dump_json(indent=2)}\n"
            f"Observation:\n{observation_json}\n"
            f"Answer:\n{answer}\n"
            'Required JSON shape: {"passed": true, "score_rationale": "...", "missing_concepts": ["..."]}'
        )
        return self._completion_as_model(system_prompt, user_prompt, QuestionScore)

    def answer_topic_chat(
        self,
        week_spec: dict[str, Any],
        context: str,
        history: list[TopicChatTurn],
        message: str,
    ) -> str:
        messages = self._topic_chat_messages(week_spec, context, history, message)
        response = self._chat_completions_create(
            model=self.model,
            temperature=0.3,
            messages=messages,
        )
        content = response.choices[0].message.content
        if not content or not content.strip():
            raise LearningAgentError("OpenAI provider returned an empty topic chat response.")
        return content.strip()

    def stream_topic_chat(
        self,
        week_spec: dict[str, Any],
        context: str,
        history: list[TopicChatTurn],
        message: str,
    ) -> Iterator[str]:
        messages = self._topic_chat_messages(week_spec, context, history, message)
        response = self._chat_completions_create(
            model=self.model,
            temperature=0.3,
            messages=messages,
            stream=True,
        )
        emitted = False
        for chunk in response:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            text = self._coerce_stream_text(getattr(delta, "content", None))
            if not text:
                continue
            emitted = True
            yield text
        if not emitted:
            raise LearningAgentError("OpenAI provider returned an empty topic chat response.")

    def _topic_chat_messages(
        self,
        week_spec: dict[str, Any],
        context: str,
        history: list[TopicChatTurn],
        message: str,
    ) -> list[dict[str, str]]:
        system_prompt = load_prompt("mentor.md")
        history_lines = []
        for turn in history[-10:]:
            history_lines.append(f"{turn.role.title()}: {turn.content}")
        history_text = "\n".join(history_lines) if history_lines else "(no prior chat)"
        user_prompt = (
            "You are the topic tutor for the current unlocked week of this learning agent.\n"
            "Answer the user's question using the provided week context.\n"
            "Stay grounded in the current week, current artifacts, current metrics, and current progress.\n"
            "Be concise but technically useful.\n"
            "Do not invent repository state that is not present in the context.\n"
            "Avoid drifting into future-week material unless the user explicitly asks for a comparison.\n\n"
            f"Current week context:\n{self._week_context_json(week_spec)}\n\n"
            f"Current app context:\n{context}\n\n"
            f"Recent chat history:\n{history_text}\n\n"
            f"User question:\n{message}\n"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _coerce_stream_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            pieces: list[str] = []
            for item in content:
                if isinstance(item, str):
                    pieces.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        pieces.append(text)
                    continue
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    pieces.append(text)
            return "".join(pieces)
        return ""

    def _completion_as_model(
        self, system_prompt: str, user_prompt: str, response_model: Type[ResponseModelT]
    ) -> ResponseModelT:
        response = self._chat_completions_create(
            model=self.model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise LearningAgentError("OpenAI provider returned an empty response.")
        payload = self._extract_json(content)
        payload = self._normalize_payload(payload, response_model)
        return response_model.model_validate(payload)

    def _chat_completions_create(self, **kwargs: Any):
        client = self._client()
        try:
            return client.chat.completions.create(**kwargs)
        except LearningAgentError:
            raise
        except Exception as exc:
            raise self._translate_chat_error(exc) from exc

    def _translate_chat_error(self, exc: Exception) -> LearningAgentError:
        try:
            import openai
        except ImportError:
            return LearningAgentError(str(exc) or "OpenAI request failed.")

        if isinstance(exc, openai.AuthenticationError):
            return LearningAgentError("OpenAI authentication failed. Check OPENAI_API_KEY.")
        if isinstance(exc, openai.APIConnectionError):
            return LearningAgentError("OpenAI connection failed. Check network access and API configuration.")
        if isinstance(exc, openai.APITimeoutError):
            return LearningAgentError("OpenAI request timed out. Try again.")
        if isinstance(exc, openai.RateLimitError):
            return LearningAgentError("OpenAI rate limit hit. Try again shortly.")
        if isinstance(exc, openai.APIStatusError):
            status_code = getattr(exc, "status_code", None)
            if status_code:
                return LearningAgentError(f"OpenAI request failed with status {status_code}.")
            return LearningAgentError("OpenAI request failed.")
        if isinstance(exc, openai.OpenAIError):
            return LearningAgentError(str(exc) or "OpenAI request failed.")
        return LearningAgentError(str(exc) or "OpenAI request failed.")

    def _client(self):
        if not self.model:
            raise LearningAgentError("Config field `model` must be set before using the OpenAI provider.")
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise LearningAgentError("OPENAI_API_KEY must be set before using the OpenAI provider.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LearningAgentError("The `openai` package is not installed.") from exc
        return OpenAI(api_key=api_key)

    def _extract_json(self, content: str):
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LearningAgentError(f"Model response was not valid JSON: {exc}") from exc

    def _normalize_payload(self, payload: Any, response_model: Type[ResponseModelT]) -> Any:
        if not isinstance(payload, dict):
            return payload

        if response_model is ConceptCardPayload:
            concept_cards = payload.get("concept_cards")
            if isinstance(concept_cards, list):
                payload = dict(payload)
                payload["concept_cards"] = [self._normalize_concept_card(card) for card in concept_cards]
            return payload

        if response_model is LearningQuestionBankPayload:
            questions = payload.get("questions")
            if isinstance(questions, list):
                payload = dict(payload)
                payload["questions"] = [self._normalize_question(question) for question in questions]
        return payload

    def _reading_theme_hints(self, questions: list[LearningQuestion]) -> list[str]:
        counts: dict[str, int] = {}
        labels: dict[str, str] = {}
        for question in questions:
            for raw_hint in self._question_theme_candidates(question):
                key = self._slugify_hint(raw_hint)
                if not key:
                    continue
                counts[key] = counts.get(key, 0) + 1
                labels.setdefault(key, self._humanize_hint(raw_hint))
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [labels[key] for key, _count in ranked[:8]]

    def _question_theme_candidates(self, question: LearningQuestion) -> list[str]:
        return [token for token in question.prompt_text.split()[:4] if len(token) >= 4]

    def _slugify_hint(self, value: str) -> str:
        return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")

    def _humanize_hint(self, value: str) -> str:
        text = value.replace("_", " ").replace("-", " ").replace("/", " ").strip()
        return " ".join(part.capitalize() for part in text.split())

    def _normalize_concept_card(self, card: Any) -> Any:
        if not isinstance(card, dict):
            return card

        normalized = dict(card)
        if "why_it_matters" not in normalized and isinstance(normalized.get("why"), str):
            normalized["why_it_matters"] = normalized["why"]
        if "common_mistake" not in normalized and isinstance(normalized.get("mistake"), str):
            normalized["common_mistake"] = normalized["mistake"]
        if "quick_check_question" not in normalized:
            for key in ("quick_check", "quick_check_prompt"):
                value = normalized.get(key)
                if isinstance(value, str):
                    normalized["quick_check_question"] = value
                    break
        return normalized

    def _normalize_question(self, question: Any) -> Any:
        if not isinstance(question, dict):
            return question

        normalized = dict(question)

        depth = normalized.get("depth")
        if isinstance(depth, str):
            normalized["depth"] = self._normalize_question_depth(depth)

        return normalized

    def _normalize_question_depth(self, value: str) -> str:
        normalized = value.strip().lower()
        if normalized in {"baseline", "deep", "stretch"}:
            return normalized
        if any(token in normalized for token in {"base", "basic", "foundation", "intro"}):
            return "baseline"
        if any(token in normalized for token in {"deep", "deeper", "intermediate"}):
            return "deep"
        if any(token in normalized for token in {"stretch", "advanced", "expert"}):
            return "stretch"
        return "deep"

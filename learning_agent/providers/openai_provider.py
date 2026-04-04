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
from learning_agent.prompts import load_prompt, render_prompt
from learning_agent.providers.base import LLMProvider


ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str):
        self.model = model.strip()

    def _week_context_json(self, week_spec: dict[str, Any]) -> str:
        return json.dumps(week_spec, indent=2, sort_keys=True)

    def generate_question_bank(self, week_spec: dict[str, Any], ledger_state: ProgressState) -> LearningQuestionBankPayload:
        system_prompt = load_prompt("mentor.md")
        base_user_prompt = render_prompt(
            "question_bank_user.md",
            {
                "WEEK_CONTEXT_JSON": self._week_context_json(week_spec),
                "LEDGER_STATE_JSON": ledger_state.model_dump_json(indent=2),
            },
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
        user_prompt = render_prompt(
            "reading_material_user.md",
            {
                "THEME_HINTS_BLOCK": (
                    "Recurring question themes to consider when naming the remaining markdown sections:\n"
                    f"{json.dumps(theme_hints, indent=2)}\n\n"
                    if theme_hints
                    else ""
                ),
                "WEEK_CONTEXT_JSON": self._week_context_json(week_spec),
                "LEDGER_STATE_JSON": ledger_state.model_dump_json(indent=2),
                "QUESTION_BANK_JSON": json.dumps([question.model_dump(mode="json") for question in questions], indent=2),
            },
        )
        return self._completion_as_model(system_prompt, user_prompt, ReadingMaterialPayload)

    def generate_concept_cards_from_reading(
        self,
        week_spec: dict[str, Any],
        ledger_state: ProgressState,
        reading_material: ReadingMaterialPayload,
    ) -> ConceptCardPayload:
        system_prompt = load_prompt("mentor.md")
        user_prompt = render_prompt(
            "concept_cards_from_reading_user.md",
            {
                "WEEK_CONTEXT_JSON": self._week_context_json(week_spec),
                "LEDGER_STATE_JSON": ledger_state.model_dump_json(indent=2),
                "READING_MATERIAL_JSON": reading_material.model_dump_json(indent=2),
            },
        )
        return self._completion_as_model(system_prompt, user_prompt, ConceptCardPayload)

    def generate_task(self, week_spec: dict[str, Any], ledger_state: ProgressState) -> GeneratedTask:
        system_prompt = load_prompt("junior.md")
        user_prompt = render_prompt(
            "generate_task_user.md",
            {
                "WEEK_CONTEXT_JSON": self._week_context_json(week_spec),
                "LEDGER_STATE_JSON": ledger_state.model_dump_json(indent=2),
            },
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
        user_prompt = render_prompt(
            "score_learning_question_user.md",
            {
                "WEEK_CONTEXT_JSON": self._week_context_json(week_spec),
                "QUESTION_JSON": question.model_dump_json(indent=2),
                "OBSERVATION_JSON": observation_json,
                "ANSWER": answer,
            },
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
        user_prompt = render_prompt(
            "topic_chat_user.md",
            {
                "WEEK_CONTEXT_JSON": self._week_context_json(week_spec),
                "APP_CONTEXT": context,
                "HISTORY_TEXT": history_text,
                "MESSAGE": message,
            },
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

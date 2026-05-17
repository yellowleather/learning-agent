from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any, Type, TypeVar

from pydantic import BaseModel

from coach.errors import CoachError
from coach.models import (
    GeneratedTask,
    ProgressState,
)
from topic_chat.models import TopicChatTurn
from verify.models import (
    ObservationRecord,
)
from learn.models import (
    ConceptCardPayload,
    LearningQuestion,
    LearningQuestionBankPayload,
    QuestionScore,
    ReadingMaterialPayload,
)
from build.prompts import render_prompt as build_render_prompt
from coach.prompts import load_prompt
from coach.providers.base import LLMProvider
from learn.prompts import render_prompt as learn_render_prompt
from topic_chat.prompts import render_prompt as chat_render_prompt


ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str):
        self.model = model.strip()

    def generate_prior_knowledge_summary(self, full_plan: str, target_week_number: int) -> str:
        system_prompt = load_prompt("mentor.md")
        user_prompt = learn_render_prompt(
            "prior_knowledge_summary.md",
            {
                "FULL_PLAN": full_plan,
                "TARGET_WEEK_NUMBER": str(target_week_number),
            },
        )
        return self._completion_as_text(system_prompt, user_prompt)

    def generate_question_bank(
        self,
        week_spec: dict[str, Any],
        prior_knowledge_summary: str,
        ledger_state: ProgressState,
    ) -> LearningQuestionBankPayload:
        system_prompt = load_prompt("mentor.md")
        base_user_prompt = learn_render_prompt(
            "question_bank.md",
            {
                "PRIOR_KNOWLEDGE_SUMMARY": prior_knowledge_summary,
                "WEEK_PLAN": self._week_plan_text(week_spec),
                "LEDGER_STATE_JSON": ledger_state.model_dump_json(indent=2),
            },
        )
        return self._completion_as_model(system_prompt, base_user_prompt, LearningQuestionBankPayload)

    def generate_reading_material(
        self,
        week_spec: dict[str, Any],
        prior_knowledge_summary: str,
        ledger_state: ProgressState,
        questions: list[LearningQuestion],
    ) -> ReadingMaterialPayload:
        system_prompt = load_prompt("mentor.md")
        user_prompt = learn_render_prompt(
            "reading_material.md",
            {
                "PRIOR_KNOWLEDGE_SUMMARY": prior_knowledge_summary,
                "WEEK_PLAN": self._week_plan_text(week_spec),
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
        user_prompt = learn_render_prompt(
            "concept_cards_from_reading.md",
            {
                "WEEK_PLAN": self._week_plan_text(week_spec),
                "LEDGER_STATE_JSON": ledger_state.model_dump_json(indent=2),
                "READING_MATERIAL_JSON": reading_material.model_dump_json(indent=2),
            },
        )
        return self._completion_as_model(system_prompt, user_prompt, ConceptCardPayload)

    def generate_task(self, week_spec: dict[str, Any], ledger_state: ProgressState) -> GeneratedTask:
        # generate_task.md lives in build/ since it shapes a build-domain artefact;
        # the junior.md system prompt is still the runtime persona, loaded from coach/.
        system_prompt = load_prompt("junior.md")
        user_prompt = build_render_prompt(
            "generate_task.md",
            {
                "WEEK_PLAN": self._week_plan_text(week_spec),
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
        user_prompt = learn_render_prompt(
            "score_learning_question.md",
            {
                "WEEK_PLAN": self._week_plan_text(week_spec),
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
            raise CoachError("OpenAI provider returned an empty topic chat response.")
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
            raise CoachError("OpenAI provider returned an empty topic chat response.")

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
        user_prompt = chat_render_prompt(
            "topic_chat.md",
            {
                "WEEK_PLAN": self._week_plan_text(week_spec),
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
            raise CoachError("OpenAI provider returned an empty response.")
        payload = self._extract_json(content)
        payload = self._normalize_payload(payload, response_model)
        return response_model.model_validate(payload)

    def _completion_as_text(self, system_prompt: str, user_prompt: str) -> str:
        response = self._chat_completions_create(
            model=self.model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        if not content or not content.strip():
            raise CoachError("OpenAI provider returned an empty response.")
        return content.strip()

    def _chat_completions_create(self, **kwargs: Any):
        client = self._client()
        try:
            return client.chat.completions.create(**kwargs)
        except CoachError:
            raise
        except Exception as exc:
            raise self._translate_chat_error(exc) from exc

    def _translate_chat_error(self, exc: Exception) -> CoachError:
        try:
            import openai
        except ImportError:
            return CoachError(str(exc) or "OpenAI request failed.")

        if isinstance(exc, openai.AuthenticationError):
            return CoachError("OpenAI authentication failed. Check OPENAI_API_KEY.")
        if isinstance(exc, openai.APIConnectionError):
            return CoachError("OpenAI connection failed. Check network access and API configuration.")
        if isinstance(exc, openai.APITimeoutError):
            return CoachError("OpenAI request timed out. Try again.")
        if isinstance(exc, openai.RateLimitError):
            return CoachError("OpenAI rate limit hit. Try again shortly.")
        if isinstance(exc, openai.APIStatusError):
            status_code = getattr(exc, "status_code", None)
            if status_code:
                return CoachError(f"OpenAI request failed with status {status_code}.")
            return CoachError("OpenAI request failed.")
        if isinstance(exc, openai.OpenAIError):
            return CoachError(str(exc) or "OpenAI request failed.")
        return CoachError(str(exc) or "OpenAI request failed.")

    def _client(self):
        if not self.model:
            raise CoachError("Config field `model` must be set before using the OpenAI provider.")
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise CoachError("OPENAI_API_KEY must be set before using the OpenAI provider.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise CoachError("The `openai` package is not installed.") from exc
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
            raise CoachError(f"Model response was not valid JSON: {exc}") from exc

    def _normalize_payload(self, payload: Any, response_model: Type[ResponseModelT]) -> Any:
        if not isinstance(payload, dict):
            return payload

        if response_model is LearningQuestionBankPayload:
            questions = payload.get("questions")
            if isinstance(questions, list):
                payload = dict(payload)
                payload["questions"] = [self._normalize_question(question) for question in questions]
        return payload

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

    def _week_plan_text(self, week_spec: dict[str, Any]) -> str:
        lines = [
            f"Week {week_spec['number']}: {week_spec['short_title']}",
            "",
            "Goal:",
            str(week_spec.get("goal") or "").strip(),
            "",
            "Narrative:",
            str(week_spec.get("narrative") or "").strip(),
            "",
            "Topics Covered:",
            *self._bullet_lines(week_spec.get("topics_covered", [])),
            "",
            "By the End of This Week You Will Be Able To:",
            *self._bullet_lines(week_spec.get("by_the_end_of_this_week_you_will_be_able_to", [])),
            "",
            "Assessment Targets:",
            *self._numbered_lines(week_spec.get("assessment_targets", [])),
            "",
            "Implementation Tasks:",
            *self._bullet_lines(week_spec.get("tasks", [])),
            "",
            "Deliverable Paths:",
            *self._bullet_lines(week_spec.get("deliverable_paths", [])),
            "",
            "Required Files:",
            *self._bullet_lines(week_spec.get("required_files", [])),
            "",
            "Active Directories:",
            *self._bullet_lines(week_spec.get("active_dirs", [])),
            "",
            "Required Metrics:",
            *self._bullet_lines(week_spec.get("required_metrics", [])),
            "",
            "Key Resources:",
            *self._bullet_lines(week_spec.get("key_resources", [])),
        ]
        return "\n".join(lines).strip()

    def _bullet_lines(self, values: Any) -> list[str]:
        items = [str(value).strip() for value in (values or []) if str(value).strip()]
        return [f"- {item}" for item in items] or ["- (none)"]

    def _numbered_lines(self, values: Any) -> list[str]:
        items = [str(value).strip() for value in (values or []) if str(value).strip()]
        return [f"{index}. {item}" for index, item in enumerate(items, start=1)] or ["1. (none)"]

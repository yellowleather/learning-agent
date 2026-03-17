from __future__ import annotations

import json
import os
from typing import Type, TypeVar

from pydantic import BaseModel

from learning_agent.errors import LearningAgentError
from learning_agent.models import GateQuestion, GateResult, GeneratedTask, ProgressState, WeekSpec
from learning_agent.prompts import load_prompt
from learning_agent.providers.base import LLMProvider


ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str):
        self.model = model.strip()

    def generate_gate_question(self, week_spec: WeekSpec) -> GateQuestion:
        system_prompt = load_prompt("mentor.md")
        user_prompt = (
            "Create one Socratic concept gate question for the current week.\n"
            "Use only the provided current-week context. Output JSON only.\n"
            f"Current week context:\n{week_spec.model_dump_json(indent=2)}\n"
            'Required JSON shape: {"week": 1, "question": "...", "rubric": ["..."], "context_summary": "..."}'
        )
        return self._completion_as_model(system_prompt, user_prompt, GateQuestion)

    def score_gate_answer(self, week_spec: WeekSpec, question: GateQuestion, answer: str) -> GateResult:
        system_prompt = load_prompt("mentor.md")
        user_prompt = (
            "Evaluate whether the answer passes the concept gate.\n"
            "Use only the current-week context and rubric. Output JSON only.\n"
            f"Current week context:\n{week_spec.model_dump_json(indent=2)}\n"
            f"Question:\n{question.model_dump_json(indent=2)}\n"
            f"Answer:\n{answer}\n"
            'Required JSON shape: {"passed": true, "score_rationale": "...", "missing_concepts": ["..."]}'
        )
        return self._completion_as_model(system_prompt, user_prompt, GateResult)

    def generate_task(self, week_spec: WeekSpec, ledger_state: ProgressState) -> GeneratedTask:
        system_prompt = load_prompt("junior.md")
        user_prompt = (
            "Generate the current-week implementation task for the Junior SWE.\n"
            "Use only the provided current-week context and ledger state. Output JSON only.\n"
            f"Current week context:\n{week_spec.model_dump_json(indent=2)}\n"
            f"Current ledger state:\n{ledger_state.model_dump_json(indent=2)}\n"
            'Required JSON shape: {"week": 1, "title": "...", "objective": "...", "allowed_dirs": ["..."], '
            '"required_files": ["..."], "implementation_steps": ["..."], "acceptance_checks": ["..."], '
            '"verification_expectations": ["..."], "summary": "..."}'
        )
        return self._completion_as_model(system_prompt, user_prompt, GeneratedTask)

    def _completion_as_model(
        self, system_prompt: str, user_prompt: str, response_model: Type[ResponseModelT]
    ) -> ResponseModelT:
        client = self._client()
        response = client.chat.completions.create(
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
        return response_model.model_validate(self._extract_json(content))

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

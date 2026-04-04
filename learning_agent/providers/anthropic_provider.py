from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from learning_agent.errors import LearningAgentError
from learning_agent.models import TopicChatTurn
from learning_agent.providers.openai_provider import OpenAIProvider, ResponseModelT


ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
ANTHROPIC_REQUEST_TIMEOUT_SECONDS = 600
DEFAULT_MAX_TOKENS = 12000
DEFAULT_TOPIC_CHAT_MAX_TOKENS = 2000


class AnthropicProvider(OpenAIProvider):
    def _completion_as_model(
        self, system_prompt: str, user_prompt: str, response_model: type[ResponseModelT]
    ) -> ResponseModelT:
        text = self._request_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=DEFAULT_MAX_TOKENS,
        )
        payload = self._extract_json(text)
        payload = self._normalize_payload(payload, response_model)
        return response_model.model_validate(payload)

    def _completion_as_text(self, system_prompt: str, user_prompt: str) -> str:
        return self._request_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=DEFAULT_MAX_TOKENS,
        )

    def answer_topic_chat(
        self,
        week_spec: dict[str, Any],
        context: str,
        history: list[TopicChatTurn],
        message: str,
    ) -> str:
        messages = self._topic_chat_messages(week_spec, context, history, message)
        text = self._request_text(
            system_prompt=messages[0]["content"],
            user_prompt=messages[1]["content"],
            temperature=0.3,
            max_tokens=DEFAULT_TOPIC_CHAT_MAX_TOKENS,
        )
        if not text.strip():
            raise LearningAgentError("Anthropic provider returned an empty topic chat response.")
        return text.strip()

    def stream_topic_chat(
        self,
        week_spec: dict[str, Any],
        context: str,
        history: list[TopicChatTurn],
        message: str,
    ):
        yield self.answer_topic_chat(week_spec, context, history, message)

    def _request_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        response = self._messages_create(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = self._response_text(response)
        if not text.strip():
            raise LearningAgentError("Anthropic provider returned an empty response.")
        return text.strip()

    def _messages_create(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        if not self.model:
            raise LearningAgentError("Config field `model` must be set before using the Anthropic provider.")
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise LearningAgentError("ANTHROPIC_API_KEY must be set before using the Anthropic provider.")

        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        request = urllib.request.Request(
            ANTHROPIC_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_API_VERSION,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=ANTHROPIC_REQUEST_TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise self._translate_http_error(exc.code, detail) from exc
        except urllib.error.URLError as exc:
            raise LearningAgentError("Anthropic connection failed. Check network access and API configuration.") from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise LearningAgentError(f"Anthropic response was not valid JSON: {exc}") from exc

    def _response_text(self, response: dict[str, Any]) -> str:
        content_blocks = response.get("content", [])
        pieces: list[str] = []
        for block in content_blocks:
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                pieces.append(block["text"])
        return "".join(pieces)

    def _translate_http_error(self, status_code: int, detail: str) -> LearningAgentError:
        if status_code in {401, 403}:
            return LearningAgentError("Anthropic authentication failed. Check ANTHROPIC_API_KEY.")
        if status_code == 408:
            return LearningAgentError("Anthropic request timed out. Try again.")
        if status_code == 429:
            return LearningAgentError("Anthropic rate limit hit. Try again shortly.")
        if detail:
            return LearningAgentError(f"Anthropic request failed with HTTP {status_code}: {detail}")
        return LearningAgentError(f"Anthropic request failed with HTTP {status_code}.")

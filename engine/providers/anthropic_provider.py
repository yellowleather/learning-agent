from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from engine.errors import EngineError
from engine.providers.base import AgentToolCall, AgentTurnResult
from topic_chat.models import TopicChatTurn
from engine.providers.openai_provider import OpenAIProvider, ResponseModelT


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
            raise EngineError("Anthropic provider returned an empty topic chat response.")
        return text.strip()

    def stream_topic_chat(
        self,
        week_spec: dict[str, Any],
        context: str,
        history: list[TopicChatTurn],
        message: str,
    ):
        yield self.answer_topic_chat(week_spec, context, history, message)

    def run_agent_turn(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        deep_reasoning: bool = True,
    ) -> AgentTurnResult:
        response = self._messages_create(
            system_prompt=system_prompt,
            messages=self._translate_messages_to_anthropic(messages),
            tools=self._anthropic_tools(tools),
            temperature=0.2,
            max_tokens=DEFAULT_MAX_TOKENS,
            thinking={"type": "enabled", "budget_tokens": 8000} if deep_reasoning else None,
        )
        pieces: list[str] = []
        tool_calls: list[AgentToolCall] = []
        for block in response.get("content", []):
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                pieces.append(block["text"])
                continue
            if block.get("type") == "tool_use":
                raw_input = block.get("input") or {}
                if not isinstance(raw_input, dict):
                    raise EngineError("Anthropic tool call input must be a JSON object.")
                tool_calls.append(
                    AgentToolCall(
                        id=str(block.get("id") or ""),
                        name=str(block.get("name") or ""),
                        arguments=raw_input,
                    )
                )
        text = "".join(pieces).strip()
        if not text and not tool_calls:
            raise EngineError("Anthropic provider returned an empty agent turn.")
        return AgentTurnResult(
            text=text,
            tool_calls=tool_calls,
            stop_reason=str(response.get("stop_reason") or ""),
        )

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
            raise EngineError("Anthropic provider returned an empty response.")
        return text.strip()

    def _messages_create(
        self,
        *,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        user_prompt: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        thinking: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.model:
            raise EngineError("Config field `model` must be set before using the Anthropic provider.")
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EngineError("ANTHROPIC_API_KEY must be set before using the Anthropic provider.")

        if messages is None:
            if user_prompt is None:
                raise EngineError("Anthropic request needs either user_prompt or messages.")
            messages = [{"role": "user", "content": user_prompt}]

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": messages,
        }
        if tools is not None:
            payload["tools"] = tools
        if thinking is not None:
            payload["thinking"] = thinking
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
            raise EngineError("Anthropic connection failed. Check network access and API configuration.") from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise EngineError(f"Anthropic response was not valid JSON: {exc}") from exc

    def _response_text(self, response: dict[str, Any]) -> str:
        content_blocks = response.get("content", [])
        pieces: list[str] = []
        for block in content_blocks:
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                pieces.append(block["text"])
        return "".join(pieces)

    def _translate_http_error(self, status_code: int, detail: str) -> EngineError:
        if status_code in {401, 403}:
            return EngineError("Anthropic authentication failed. Check ANTHROPIC_API_KEY.")
        if status_code == 408:
            return EngineError("Anthropic request timed out. Try again.")
        if status_code == 429:
            return EngineError("Anthropic rate limit hit. Try again shortly.")
        if detail:
            return EngineError(f"Anthropic request failed with HTTP {status_code}: {detail}")
        return EngineError(f"Anthropic request failed with HTTP {status_code}.")

    def _translate_messages_to_anthropic(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        translated: list[dict[str, Any]] = []
        # Anthropic requires all tool results from one assistant turn batched into
        # a single user message, so we buffer them until the run ends or a non-tool
        # message breaks the sequence.
        pending_results: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role")

            if role == "tool":
                pending_results.append({
                    "type": "tool_result",
                    "tool_use_id": str(msg.get("tool_call_id") or ""),
                    "content": str(msg.get("content") or ""),
                })
                continue

            if pending_results:
                translated.append({"role": "user", "content": pending_results})
                pending_results = []

            if role == "assistant" and msg.get("tool_calls"):
                content: list[dict[str, Any]] = []
                # The model may produce tool_use blocks with no text (e.g. when
                # extended thinking absorbs the reasoning), so the text block is optional.
                if msg.get("content"):
                    content.append({"type": "text", "text": str(msg["content"])})
                for tc in msg["tool_calls"]:
                    content.append({
                        "type": "tool_use",
                        "id": str(tc["id"]),
                        "name": str(tc["name"]),
                        "input": dict(tc["arguments"]),
                    })
                translated.append({"role": "assistant", "content": content})
            else:
                translated.append(msg)

        if pending_results:
            translated.append({"role": "user", "content": pending_results})

        return translated

    def _anthropic_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted = []
        for tool in tools:
            function = tool.get("function", tool)
            converted.append(
                {
                    "name": function["name"],
                    "description": function.get("description", ""),
                    "input_schema": function.get("parameters", {"type": "object"}),
                }
            )
        return converted

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from build.agent.tools import BuildToolContext, tool_schemas
from build.models import BuildReport, BuildSession, TranscriptEvent
from engine.errors import EngineError
from engine.providers.base import LLMProvider
from engine.state import StateStore


class BuildAgentLoop:
    """Execute the think -> tool -> observe loop for one build session."""

    def __init__(
        self,
        *,
        state: StateStore,
        provider: LLMProvider,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: BuildToolContext,
        wall_clock_seconds: int,
        max_turns: int,
    ):
        self.state = state
        self.provider = provider
        self.system_prompt = system_prompt
        self.messages = messages
        self.tools = tools
        self.wall_clock_seconds = wall_clock_seconds
        self.max_turns = max_turns
        self._seq = 0

    def run(self, session: BuildSession) -> BuildSession:
        started = time.monotonic()
        try:
            for turn_index in range(self.max_turns):
                if time.monotonic() - started >= self.wall_clock_seconds:
                    session.report = self._report("timed_out", "BuildAgent timed out.", "")
                    break

                result = self.provider.run_agent_turn(
                    system_prompt=self.system_prompt,
                    messages=self.messages,
                    tools=tool_schemas(),
                    deep_reasoning=True,
                )
                session.turn_count = turn_index + 1
                if result.text:
                    self._append("thought", {"text": result.text})

                assistant_msg: dict[str, Any] = {"role": "assistant", "content": result.text}
                if result.tool_calls:
                    # Providers need id/name/arguments to reconstruct their wire format
                    # (Anthropic: tool_use content blocks; OpenAI: tool_calls with JSON-encoded args).
                    assistant_msg["tool_calls"] = [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in result.tool_calls
                    ]
                self.messages.append(assistant_msg)

                if not result.tool_calls:
                    self._append("system", {"message": "Agent turn had no tool calls."})
                    continue

                for tool_call in result.tool_calls:
                    self._append(
                        "tool_call",
                        {
                            "id": tool_call.id,
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                        },
                    )
                    try:
                        payload = self.tools.execute(tool_call.name, tool_call.arguments)
                    except EngineError as exc:
                        payload = {"error": str(exc)}
                        self._append("tool_error", {"id": tool_call.id, **payload})
                    else:
                        self._append("tool_result", {"id": tool_call.id, "result": payload})

                    self.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": json.dumps(payload, sort_keys=True),
                        }
                    )

                    if self.tools.done_payload is not None:
                        session.report = self._report(
                            self.tools.done_payload["status"],
                            self.tools.done_payload["summary"],
                            self.tools.done_payload.get("notes", ""),
                        )
                        break

                if session.report is not None:
                    break

            if session.report is None:
                session.report = self._report(
                    "errored",
                    "BuildAgent reached the maximum turn count without calling done.",
                    "",
                )
        except Exception as exc:
            if isinstance(exc, EngineError):
                message = str(exc)
            else:  # pragma: no cover
                message = f"Unexpected BuildAgent error: {exc}"
            self._append("system", {"error": message})
            session.report = self._report("errored", message, "")

        session.ended_at_utc = _now_iso()
        session.duration_seconds = int(time.monotonic() - started)
        self.state.save_build_session(session)
        return session

    def _report(self, status: str, summary: str, notes: str) -> BuildReport:
        return BuildReport(
            status=status,  # type: ignore[arg-type]
            summary=summary,
            commands_run=self.tools.commands_run,
            files_touched=self.tools.files_touched(),
            metrics_recorded=self.tools.metrics_recorded,
            notes=notes,
        )

    def _append(self, kind: str, payload: dict[str, Any]) -> None:
        event = TranscriptEvent(
            seq=self._seq,
            timestamp_utc=_now_iso(),
            kind=kind,  # type: ignore[arg-type]
            payload=payload,
        )
        self._seq += 1
        self.state.append_transcript_event(event)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

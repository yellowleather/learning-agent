"""Topic chat service.

A standalone chat surface that the orchestrator wires up. It owns the
chat-internal transformations — reply normalisation, JSON-wrapped reply
unwrapping, selection-context truncation, system-context formatting — and
the streaming handshake with the provider.

It does not reach into stages or load state itself. Cross-stage facts
(blockers, question progress, default-step fallback) are passed in by the
caller, keeping the dependency direction one-way: orchestrator → TopicChat.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any, Callable

from coach.errors import CoachError
from coach.models import Ledger, LearningSession, TopicChatTurn
from coach.providers.base import LLMProvider


VALID_STEPS = {"learn", "build", "verify", "approve"}

MAX_SELECTION_CHARS = 2400

_REPLY_JSON_KEYS = ("response", "reply", "message", "content", "text", "answer")


class TopicChat:
    """Chat handler. Constructed with a factory so each request talks to a
    freshly-resolved provider (matching the prior controller behaviour)."""

    def __init__(self, provider_factory: Callable[[], LLMProvider]):
        self._provider_factory = provider_factory

    # -- Public API --------------------------------------------------------

    def stream(
        self,
        *,
        ledger: Ledger,
        week_spec: dict[str, Any],
        learning_session: LearningSession | None,
        message: str,
        history: list[dict[str, str]] | list[TopicChatTurn],
        current_step: str,
        default_step_fallback: str,
        blockers: list[str],
        question_progress: dict[str, Any],
        selected_question_id: str | None = None,
        selection_context: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream `start` → many `delta` → `done` events for a chat turn.

        The orchestrator is responsible for loading ledger / week / session and
        for resolving the default step + blockers + progress before calling.
        """
        if not message.strip():
            raise CoachError("Topic chat message cannot be empty.")

        step_id = current_step.strip().lower() or default_step_fallback
        if step_id not in VALID_STEPS:
            raise CoachError(f"Unknown workflow step: {current_step}")

        history_turns = [
            turn if isinstance(turn, TopicChatTurn) else TopicChatTurn.model_validate(turn)
            for turn in history
        ]
        context_label, context = self._build_context(
            ledger=ledger,
            week_spec=week_spec,
            learning_session=learning_session,
            current_step=step_id,
            blockers=blockers,
            question_progress=question_progress,
            selected_question_id=selected_question_id,
            selection_context=selection_context,
        )
        yield {
            "type": "start",
            "week": int(week_spec["number"]),
            "context_label": context_label,
        }

        raw_chunks: list[str] = []
        provider = self._provider_factory()
        stream_method = getattr(provider, "stream_topic_chat", None)
        if callable(stream_method):
            stream = stream_method(week_spec, context, history_turns, message.strip())
        else:
            stream = iter([provider.answer_topic_chat(week_spec, context, history_turns, message.strip())])

        for chunk in stream:
            text = str(chunk or "")
            if not text:
                continue
            raw_chunks.append(text)
            yield {"type": "delta", "delta": text}

        reply = self._normalize_reply("".join(raw_chunks))
        yield {
            "type": "done",
            "reply": reply,
            "week": int(week_spec["number"]),
            "context_label": context_label,
        }

    def answer(
        self,
        *,
        ledger: Ledger,
        week_spec: dict[str, Any],
        learning_session: LearningSession | None,
        message: str,
        history: list[dict[str, str]] | list[TopicChatTurn],
        current_step: str,
        default_step_fallback: str,
        blockers: list[str],
        question_progress: dict[str, Any],
        selected_question_id: str | None = None,
        selection_context: str | None = None,
    ) -> dict[str, Any]:
        """Non-streaming convenience: drains stream() and returns the final reply."""
        done_event: dict[str, Any] | None = None
        error_message: str | None = None
        for event in self.stream(
            ledger=ledger,
            week_spec=week_spec,
            learning_session=learning_session,
            message=message,
            history=history,
            current_step=current_step,
            default_step_fallback=default_step_fallback,
            blockers=blockers,
            question_progress=question_progress,
            selected_question_id=selected_question_id,
            selection_context=selection_context,
        ):
            event_type = str(event.get("type") or "")
            if event_type == "done":
                done_event = event
            if event_type == "error":
                error_message = str(event.get("error") or "Topic chat request failed.")

        if error_message:
            raise CoachError(error_message)
        if done_event is None:
            raise CoachError("Topic chat stream ended before a final reply was produced.")
        return {
            "reply": str(done_event.get("reply") or ""),
            "week": done_event.get("week"),
            "context_label": str(done_event.get("context_label") or ""),
        }

    # -- Reply normalisation -----------------------------------------------

    def _normalize_reply(self, reply: str) -> str:
        """Strip JSON wrappers some providers wrap chat replies in."""
        text = str(reply or "").strip()
        if not text:
            raise CoachError("Topic chat returned an empty reply.")

        parsed = self._parse_json(text)
        if parsed is None:
            return text

        extracted = self._extract_message(parsed)
        return extracted or text

    def _parse_json(self, text: str) -> dict[str, Any] | list[Any] | None:
        """Try the raw text first, then a fenced ```json``` block."""
        candidates = [text]
        fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL)
        if fenced:
            candidates.insert(0, fenced.group(1).strip())

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, (dict, list)):
                return parsed
        return None

    def _extract_message(self, payload: dict[str, Any] | list[Any]) -> str | None:
        """Walk a parsed JSON reply for the first plausible message field."""
        if isinstance(payload, dict):
            for key in _REPLY_JSON_KEYS:
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, dict):
                    nested = self._extract_message(value)
                    if nested:
                        return nested
            return None
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, str) and item.strip():
                    return item.strip()
                if isinstance(item, (dict, list)):
                    nested = self._extract_message(item)
                    if nested:
                        return nested
        return None

    # -- Selection-context truncation --------------------------------------

    def _normalize_selection(self, selection_context: str | None) -> tuple[str, bool]:
        """Clamp pasted UI text to MAX_SELECTION_CHARS, preferring a line boundary."""
        text = str(selection_context or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            return "", False

        if len(text) <= MAX_SELECTION_CHARS:
            return text, False

        clipped = text[:MAX_SELECTION_CHARS].rstrip()
        if "\n" not in clipped:
            clipped = clipped.rsplit(" ", 1)[0].rstrip() or text[:MAX_SELECTION_CHARS].rstrip()
        return clipped, True

    # -- Context assembly --------------------------------------------------

    def _build_context(
        self,
        *,
        ledger: Ledger,
        week_spec: dict[str, Any],
        learning_session: LearningSession | None,
        current_step: str,
        blockers: list[str],
        question_progress: dict[str, Any],
        selected_question_id: str | None,
        selection_context: str | None,
    ) -> tuple[str, str]:
        """Render the week + ledger + learning + selection facts into a chat
        system context block. Returns (context_label, context_text)."""
        normalized_selection, selection_was_truncated = self._normalize_selection(selection_context)
        lines = [
            f"Step: {current_step}",
            f"Week title: {week_spec['short_title']}",
            f"Week goal: {week_spec['goal']}",
            "Active directories: " + (", ".join(week_spec["active_dirs"]) or "(none)"),
            "Required files: " + (", ".join(week_spec["required_files"]) or "(none)"),
            "Required metrics: " + (", ".join(week_spec["required_metrics"]) or "(none)"),
            "Completed files: " + (", ".join(ledger.state.artifacts.completed_files) or "(none)"),
            "Recorded metrics: "
            + (json.dumps(ledger.state.metrics.recorded, sort_keys=True) if ledger.state.metrics.recorded else "(none)"),
            "Approval blockers: " + (", ".join(blockers) or "(none)"),
            (
                "Learning progress: "
                f"{question_progress['required_passed']}/{question_progress['required_total']} baseline questions passed"
            ),
        ]

        context_label = f"Week {week_spec['number']} · {_humanize_label(current_step)}"
        if selected_question_id and current_step == "learn":
            lines.append(
                "Selected question context is available in the UI but is intentionally not injected into chat grounding by default."
            )
        if normalized_selection:
            lines.append("Selected UI text for this message:")
            lines.append("<<<SELECTED_TEXT")
            lines.append(normalized_selection)
            lines.append("SELECTED_TEXT>>>")
            if selection_was_truncated:
                lines.append("Selected UI text was truncated to fit the topic chat context window.")

        if learning_session is not None:
            lines.append(
                "Available concept cards: "
                + (
                    ", ".join(card.title or card.concept for card in learning_session.concept_cards[:8])
                    or "(none)"
                )
            )
            if learning_session.reading_material is not None:
                lines.append(f"Reading title: {learning_session.reading_material.title}")

        if ledger.state.observation is not None:
            observation = ledger.state.observation
            lines.append(f"Latest observation command: {observation.command}")
            lines.append(f"Latest observation artifact: {observation.artifact_path}")
            lines.append(f"Latest observation reliability: {observation.reliability}")

        if ledger.state.verification is not None:
            verification = ledger.state.verification
            lines.append(f"Latest verification status: {'passed' if verification.passed else 'failed'}")
            lines.append(f"Latest verification summary: {verification.summary}")

        if ledger.state.reflection is not None:
            lines.append(f"Latest reflection: {ledger.state.reflection.text}")

        return context_label, "\n".join(lines)


def _humanize_label(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("-", "_").split("_") if part)

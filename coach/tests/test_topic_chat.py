"""Unit tests for the TopicChat service.

Covers the chat-internal behaviours that used to live on WeekOrchestrator:
empty-message rejection, step validation, default-step fallback, streaming
event shape, JSON-wrapped reply unwrapping, and selection-context truncation.
"""

from collections.abc import Iterator

import pytest

from coach.errors import CoachError
from coach.models import (
    ArtifactState,
    ConceptCard,
    Gates,
    Ledger,
    LearningSession,
    MetricsState,
    ProgressState,
    ReadingMaterialPayload,
)
from coach.topic_chat import MAX_SELECTION_CHARS, TopicChat


class _RecordingProvider:
    """Captures the (context, history, message) the chat handed to the provider
    and returns a configurable reply for assertion."""

    def __init__(self, reply: str):
        self._reply = reply
        self.last_week_spec = None
        self.last_context = None
        self.last_history = None
        self.last_message = None

    def answer_topic_chat(self, week_spec, context, history, message):
        self.last_week_spec = week_spec
        self.last_context = context
        self.last_history = history
        self.last_message = message
        return self._reply


class _StreamingProvider(_RecordingProvider):
    """Splits the configured reply into chunks so we can assert delta events."""

    def __init__(self, chunks: list[str]):
        super().__init__(reply="".join(chunks))
        self._chunks = chunks

    def stream_topic_chat(self, week_spec, context, history, message) -> Iterator[str]:
        self.last_week_spec = week_spec
        self.last_context = context
        self.last_history = history
        self.last_message = message
        for chunk in self._chunks:
            yield chunk


def _empty_ledger() -> Ledger:
    return Ledger(
        curriculum_metadata={
            "title": "Test",
            "total_weeks": 1,
            "target_repo": "target",
        },
        state=ProgressState(
            current_week=1,
            active_dirs=["dir_one"],
            artifacts=ArtifactState(required_files=["dir_one/file.py"], completed_files=[]),
            gates=Gates(),
            metrics=MetricsState(required=["latency_p95"], recorded={}),
        ),
    )


def _week_spec() -> dict:
    return {
        "number": 1,
        "short_title": "First Week",
        "goal": "Do the thing.",
        "active_dirs": ["dir_one"],
        "required_files": ["dir_one/file.py"],
        "required_metrics": ["latency_p95"],
    }


def _facts() -> dict:
    return {
        "blockers": ["learning check not passed"],
        "question_progress": {"required_passed": 0, "required_total": 5},
        "default_step_fallback": "learn",
    }


def test_empty_message_is_rejected() -> None:
    # Empty / whitespace messages must not reach the provider.
    chat = TopicChat(provider_factory=lambda: _RecordingProvider("ignored"))
    with pytest.raises(CoachError):
        list(
            chat.stream(
                ledger=_empty_ledger(),
                week_spec=_week_spec(),
                learning_session=None,
                message="   ",
                history=[],
                current_step="learn",
                **_facts(),
            )
        )


def test_unknown_step_is_rejected() -> None:
    # Only the four canonical workflow steps are valid.
    chat = TopicChat(provider_factory=lambda: _RecordingProvider("ignored"))
    with pytest.raises(CoachError) as excinfo:
        list(
            chat.stream(
                ledger=_empty_ledger(),
                week_spec=_week_spec(),
                learning_session=None,
                message="hi",
                history=[],
                current_step="wat",
                **_facts(),
            )
        )
    assert "Unknown workflow step" in str(excinfo.value)


def test_blank_step_falls_back_to_default_step() -> None:
    # When the caller doesn't specify a step, we use the orchestrator-supplied
    # default and surface it in the context label.
    provider = _RecordingProvider("ok")
    chat = TopicChat(provider_factory=lambda: provider)
    events = list(
        chat.stream(
            ledger=_empty_ledger(),
            week_spec=_week_spec(),
            learning_session=None,
            message="hi",
            history=[],
            current_step="",
            blockers=[],
            question_progress={"required_passed": 1, "required_total": 3},
            default_step_fallback="build",
        )
    )
    start = next(e for e in events if e["type"] == "start")
    assert start["context_label"].endswith("Build")
    assert "Step: build" in provider.last_context


def test_streaming_emits_start_delta_done_with_assembled_reply() -> None:
    # Stream should emit a start event, one delta per non-empty chunk, then a
    # done event whose reply concatenates the chunks.
    provider = _StreamingProvider(["Hello ", "", "world."])
    chat = TopicChat(provider_factory=lambda: provider)
    events = list(
        chat.stream(
            ledger=_empty_ledger(),
            week_spec=_week_spec(),
            learning_session=None,
            message="hi",
            history=[],
            current_step="learn",
            **_facts(),
        )
    )
    types = [e["type"] for e in events]
    assert types == ["start", "delta", "delta", "done"]
    assert events[1]["delta"] == "Hello "
    assert events[2]["delta"] == "world."
    assert events[-1]["reply"] == "Hello world."


def test_answer_drains_stream_and_returns_final_reply() -> None:
    # answer() is the non-streaming convenience: it must consume the stream
    # internally and surface only the done event's contents.
    provider = _StreamingProvider(["one ", "two"])
    chat = TopicChat(provider_factory=lambda: provider)
    result = chat.answer(
        ledger=_empty_ledger(),
        week_spec=_week_spec(),
        learning_session=None,
        message="hi",
        history=[],
        current_step="learn",
        **_facts(),
    )
    assert result == {"reply": "one two", "week": 1, "context_label": "Week 1 · Learn"}


def test_json_wrapped_reply_is_unwrapped() -> None:
    # Some providers wrap chat replies in JSON; the chat surface should expose
    # the inner message text rather than the raw JSON.
    provider = _RecordingProvider('{"response": "the real answer"}')
    chat = TopicChat(provider_factory=lambda: provider)
    result = chat.answer(
        ledger=_empty_ledger(),
        week_spec=_week_spec(),
        learning_session=None,
        message="hi",
        history=[],
        current_step="learn",
        **_facts(),
    )
    assert result["reply"] == "the real answer"


def test_fenced_json_reply_is_unwrapped() -> None:
    # Replies wrapped in a ```json``` fence are also unwrapped before display.
    provider = _RecordingProvider('```json\n{"reply": "fenced answer"}\n```')
    chat = TopicChat(provider_factory=lambda: provider)
    result = chat.answer(
        ledger=_empty_ledger(),
        week_spec=_week_spec(),
        learning_session=None,
        message="hi",
        history=[],
        current_step="learn",
        **_facts(),
    )
    assert result["reply"] == "fenced answer"


def test_empty_provider_reply_raises() -> None:
    # An empty reply from the provider is a defect we must surface, not hide.
    provider = _RecordingProvider("")
    chat = TopicChat(provider_factory=lambda: provider)
    with pytest.raises(CoachError):
        chat.answer(
            ledger=_empty_ledger(),
            week_spec=_week_spec(),
            learning_session=None,
            message="hi",
            history=[],
            current_step="learn",
            **_facts(),
        )


def test_selection_context_under_limit_is_passed_through_verbatim() -> None:
    # Short selection text is embedded between SELECTED_TEXT markers untouched.
    provider = _RecordingProvider("ok")
    chat = TopicChat(provider_factory=lambda: provider)
    list(
        chat.stream(
            ledger=_empty_ledger(),
            week_spec=_week_spec(),
            learning_session=None,
            message="hi",
            history=[],
            current_step="learn",
            selection_context="a tiny selection",
            **_facts(),
        )
    )
    assert "<<<SELECTED_TEXT" in provider.last_context
    assert "a tiny selection" in provider.last_context
    assert "truncated" not in provider.last_context


def test_selection_context_over_limit_is_truncated_with_marker() -> None:
    # Selection text longer than MAX_SELECTION_CHARS is clipped and the chat
    # context calls out that truncation happened so the model knows.
    provider = _RecordingProvider("ok")
    chat = TopicChat(provider_factory=lambda: provider)
    huge = "x" * (MAX_SELECTION_CHARS + 500)
    list(
        chat.stream(
            ledger=_empty_ledger(),
            week_spec=_week_spec(),
            learning_session=None,
            message="hi",
            history=[],
            current_step="learn",
            selection_context=huge,
            **_facts(),
        )
    )
    assert "truncated to fit the topic chat context window" in provider.last_context


def test_context_includes_concept_cards_and_reading_when_session_present() -> None:
    # When a learning session exists, its concept-card titles and reading-material
    # title are surfaced so the chat can ground on them.
    session = LearningSession(
        week=1,
        questions=[],
        attempts=[],
        reading_material=ReadingMaterialPayload(
            week=1,
            title="Reading One",
            body_markdown="## How This Week Works\n\nbody",
        ),
        concept_cards=[
            ConceptCard(
                id="c-1",
                concept="concept_one",
                title="Concept One",
                explanation="x",
                why_it_matters="y",
                common_mistake="z",
                quick_check_question=None,
            )
        ],
    )
    provider = _RecordingProvider("ok")
    chat = TopicChat(provider_factory=lambda: provider)
    list(
        chat.stream(
            ledger=_empty_ledger(),
            week_spec=_week_spec(),
            learning_session=session,
            message="hi",
            history=[],
            current_step="learn",
            **_facts(),
        )
    )
    assert "Concept One" in provider.last_context
    assert "Reading title: Reading One" in provider.last_context

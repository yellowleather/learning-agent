import io
import json
import urllib.error

from engine.errors import EngineError
from engine.models import ProgressState
from topic_chat.models import TopicChatTurn
from learn.models import ReadingMaterialPayload
from engine.providers.anthropic_provider import AnthropicProvider


def _week_spec() -> dict:
    return {
        "number": 1,
        "title": "Week 1: Build a Baseline Inference Server",
        "short_title": "Build a Baseline Inference Server",
        "goal": "Run a model locally and expose it as an API.",
        "narrative": "This week establishes the baseline serving path and first measurements.",
        "topics_covered": ["prefill vs decode", "request flow"],
        "by_the_end_of_this_week_you_will_be_able_to": [
            "Explain how the baseline server works",
            "Measure the first performance numbers",
        ],
        "assessment_targets": [
            "Explain prefill vs decode.",
            "Describe how to benchmark the server.",
        ],
        "tasks": ["`simple_server/server.py` - API server entrypoint."],
        "deliverable_paths": ["simple_server/server.py", "docs/baseline_results.md"],
        "active_dirs": ["simple_server"],
        "required_files": ["simple_server/server.py"],
        "required_metrics": ["latency_p95"],
        "key_resources": ["Example resource"],
    }


def test_generate_question_bank_uses_anthropic_messages_api(monkeypatch):
    provider = AnthropicProvider(model="claude-test")
    captured = {}

    def fake_messages_create(**kwargs):
        captured.update(kwargs)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "week": 1,
                            "questions": [
                                {
                                    "id": "q1",
                                    "depth": "baseline",
                                    "prompt_text": "Explain prefill vs decode.",
                                    "scoring_rubric": ["Mention prompt processing.", "Mention iterative decoding."],
                                }
                            ],
                        }
                    ),
                }
            ]
        }

    monkeypatch.setattr(provider, "_messages_create", fake_messages_create)

    payload = provider.generate_question_bank(
        week_spec=_week_spec(),
        prior_knowledge_summary="The learner has no prior knowledge of LLMs, transformers, or inference systems.",
        ledger_state=ProgressState(current_week=1),
    )

    assert payload.week == 1
    assert payload.questions[0].id == "q1"
    assert captured["system_prompt"]
    assert "## Prior knowledge" in captured["user_prompt"]
    assert "Week 1: Build a Baseline Inference Server" in captured["user_prompt"]
    assert captured["temperature"] == 0.2


def test_answer_topic_chat_uses_anthropic_messages_api(monkeypatch):
    provider = AnthropicProvider(model="claude-test")
    captured = {}

    def fake_messages_create(**kwargs):
        captured.update(kwargs)
        return {"content": [{"type": "text", "text": "Use benchmark.py and explain decode time."}]}

    monkeypatch.setattr(provider, "_messages_create", fake_messages_create)

    reply = provider.answer_topic_chat(
        week_spec=_week_spec(),
        context="Step: learn\nWeek goal: Run a model locally and expose it as an API.",
        history=[TopicChatTurn(role="user", content="What should I focus on first?")],
        message="How should I measure tokens per second?",
    )

    assert reply == "Use benchmark.py and explain decode time."
    assert captured["temperature"] == 0.3
    assert "Current app context:" in captured["user_prompt"]
    assert "How should I measure tokens per second?" in captured["user_prompt"]


def test_run_agent_turn_parses_anthropic_tool_calls(monkeypatch):
    provider = AnthropicProvider(model="claude-test")
    captured = {}

    def fake_messages_create(**kwargs):
        captured.update(kwargs)
        return {
            "stop_reason": "tool_use",
            "content": [
                {"type": "text", "text": "I will inspect the file."},
                {"type": "tool_use", "id": "toolu-1", "name": "read_file", "input": {"path": "src/app.py"}},
            ],
        }

    monkeypatch.setattr(provider, "_messages_create", fake_messages_create)

    result = provider.run_agent_turn(
        system_prompt="system",
        messages=[{"role": "user", "content": "begin"}],
        tools=[{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}],
    )

    assert captured["system_prompt"] == "system"
    assert captured["tools"][0]["input_schema"] == {"type": "object"}
    assert captured["thinking"]["type"] == "enabled"
    assert result.stop_reason == "tool_use"
    assert result.tool_calls[0].id == "toolu-1"
    assert result.tool_calls[0].arguments == {"path": "src/app.py"}


def test_run_agent_turn_translates_history_to_anthropic_format(monkeypatch):
    provider = AnthropicProvider(model="claude-test")
    captured = {}

    def fake_messages_create(**kwargs):
        captured.update(kwargs)
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Done."}]}

    monkeypatch.setattr(provider, "_messages_create", fake_messages_create)

    provider.run_agent_turn(
        system_prompt="system",
        messages=[
            {"role": "user", "content": "begin"},
            {
                "role": "assistant",
                "content": "Reading the file.",
                "tool_calls": [{"id": "tc-1", "name": "read_file", "arguments": {"path": "src/app.py"}}],
            },
            {"role": "tool", "tool_call_id": "tc-1", "name": "read_file", "content": '{"content": "code"}'},
            {"role": "tool", "tool_call_id": "tc-2", "name": "write_file", "content": '{"ok": true}'},
        ],
        tools=[],
        deep_reasoning=False,
    )

    sent = captured["messages"]
    assert sent[0] == {"role": "user", "content": "begin"}
    assert sent[1]["role"] == "assistant"
    assert sent[1]["content"][0] == {"type": "text", "text": "Reading the file."}
    assert sent[1]["content"][1] == {
        "type": "tool_use",
        "id": "tc-1",
        "name": "read_file",
        "input": {"path": "src/app.py"},
    }
    assert sent[2]["role"] == "user"
    assert sent[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "tc-1", "content": '{"content": "code"}'},
        {"type": "tool_result", "tool_use_id": "tc-2", "content": '{"ok": true}'},
    ]


def test_messages_create_surfaces_auth_failure(monkeypatch):
    provider = AnthropicProvider(model="claude-test")

    def fake_urlopen(_request, timeout):
        del timeout
        raise urllib.error.HTTPError(
            url="https://api.anthropic.com/v1/messages",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"invalid api key"}'),
        )

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    try:
        provider._messages_create(
            system_prompt="system",
            user_prompt="user",
            temperature=0.2,
            max_tokens=100,
        )
    except EngineError as exc:
        assert str(exc) == "Anthropic authentication failed. Check ANTHROPIC_API_KEY."
    else:  # pragma: no cover
        raise AssertionError("Expected Anthropic auth failure to raise EngineError.")


def test_generate_concept_cards_from_reading_uses_week_plan(monkeypatch):
    provider = AnthropicProvider(model="claude-test")
    captured = {}

    def fake_messages_create(**kwargs):
        captured.update(kwargs)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "week": 1,
                            "concept_cards": [
                                {
                                    "id": "prefill-vs-decode",
                                    "concept": "prefill_vs_decode",
                                    "title": "Prefill vs Decode",
                                    "explanation": "Prefill processes the prompt and decode emits output token by token.",
                                    "why_it_matters": "It explains why prompt length and output length stress the system differently.",
                                    "common_mistake": "Treating inference as one undifferentiated block.",
                                    "quick_check_question": "What changes once prefill ends and decode begins?",
                                }
                            ],
                        }
                    ),
                }
            ]
        }

    monkeypatch.setattr(provider, "_messages_create", fake_messages_create)

    payload = provider.generate_concept_cards_from_reading(
        week_spec=_week_spec(),
        ledger_state=ProgressState(current_week=1),
        reading_material=ReadingMaterialPayload(
            week=1,
            title="Week 1 Reading",
            body_markdown="## How This Week Works\n\nRead the system from outside in.",
        ),
    )

    assert payload.week == 1
    assert payload.concept_cards[0].id == "prefill-vs-decode"
    assert "### Current week plan" in captured["user_prompt"]

from types import SimpleNamespace

from learning_agent.models import ClassifiedQuestionBankPayload, RawQuestionBankPayload, TopicChatTurn, WeekSpec
from learning_agent.providers.openai_provider import OpenAIProvider


def test_normalize_raw_payload_maps_common_tier_variants():
    provider = OpenAIProvider(model="test-model")
    payload = {
        "week": 1,
        "questions": [
            {
                "prompt_text": "Explain the result.",
                "tier": "Tier 2",
                "topic_area": "benchmarking",
            }
        ],
    }

    normalized = provider._normalize_payload(payload, RawQuestionBankPayload)

    assert normalized["questions"][0]["tier"] == "implementation_knowledge"


def test_normalize_classified_payload_maps_common_question_variants():
    provider = OpenAIProvider(model="test-model")
    payload = {
        "week": 1,
        "questions": [
            {
                "id": "q1",
                "type": "implementation_oriented",
                "scope": "required",
                "depth": "intermediate",
                "prompt_text": "Show evidence.",
                "scoring_rubric": ["Provide evidence."],
                "roadmap_anchor": {"week": 1},
                "observation_required": False,
            }
        ],
    }

    normalized = provider._normalize_payload(payload, ClassifiedQuestionBankPayload)

    assert normalized["questions"][0]["type"] == "implementation"
    assert normalized["questions"][0]["scope"] == "core"
    assert normalized["questions"][0]["depth"] == "deep"


def test_validate_raw_question_bank_rejects_small_bank():
    provider = OpenAIProvider(model="test-model")
    payload = RawQuestionBankPayload.model_validate(
        {
            "week": 1,
            "questions": [
                {
                    "prompt_text": "Show evidence.",
                    "tier": "foundational_concepts",
                    "topic_area": "prefill_vs_decode",
                }
            ],
        }
    )

    errors = provider._validate_raw_question_bank(payload)

    assert any("at least 60 raw questions" in error for error in errors)


def test_answer_topic_chat_uses_week_context_and_history(monkeypatch):
    provider = OpenAIProvider(model="test-model")
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="Use benchmark.py and explain decode time."))]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(provider, "_client", lambda: fake_client)

    reply = provider.answer_topic_chat(
        week_spec=WeekSpec(
            number=1,
            title="Build a Baseline Inference Server",
            goal="Run a model locally and expose it as an API.",
            active_dirs=["simple_server"],
            required_files=["simple_server/server.py"],
            required_metrics=["latency_p95"],
        ),
        context="Step: learn\nWeek goal: Run a model locally and expose it as an API.",
        history=[TopicChatTurn(role="user", content="What should I focus on first?")],
        message="How should I measure tokens per second?",
    )

    assert reply == "Use benchmark.py and explain decode time."
    assert captured["model"] == "test-model"
    prompt = captured["messages"][1]["content"]
    assert "Current app context:" in prompt
    assert "Week goal: Run a model locally and expose it as an API." in prompt
    assert "What should I focus on first?" in prompt
    assert "How should I measure tokens per second?" in prompt

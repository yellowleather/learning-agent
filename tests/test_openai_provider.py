from types import SimpleNamespace

import httpx
import openai

from learning_agent.errors import LearningAgentError
from learning_agent.models import (
    ClassifiedQuestionBankPayload,
    ConceptCardPayload,
    LearningQuestion,
    ProgressState,
    RawQuestionBankPayload,
    ReadingMaterialPayload,
    TopicChatTurn,
)
from learning_agent.providers.openai_provider import OpenAIProvider


def _week_spec() -> dict:
    return {
        "number": 1,
        "title": "Week 1: Build a Baseline Inference Server",
        "short_title": "Build a Baseline Inference Server",
        "goal": "Run a model locally and expose it as an API.",
        "active_dirs": ["simple_server"],
        "required_files": ["simple_server/server.py"],
        "required_metrics": ["latency_p95"],
    }


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
        week_spec=_week_spec(),
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


def test_generate_reading_material_uses_blog_style_contract(monkeypatch):
    provider = OpenAIProvider(model="test-model")
    captured = {}

    def fake_completion(system_prompt, user_prompt, response_model):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        captured["response_model"] = response_model
        return ReadingMaterialPayload(
            week=1,
            reading_sections=[
                {
                    "id": "week_map",
                    "title": "How This Week Works",
                    "body_markdown": "Read the system from outside in.",
                }
            ],
        )

    monkeypatch.setattr(provider, "_completion_as_model", fake_completion)

    payload = provider.generate_reading_material(
        week_spec=_week_spec(),
        ledger_state=ProgressState(current_week=1, learning_assist_enabled=True),
        questions=[
            LearningQuestion(
                id="q1",
                type="concept",
                scope="core",
                depth="baseline",
                prompt_text="Explain prefill vs decode.",
                scoring_rubric=["Mention prompt processing."],
                roadmap_anchor={"week": 1},
                observation_required=False,
            )
        ],
    )

    assert payload.week == 1
    prompt = captured["user_prompt"]
    assert "technical blog post or explainer" in prompt
    assert "Do not mention the words chapter, section, concept card" in prompt
    assert '"id": "week_map"' in prompt
    assert "The remaining reading blocks should be generated dynamically from the classified question bank." in prompt
    assert "Do not assume Week 1 topics such as prefill/decode unless they are clearly supported by the provided questions." in prompt
    assert captured["response_model"] is ReadingMaterialPayload


def test_generate_concept_cards_from_reading_uses_reading_material_contract(monkeypatch):
    provider = OpenAIProvider(model="test-model")
    captured = {}

    def fake_completion(system_prompt, user_prompt, response_model):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        captured["response_model"] = response_model
        return ConceptCardPayload(
            week=1,
            concept_cards=[
                {
                    "id": "prefill-vs-decode",
                    "concept": "prefill_vs_decode",
                    "title": "Prefill vs Decode",
                    "explanation": "Prefill processes the prompt and decode emits output token by token.",
                    "why_it_matters": "It explains why prompt length and output length stress the system differently.",
                    "common_mistake": "Treating inference as one undifferentiated block.",
                    "quick_check_question": "What changes once prefill ends and decode begins?",
                    "related_section_ids": ["generation_mechanics"],
                }
            ],
        )

    monkeypatch.setattr(provider, "_completion_as_model", fake_completion)

    payload = provider.generate_concept_cards_from_reading(
        week_spec=_week_spec(),
        ledger_state=ProgressState(current_week=1, learning_assist_enabled=True),
        reading_sections=[
            {
                "id": "generation_mechanics",
                "title": "Prefill, Decode, And Why The Split Matters",
                "body_markdown": "Prefill processes the prompt. Decode emits output token by token.",
            }
        ],
    )

    assert payload.week == 1
    prompt = captured["user_prompt"]
    assert "Generate learner-facing concept cards derived from the provided current-week reading material." in prompt
    assert "Do not generate cards directly from a question bank." in prompt
    assert '"id": "prefill-vs-decode"' in prompt
    assert captured["response_model"] is ConceptCardPayload


def test_stream_topic_chat_uses_streaming_and_yields_deltas(monkeypatch):
    provider = OpenAIProvider(model="test-model")
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return iter(
                [
                    SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Use "))]),
                    SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))]),
                    SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="benchmark.py"))]),
                ]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(provider, "_client", lambda: fake_client)

    chunks = list(
        provider.stream_topic_chat(
            week_spec=_week_spec(),
            context="Step: learn\nWeek goal: Run a model locally and expose it as an API.",
            history=[TopicChatTurn(role="user", content="What should I focus on first?")],
            message="How should I measure tokens per second?",
        )
    )

    assert chunks == ["Use ", "benchmark.py"]
    assert captured["model"] == "test-model"
    assert captured["stream"] is True
    prompt = captured["messages"][1]["content"]
    assert "Current app context:" in prompt
    assert "Week goal: Run a model locally and expose it as an API." in prompt
    assert "What should I focus on first?" in prompt
    assert "How should I measure tokens per second?" in prompt


def test_stream_topic_chat_surfaces_connection_errors_clearly(monkeypatch):
    provider = OpenAIProvider(model="test-model")

    class FakeCompletions:
        def create(self, **kwargs):
            raise openai.APIConnectionError(
                message="Connection error.",
                request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(provider, "_client", lambda: fake_client)

    try:
        list(
            provider.stream_topic_chat(
                week_spec=_week_spec(),
                context="Step: learn",
                history=[],
                message="hello",
            )
        )
    except LearningAgentError as exc:
        assert str(exc) == "OpenAI connection failed. Check network access and API configuration."
    else:  # pragma: no cover
        raise AssertionError("Expected connection failure to raise LearningAgentError.")

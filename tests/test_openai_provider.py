from types import SimpleNamespace

import httpx
import openai

from learning_agent.errors import LearningAgentError
from learning_agent.models import (
    ConceptCardPayload,
    LearningQuestion,
    LearningQuestionBankPayload,
    ProgressState,
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


def test_normalize_question_bank_payload_maps_question_variants():
    provider = OpenAIProvider(model="test-model")
    payload = {
        "week": 1,
        "questions": [
            {
                "id": "q1",
                "prompt_text": "Explain the result.",
                "depth": "intermediate",
                "scoring_rubric": ["Explain the tradeoff."],
            }
        ],
    }

    normalized = provider._normalize_payload(payload, LearningQuestionBankPayload)

    assert normalized["questions"][0]["depth"] == "deep"


def test_generate_prior_knowledge_summary_uses_full_plan_and_target_week(monkeypatch):
    provider = OpenAIProvider(model="test-model")
    captured = {}

    def fake_completion(system_prompt, user_prompt):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return "The learner can explain basic request flow."

    monkeypatch.setattr(provider, "_completion_as_text", fake_completion)

    summary = provider.generate_prior_knowledge_summary(
        full_plan="# Plan\n\n## Week 1: Intro\n",
        target_week_number=2,
    )

    assert summary == "The learner can explain basic request flow."
    prompt = captured["user_prompt"]
    assert "Given a multi-week learning plan" in prompt
    assert "## Full learning plan" in prompt
    assert "# Plan" in prompt
    assert "## Target week" in prompt
    assert "2" in prompt


def test_generate_question_bank_uses_prior_knowledge_and_week_plan(monkeypatch):
    provider = OpenAIProvider(model="test-model")
    captured = {}

    def fake_completion(system_prompt, user_prompt, response_model):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        captured["response_model"] = response_model
        return LearningQuestionBankPayload(
            week=1,
            questions=[
                LearningQuestion(
                    id="q1",
                    depth="baseline",
                    prompt_text="Explain prefill vs decode.",
                    scoring_rubric=["Mention prompt processing.", "Mention iterative decoding."],
                )
            ],
        )

    monkeypatch.setattr(provider, "_completion_as_model", fake_completion)

    payload = provider.generate_question_bank(
        week_spec=_week_spec(),
        prior_knowledge_summary="The learner has no prior knowledge of LLMs, transformers, or inference systems.",
        ledger_state=ProgressState(current_week=1),
    )

    assert payload.week == 1
    prompt = captured["user_prompt"]
    assert "## Prior knowledge" in prompt
    assert "The learner has no prior knowledge of LLMs" in prompt
    assert "## Current week plan" in prompt
    assert "Week 1: Build a Baseline Inference Server" in prompt
    assert "Required Metrics:" in prompt
    assert '"current_week": 1' in prompt
    assert captured["response_model"] is LearningQuestionBankPayload


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
            title="Week 1 Reading",
            body_markdown="## How This Week Works\n\nRead the system from outside in.\n\n## System Shape\n\nStart at the API boundary.",
        )

    monkeypatch.setattr(provider, "_completion_as_model", fake_completion)

    payload = provider.generate_reading_material(
        week_spec=_week_spec(),
        prior_knowledge_summary="The learner has no prior knowledge of LLMs, transformers, or inference systems.",
        ledger_state=ProgressState(current_week=1),
        questions=[
            LearningQuestion(
                id="q1",
                depth="baseline",
                prompt_text="Explain prefill vs decode.",
                scoring_rubric=["Mention prompt processing."],
            )
        ],
    )

    assert payload.week == 1
    prompt = captured["user_prompt"]
    assert "graduate-level textbook" in prompt
    assert "Do not mention the words concept card, question bank" in prompt
    assert "## How This Week Works" in prompt
    assert "### Prior knowledge summary" in prompt
    assert "The learner has no prior knowledge of LLMs" in prompt
    assert "### Current week plan" in prompt
    assert "Week 1: Build a Baseline Inference Server" in prompt
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
                }
            ],
        )

    monkeypatch.setattr(provider, "_completion_as_model", fake_completion)

    payload = provider.generate_concept_cards_from_reading(
        week_spec=_week_spec(),
        ledger_state=ProgressState(current_week=1),
        reading_material=ReadingMaterialPayload(
            week=1,
            title="Week 1 Reading",
            body_markdown=(
                "## How This Week Works\n\n"
                "Read the system from outside in.\n\n"
                "## Prefill, Decode, And Why The Split Matters\n\n"
                "Prefill processes the prompt. Decode emits output token by token."
            ),
        ),
    )

    assert payload.week == 1
    prompt = captured["user_prompt"]
    assert "Generate learner-facing concept cards derived from the" in prompt
    assert "provided current-week reading material. Output JSON only." in prompt
    assert "generate cards directly from the question bank" in prompt
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

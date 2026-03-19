import json

from learning_agent.errors import LearningAgentError
from learning_agent.ui import render_page, run_action, run_topic_chat


class FakeProvider:
    def generate_raw_question_bank(self, week_spec, ledger_state):
        questions = [
            {
                "prompt_text": "Explain prefill vs decode.",
                "tier": "foundational_concepts",
                "topic_area": "prefill_vs_decode",
            }
        ]
        questions.extend(
            {
                "prompt_text": f"Concept deep question {index}",
                "tier": "foundational_concepts",
                "topic_area": "latency_metrics",
            }
            for index in range(2, 19)
        )
        questions.append(
            {
                "prompt_text": "How would you measure tokens per second?",
                "tier": "implementation_knowledge",
                "topic_area": "benchmarking",
            }
        )
        questions.extend(
            {
                "prompt_text": f"Implementation deep question {index}",
                "tier": "implementation_knowledge",
                "topic_area": "api_serving",
            }
            for index in range(2, 21)
        )
        questions.extend(
            {
                "prompt_text": f"Optimization question {index}",
                "tier": "optimization_and_production_insights",
                "topic_area": "throughput_tradeoffs",
            }
            for index in range(1, 13)
        )
        return {
            "week": week_spec.number,
            "questions": questions,
        }

    def generate_concept_cards(self, week_spec, ledger_state, questions):
        return {
            "week": week_spec.number,
            "concept_cards": [
                {
                    "concept": "prefill_vs_decode",
                    "explanation": "Prefill handles the prompt while decode emits tokens.",
                    "why_it_matters": "Benchmark interpretation depends on this split.",
                    "common_mistake": "Treating all latency as one number.",
                    "quick_check_question": "Which phase grows first with prompt length?",
                }
            ],
        }

    def classify_question_bank(self, week_spec, ledger_state, questions):
        classified_questions = [
            {
                "id": "core_prefill",
                "type": "concept",
                "scope": "core",
                "depth": "baseline",
                "prompt_text": "Explain prefill vs decode.",
                "scoring_rubric": ["Mention prompt processing.", "Mention iterative decoding."],
                "roadmap_anchor": {"week": week_spec.number},
                "observation_required": False,
            }
        ]
        classified_questions.extend(
            {
                "id": f"core_concept_deep_{index}",
                "type": "concept",
                "scope": "core",
                "depth": "deep",
                "prompt_text": f"Concept deep question {index}",
                "scoring_rubric": ["Explain the concept clearly."],
                "roadmap_anchor": {"week": week_spec.number},
                "observation_required": False,
            }
            for index in range(2, 19)
        )
        classified_questions.append(
            {
                "id": "impl_measure_tokens",
                "type": "implementation",
                "scope": "core",
                "depth": "baseline",
                "prompt_text": "How would you measure tokens per second?",
                "scoring_rubric": ["Count generated tokens.", "Divide by decode time."],
                "roadmap_anchor": {"week": week_spec.number},
                "observation_required": False,
            }
        )
        classified_questions.extend(
            {
                "id": f"impl_deep_{index}",
                "type": "implementation",
                "scope": "core",
                "depth": "deep",
                "prompt_text": f"Implementation deep question {index}",
                "scoring_rubric": ["Describe the implementation tradeoff."],
                "roadmap_anchor": {"week": week_spec.number},
                "observation_required": False,
            }
            for index in range(2, 21)
        )
        classified_questions.extend(
            {
                "id": f"adjacent_opt_{index}",
                "type": "concept",
                "scope": "adjacent",
                "depth": "deep",
                "prompt_text": f"Optimization question {index}",
                "scoring_rubric": ["Discuss the tradeoff."],
                "roadmap_anchor": {"week": week_spec.number},
                "observation_required": False,
            }
            for index in range(1, 13)
        )
        return {"week": week_spec.number, "questions": classified_questions}

    def generate_gate_question(self, week_spec):
        raise AssertionError("Legacy gate is not exercised in this UI test.")

    def score_gate_answer(self, week_spec, question, answer):
        raise AssertionError("Legacy gate is not exercised in this UI test.")

    def generate_task(self, week_spec, ledger_state):
        raise AssertionError("Task generation is not exercised in this UI test.")

    def score_learning_question(self, week_spec, question, answer, observation):
        return {"passed": True, "score_rationale": "Good answer.", "missing_concepts": []}

    def generate_evidence_questions(self, week_spec, observation, learning_session):
        return {"week": week_spec.number, "questions": []}

    def answer_topic_chat(self, week_spec, context, history, message):
        return f"Tutor reply about: {message}"


class CountingProvider(FakeProvider):
    def __init__(self):
        self.learning_generate_calls = 0

    def generate_raw_question_bank(self, week_spec, ledger_state):
        self.learning_generate_calls += 1
        return super().generate_raw_question_bank(week_spec, ledger_state)


def write_config(tmp_path):
    config = {
        "provider": "openai",
        "model": "test-model",
        "roadmap_path": "docs/plan.md",
        "target_repo_path": "ai_inference_engineering",
        "state_dir": "state",
    }
    (tmp_path / "learning_agent.config.json").write_text(json.dumps(config))


def write_roadmap(tmp_path):
    roadmap = tmp_path / "docs" / "plan.md"
    roadmap.parent.mkdir(parents=True, exist_ok=True)
    roadmap.write_text(
        """# 8-Week Inference Engineering Roadmap

# Week 1 --- Build a Baseline Inference Server

## Goal

Run a model locally and expose it as an API.

## Learn

Concepts:

- prefill vs decode

## Tasks

- Load a small LLM
- measure tokens/sec

## Deliverables

    simple_server/
        server.py

Document:

    docs/baseline_results.md
"""
    )


def test_render_page_shows_uninitialized_state(monkeypatch, tmp_path):
    write_config(tmp_path)
    write_roadmap(tmp_path)
    monkeypatch.chdir(tmp_path)

    page = render_page()

    assert "Initialize Week 1" in page
    assert "No ledger loaded yet" in page
    assert 'href="/favicon.ico"' in page
    assert 'src="/assets/icon.png"' in page
    assert "How It Works" in page
    assert "Quick Start" in page
    assert "What You Will See" in page
    assert "sidebar-edge-toggle" in page
    assert "right-rail-toggle" in page
    assert "left-sidebar" in page
    assert "right-sidebar" in page
    assert "data-rail-backdrop" in page
    assert "data-course-bar" in page
    assert "Initialize Week 1 to start the course" in page
    assert "Week Chat" in page
    assert "Chats for this week" in page
    assert "New Chat" in page
    assert "Delete Chat" in page
    assert "What is this week about?" in page
    assert "senior software engineer" in page
    assert "Learn:" in page
    assert "Approve:" in page
    assert "learning-agent-left-rail-collapsed" in page
    assert "learning-agent-right-rail-collapsed" in page
    assert "/api/topic-chat" in page
    assert "data-topic-chat-root" in page
    assert "data-topic-chat-session-list" in page
    assert "data-topic-chat-suggestion" in page


def test_run_action_init_creates_week_one(monkeypatch, tmp_path):
    write_config(tmp_path)
    write_roadmap(tmp_path)
    (tmp_path / "ai_inference_engineering" / "simple_server").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ai_inference_engineering" / "docs").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)

    message = run_action("init", {"action": ["init"]})

    assert message == "Initialized Week 1."
    page = render_page()
    assert "Week 1" in page
    assert "simple_server/server.py" in page
    assert "Week 1 - Build a Baseline Inference Server" in page


def test_render_page_shows_learning_assist(monkeypatch, tmp_path):
    write_config(tmp_path)
    write_roadmap(tmp_path)
    (tmp_path / "ai_inference_engineering" / "simple_server").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ai_inference_engineering" / "docs").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("learning_agent.controller.get_provider", lambda _config: FakeProvider())

    assert run_action("init", {"action": ["init"]}) == "Initialized Week 1."

    page = render_page()
    assert "Learn" in page
    assert "Build" in page
    assert "Verify" in page
    assert "Approve" in page
    assert "Concept Cards" in page
    assert "Reading Material" in page
    assert "Answer Question" in page
    assert "open-book exam" in page
    assert "/assets/illustrations/prefill-decode.svg" in page
    assert "core_prefill" in page
    assert "Record Observation" in page
    assert "Record Reflection" in page
    assert "Generate Learning Assist" not in page
    assert "Open Learn" in page
    assert "Concept Card Visibility" not in page
    assert "Hide Concept Cards" not in page
    assert "Learn by Building Real Systems" in page
    assert "Move through one unlocked week at a time." in page
    assert "One week at a time" in page
    assert "Real project artifacts" in page
    assert "Your Next Step" in page
    assert "This Week's Outcome" in page
    assert "Mentor Control Surface" not in page
    assert "Week 1 - Build a Baseline Inference Server" in page
    assert "Current step: Learn" in page
    assert "Local only" in page
    assert "Port 4010" in page
    assert "right-sidebar" in page
    assert "Week Chat" in page
    assert "Week 1" in page
    assert "Build a Baseline Inference Server" in page
    assert "Chats for this week" in page
    assert "New Chat" in page
    assert "Delete Chat" in page
    assert "What is this week about?" in page
    assert "What is an LLM?" in page
    assert "/api/topic-chat" in page
    assert "learning-agent-topic-chat-" in page
    assert 'return storageKey(root, "sessions");' in page
    assert 'return storageKey(root, "draft");' in page
    assert "learning-agent-left-rail-collapsed" in page
    assert "learning-agent-right-rail-collapsed" in page
    assert "left-rail-open" in page
    assert "right-rail-open" in page
    assert "Active Question" not in page
    assert 'content: "▶"' in page
    assert "data-reading-scroll" in page
    assert "window.scrollBy({ top: event.deltaY, left: 0, behavior: \"auto\" })" in page
    assert page.index("Concept Cards") < page.index("Answer Question")
    assert "Question 1 of 50" in page
    assert "title='Previous Question'" in page
    assert "title='Next Question'" in page
    assert "question-nav-arrow" in page
    assert "See Full Question List" in page
    assert 'id="question-list-modal"' in page
    assert "Full Question List" in page
    assert "Correct So Far" in page
    assert "0/2 baseline questions passed" in page
    assert 'role="progressbar"' in page
    assert "/?question_id=core_prefill#question-workspace" not in page
    assert "/?question_id=core_prefill" in page
    assert "question-list-panel" not in page
    assert "data-question-step-link" in page
    assert "data-question-modal-link" in page
    assert "data-question-status-badge" in page
    assert "data-base-status='not_started'" in page
    assert 'draft: "Draft"' in page
    assert "data-question-modal-open" in page
    assert "data-question-modal-close" in page
    assert "data-learning-answer-form" in page
    assert "data-learning-answer-textarea" in page
    assert "data-draft-status" in page
    assert "learning-agent-draft-week-" in page
    assert "<summary>What A Good Answer Should Cover</summary>" in page
    assert "rubric-inline" in page


def test_run_topic_chat_returns_json(monkeypatch, tmp_path):
    write_config(tmp_path)
    write_roadmap(tmp_path)
    (tmp_path / "ai_inference_engineering" / "simple_server").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ai_inference_engineering" / "docs").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("learning_agent.controller.get_provider", lambda _config: FakeProvider())

    assert run_action("init", {"action": ["init"]}) == "Initialized Week 1."
    assert run_action("learning_generate", {"action": ["learning_generate"]}) == "Generated Learning Assist for Week 1."

    payload = run_topic_chat(
        {
            "message": "How should I measure tokens per second?",
            "history": [{"role": "user", "content": "What should I focus on?"}],
            "current_step": "learn",
            "selected_question_id": "core_prefill",
        }
    )

    assert payload["week"] == 1
    assert payload["context_label"] == "Week 1 · Learn"
    assert payload["reply"] == "Tutor reply about: How should I measure tokens per second?"


def test_run_topic_chat_returns_validation_error(monkeypatch, tmp_path):
    write_config(tmp_path)
    write_roadmap(tmp_path)
    (tmp_path / "ai_inference_engineering" / "simple_server").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ai_inference_engineering" / "docs").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("learning_agent.controller.get_provider", lambda _config: FakeProvider())

    assert run_action("init", {"action": ["init"]}) == "Initialized Week 1."

    try:
        run_topic_chat(
            {
                "message": "",
                "history": [],
                "current_step": "learn",
                "selected_question_id": "core_prefill",
            }
        )
    except LearningAgentError as exc:
        assert str(exc) == "Topic chat message cannot be empty."
    else:  # pragma: no cover
        raise AssertionError("Expected topic chat request to fail.")


def test_render_page_autoloads_learning_assist_only_once(monkeypatch, tmp_path):
    write_config(tmp_path)
    write_roadmap(tmp_path)
    (tmp_path / "ai_inference_engineering" / "simple_server").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ai_inference_engineering" / "docs").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    provider = CountingProvider()
    monkeypatch.setattr("learning_agent.controller.get_provider", lambda _config: provider)

    assert run_action("init", {"action": ["init"]}) == "Initialized Week 1."

    first_page = render_page()
    second_page = render_page()

    assert "Concept Cards" in first_page
    assert "Answer Question" in second_page
    assert provider.learning_generate_calls == 1

import json

from learning_agent.errors import LearningAgentError
from learning_agent.ui import render_page, run_action, run_topic_chat, run_topic_chat_stream


def _extra_weeks(start: int = 2) -> str:
    blocks = []
    for week_number in range(start, 9):
        blocks.append(
            f"""## Week {week_number}: Extra Week {week_number}

### Goal

Goal for week {week_number}.

### Narrative

Narrative for week {week_number}.

### Topics Covered

- concept {week_number}

### By the End of This Week You Will Be Able To

- Explain concept {week_number}
- Build artifact {week_number}

### Assessment Targets

1. Explain concept {week_number}.
2. Describe artifact {week_number}.

### Implementation

**Files created this week:**

- `docs/week_{week_number}.md` — Artifact for week {week_number}.

**Deliverables:** A written artifact in `docs/week_{week_number}.md`.

**Cloud deployment:** Not required.

### Key Resources

- **Example resource.**
- Production reference in `simple_server/server.py`.
"""
        )
    return "\n\n".join(blocks)


def _reading_material_for(questions):
    question_ids = [question["id"] if isinstance(question, dict) else question.id for question in questions]
    del question_ids
    return {
        "week": 1,
        "title": "Week 1 Reading",
        "body_markdown": (
            "## How This Week Works\n\n"
            "Week 1 introduces the shape of a small inference system before implementation starts. "
            "The learner should understand the serving boundary, the model runtime, the split between prompt handling and token generation, "
            "and the role of measurement in proving that the system behaves the way it is described. "
            "That foundation is what makes the later coding and benchmarking work coherent.\n\n"
            "## From Request To Generated Tokens\n\n"
            "Tracing one request from API entry to generated output gives the clearest mental model for the week. "
            "The server receives and validates input, prepares the prompt, delegates model work to the runtime, and packages the output back into a response. "
            "Every debugging conversation and every system explanation can be grounded in that path.\n\n"
            "## Prefill, Decode, And Why The Split Matters\n\n"
            "Prefill processes the prompt first so the model can build the state it needs for generation. "
            "After that, decode produces output incrementally over time. "
            "Keeping those phases separate helps the learner explain performance behavior, user-visible latency, and why prompt length and output length affect the system differently. "
            "It also makes the benchmark results more interpretable.\n\n"
            "## How Week 1 Maps Onto Code\n\n"
            "The reading should point naturally toward the files that get built next. "
            "A serving file defines the API boundary, a benchmark file defines how behavior is measured, and a results document records what was observed. "
            "That mapping keeps implementation grounded in system responsibilities instead of reducing the work to disconnected tasks.\n\n"
            "## How To Measure And Verify\n\n"
            "Performance reasoning should be disciplined. "
            "A metric only becomes useful when the learner can explain what was timed, what the value means, what the benchmark setup included, and what the number still does not tell you. "
            "Latency and throughput answer different questions, and both need to be connected back to the inference path that produced them."
        ),
    }


def _concept_cards_for(_reading_material):
    return {
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
            },
            {
                "id": "token-generation",
                "concept": "token_generation",
                "title": "Token Generation",
                "explanation": "Token generation is the repeated loop that turns model state into output over time.",
                "why_it_matters": "It helps the learner reason about behavior and performance.",
                "common_mistake": "Talking about generation without distinguishing it from prompt processing.",
                "quick_check_question": "What part of the system repeats for every next token?",
            },
            {
                "id": "request-flow",
                "concept": "request_flow",
                "title": "Request Flow",
                "explanation": "Request flow is the path from API input through runtime work to returned output.",
                "why_it_matters": "It anchors system explanations in the serving path.",
                "common_mistake": "Explaining the model while skipping the server around it.",
                "quick_check_question": "What happens between request arrival and response delivery?",
            },
            {
                "id": "api-serving",
                "concept": "api_serving",
                "title": "API Serving",
                "explanation": "API serving turns the model into a usable system boundary for requests and responses.",
                "why_it_matters": "It ties the reading to the actual service the learner will build.",
                "common_mistake": "Treating serving as a thin wrapper.",
                "quick_check_question": "Why is model quality alone not enough for a usable inference service?",
            },
            {
                "id": "implementation-boundaries",
                "concept": "implementation_boundaries",
                "title": "Implementation Boundaries",
                "explanation": "Implementation boundaries connect the ideas in the reading to the files that express them in code.",
                "why_it_matters": "This keeps implementation grounded in responsibilities.",
                "common_mistake": "Treating files as disconnected tasks.",
                "quick_check_question": "Which file owns which responsibility?",
            },
            {
                "id": "latency-metrics",
                "concept": "latency_metrics",
                "title": "Latency Metrics",
                "explanation": "Latency metrics describe how long the system takes to respond.",
                "why_it_matters": "They make performance reasoning concrete.",
                "common_mistake": "Quoting latency without context.",
                "quick_check_question": "What part of the path could increase latency?",
            },
            {
                "id": "throughput-metrics",
                "concept": "throughput_metrics",
                "title": "Throughput Metrics",
                "explanation": "Throughput metrics describe how much generation work the system sustains over time.",
                "why_it_matters": "They clarify efficiency, not just correctness.",
                "common_mistake": "Treating throughput as interchangeable with latency.",
                "quick_check_question": "What does tokens per second tell you that latency alone does not?",
            },
            {
                "id": "benchmark-evidence",
                "concept": "benchmark_evidence",
                "title": "Benchmark Evidence",
                "explanation": "Benchmark evidence turns performance claims into inspectable results.",
                "why_it_matters": "It connects measurement to trust.",
                "common_mistake": "Reporting numbers without benchmark context.",
                "quick_check_question": "What makes a benchmark trustworthy?",
            },
        ],
    }


class FakeProvider:
    def generate_question_bank(self, week_spec, ledger_state):
        questions = [
            {
                "id": "prefill_decode_baseline",
                "depth": "baseline",
                "prompt_text": "Explain prefill vs decode.",
                "scoring_rubric": ["Mention prompt processing.", "Mention iterative decoding."],
            }
        ]
        questions.append(
            {
                "id": "baseline_metrics_reasoning",
                "depth": "baseline",
                "prompt_text": "How should you reason about tokens per second in relation to decode work?",
                "scoring_rubric": ["Connect the metric to decode throughput.", "Explain what the metric hides."],
            }
        )
        questions.extend(
            {
                "id": f"baseline_concept_{index}",
                "depth": "baseline",
                "prompt_text": f"Baseline concept question {index}",
                "scoring_rubric": ["Explain the concept clearly."],
            }
            for index in range(3, 19)
        )
        questions.extend(
            {
                "id": f"concept_deep_{index}",
                "depth": "deep",
                "prompt_text": f"Concept deep question {index}",
                "scoring_rubric": ["Explain the concept clearly.", "Include the key tradeoff."],
            }
            for index in range(1, 21)
        )
        questions.extend(
            {
                "id": f"stretch_tradeoff_{index}",
                "depth": "stretch",
                "prompt_text": f"Stretch tradeoff question {index}",
                "scoring_rubric": ["Discuss the ceiling-level tradeoff."],
            }
            for index in range(1, 13)
        )
        return {"week": week_spec["number"], "questions": questions}

    def generate_reading_material(self, week_spec, ledger_state, questions):
        return _reading_material_for(questions)

    def generate_concept_cards_from_reading(self, week_spec, ledger_state, reading_material):
        return _concept_cards_for(reading_material)

    def generate_task(self, week_spec, ledger_state):
        raise AssertionError("Task generation is not exercised in this UI test.")

    def score_learning_question(self, week_spec, question, answer, observation):
        return {"passed": True, "score_rationale": "Good answer.", "missing_concepts": []}

    def answer_topic_chat(self, week_spec, context, history, message):
        return f"Tutor reply about: {message}"


class CountingProvider(FakeProvider):
    def __init__(self):
        self.learning_generate_calls = 0

    def generate_question_bank(self, week_spec, ledger_state):
        self.learning_generate_calls += 1
        return super().generate_question_bank(week_spec, ledger_state)


class FailingProvider(FakeProvider):
    def score_learning_question(self, week_spec, question, answer, observation):
        return {"passed": False, "score_rationale": "Missing a key idea.", "missing_concepts": ["iterative decoding"]}


class StreamingProvider(FakeProvider):
    def stream_topic_chat(self, week_spec, context, history, message):
        yield "Tutor reply "
        yield "about: "
        yield message


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
        f"""# 8-Week Inference Engineering Roadmap

## Overview

Overview text.

## Repository Structure

```
inference/
├── simple_server/
└── docs/
```

Repository description.

## Week 1: Build a Baseline Inference Server

### Goal

Run a model locally and expose it as an API.

### Narrative

This week establishes the baseline serving path and the first performance measurements.

### Topics Covered

- prefill vs decode

### By the End of This Week You Will Be Able To

- Explain how the baseline server works
- Measure the initial performance characteristics

### Assessment Targets

1. Explain prefill vs decode.
2. Describe how to measure the baseline server.

### Implementation

**Files created this week:**

- `simple_server/server.py` — API server entrypoint.

**Deliverables:** A benchmark note in `docs/baseline_results.md` measuring tokens/sec for the server.

**Cloud deployment:** Not required.

### Key Resources

- **Example resource.**
- Production reference in `simple_server/server.py`.

{_extra_weeks()}

## Capstone Summary

### Artifacts Built

| Artifact | Location | Description |
|---|---|---|
| Baseline server | `simple_server/server.py` | Example |

### What You Can Now Do

You can ship the system.
"""
    )


def test_render_page_shows_uninitialized_state(monkeypatch, tmp_path):
    write_config(tmp_path)
    write_roadmap(tmp_path)
    monkeypatch.chdir(tmp_path)

    page = render_page()

    assert "Capstone Project" in page
    assert "Learn by Building Real Systems" in page
    assert "Master concepts, build artifacts, and unlock the next stage." in page
    assert "Initialize Week 1" in page
    assert "No ledger loaded yet" in page
    assert 'href="/favicon.ico"' in page
    assert 'src="/assets/icon.png"' in page
    assert "Quick Start" in page
    assert "Set up the week ledger to begin the guided workflow." in page
    assert "left-sidebar" in page
    assert "right-sidebar" in page
    assert "Initialize Week 1 to start the course" in page
    assert "Assistant" in page
    assert "Ask" in page
    assert "Hints" in page
    assert "Context" in page
    assert "Week Chat" not in page
    assert "Ask The Model" not in page
    assert "Current Assessment" in page
    assert "Starter questions will appear once learning content is loaded." in page
    assert "Explain prefill vs decode" not in page
    assert "Show example pipeline" not in page
    assert "Common pitfalls" not in page
    assert "Performance tips" not in page
    assert 'data-topic-chat-delete' in page
    assert 'aria-label="Delete chat"' in page
    assert "workspace-sidebar-v3" in page
    assert "stepper-bar-v3" in page
    assert "Search" in page
    assert "Marathon Progress" in page
    assert "The 8-Week AI Engineering Marathon" in page
    assert "Week 1 / Question 0 of 0" in page
    assert "Week 1" in page
    assert "data-marathon-strip" in page
    assert "data-marathon-progress" in page
    assert "data-marathon-runner" in page
    assert "Finish" in page
    assert "/api/topic-chat" in page
    assert "data-topic-chat-root" in page
    assert "data-topic-chat-session-list" in page
    assert "data-topic-chat-suggestion" in page
    assert "How It Works" not in page
    assert "What You Will See" not in page


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
    assert "server.py" in page
    assert "Build a Baseline Inference Server" in page
    assert "Baseline Inference Server" in page


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
    assert "Concept Mastery" in page
    assert "Create Deliverables" in page
    assert "Metrics &amp; Evidence" in page
    assert "Unlock Next Stage" in page
    assert "Learn Workspace" in page
    assert "Study on the left and answer on the right." in page
    assert "Question 1 of 50" in page
    assert "Explain prefill vs decode." in page
    assert "Mention prompt processing." in page
    assert "Mention iterative decoding." in page
    assert "Submit Answer" in page
    assert "0% complete" in page
    assert "Token Generation" in page
    assert "Prefill vs Decode" in page
    assert "Implementation" in page
    assert "Deliverables" in page
    assert "Benchmark Metrics" in page
    assert "Additional Resources" in page
    assert "<strong>Example resource.</strong>" in page
    assert "Production reference in <code>simple_server/server.py</code>." in page
    assert "Approval Readiness" in page
    assert "Concept Questions" in page
    assert "Required Files" in page
    assert "Required Metrics" in page
    assert "Verification" in page
    assert "Assistant" in page
    assert "Chat" in page
    assert "I&#x27;m new to this. Can you explain prefill vs decode in simple terms?" in page
    assert 'Can you walk me through &quot;From Request To Generated Tokens&quot; like I&#x27;m just getting started?' in page
    assert 'What does &quot;Prefill vs Decode&quot; mean, and why does it matter this week?' in page
    assert 'What should I pay attention to when reading &quot;How To Measure And Verify&quot;?' in page
    assert "prefill_decode_baseline" in page
    assert "Continue Step" in page
    assert "Capstone Project" in page
    assert "In Progress" in page
    assert "What is this week about?" not in page
    assert "New Chat" not in page
    assert "How It Works" not in page
    assert "Learn by Building Real Systems" in page
    assert "Master concepts, build artifacts, and unlock the next stage." in page
    assert "Marathon Progress" in page
    assert "The 8-Week AI Engineering Marathon" in page
    assert "Week 1 / Question 0 of 50" in page
    assert "0 of 18 required checkpoints passed. Current stop: Learn." in page
    assert "data-marathon-strip" in page
    assert "data-marathon-progress" in page
    assert "data-marathon-runner" in page
    assert "Week 8" in page
    assert "Finish" in page
    assert "You" in page
    assert "Week 1" in page
    assert "localhost:4010" in page
    assert "right-sidebar" in page
    assert "Week Chat" not in page
    assert "Ask The Model" not in page
    assert "Build a Baseline Inference Server" in page
    assert 'data-topic-chat-delete' in page
    assert 'aria-label="Delete chat"' in page
    assert "I&#x27;m new to this. Can you explain prefill vs decode in simple terms?" in page
    assert 'Can you walk me through &quot;From Request To Generated Tokens&quot; like I&#x27;m just getting started?' in page
    assert "/api/topic-chat" in page
    assert "learning-agent-topic-chat-" in page
    assert 'buffer.split(/\\r?\\n/);' in page
    assert 'return storageKey(root, "sessions");' in page
    assert 'return storageKey(root, "draft");' in page
    assert 'textarea.addEventListener("keydown"' in page
    assert 'if (event.key !== "Enter" || event.shiftKey || event.isComposing)' in page
    assert 'submitTopicChatForm(form);' in page
    assert "See Full Question List" in page
    assert 'id="question-list-modal"' in page
    assert "Full Question List" in page
    assert 'Explain prefill vs decode. <span class="required-question-marker">*</span>' in page
    assert 'Baseline concept question 3 <span class="required-question-marker">*</span>' in page
    assert "`*` marks a required question." in page
    assert ".required-question-marker {" in page
    assert 'color: #c7332f;' in page
    assert 'role="progressbar"' in page
    assert "/?question_id=prefill_decode_baseline" in page
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
    assert "Concept Cards" in page
    assert "Reading Material" in page
    assert "Open Learn" not in page


def test_marathon_strip_advances_when_a_required_question_passes(monkeypatch, tmp_path):
    write_config(tmp_path)
    write_roadmap(tmp_path)
    (tmp_path / "ai_inference_engineering" / "simple_server").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ai_inference_engineering" / "docs").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("learning_agent.controller.get_provider", lambda _config: FakeProvider())

    assert run_action("init", {"action": ["init"]}) == "Initialized Week 1."

    before = render_page()
    assert "Week 1 / Question 0 of 50" in before

    result = run_action(
        "learning_answer",
        {
            "action": ["learning_answer"],
            "question_id": ["prefill_decode_baseline"],
            "learning_answer": ["Prefill processes the prompt and decode emits tokens autoregressively."],
        },
    )

    assert result == "Question passed."

    after = render_page(selected_question_id="prefill_decode_baseline")
    assert "Week 1 / Question 1 of 50" in after
    assert (
        '<textarea name="learning_answer" placeholder="Answer this question while using the material on the left as reference." '
        'data-learning-answer-textarea>Prefill processes the prompt and decode emits tokens autoregressively.</textarea>'
    ) in after


def test_failed_answer_is_reloaded_into_textarea(monkeypatch, tmp_path):
    write_config(tmp_path)
    write_roadmap(tmp_path)
    (tmp_path / "ai_inference_engineering" / "simple_server").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ai_inference_engineering" / "docs").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("learning_agent.controller.get_provider", lambda _config: FailingProvider())

    assert run_action("init", {"action": ["init"]}) == "Initialized Week 1."
    assert run_action("learning_generate", {"action": ["learning_generate"]}) == "Generated Learning Assist for Week 1."

    submitted = "QKV are just weights and they help the model somehow."
    result = run_action(
        "learning_answer",
        {
            "action": ["learning_answer"],
            "question_id": ["prefill_decode_baseline"],
            "learning_answer": [submitted],
        },
    )

    assert result == "Question failed."

    after = render_page(selected_question_id="prefill_decode_baseline")
    assert (
        '<textarea name="learning_answer" placeholder="Answer this question while using the material on the left as reference." '
        f'data-learning-answer-textarea>{submitted}</textarea>'
    ) in after


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
            "selected_question_id": "prefill_decode_baseline",
        }
    )

    assert payload["week"] == 1
    assert payload["context_label"] == "Week 1 · Learn"
    assert payload["reply"] == "Tutor reply about: How should I measure tokens per second?"


def test_run_topic_chat_stream_returns_events(monkeypatch, tmp_path):
    write_config(tmp_path)
    write_roadmap(tmp_path)
    (tmp_path / "ai_inference_engineering" / "simple_server").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ai_inference_engineering" / "docs").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("learning_agent.controller.get_provider", lambda _config: StreamingProvider())

    assert run_action("init", {"action": ["init"]}) == "Initialized Week 1."
    assert run_action("learning_generate", {"action": ["learning_generate"]}) == "Generated Learning Assist for Week 1."

    events = list(
        run_topic_chat_stream(
            {
                "message": "How should I measure tokens per second?",
                "history": [{"role": "user", "content": "What should I focus on?"}],
                "current_step": "learn",
            }
        )
    )

    assert [event["type"] for event in events] == ["start", "delta", "delta", "delta", "done"]
    assert events[0]["week"] == 1
    assert events[0]["context_label"] == "Week 1 · Learn"
    assert events[-1]["reply"] == "Tutor reply about: How should I measure tokens per second?"


def test_run_topic_chat_stream_returns_validation_error_event(monkeypatch, tmp_path):
    write_config(tmp_path)
    write_roadmap(tmp_path)
    (tmp_path / "ai_inference_engineering" / "simple_server").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ai_inference_engineering" / "docs").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("learning_agent.controller.get_provider", lambda _config: FakeProvider())

    assert run_action("init", {"action": ["init"]}) == "Initialized Week 1."

    events = list(
        run_topic_chat_stream(
            {
                "message": "",
                "history": [],
                "current_step": "learn",
            }
        )
    )

    assert events == [{"type": "error", "error": "Topic chat message cannot be empty."}]


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
                "selected_question_id": "prefill_decode_baseline",
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

    assert "Learn Workspace" in first_page
    assert "Submit Answer" in second_page
    assert provider.learning_generate_calls == 1

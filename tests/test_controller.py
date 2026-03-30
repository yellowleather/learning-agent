import json
from pathlib import Path

from learning_agent.config import load_config
from learning_agent.controller import LearningController
from learning_agent.models import (
    ClassifiedQuestionBankPayload,
    ConceptCardPayload,
    EvidenceQuestionPayload,
    GateQuestion,
    GateResult,
    GeneratedTask,
    ObservationRecord,
    QuestionScore,
    RawQuestionBankPayload,
    ReadingMaterialPayload,
    ReflectionRecord,
)


def _extra_weeks(start: int = 3) -> str:
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

- Example resource.
"""
        )
    return "\n\n".join(blocks)


def _reading_sections_for(questions):
    question_ids = [question["id"] if isinstance(question, dict) else question.id for question in questions]
    return ReadingMaterialPayload(
        week=1,
        reading_sections=[
            {
                "id": "week_map",
                "title": "How This Week Works",
                "body_markdown": (
                    "Week 1 is about learning the shape of a small inference system before you start writing code. "
                    "You should come away knowing what the server is responsible for, how the model runtime fits into the path, "
                    "why prompt handling and token generation are different kinds of work, and what evidence will later prove the system behaves correctly. "
                    "If you can explain the system from the outside in, the implementation will feel grounded instead of random."
                ),
            },
            {
                "id": "request_to_response",
                "title": "From Request To Generated Tokens",
                "body_markdown": (
                    "A useful mental model starts with one request entering the server and ends with generated output returning to the caller. "
                    "The server validates the request, shapes the prompt, hands work to the runtime, and turns generated tokens back into an API response. "
                    "That path matters because every performance claim, debugging step, and implementation decision sits somewhere along it. "
                    "When you answer a question, you should be able to place the concept on this path instead of describing it in isolation."
                ),
            },
            {
                "id": "generation_mechanics",
                "title": "Prefill, Decode, And Why The Split Matters",
                "body_markdown": (
                    "The core technical distinction this week is the split between prefill and decode. "
                    "During prefill, the model absorbs the prompt and prepares state from the input context. "
                    "After that, decode becomes a loop where each new token depends on the state built so far. "
                    "If you blur those phases together, you lose the ability to explain latency behavior, throughput tradeoffs, and why prompt length and output length stress the system differently."
                ),
            },
            {
                "id": "build_artifacts",
                "title": "How Week 1 Maps Onto Code",
                "body_markdown": (
                    "The reading should connect cleanly to the files you will build next. "
                    "A server file expresses the request boundary, a benchmark file expresses how behavior gets measured, and the written results capture evidence that the system works as described. "
                    "Thinking this way keeps implementation tied to system responsibilities rather than turning it into a list of disconnected coding tasks. "
                    "Good answers about implementation should map ideas back to files, responsibilities, and observable behavior."
                ),
            },
            {
                "id": "measure_and_verify",
                "title": "How To Measure And Verify",
                "body_markdown": (
                    "Performance numbers are only useful when you can say what was measured, what the number means, and what it hides. "
                    "Latency and throughput answer different questions, and neither one is trustworthy without enough context about prompts, outputs, and the benchmark loop that produced them. "
                    "The goal is to make performance reasoning disciplined rather than impressionistic. "
                    "By the end of the week, you should be able to connect a metric back to the exact part of the inference path that could have produced it."
                ),
            },
        ],
    )


def _concept_cards_for(_reading_sections):
    return ConceptCardPayload(
        week=1,
        concept_cards=[
            {
                "id": "prefill-vs-decode",
                "concept": "prefill_vs_decode",
                "title": "Prefill vs Decode",
                "explanation": "Prefill processes the prompt and decode emits output token by token.",
                "why_it_matters": "This distinction explains why prompt length and output length stress the system differently.",
                "common_mistake": "Treating all inference work as one undifferentiated block.",
                "quick_check_question": "What changes once prefill ends and decode begins?",
                "related_section_ids": ["generation_mechanics"],
            },
            {
                "id": "token-generation",
                "concept": "token_generation",
                "title": "Token Generation",
                "explanation": "Token generation is the repeated loop that turns model state into output over time.",
                "why_it_matters": "It helps the learner reason about user-visible behavior and performance.",
                "common_mistake": "Talking about generation without distinguishing it from prompt processing.",
                "quick_check_question": "What part of the system repeats for every next token?",
                "related_section_ids": ["generation_mechanics"],
            },
            {
                "id": "request-flow",
                "concept": "request_flow",
                "title": "Request Flow",
                "explanation": "Request flow is the full path from API input through runtime work to returned output.",
                "why_it_matters": "It anchors system explanations in the serving path rather than isolated model facts.",
                "common_mistake": "Explaining the model while skipping the server around it.",
                "quick_check_question": "What are the major stages between request arrival and response delivery?",
                "related_section_ids": ["request_to_response"],
            },
            {
                "id": "api-serving",
                "concept": "api_serving",
                "title": "API Serving",
                "explanation": "API serving turns the model into a usable system boundary for requests, responses, and operations.",
                "why_it_matters": "It ties the reading back to the actual service the learner will build.",
                "common_mistake": "Treating serving as a thin wrapper instead of part of the design.",
                "quick_check_question": "Why is model quality alone not enough for a usable inference service?",
                "related_section_ids": ["request_to_response", "build_artifacts"],
            },
            {
                "id": "implementation-boundaries",
                "concept": "implementation_boundaries",
                "title": "Implementation Boundaries",
                "explanation": "Implementation boundaries connect the ideas in the reading to the files that represent them in code.",
                "why_it_matters": "This keeps implementation grounded in responsibilities instead of disconnected tasks.",
                "common_mistake": "Jumping into files without first understanding which system boundary each file owns.",
                "quick_check_question": "How should the week’s files map onto the system responsibilities?",
                "related_section_ids": ["build_artifacts"],
            },
            {
                "id": "latency-metrics",
                "concept": "latency_metrics",
                "title": "Latency Metrics",
                "explanation": "Latency metrics describe how long the system takes to respond and must be tied back to the inference path.",
                "why_it_matters": "They make performance discussions concrete and testable.",
                "common_mistake": "Quoting latency without saying what part of the system it reflects.",
                "quick_check_question": "What part of the request path could make latency rise?",
                "related_section_ids": ["measure_and_verify"],
            },
            {
                "id": "throughput-metrics",
                "concept": "throughput_metrics",
                "title": "Throughput Metrics",
                "explanation": "Throughput metrics describe how much generation work the system can sustain over time.",
                "why_it_matters": "They clarify efficiency, not just correctness.",
                "common_mistake": "Treating throughput as interchangeable with latency.",
                "quick_check_question": "What does tokens per second tell you that latency alone does not?",
                "related_section_ids": ["measure_and_verify"],
            },
            {
                "id": "benchmark-evidence",
                "concept": "benchmark_evidence",
                "title": "Benchmark Evidence",
                "explanation": "Benchmark evidence turns performance claims into something inspectable and trustworthy.",
                "why_it_matters": "It connects measurement to disciplined engineering judgment.",
                "common_mistake": "Reporting numbers without enough benchmark context to trust them.",
                "quick_check_question": "What makes a benchmark result trustworthy instead of just plausible?",
                "related_section_ids": ["measure_and_verify", "week_map"],
            },
        ],
    )


class FakeProvider:
    def generate_raw_question_bank(self, week_spec, ledger_state):
        questions = [
            {
                "prompt_text": "What is the difference between prefill and decode?",
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
        return RawQuestionBankPayload(
            week=week_spec["number"],
            questions=questions,
        )

    def classify_question_bank(self, week_spec, ledger_state, questions):
        classified_questions = [
            {
                "id": "core_prefill_decode",
                "type": "concept",
                "scope": "core",
                "depth": "baseline",
                "prompt_text": "What is the difference between prefill and decode?",
                "scoring_rubric": ["Explain prompt processing.", "Explain iterative generation."],
                "roadmap_anchor": {"week": week_spec["number"], "concept": "prefill_vs_decode"},
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
                "roadmap_anchor": {"week": week_spec["number"], "topic": "latency_metrics"},
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
                "roadmap_anchor": {"week": week_spec["number"], "deliverable": "simple_server/benchmark.py"},
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
                "roadmap_anchor": {"week": week_spec["number"], "deliverable": "simple_server/server.py"},
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
                "roadmap_anchor": {"week": week_spec["number"], "topic": "throughput_tradeoffs"},
                "observation_required": False,
            }
            for index in range(1, 13)
        )
        return ClassifiedQuestionBankPayload(
            week=week_spec["number"],
            questions=classified_questions,
        )

    def generate_reading_material(self, week_spec, ledger_state, questions):
        return _reading_sections_for(questions)

    def generate_concept_cards_from_reading(self, week_spec, ledger_state, reading_sections):
        return _concept_cards_for(reading_sections)

    def generate_gate_question(self, week_spec):
        return GateQuestion(
            week=week_spec["number"],
            question="Explain prefill vs decode.",
            rubric=["Explain the distinction.", "Mention why decode repeats."],
            context_summary=week_spec["goal"],
        )

    def score_gate_answer(self, week_spec, question, answer):
        return GateResult(
            passed=True,
            score_rationale="Answer covered the core distinction.",
            missing_concepts=[],
        )

    def generate_task(self, week_spec, ledger_state):
        return GeneratedTask(
            week=week_spec["number"],
            title=week_spec["short_title"],
            objective=week_spec["goal"],
            allowed_dirs=week_spec["active_dirs"],
            required_files=week_spec["required_files"],
            implementation_steps=["Create the required files."],
            acceptance_checks=["Files exist."],
            verification_expectations=["Verification is recorded."],
            summary="Implement Week 1.",
        )

    def score_learning_question(self, week_spec, question, answer, observation):
        return QuestionScore(
            passed=True,
            score_rationale=f"Answer covered {question.id}.",
            missing_concepts=[],
        )

    def generate_evidence_questions(self, week_spec, observation, learning_session):
        return EvidenceQuestionPayload(
            week=week_spec["number"],
            questions=[
                {
                    "id": "evidence_latency",
                    "type": "evidence_based",
                    "scope": "core",
                    "depth": "baseline",
                    "prompt_text": "What does the latency pattern suggest?",
                    "scoring_rubric": ["Tie the result to prefill cost."],
                    "roadmap_anchor": {"week": week_spec["number"], "metric": "latency_p95"},
                    "observation_required": True,
                }
            ],
        )

    def answer_topic_chat(self, week_spec, context, history, message):
        return f"Topic tutor: {message}"


class ChatCapturingProvider(FakeProvider):
    def __init__(self):
        self.chat_calls = []

    def answer_topic_chat(self, week_spec, context, history, message):
        self.chat_calls.append(
            {
                "week_spec": week_spec,
                "context": context,
                "history": history,
                "message": message,
            }
        )
        return f"Topic tutor: {message}"


class JsonChatProvider(FakeProvider):
    def answer_topic_chat(self, week_spec, context, history, message):
        return """```json
{"response": "Could you clarify your question? Are you asking about testing a specific aspect of the inference server?"}
```"""


class StreamingChatProvider(FakeProvider):
    def __init__(self):
        self.chat_calls = []

    def stream_topic_chat(self, week_spec, context, history, message):
        self.chat_calls.append(
            {
                "week_spec": week_spec,
                "context": context,
                "history": history,
                "message": message,
            }
        )
        yield "Topic "
        yield "tutor: "
        yield message


class JsonStreamingChatProvider(FakeProvider):
    def stream_topic_chat(self, week_spec, context, history, message):
        yield "```json\n"
        yield '{"response": "Could you clarify your question? '
        yield 'Are you asking about testing a specific aspect of the inference server?"}\n```'


def write_config(tmp_path: Path, roadmap_path: Path, target_repo_path: Path) -> None:
    payload = {
        "provider": "openai",
        "model": "test-model",
        "roadmap_path": str(roadmap_path.relative_to(tmp_path)),
        "target_repo_path": str(target_repo_path.relative_to(tmp_path)),
        "state_dir": "state",
    }
    (tmp_path / "learning_agent.config.json").write_text(json.dumps(payload))


def write_roadmap(tmp_path: Path) -> Path:
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
├── docs/
└── benchmarking/
```

Repository description.

## Week 1: Build a Baseline Inference Server

### Goal

Run a model locally and expose it as an API.

### Narrative

This week establishes the baseline serving path and the first performance measurements.

### Topics Covered

- prefill vs decode
- latency vs throughput

### By the End of This Week You Will Be Able To

- Explain the serving path and the key metrics
- Build the baseline service and benchmark it

### Assessment Targets

1. Explain prefill vs decode.
2. Describe how you would benchmark the baseline server.

### Implementation

**Files created this week:**

- `simple_server/server.py` — API server entrypoint.
- `simple_server/benchmark.py` — Benchmark runner.

**Deliverables:** A baseline report in `docs/baseline_results.md` capturing latency and tokens/sec.

**Cloud deployment:** Not required.

### Key Resources

- Example resource.

## Week 2: Next Week

### Goal

Do more things.

### Narrative

This week extends the baseline with one additional implementation step.

### Topics Covered

- next-step system design

### By the End of This Week You Will Be Able To

- Explain the next implementation step
- Extend the system with a new artifact

### Assessment Targets

1. Explain the purpose of the next implementation step.
2. Describe the new artifact.

### Implementation

**Files created this week:**

- `benchmarking/run.py` — Next benchmark script.

**Deliverables:** A runnable benchmark script in `benchmarking/run.py`.

**Cloud deployment:** Not required.

### Key Resources

- Example resource.

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
    return roadmap


def make_controller(tmp_path: Path, monkeypatch):
    roadmap_path = write_roadmap(tmp_path)
    target_repo = tmp_path / "ai_inference_engineering"
    (target_repo / "simple_server").mkdir(parents=True, exist_ok=True)
    (target_repo / "docs").mkdir(parents=True, exist_ok=True)
    write_config(tmp_path, roadmap_path, target_repo)
    monkeypatch.chdir(tmp_path)
    repo_root, config = load_config()
    controller = LearningController(repo_root, config)
    monkeypatch.setattr("learning_agent.controller.get_provider", lambda _config: FakeProvider())
    return controller, target_repo


def test_full_week_one_transition(monkeypatch, tmp_path):
    controller, target_repo = make_controller(tmp_path, monkeypatch)
    ledger = controller.initialize()
    assert ledger.state.current_week == 1
    assert ledger.state.active_functional_dirs == ["simple_server", "docs"]

    gate = controller.ask_gate()
    assert gate.prompt.week == 1

    result = controller.submit_gate("Prefill processes the prompt once; decode generates next tokens iteratively.")
    assert result.passed is True

    task_session = controller.generate_task()
    assert task_session.task.required_files == [
        "simple_server/server.py",
        "simple_server/benchmark.py",
        "docs/baseline_results.md",
    ]

    (target_repo / "simple_server" / "server.py").write_text("print('ok')\n")
    (target_repo / "simple_server" / "benchmark.py").write_text("print('ok')\n")
    (target_repo / "docs" / "baseline_results.md").write_text("latency_p95: 10\n")

    ledger = controller.sync_artifacts()
    assert ledger.state.gates.implementation_complete is True

    controller.record_metric("latency_p95", 10.0)
    controller.record_metric("tokens_per_sec", 25.0)
    ledger = controller.record_verification(True, "Local verification passed.")
    assert ledger.state.gates.verification_passed is True

    ledger = controller.record_observation(
        ObservationRecord(
            command=".venv/bin/python simple_server/benchmark.py",
            artifact_path="docs/baseline_results.md",
            prompt_tokens=512,
            output_tokens=128,
            latency_p95_ms=10.0,
            tokens_per_sec=25.0,
            reliability="valid",
            notes="Baseline benchmark completed successfully.",
        )
    )
    assert ledger.state.gates.evidence_reliable is True

    ledger = controller.record_reflection(
        ReflectionRecord(
            text="The measurement is trustworthy and matches the intended baseline.",
            trustworthy=True,
            buggy=False,
            next_fix="",
        )
    )
    assert ledger.state.reflection is not None

    ledger = controller.approve_week()
    assert ledger.state.gates.week_approved is True

    next_ledger = controller.advance_week()
    assert next_ledger.state.current_week == 2
    assert next_ledger.state.gates.socratic_check_passed is False


def test_generate_task_requires_gate(monkeypatch, tmp_path):
    controller, _target_repo = make_controller(tmp_path, monkeypatch)
    controller.initialize()

    try:
        controller.generate_task()
    except Exception as exc:  # pragma: no cover - assertion below narrows the behavior.
        assert "concept gate passes" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected task generation to fail before the gate passes.")


def test_learning_assist_flow_records_evidence_and_reflection(monkeypatch, tmp_path):
    controller, target_repo = make_controller(tmp_path, monkeypatch)
    controller.initialize()

    session = controller.generate_learning_assist()
    assert session.week == 1
    assert len(session.questions) == 50
    assert session.figures
    assert session.reading_sections
    assert session.concept_cards[0].image_path == "/assets/illustrations/prefill-decode.svg"
    assert session.reading_sections[0].title == "How This Week Works"
    assert "generation_mechanics" in [section.id for section in session.reading_sections]
    assert session.concept_cards[0].related_section_ids

    bundle = controller.get_learning_bundle()
    assert bundle is not None
    assert bundle.figures
    assert bundle.reading_sections
    assert bundle.questions[0].related_concept_ids

    controller.answer_learning_question("core_prefill_decode", "Prefill processes the prompt once.")
    result = controller.answer_learning_question("impl_measure_tokens", "Count tokens and divide by decode time.")
    assert result.passed is True
    assert controller.status()["gates"]["socratic_check_passed"] is True

    controller.generate_task()
    (target_repo / "simple_server" / "server.py").write_text("print('ok')\n")
    (target_repo / "simple_server" / "benchmark.py").write_text("print('ok')\n")
    (target_repo / "docs" / "baseline_results.md").write_text("latency_p95: 10\n")
    controller.sync_artifacts()
    controller.record_verification(True, "Local verification passed.")

    ledger = controller.record_observation(
        ObservationRecord(
            command=".venv/bin/python simple_server/benchmark.py",
            artifact_path="docs/baseline_results.md",
            prompt_tokens=512,
            output_tokens=128,
            latency_p95_ms=840.0,
            tokens_per_sec=32.4,
            reliability="valid",
            notes="Repeated runs were stable.",
        )
    )
    assert ledger.state.gates.evidence_reliable is True
    assert ledger.state.metrics.recorded["latency_p95"] == 840.0
    assert ledger.state.metrics.recorded["tokens_per_sec"] == 32.4

    evidence_result = controller.answer_learning_question(
        "evidence_latency",
        "The latency increase is more consistent with prompt processing cost growing.",
    )
    assert evidence_result.passed is True

    ledger = controller.record_reflection(
        ReflectionRecord(
            text="The benchmark seems trustworthy after warm-up and repeated runs.",
            trustworthy=True,
            buggy=False,
            next_fix="",
        )
    )
    assert ledger.state.reflection is not None

    status = controller.status()
    assert status["question_progress"]["evidence_answered"] == 1
    assert not status["approval_blockers"]

    approved = controller.approve_week()
    assert approved.state.gates.week_approved is True


def test_answer_topic_chat_builds_learn_context(monkeypatch, tmp_path):
    controller, _target_repo = make_controller(tmp_path, monkeypatch)
    provider = ChatCapturingProvider()
    monkeypatch.setattr("learning_agent.controller.get_provider", lambda _config: provider)
    controller.initialize()
    controller.generate_learning_assist()

    result = controller.answer_topic_chat(
        message="How should I connect this to the benchmark task?",
        history=[{"role": "user", "content": "Remind me what matters most."}],
        current_step="learn",
        selected_question_id="core_prefill_decode",
    )

    assert result["week"] == 1
    assert result["context_label"] == "Week 1 · Learn"
    assert result["reply"] == "Topic tutor: How should I connect this to the benchmark task?"
    assert len(provider.chat_calls) == 1
    call = provider.chat_calls[0]
    assert call["message"] == "How should I connect this to the benchmark task?"
    assert call["history"][0].role == "user"
    assert "Week title: Build a Baseline Inference Server" in call["context"]
    assert "Selected question context is available in the UI but is intentionally not injected into chat grounding by default." in call["context"]
    assert "Selected question prompt: What is the difference between prefill and decode?" not in call["context"]


def test_stream_topic_chat_emits_events_and_context(monkeypatch, tmp_path):
    controller, _target_repo = make_controller(tmp_path, monkeypatch)
    provider = StreamingChatProvider()
    monkeypatch.setattr("learning_agent.controller.get_provider", lambda _config: provider)
    controller.initialize()
    controller.generate_learning_assist()

    events = list(
        controller.stream_topic_chat(
            message="How should I connect this to the benchmark task?",
            history=[{"role": "user", "content": "Remind me what matters most."}],
            current_step="learn",
            selected_question_id="core_prefill_decode",
        )
    )

    assert [event["type"] for event in events] == ["start", "delta", "delta", "delta", "done"]
    assert events[0]["week"] == 1
    assert events[0]["context_label"] == "Week 1 · Learn"
    assert events[-1]["reply"] == "Topic tutor: How should I connect this to the benchmark task?"
    assert len(provider.chat_calls) == 1
    call = provider.chat_calls[0]
    assert call["message"] == "How should I connect this to the benchmark task?"
    assert call["history"][0].role == "user"
    assert "Week title: Build a Baseline Inference Server" in call["context"]
    assert "Selected question context is available in the UI but is intentionally not injected into chat grounding by default." in call["context"]


def test_answer_topic_chat_normalizes_json_wrapped_reply(monkeypatch, tmp_path):
    controller, _target_repo = make_controller(tmp_path, monkeypatch)
    monkeypatch.setattr("learning_agent.controller.get_provider", lambda _config: JsonChatProvider())
    controller.initialize()

    result = controller.answer_topic_chat(
        message="test",
        history=[],
        current_step="learn",
    )

    assert result["reply"] == "Could you clarify your question? Are you asking about testing a specific aspect of the inference server?"


def test_stream_topic_chat_normalizes_json_wrapped_final_reply(monkeypatch, tmp_path):
    controller, _target_repo = make_controller(tmp_path, monkeypatch)
    monkeypatch.setattr("learning_agent.controller.get_provider", lambda _config: JsonStreamingChatProvider())
    controller.initialize()

    events = list(
        controller.stream_topic_chat(
            message="test",
            history=[],
            current_step="learn",
        )
    )

    assert [event["type"] for event in events] == ["start", "delta", "delta", "delta", "done"]
    assert events[-1]["reply"] == "Could you clarify your question? Are you asking about testing a specific aspect of the inference server?"

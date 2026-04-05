import json
from pathlib import Path

from learning_agent.config import load_config
from learning_agent.controller import LearningController
from learning_agent.models import (
    ConceptCardPayload,
    GeneratedTask,
    LearningQuestionBankPayload,
    ObservationRecord,
    QuestionScore,
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


def _reading_material_for(questions):
    question_ids = [question["id"] if isinstance(question, dict) else question.id for question in questions]
    del question_ids
    return ReadingMaterialPayload(
        week=1,
        title="Week 1 Reading",
        body_markdown=(
            "## How This Week Works\n\n"
            "Week 1 is about learning the shape of a small inference system before you start writing code. "
            "You should come away knowing what the server is responsible for, how the model runtime fits into the path, "
            "why prompt handling and token generation are different kinds of work, and what evidence will later prove the system behaves correctly. "
            "If you can explain the system from the outside in, the implementation will feel grounded instead of random.\n\n"
            "## From Request To Generated Tokens\n\n"
            "A useful mental model starts with one request entering the server and ends with generated output returning to the caller. "
            "The server validates the request, shapes the prompt, hands work to the runtime, and turns generated tokens back into an API response. "
            "That path matters because every performance claim, debugging step, and implementation decision sits somewhere along it. "
            "When you answer a question, you should be able to place the concept on this path instead of describing it in isolation.\n\n"
            "## Prefill, Decode, And Why The Split Matters\n\n"
            "The core technical distinction this week is the split between prefill and decode. "
            "During prefill, the model absorbs the prompt and prepares state from the input context. "
            "After that, decode becomes a loop where each new token depends on the state built so far. "
            "If you blur those phases together, you lose the ability to explain latency behavior, throughput tradeoffs, and why prompt length and output length stress the system differently.\n\n"
            "## How Week 1 Maps Onto Code\n\n"
            "The reading should connect cleanly to the files you will build next. "
            "A server file expresses the request boundary, a benchmark file expresses how behavior gets measured, and the written results capture evidence that the system works as described. "
            "Thinking this way keeps implementation tied to system responsibilities rather than turning it into a list of disconnected coding tasks. "
            "Good answers about implementation should map ideas back to files, responsibilities, and observable behavior.\n\n"
            "## How To Measure And Verify\n\n"
            "Performance numbers are only useful when you can say what was measured, what the number means, and what it hides. "
            "Latency and throughput answer different questions, and neither one is trustworthy without enough context about prompts, outputs, and the benchmark loop that produced them. "
            "The goal is to make performance reasoning disciplined rather than impressionistic. "
            "By the end of the week, you should be able to connect a metric back to the exact part of the inference path that could have produced it."
        ),
    )


def _concept_cards_for(_reading_material):
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
            },
            {
                "id": "token-generation",
                "concept": "token_generation",
                "title": "Token Generation",
                "explanation": "Token generation is the repeated loop that turns model state into output over time.",
                "why_it_matters": "It helps the learner reason about user-visible behavior and performance.",
                "common_mistake": "Talking about generation without distinguishing it from prompt processing.",
                "quick_check_question": "What part of the system repeats for every next token?",
            },
            {
                "id": "request-flow",
                "concept": "request_flow",
                "title": "Request Flow",
                "explanation": "Request flow is the full path from API input through runtime work to returned output.",
                "why_it_matters": "It anchors system explanations in the serving path rather than isolated model facts.",
                "common_mistake": "Explaining the model while skipping the server around it.",
                "quick_check_question": "What are the major stages between request arrival and response delivery?",
            },
            {
                "id": "api-serving",
                "concept": "api_serving",
                "title": "API Serving",
                "explanation": "API serving turns the model into a usable system boundary for requests, responses, and operations.",
                "why_it_matters": "It ties the reading back to the actual service the learner will build.",
                "common_mistake": "Treating serving as a thin wrapper instead of part of the design.",
                "quick_check_question": "Why is model quality alone not enough for a usable inference service?",
            },
            {
                "id": "implementation-boundaries",
                "concept": "implementation_boundaries",
                "title": "Implementation Boundaries",
                "explanation": "Implementation boundaries connect the ideas in the reading to the files that represent them in code.",
                "why_it_matters": "This keeps implementation grounded in responsibilities instead of disconnected tasks.",
                "common_mistake": "Jumping into files without first understanding which system boundary each file owns.",
                "quick_check_question": "How should the week’s files map onto the system responsibilities?",
            },
            {
                "id": "latency-metrics",
                "concept": "latency_metrics",
                "title": "Latency Metrics",
                "explanation": "Latency metrics describe how long the system takes to respond and must be tied back to the inference path.",
                "why_it_matters": "They make performance discussions concrete and testable.",
                "common_mistake": "Quoting latency without saying what part of the system it reflects.",
                "quick_check_question": "What part of the request path could make latency rise?",
            },
            {
                "id": "throughput-metrics",
                "concept": "throughput_metrics",
                "title": "Throughput Metrics",
                "explanation": "Throughput metrics describe how much generation work the system can sustain over time.",
                "why_it_matters": "They clarify efficiency, not just correctness.",
                "common_mistake": "Treating throughput as interchangeable with latency.",
                "quick_check_question": "What does tokens per second tell you that latency alone does not?",
            },
            {
                "id": "benchmark-evidence",
                "concept": "benchmark_evidence",
                "title": "Benchmark Evidence",
                "explanation": "Benchmark evidence turns performance claims into something inspectable and trustworthy.",
                "why_it_matters": "It connects measurement to disciplined engineering judgment.",
                "common_mistake": "Reporting numbers without enough benchmark context to trust them.",
                "quick_check_question": "What makes a benchmark result trustworthy instead of just plausible?",
            },
        ],
    )


class FakeProvider:
    def generate_prior_knowledge_summary(self, full_plan, target_week_number):
        del full_plan, target_week_number
        return "The learner has no prior knowledge of LLMs, transformers, or inference systems."

    def generate_question_bank(self, week_spec, prior_knowledge_summary, ledger_state):
        del prior_knowledge_summary, ledger_state
        questions = [
            {
                "id": "prefill_decode_baseline",
                "depth": "baseline",
                "prompt_text": "What is the difference between prefill and decode?",
                "scoring_rubric": ["Explain prompt processing.", "Explain iterative generation."],
            }
        ]
        questions.append(
            {
                "id": "baseline_metrics_reasoning",
                "depth": "baseline",
                "prompt_text": "How should you reason about tokens per second in relation to decode work?",
                "scoring_rubric": ["Connect tokens per second to decode throughput.", "Explain what the metric hides."],
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
        return LearningQuestionBankPayload(
            week=week_spec["number"],
            questions=questions,
        )

    def generate_reading_material(self, week_spec, prior_knowledge_summary, ledger_state, questions):
        del week_spec, prior_knowledge_summary, ledger_state
        return _reading_material_for(questions)

    def generate_concept_cards_from_reading(self, week_spec, ledger_state, reading_material):
        return _concept_cards_for(reading_material)

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


class VariantProvider(FakeProvider):
    def __init__(self, prefix: str):
        self.prefix = prefix

    def generate_prior_knowledge_summary(self, full_plan, target_week_number):
        del full_plan, target_week_number
        return f"{self.prefix} prior knowledge summary."

    def generate_question_bank(self, week_spec, prior_knowledge_summary, ledger_state):
        payload = super().generate_question_bank(week_spec, prior_knowledge_summary, ledger_state)
        questions = []
        for index, question in enumerate(payload.questions, start=1):
            entry = question.model_dump(mode="json") if hasattr(question, "model_dump") else dict(question)
            entry["id"] = f"{self.prefix}_{index}"
            entry["prompt_text"] = f"{self.prefix}: {entry['prompt_text']}"
            questions.append(entry)
        return LearningQuestionBankPayload(week=payload.week, questions=questions)

    def generate_reading_material(self, week_spec, prior_knowledge_summary, ledger_state, questions):
        del week_spec, prior_knowledge_summary, ledger_state, questions
        return ReadingMaterialPayload(
            week=1,
            title=f"{self.prefix.title()} Reading",
            body_markdown=(
                "## How This Week Works\n\n"
                f"{self.prefix} overview of the system. "
                "This opening explains how the request boundary, model runtime, token generation loop, "
                "and measurement discipline fit together before implementation starts. "
                "It gives enough context to understand why the week exists, how the system behaves, "
                "and which distinctions matter when reasoning about performance, correctness, and later implementation work. "
                "The learner should come away with a concrete mental model rather than a vague summary.\n\n"
                "## Topic A\n\n"
                f"{self.prefix} topic A details. "
                "This part spells out the first mechanism in technical terms, explains the failure modes, "
                "and connects the concept back to the request path. "
                "It emphasizes what changes during runtime, what remains stable across requests, "
                "and how the learner should reason about the tradeoffs when metrics move unexpectedly. "
                "The explanation is deliberately detailed so the validator sees a reading body large enough to support the questions.\n\n"
                "## Topic B\n\n"
                f"{self.prefix} topic B details. "
                "This part continues with a second mechanism and explains why surface-level recall is insufficient. "
                "It distinguishes related ideas, addresses a likely misconception, and shows how observable behavior can be traced "
                "back to the underlying inference path. "
                "That way the reading supports both conceptual questions and later implementation reasoning without collapsing into steps.\n\n"
                "## Topic C\n\n"
                f"{self.prefix} topic C details. "
                "This final part ties the week back to files, deliverables, and metrics while remaining conceptual. "
                "It explains why those artifacts exist, what system responsibility they correspond to, "
                "and how a learner should interpret results produced during verification. "
                "The goal is depth, not brevity, so the content stays comfortably above the minimum length requirement."
            ),
        )

    def generate_concept_cards_from_reading(self, week_spec, ledger_state, reading_material):
        del week_spec, ledger_state, reading_material
        return ConceptCardPayload(
            week=1,
            concept_cards=[
                {
                    "id": f"{self.prefix}-card-{index}",
                    "concept": f"{self.prefix}_concept_{index}",
                    "title": f"{self.prefix.title()} Card {index}",
                    "explanation": f"{self.prefix} explanation {index}.",
                    "why_it_matters": f"{self.prefix} matters {index}.",
                    "common_mistake": f"{self.prefix} mistake {index}.",
                    "quick_check_question": f"{self.prefix} quick check {index}?",
                }
                for index in range(1, 4)
            ],
        )


class InvalidQuestionBankProvider(VariantProvider):
    def generate_question_bank(self, week_spec, prior_knowledge_summary, ledger_state):
        payload = super().generate_question_bank(week_spec, prior_knowledge_summary, ledger_state)
        questions = [question.model_dump(mode="json") for question in payload.questions[:48]]
        deep_seen = 0
        for question in questions:
            if question["depth"] == "deep":
                deep_seen += 1
                if deep_seen > 18:
                    question["depth"] = "baseline"
        return LearningQuestionBankPayload(week=payload.week, questions=questions)


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


def pass_required_learning_questions(controller: LearningController) -> None:
    session = controller.generate_learning_assist()
    for question in session.questions:
        if question.depth == "baseline":
            result = controller.answer_learning_question(question.id, f"Answer for {question.id}.")
            assert result.passed is True


def test_full_week_one_transition(monkeypatch, tmp_path):
    controller, target_repo = make_controller(tmp_path, monkeypatch)
    ledger = controller.initialize()
    assert ledger.state.current_week == 1
    assert ledger.state.active_dirs == ["simple_server", "docs"]
    pass_required_learning_questions(controller)

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
    assert next_ledger.state.gates.learning_check_passed is False


def test_generate_task_requires_gate(monkeypatch, tmp_path):
    controller, _target_repo = make_controller(tmp_path, monkeypatch)
    controller.initialize()

    try:
        controller.generate_task()
    except Exception as exc:  # pragma: no cover - assertion below narrows the behavior.
        assert "learning check passes" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected task generation to fail before the learning check passes.")


def test_learning_assist_flow_records_evidence_and_reflection(monkeypatch, tmp_path):
    controller, target_repo = make_controller(tmp_path, monkeypatch)
    controller.initialize()

    session = controller.generate_learning_assist()
    assert session.week == 1
    assert len(session.questions) == 50
    assert session.reading_material is not None
    assert session.reading_material.title == "Week 1 Reading"
    assert "## How This Week Works" in session.reading_material.body_markdown
    assert "## Prefill, Decode, And Why The Split Matters" in session.reading_material.body_markdown

    bundle = controller.get_learning_bundle()
    assert bundle is not None
    assert bundle.reading_material is not None

    baseline_questions = [question for question in session.questions if question.depth == "baseline"]
    for question in baseline_questions:
        result = controller.answer_learning_question(question.id, f"Answer for {question.id}.")
        assert result.passed is True
    assert controller.status()["gates"]["learning_check_passed"] is True

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
    assert not status["approval_blockers"]

    approved = controller.approve_week()
    assert approved.state.gates.week_approved is True


def test_compare_learning_providers_resets_state_and_writes_outputs(monkeypatch, tmp_path):
    controller, target_repo = make_controller(tmp_path, monkeypatch)
    controller.initialize()

    session = controller.generate_learning_assist()
    assert session.questions
    for question in session.questions:
        if question.depth == "baseline":
            controller.answer_learning_question(question.id, f"Answer for {question.id}.")
    controller.generate_task()
    (target_repo / "simple_server" / "server.py").write_text("print('ok')\n")
    (target_repo / "simple_server" / "benchmark.py").write_text("print('ok')\n")
    (target_repo / "docs" / "baseline_results.md").write_text("latency_p95: 10\n")
    controller.sync_artifacts()
    controller.record_metric("latency_p95", 10.0)
    controller.record_verification(True, "Local verification passed.")

    output_dir = tmp_path / "tmp" / "learning_compare" / "case"
    result = controller.compare_learning_providers(
        providers=[
            ("claude", "claude-test", VariantProvider("claude")),
            ("gpt", "gpt-test", VariantProvider("gpt")),
        ],
        output_dir=output_dir,
    )

    assert result["output_dir"] == str(output_dir)
    assert controller.get_learning_session() is None
    assert controller.get_task_session() is None
    assert result["providers"][0]["status"] == "valid"
    assert result["providers"][1]["status"] == "valid"

    ledger = controller.state.load_ledger()
    assert ledger.state.gates.learning_check_passed is False
    assert ledger.state.gates.implementation_complete is False
    assert ledger.state.gates.verification_passed is False
    assert ledger.state.metrics.recorded == {}
    assert ledger.state.verification is None

    assert (output_dir / "claude" / "prior_knowledge_summary.txt").exists()
    assert (output_dir / "claude" / "question_bank.json").exists()
    assert (output_dir / "claude" / "reading_material.json").exists()
    assert (output_dir / "claude" / "concept_cards.json").exists()
    assert (output_dir / "claude" / "validation_errors.json").exists()
    assert (output_dir / "gpt" / "prior_knowledge_summary.txt").exists()
    assert (output_dir / "gpt" / "question_bank.json").exists()
    assert (output_dir / "gpt" / "reading_material.json").exists()
    assert (output_dir / "gpt" / "concept_cards.json").exists()
    assert (output_dir / "gpt" / "validation_errors.json").exists()


def test_compare_learning_providers_continues_when_one_provider_is_invalid(monkeypatch, tmp_path):
    controller, _target_repo = make_controller(tmp_path, monkeypatch)
    controller.initialize()

    output_dir = tmp_path / "tmp" / "learning_compare" / "invalid-case"
    result = controller.compare_learning_providers(
        providers=[
            ("claude", "claude-test", InvalidQuestionBankProvider("claude")),
            ("gpt", "gpt-test", VariantProvider("gpt")),
        ],
        output_dir=output_dir,
    )

    providers = {item["provider_label"]: item for item in result["providers"]}
    assert providers["claude"]["status"] == "invalid"
    assert providers["gpt"]["status"] == "valid"
    assert (output_dir / "claude" / "question_bank.json").exists()
    assert (output_dir / "claude" / "reading_material.json").exists()
    assert (output_dir / "claude" / "concept_cards.json").exists()
    assert (output_dir / "claude" / "validation_errors.json").exists()
    assert (output_dir / "gpt" / "question_bank.json").exists()

    validation_errors = json.loads((output_dir / "claude" / "validation_errors.json").read_text())
    assert validation_errors["question_bank"]


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
        selected_question_id="prefill_decode_baseline",
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


def test_answer_topic_chat_includes_selected_ui_text(monkeypatch, tmp_path):
    controller, _target_repo = make_controller(tmp_path, monkeypatch)
    provider = ChatCapturingProvider()
    monkeypatch.setattr("learning_agent.controller.get_provider", lambda _config: provider)
    controller.initialize()
    controller.generate_learning_assist()

    result = controller.answer_topic_chat(
        message="Explain this.",
        history=[],
        current_step="learn",
        selection_context="QKV projections map hidden states into query, key, and value spaces.",
    )

    assert result["reply"] == "Topic tutor: Explain this."
    assert len(provider.chat_calls) == 1
    call = provider.chat_calls[0]
    assert "Selected UI text for this message:" in call["context"]
    assert "<<<SELECTED_TEXT" in call["context"]
    assert "QKV projections map hidden states into query, key, and value spaces." in call["context"]
    assert "SELECTED_TEXT>>>" in call["context"]


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
            selected_question_id="prefill_decode_baseline",
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

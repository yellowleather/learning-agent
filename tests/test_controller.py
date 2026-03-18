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
    ReflectionRecord,
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
            week=week_spec.number,
            questions=questions,
        )

    def generate_concept_cards(self, week_spec, ledger_state, questions):
        return ConceptCardPayload(
            week=week_spec.number,
            concept_cards=[
                {
                    "concept": "prefill_vs_decode",
                    "explanation": "Prefill processes the prompt, decode emits tokens one at a time.",
                    "why_it_matters": "Latency interpretation depends on the phase.",
                    "common_mistake": "Treating latency as one undifferentiated number.",
                    "quick_check_question": "Which phase grows first as prompt length increases?",
                }
            ],
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
                "roadmap_anchor": {"week": week_spec.number, "concept": "prefill_vs_decode"},
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
                "roadmap_anchor": {"week": week_spec.number, "topic": "latency_metrics"},
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
                "roadmap_anchor": {"week": week_spec.number, "deliverable": "simple_server/benchmark.py"},
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
                "roadmap_anchor": {"week": week_spec.number, "deliverable": "simple_server/server.py"},
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
                "roadmap_anchor": {"week": week_spec.number, "topic": "throughput_tradeoffs"},
                "observation_required": False,
            }
            for index in range(1, 13)
        )
        return ClassifiedQuestionBankPayload(
            week=week_spec.number,
            questions=classified_questions,
        )

    def generate_gate_question(self, week_spec):
        return GateQuestion(
            week=week_spec.number,
            question="Explain prefill vs decode.",
            rubric=["Explain the distinction.", "Mention why decode repeats."],
            context_summary=week_spec.goal,
        )

    def score_gate_answer(self, week_spec, question, answer):
        return GateResult(
            passed=True,
            score_rationale="Answer covered the core distinction.",
            missing_concepts=[],
        )

    def generate_task(self, week_spec, ledger_state):
        return GeneratedTask(
            week=week_spec.number,
            title=week_spec.title,
            objective=week_spec.goal,
            allowed_dirs=week_spec.active_dirs,
            required_files=week_spec.required_files,
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
            week=week_spec.number,
            questions=[
                {
                    "id": "evidence_latency",
                    "type": "evidence_based",
                    "scope": "core",
                    "depth": "baseline",
                    "prompt_text": "What does the latency pattern suggest?",
                    "scoring_rubric": ["Tie the result to prefill cost."],
                    "roadmap_anchor": {"week": week_spec.number, "metric": "latency_p95"},
                    "observation_required": True,
                }
            ],
        )


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
        """# 8-Week Inference Engineering Roadmap

# Week 1 --- Build a Baseline Inference Server

## Goal

Run a model locally and expose it as an API.

## Learn

Concepts:

- prefill vs decode
- latency vs throughput

## Tasks

- Load a small LLM
- expose API

## Deliverables

    simple_server/
        server.py
        benchmark.py

Document:

    docs/baseline_results.md

# Week 2 --- Next Week

## Goal

Do more things.

## Tasks

- Ship a next file

## Deliverables

    benchmarking/
        run.py
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

import json
from pathlib import Path

from learning_agent.config import load_config
from learning_agent.controller import LearningController
from learning_agent.models import GateQuestion, GateResult, GeneratedTask


class FakeProvider:
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

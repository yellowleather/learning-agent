import json

from typer.testing import CliRunner

from learning_agent.cli import app
from learning_agent.models import GateQuestion, GateResult


runner = CliRunner()


class FakeProvider:
    def generate_gate_question(self, week_spec):
        return GateQuestion(
            week=week_spec.number,
            question="Explain token generation.",
            rubric=["Mention tokens.", "Mention iterative decoding."],
            context_summary=week_spec.goal,
        )

    def score_gate_answer(self, week_spec, question, answer):
        return GateResult(
            passed=True,
            score_rationale="Sufficient answer.",
            missing_concepts=[],
        )

    def generate_task(self, week_spec, ledger_state):
        raise AssertionError("Task generation is not exercised in this CLI test.")


def test_init_and_status(monkeypatch, tmp_path):
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

## Deliverables

    simple_server/
        server.py
"""
    )

    config = {
        "provider": "openai",
        "model": "test-model",
        "roadmap_path": "docs/plan.md",
        "target_repo_path": "ai_inference_engineering",
        "state_dir": "state",
    }
    (tmp_path / "learning_agent.config.json").write_text(json.dumps(config))
    (tmp_path / "ai_inference_engineering" / "simple_server").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("learning_agent.controller.get_provider", lambda _config: FakeProvider())

    init_result = runner.invoke(app, ["init"])
    assert init_result.exit_code == 0

    status_result = runner.invoke(app, ["status"])
    assert status_result.exit_code == 0
    assert "Week 1: Build a Baseline Inference Server" in status_result.stdout
    assert "simple_server/server.py" in status_result.stdout

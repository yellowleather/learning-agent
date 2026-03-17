import json

from learning_agent.ui import render_page, run_action


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

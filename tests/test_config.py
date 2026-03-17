import json
import os

from learning_agent.config import load_config


def test_load_config_reads_repo_dotenv(monkeypatch, tmp_path):
    config = {
        "provider": "openai",
        "model": "test-model",
        "roadmap_path": "docs/plan.md",
        "target_repo_path": "ai_inference_engineering",
        "state_dir": "state",
    }
    (tmp_path / "learning_agent.config.json").write_text(json.dumps(config))
    (tmp_path / ".env").write_text("OPENAI_API_KEY=from-dotenv\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    _repo_root, _loaded = load_config()

    assert os.environ["OPENAI_API_KEY"] == "from-dotenv"


def test_dotenv_does_not_override_existing_env(monkeypatch, tmp_path):
    config = {
        "provider": "openai",
        "model": "test-model",
        "roadmap_path": "docs/plan.md",
        "target_repo_path": "ai_inference_engineering",
        "state_dir": "state",
    }
    (tmp_path / "learning_agent.config.json").write_text(json.dumps(config))
    (tmp_path / ".env").write_text("OPENAI_API_KEY=from-dotenv\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "already-set")

    _repo_root, _loaded = load_config()

    assert os.environ["OPENAI_API_KEY"] == "already-set"

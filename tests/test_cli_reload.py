from pathlib import Path

from learning_agent.cli import build_reload_command, snapshot_reload_state


def test_build_reload_command_includes_no_reload_flag():
    command = build_reload_command("127.0.0.1", 4010)

    assert command[-1] == "--no-reload"
    assert "serve" in command
    assert "4010" in command


def test_snapshot_reload_state_watches_code_and_config_not_runtime_state(tmp_path: Path):
    (tmp_path / "learning_agent").mkdir()
    (tmp_path / "learning_agent" / "ui.py").write_text("print('ui')\n")
    (tmp_path / "learning_agent.config.json").write_text("{}\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "progress_ledger.json").write_text("{}\n")
    (tmp_path / "learning_agent" / "__pycache__").mkdir()
    (tmp_path / "learning_agent" / "__pycache__" / "ui.cpython-39.pyc").write_bytes(b"pyc")

    snapshot = snapshot_reload_state(tmp_path)

    assert "learning_agent/ui.py" in snapshot
    assert "learning_agent.config.json" in snapshot
    assert "pyproject.toml" in snapshot
    assert "state/progress_ledger.json" not in snapshot
    assert "learning_agent/__pycache__/ui.cpython-39.pyc" not in snapshot

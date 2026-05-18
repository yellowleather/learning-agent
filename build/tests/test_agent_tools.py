from __future__ import annotations

from pathlib import Path

import pytest

from build.agent.tools import BuildToolContext
from build.models import CommandRun
from engine.errors import EngineError


class _Executor:
    def run(self, argv):
        return CommandRun(
            cmd=" ".join(argv),
            exit_code=0,
            stdout_tail="ok",
            stderr_tail="",
            duration_ms=1,
            truncated=False,
        )


def _tools(tmp_path: Path) -> BuildToolContext:
    target = tmp_path / "target"
    target.mkdir()
    return BuildToolContext(
        target_repo_path=target,
        allowed_dirs=["src"],
        required_metrics=["latency_p95"],
        verification_command="pytest",
        executor=_Executor(),  # type: ignore[arg-type]
    )


def test_write_file_is_limited_to_allowed_dirs(tmp_path: Path) -> None:
    tools = _tools(tmp_path)

    with pytest.raises(EngineError) as excinfo:
        tools.write_file("docs/out.md", "nope")

    assert "outside allowed directories" in str(excinfo.value)


def test_write_file_records_file_diff(tmp_path: Path) -> None:
    tools = _tools(tmp_path)

    tools.write_file("src/app.py", "print('hi')\n")

    touched = tools.files_touched()
    assert touched[0].path == "src/app.py"
    assert touched[0].action == "create"
    assert "+print('hi')" in touched[0].diff


def test_dotfile_names_are_preserved_when_normalizing_paths(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    dotfile = tools.target_repo_path / ".env"
    dotfile.write_text("TOKEN=test\n")

    assert tools.read_file(".env") == "TOKEN=test\n"
    assert tools.read_file("./.env") == "TOKEN=test\n"


def test_allowed_dotfiles_inside_allowed_dirs_keep_their_name(tmp_path: Path) -> None:
    tools = _tools(tmp_path)

    tools.write_file("src/.gitignore", "*.pyc\n")

    assert (tools.target_repo_path / "src" / ".gitignore").read_text() == "*.pyc\n"
    assert not (tools.target_repo_path / "src" / "gitignore").exists()
    assert tools.files_touched()[0].path == "src/.gitignore"


def test_edit_file_replaces_one_match_and_records_modify(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    path = tools.target_repo_path / "src" / "app.py"
    path.parent.mkdir()
    path.write_text("old\nold\n")

    tools.edit_file("src/app.py", "old", "new")

    assert path.read_text() == "new\nold\n"
    touched = tools.files_touched()
    assert touched[0].action == "modify"
    assert "-old" in touched[0].diff
    assert "+new" in touched[0].diff


def test_run_command_enforces_allowlist(tmp_path: Path) -> None:
    tools = _tools(tmp_path)

    with pytest.raises(EngineError):
        tools.run_command(["bash", "-lc", "echo nope"])

    result = tools.run_command(["pytest"])
    assert result.exit_code == 0


def test_record_metric_only_accepts_required_metrics(tmp_path: Path) -> None:
    tools = _tools(tmp_path)

    tools.record_metric("latency_p95", 12.5)

    assert tools.metrics_recorded == {"latency_p95": 12.5}
    with pytest.raises(EngineError):
        tools.record_metric("tokens_per_sec", 1)

"""Unit tests for BuildStage.

Covers the gate-protected task generation, the repo scan that drives
implementation_complete, the task-session accessor, and the four branches of
the Implementation checkpoint card.
"""

import json
from pathlib import Path

import pytest

from coach.config import AppConfig
from curriculum.access import CurriculumAccess
from coach.errors import CoachError
from coach.models import (
    ArtifactState,
    Gates,
    GeneratedTask,
    Ledger,
    MetricsState,
    ProgressState,
)
from verify.models import (
    VerificationRecord,
)
from build.stage import BuildStage
from coach.state import StateStore


class _StubProvider:
    """Returns a fixed GeneratedTask so tests don't need a real LLM."""

    def generate_task(self, week_spec, ledger_state):
        return GeneratedTask(
            week=int(week_spec["number"]),
            title="Stub Task",
            objective="objective",
            allowed_dirs=list(week_spec["active_dirs"]),
            required_files=list(week_spec["required_files"]),
            implementation_steps=["step 1"],
            acceptance_checks=["check 1"],
            verification_expectations=["expect 1"],
            summary="summary",
        )


class _StubCurriculum:
    """CurriculumAccess stand-in that returns a fixed week spec."""

    def __init__(self, week_spec: dict):
        self._week_spec = week_spec

    def current_week(self, _number: int) -> dict:
        return self._week_spec


def _make_stage(
    tmp_path: Path,
    *,
    learning_passed: bool = True,
    required_files: list[str] | None = None,
) -> BuildStage:
    """Build a BuildStage backed by a real StateStore in tmp_path, plus stub
    curriculum + provider so tests are fully hermetic."""
    config = AppConfig(
        provider="openai",
        model="test-model",
        roadmap_path="docs/plan.md",
        target_repo_path="target",
        state_dir="state",
    )
    state = StateStore(tmp_path, config)
    state.ensure_state_dir()
    files = required_files if required_files is not None else ["dir_one/file.py"]
    ledger = Ledger(
        curriculum_metadata={"title": "T", "total_weeks": 1, "target_repo": "target"},
        state=ProgressState(
            current_week=1,
            active_dirs=["dir_one"],
            artifacts=ArtifactState(required_files=files, completed_files=[]),
            gates=Gates(learning_check_passed=learning_passed),
            metrics=MetricsState(required=["latency_p95"], recorded={}),
        ),
    )
    state.save_ledger(ledger)

    week_spec = {
        "number": 1,
        "short_title": "First Week",
        "goal": "Do the thing",
        "active_dirs": ["dir_one"],
        "required_files": files,
        "required_metrics": ["latency_p95"],
    }

    target_repo = tmp_path / "target"
    target_repo.mkdir(parents=True, exist_ok=True)

    return BuildStage(
        state=state,
        curriculum=_StubCurriculum(week_spec),
        provider_factory=lambda: _StubProvider(),
        target_repo_path=target_repo,
    )


def test_generate_task_blocked_until_learning_check_passes(tmp_path: Path) -> None:
    # Generating the brief before the learning gate passes is a precondition
    # error — it would break the pedagogical ordering.
    stage = _make_stage(tmp_path, learning_passed=False)
    with pytest.raises(CoachError) as excinfo:
        stage.generate_task()
    assert "learning check passes" in str(excinfo.value)


def test_generate_task_writes_session_to_disk_when_unlocked(tmp_path: Path) -> None:
    # When the learning gate is open, generate_task persists a TaskSession
    # to current_task.json so it can be read back later.
    stage = _make_stage(tmp_path, learning_passed=True)
    session = stage.generate_task()
    assert session.task.title == "Stub Task"
    assert stage.state.task_path.exists()
    on_disk = json.loads(stage.state.task_path.read_text())
    assert on_disk["task"]["title"] == "Stub Task"


def test_sync_artifacts_marks_files_completed_when_present(tmp_path: Path) -> None:
    # sync_artifacts inspects the target repo and records which required
    # files actually exist on disk.
    stage = _make_stage(
        tmp_path,
        required_files=["dir_one/file_a.py", "dir_one/file_b.py"],
    )
    (stage.target_repo_path / "dir_one").mkdir(parents=True, exist_ok=True)
    (stage.target_repo_path / "dir_one" / "file_a.py").write_text("a")
    ledger = stage.sync_artifacts()
    assert ledger.state.artifacts.completed_files == ["dir_one/file_a.py"]


def test_sync_artifacts_flips_gate_only_when_all_files_present(tmp_path: Path) -> None:
    # The implementation_complete gate must only flip true once every required
    # file is present — partial completion stays false.
    stage = _make_stage(
        tmp_path,
        required_files=["dir_one/file_a.py", "dir_one/file_b.py"],
    )
    (stage.target_repo_path / "dir_one").mkdir(parents=True, exist_ok=True)
    (stage.target_repo_path / "dir_one" / "file_a.py").write_text("a")
    partial = stage.sync_artifacts()
    assert partial.state.gates.implementation_complete is False

    (stage.target_repo_path / "dir_one" / "file_b.py").write_text("b")
    full = stage.sync_artifacts()
    assert full.state.gates.implementation_complete is True


def test_get_task_session_returns_none_when_no_brief_generated(tmp_path: Path) -> None:
    # With no task file on disk, the accessor returns None rather than raising,
    # so the UI can render an empty Build stage.
    stage = _make_stage(tmp_path)
    assert stage.get_task_session() is None


def test_get_task_session_round_trips_after_generation(tmp_path: Path) -> None:
    # After generate_task(), get_task_session() must return the same brief.
    stage = _make_stage(tmp_path)
    generated = stage.generate_task()
    loaded = stage.get_task_session()
    assert loaded is not None
    assert loaded.task.title == generated.task.title


def test_build_checkpoint_not_started_with_no_task_and_no_files(tmp_path: Path) -> None:
    # Before the brief is generated and no files exist yet, the checkpoint
    # reads as not_started so the UI prompts the user to begin.
    stage = _make_stage(tmp_path)
    ledger = stage.state.load_ledger()
    checkpoint = stage.build_checkpoint(ledger)
    assert checkpoint.status == "not_started"


def test_build_checkpoint_in_progress_once_task_generated(tmp_path: Path) -> None:
    # As soon as a brief exists (or any required files are present), the
    # checkpoint flips to in_progress with a fraction in the reason.
    stage = _make_stage(tmp_path)
    stage.generate_task()
    ledger = stage.state.load_ledger()
    checkpoint = stage.build_checkpoint(ledger)
    assert checkpoint.status == "in_progress"
    assert "0/1" in checkpoint.reason


def test_build_checkpoint_failed_when_verification_recorded_as_failed(tmp_path: Path) -> None:
    # A failing verification record takes the implementation checkpoint to
    # failed regardless of file completeness — verification failure dominates.
    stage = _make_stage(tmp_path)
    ledger = stage.state.load_ledger()
    ledger.state.verification = VerificationRecord(passed=False, summary="tests failed")
    ledger.state.gates.verification_passed = False
    stage.state.save_ledger(ledger)
    checkpoint = stage.build_checkpoint(ledger)
    assert checkpoint.status == "failed"


def test_build_checkpoint_passed_when_files_and_verification_both_pass(tmp_path: Path) -> None:
    # Both gates true → checkpoint passes with the canonical reason text.
    stage = _make_stage(tmp_path)
    ledger = stage.state.load_ledger()
    ledger.state.gates.implementation_complete = True
    ledger.state.gates.verification_passed = True
    stage.state.save_ledger(ledger)
    checkpoint = stage.build_checkpoint(ledger)
    assert checkpoint.status == "passed"

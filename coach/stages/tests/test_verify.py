"""Unit tests for VerifyStage.

Covers ledger writes (metric, observation, reflection, verification), the
evidence-required policy question, and the evidence-reliability checkpoint
card across its five distinct rendering branches.
"""

import json
from pathlib import Path

import pytest

from coach.config import AppConfig
from coach.errors import CoachError
from coach.models import (
    ArtifactState,
    Gates,
    Ledger,
    MetricsState,
    ObservationRecord,
    ProgressState,
    ReflectionRecord,
)
from coach.stages.verify import VerifyStage
from coach.state import StateStore


def _make_stage(tmp_path: Path, *, required_metrics: list[str] | None = None) -> VerifyStage:
    """Build a VerifyStage backed by a real StateStore in a tmp dir, with the
    ledger pre-seeded so each test starts from a known good state."""
    config = AppConfig(
        provider="openai",
        model="test-model",
        roadmap_path="docs/plan.md",
        target_repo_path="target",
        state_dir="state",
    )
    state = StateStore(tmp_path, config)
    state.ensure_state_dir()
    ledger = Ledger(
        curriculum_metadata={"title": "T", "total_weeks": 1, "target_repo": "target"},
        state=ProgressState(
            current_week=1,
            active_dirs=["dir_one"],
            artifacts=ArtifactState(required_files=["dir_one/file.py"], completed_files=[]),
            gates=Gates(),
            metrics=MetricsState(
                required=["latency_p95"] if required_metrics is None else required_metrics,
                recorded={},
            ),
        ),
    )
    state.save_ledger(ledger)
    return VerifyStage(state)


def test_record_metric_persists_value_to_ledger(tmp_path: Path) -> None:
    # record_metric writes a single key/value into the recorded-metrics map
    # and returns the updated ledger.
    stage = _make_stage(tmp_path)
    ledger = stage.record_metric("latency_p95", 42.5)
    assert ledger.state.metrics.recorded == {"latency_p95": 42.5}


def test_record_observation_rolls_values_into_metrics_and_sets_reliability(tmp_path: Path) -> None:
    # A "valid" observation backfills the canonical latency/tokens metrics and
    # flips evidence_reliable on. Other reliability values must leave it off.
    stage = _make_stage(tmp_path)
    ledger = stage.record_observation(
        ObservationRecord(
            command="python bench.py",
            artifact_path="docs/baseline.md",
            prompt_tokens=128,
            output_tokens=32,
            latency_p95_ms=12.0,
            tokens_per_sec=80.0,
            reliability="valid",
            notes="ok",
        )
    )
    assert ledger.state.metrics.recorded["latency_p95"] == 12.0
    assert ledger.state.metrics.recorded["tokens_per_sec"] == 80.0
    assert ledger.state.gates.evidence_reliable is True


def test_record_observation_marked_suspect_leaves_evidence_unreliable(tmp_path: Path) -> None:
    # Non-valid reliability must not pass the evidence_reliable gate, even if
    # latency / tokens are present.
    stage = _make_stage(tmp_path)
    ledger = stage.record_observation(
        ObservationRecord(
            command="python bench.py",
            artifact_path="docs/baseline.md",
            prompt_tokens=128,
            output_tokens=32,
            latency_p95_ms=12.0,
            tokens_per_sec=80.0,
            reliability="uncertain",
            notes="weird numbers",
        )
    )
    assert ledger.state.gates.evidence_reliable is False


def test_record_reflection_clears_evidence_gate_when_buggy(tmp_path: Path) -> None:
    # A reflection that flags the run as buggy or untrustworthy must clear
    # evidence_reliable so the week cannot advance on stale confidence.
    stage = _make_stage(tmp_path)
    # First record a valid observation to set the gate.
    stage.record_observation(
        ObservationRecord(
            command="python bench.py",
            artifact_path="docs/baseline.md",
            prompt_tokens=128,
            output_tokens=32,
            latency_p95_ms=12.0,
            tokens_per_sec=80.0,
            reliability="valid",
            notes="ok",
        )
    )
    ledger = stage.record_reflection(
        ReflectionRecord(text="actually it was off", trustworthy=False, buggy=True, next_fix="fix harness")
    )
    assert ledger.state.gates.evidence_reliable is False
    assert ledger.state.reflection is not None


def test_record_verification_requires_task_to_exist(tmp_path: Path) -> None:
    # Verification must always be tied back to a task. Without a current task
    # session on disk, recording verification is a defect.
    stage = _make_stage(tmp_path)
    with pytest.raises(CoachError):
        stage.record_verification(True, "ok")


def test_record_verification_writes_record_and_flips_gate(tmp_path: Path) -> None:
    # With a task session present, verification writes through to the task
    # session and flips the verification_passed gate.
    stage = _make_stage(tmp_path)
    # Drop a minimal task session on disk so the require-task check passes.
    task_session = {
        "task": {
            "week": 1,
            "title": "T",
            "objective": "o",
            "allowed_dirs": ["dir_one"],
            "required_files": ["dir_one/file.py"],
            "implementation_steps": ["step"],
            "acceptance_checks": ["check"],
            "verification_expectations": ["run it"],
            "summary": "s",
        },
        "verification": None,
    }
    stage.state.task_path.write_text(json.dumps(task_session))
    ledger = stage.record_verification(True, "verified")
    assert ledger.state.gates.verification_passed is True
    assert ledger.state.verification is not None
    assert ledger.state.verification.summary == "verified"


def test_requires_evidence_true_when_metrics_required(tmp_path: Path) -> None:
    # Weeks declaring required metrics require evidence.
    stage = _make_stage(tmp_path, required_metrics=["latency_p95"])
    ledger = stage.state.load_ledger()
    assert stage.requires_evidence(ledger) is True


def test_requires_evidence_false_when_no_metrics_required(tmp_path: Path) -> None:
    # Weeks with no required metrics do not require evidence; the checkpoint
    # is skipped at the orchestrator level.
    stage = _make_stage(tmp_path, required_metrics=[])
    ledger = stage.state.load_ledger()
    assert stage.requires_evidence(ledger) is False


def test_build_checkpoint_is_not_started_when_no_records(tmp_path: Path) -> None:
    # Before any observation/reflection is recorded the checkpoint must read
    # as not started.
    stage = _make_stage(tmp_path)
    ledger = stage.state.load_ledger()
    checkpoint = stage.build_checkpoint(ledger, learning_session=None)
    assert checkpoint.status == "not_started"


def test_build_checkpoint_failed_when_observation_marked_suspect(tmp_path: Path) -> None:
    # A non-valid observation reliability surfaces as a failed checkpoint with
    # the reliability label echoed in the reason.
    stage = _make_stage(tmp_path)
    stage.record_observation(
        ObservationRecord(
            command="python bench.py",
            artifact_path="docs/baseline.md",
            prompt_tokens=128,
            output_tokens=32,
            latency_p95_ms=12.0,
            tokens_per_sec=80.0,
            reliability="uncertain",
            notes="weird",
        )
    )
    ledger = stage.state.load_ledger()
    checkpoint = stage.build_checkpoint(ledger, learning_session=None)
    assert checkpoint.status == "failed"
    assert "uncertain" in checkpoint.reason


def test_build_checkpoint_failed_when_reflection_flags_buggy(tmp_path: Path) -> None:
    # A buggy reflection takes the checkpoint to failed regardless of
    # observation reliability.
    stage = _make_stage(tmp_path)
    stage.record_observation(
        ObservationRecord(
            command="python bench.py",
            artifact_path="docs/baseline.md",
            prompt_tokens=128,
            output_tokens=32,
            latency_p95_ms=12.0,
            tokens_per_sec=80.0,
            reliability="valid",
            notes="ok",
        )
    )
    stage.record_reflection(
        ReflectionRecord(text="bug found", trustworthy=False, buggy=True, next_fix="fix")
    )
    ledger = stage.state.load_ledger()
    checkpoint = stage.build_checkpoint(ledger, learning_session=None)
    assert checkpoint.status == "failed"


def test_build_checkpoint_passed_when_observation_valid_and_reflection_present(tmp_path: Path) -> None:
    # A valid observation plus a non-buggy reflection passes the checkpoint.
    stage = _make_stage(tmp_path)
    stage.record_observation(
        ObservationRecord(
            command="python bench.py",
            artifact_path="docs/baseline.md",
            prompt_tokens=128,
            output_tokens=32,
            latency_p95_ms=12.0,
            tokens_per_sec=80.0,
            reliability="valid",
            notes="ok",
        )
    )
    stage.record_reflection(
        ReflectionRecord(text="solid", trustworthy=True, buggy=False, next_fix="")
    )
    ledger = stage.state.load_ledger()
    checkpoint = stage.build_checkpoint(ledger, learning_session=None)
    assert checkpoint.status == "passed"

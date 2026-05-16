"""Unit tests for the BuildAgent-facing state surface.

Covers the new persistence methods on StateStore (build session save/load,
transcript JSONL append/replay), the archive flow used by WeekOrchestrator's
advance_week, and the strict-validation behaviour of the new Pydantic models
(unknown TranscriptEvent kinds are rejected, BuildReport status is enumerated).
"""

from datetime import datetime, timezone
from pathlib import Path

import json
import pytest
from pydantic import ValidationError

from build.models import (
    BuildReport,
    BuildSession,
    CommandRun,
    FileTouched,
    TranscriptEvent,
)
from coach.config import AppConfig
from coach.state import StateStore


def _make_store(tmp_path: Path) -> StateStore:
    """StateStore rooted at tmp_path/state. No ledger pre-seeded — the build
    surface is independent of ledger contents."""
    config = AppConfig(
        provider="openai",
        model="test-model",
        roadmap_path="docs/plan.md",
        target_repo_path="target",
        state_dir="state",
    )
    store = StateStore(tmp_path, config)
    store.ensure_state_dir()
    return store


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_report(status: str = "completed") -> BuildReport:
    return BuildReport(
        status=status,  # type: ignore[arg-type]
        summary="ran the brief end-to-end",
        commands_run=[
            CommandRun(
                cmd="pytest",
                exit_code=0,
                stdout_tail="12 passed",
                stderr_tail="",
                duration_ms=4200,
                truncated=False,
            )
        ],
        files_touched=[
            FileTouched(
                path="model/loader.py",
                action="create",
                diff="+def load(): ...",
                diff_truncated=False,
            )
        ],
        metrics_recorded={"latency_p95": 42.5},
        notes="ran in the project venv",
    )


# -- Models -----------------------------------------------------------------


def test_build_report_rejects_unknown_status() -> None:
    # Status is a Literal enum — any value outside the five canonical states
    # must fail validation so callers can't introduce silent new terminal modes.
    with pytest.raises(ValidationError):
        BuildReport(status="great", summary="x")  # type: ignore[arg-type]


def test_transcript_event_rejects_unknown_kind() -> None:
    # New event kinds must be added to the Literal explicitly; an agent that
    # emits an unrecognised kind should crash loudly rather than silently log it.
    with pytest.raises(ValidationError):
        TranscriptEvent(
            seq=1,
            timestamp_utc=_now_iso(),
            kind="reflection",  # type: ignore[arg-type]
            payload={},
        )


def test_strictmodel_rejects_unknown_fields_on_build_report() -> None:
    # All new models extend StrictModel (extra="forbid"); a stale or hand-edited
    # current_build.json with an unknown field is a defect to surface, not hide.
    with pytest.raises(ValidationError):
        BuildReport.model_validate(
            {"status": "completed", "summary": "x", "unexpected_field": 1}
        )


# -- Build session save / load ---------------------------------------------


def test_save_and_load_build_session_round_trips(tmp_path: Path) -> None:
    # A BuildSession serialised to current_build.json must reload into the same
    # values, including a nested BuildReport with commands and files.
    store = _make_store(tmp_path)
    session = BuildSession(
        week=1,
        started_at_utc=_now_iso(),
        ended_at_utc=_now_iso(),
        duration_seconds=120,
        turn_count=8,
        report=_make_report(),
    )
    store.save_build_session(session)
    loaded = store.load_build_session()
    assert loaded.week == 1
    assert loaded.report is not None
    assert loaded.report.commands_run[0].cmd == "pytest"
    assert loaded.report.files_touched[0].action == "create"
    assert loaded.report.metrics_recorded == {"latency_p95": 42.5}


def test_load_build_session_missing_file_raises(tmp_path: Path) -> None:
    # Loading when no build has been started must surface a CoachError so UI
    # callers can present a clear "no run in progress" state rather than crash.
    store = _make_store(tmp_path)
    with pytest.raises(Exception):
        store.load_build_session()


# -- Transcript append / replay --------------------------------------------


def test_append_transcript_event_creates_jsonl_with_one_line_per_event(tmp_path: Path) -> None:
    # Each appended event becomes one line; the file is plain JSONL (parseable
    # line by line) so debugging tooling can stream-read it without loading the
    # whole transcript into memory.
    store = _make_store(tmp_path)
    e1 = TranscriptEvent(seq=0, timestamp_utc=_now_iso(), kind="thought", payload={"text": "first"})
    e2 = TranscriptEvent(seq=1, timestamp_utc=_now_iso(), kind="tool_call", payload={"name": "run_command"})
    store.append_transcript_event(e1)
    store.append_transcript_event(e2)
    lines = store.build_transcript_path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["seq"] == 0
    assert json.loads(lines[1])["kind"] == "tool_call"


def test_iter_transcript_events_replays_in_order(tmp_path: Path) -> None:
    # Replay returns events in append order so debugging tools can reconstruct
    # the run timeline exactly as the agent saw it.
    store = _make_store(tmp_path)
    for i, kind in enumerate(["thought", "tool_call", "tool_result", "system"]):
        store.append_transcript_event(
            TranscriptEvent(seq=i, timestamp_utc=_now_iso(), kind=kind, payload={"i": i})  # type: ignore[arg-type]
        )
    seqs = [event.seq for event in store.iter_transcript_events()]
    assert seqs == [0, 1, 2, 3]


def test_iter_transcript_events_returns_empty_when_no_file(tmp_path: Path) -> None:
    # If no transcript file exists yet (no build started), iteration yields
    # nothing rather than raising — matches the rest of the StateStore's
    # "missing file is benign for reads of in-flight state" philosophy.
    store = _make_store(tmp_path)
    assert list(store.iter_transcript_events()) == []


# -- Archive flow ----------------------------------------------------------


def test_archive_week_state_moves_all_ephemeral_files(tmp_path: Path) -> None:
    # archive_week_state must relocate every ephemeral file (learning, task,
    # build session, build transcript) into state/archive/week_N/, leaving the
    # active state directory clean.
    store = _make_store(tmp_path)
    store.learning_path.write_text("{}")
    store.task_path.write_text("{}")
    store.build_session_path.write_text("{}")
    store.build_transcript_path.write_text('{"seq": 0}\n')

    archived = store.archive_week_state(3)
    assert archived == store.archive_dir / "week_3"
    for name in (
        "current_learning.json",
        "current_task.json",
        "current_build.json",
        "current_build.transcript.jsonl",
    ):
        assert (archived / name).exists(), f"{name} not archived"
        assert not (store.state_dir / name).exists(), f"{name} still in state dir"


def test_archive_week_state_only_moves_files_that_exist(tmp_path: Path) -> None:
    # A week with no build run, no task, etc. should still produce an empty
    # archive directory rather than raising on missing files.
    store = _make_store(tmp_path)
    store.learning_path.write_text("{}")  # only learning was generated
    archived = store.archive_week_state(1)
    assert (archived / "current_learning.json").exists()
    assert not (archived / "current_build.json").exists()


def test_clear_ephemeral_state_still_deletes_outright(tmp_path: Path) -> None:
    # clear_ephemeral_state remains the "wipe without archiving" path used by
    # reset_pipeline and initialize_ledger — it must NOT create archive dirs.
    store = _make_store(tmp_path)
    store.learning_path.write_text("{}")
    store.task_path.write_text("{}")
    store.build_session_path.write_text("{}")
    store.build_transcript_path.write_text("\n")

    store.clear_ephemeral_state()

    assert not store.learning_path.exists()
    assert not store.task_path.exists()
    assert not store.build_session_path.exists()
    assert not store.build_transcript_path.exists()
    assert not store.archive_dir.exists()

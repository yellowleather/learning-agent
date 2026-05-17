"""Pydantic models owned by the build domain.

These describe what a BuildAgent run produces and how that run is persisted.
The provider's brief shape (`GeneratedTask`, `TaskSession`) stays in
`coach.models` because it predates the agent work and is also consumed by
the verify stage; this module owns only what the agent itself emits.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import Field

from engine._base import StrictModel


class CommandRun(StrictModel):
    """One subprocess invocation by the BuildAgent through the run_command tool.

    Carries the captured *facts* of the run only — exit code and tails of
    stdout/stderr. No judgement about whether the command succeeded relative
    to the brief (that is review_build's job)."""
    cmd: str
    exit_code: int
    stdout_tail: str
    stderr_tail: str
    duration_ms: int
    truncated: bool


class FileTouched(StrictModel):
    """Net effect of the BuildAgent on a single file in the target repo.

    `diff` is a unified diff against the file's contents at agent start,
    truncated to a reasonable cap; `diff_truncated` signals when content
    was clipped."""
    path: str
    action: Literal["create", "modify", "delete"]
    diff: str
    diff_truncated: bool


class BuildReport(StrictModel):
    """Terminal report from a BuildAgent run.

    Pure facts. The agent declares `status`, `summary`, and `notes`; the
    platform fills `commands_run`, `files_touched`, and `metrics_recorded`
    from observed tool calls. No verification verdict — that belongs to
    review_build."""
    status: Literal[
        "completed",
        "gave_up",
        "timed_out",
        "stopped_by_user",
        "errored",
    ]
    summary: str
    commands_run: List[CommandRun] = Field(default_factory=list)
    files_touched: List[FileTouched] = Field(default_factory=list)
    metrics_recorded: Dict[str, float] = Field(default_factory=dict)
    notes: str = ""


class BuildSession(StrictModel):
    """Persisted lifecycle record for a single BuildAgent run.

    Lives in state/current_build.json. The streaming transcript is *not*
    embedded here — it lives in state/current_build.transcript.jsonl so a
    long run doesn't bloat the loaded session payload."""
    week: int
    started_at_utc: str
    ended_at_utc: Optional[str] = None
    duration_seconds: int = 0
    turn_count: int = 0
    report: Optional[BuildReport] = None


class TranscriptEvent(StrictModel):
    """One event line in state/current_build.transcript.jsonl.

    `kind` is strictly enumerated; an agent that emits a new kind will
    fail validation loudly so the enum can be extended deliberately."""
    seq: int
    timestamp_utc: str
    kind: Literal["thought", "tool_call", "tool_result", "tool_error", "system"]
    payload: Dict[str, Any] = Field(default_factory=dict)

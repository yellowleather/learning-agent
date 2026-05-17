"""Pydantic models owned by the verify domain.

These describe the evidence the user (and eventually `review_build`) records
about a built artefact: verification pass/fail, structured observations,
and reflection. Cross-stage models (Ledger, Gates, ProgressState) stay in
coach.models.
"""

from __future__ import annotations

from typing import Literal, Optional

from engine._base import StrictModel


class VerificationRecord(StrictModel):
    passed: bool
    summary: str


class ObservationRecord(StrictModel):
    command: str
    artifact_path: str
    prompt_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_p95_ms: Optional[float] = None
    tokens_per_sec: Optional[float] = None
    notes: str = ""
    reliability: Literal[
        "valid",
        "invalid_due_to_bug",
        "invalid_due_to_bad_measurement",
        "uncertain",
    ] = "uncertain"


class ReflectionRecord(StrictModel):
    text: str
    trustworthy: Optional[bool] = None
    buggy: bool = False
    next_fix: str = ""

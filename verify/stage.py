"""Verify stage.

Owns the ledger writes that capture evidence about a built artifact:
metrics, structured observations, reflections, and verification records.
Also owns the per-stage policy questions (does this week require evidence?)
and the evidence-reliability checkpoint card the orchestrator surfaces.

Stages do not call into other stages. Cross-stage coordination happens via
ledger reads at the orchestrator level.
"""

from __future__ import annotations

from typing import Any

from coach.errors import CoachError
from coach.models import (
    CheckpointState,
    Ledger,
)
from verify.models import (
    ObservationRecord,
    ReflectionRecord,
    VerificationRecord,
)
from learn.models import (
    LearningSession,
)
from coach.state import StateStore


class VerifyStage:
    """Stage controller for evidence + verification ledger updates."""

    def __init__(self, state: StateStore):
        self.state = state

    # -- Ledger writes -----------------------------------------------------

    def record_metric(self, key: str, value: Any) -> Ledger:
        """Write or overwrite a single recorded metric value on the ledger."""
        ledger = self.state.load_ledger()
        ledger.state.metrics.recorded[key] = value
        self.state.save_ledger(ledger)
        return ledger

    def record_observation(self, observation: ObservationRecord) -> Ledger:
        """Persist a structured observation and roll up its values into the
        recorded metrics and the evidence_reliable gate."""
        ledger = self.state.load_ledger()
        ledger.state.observation = observation
        if observation.latency_p95_ms is not None:
            ledger.state.metrics.recorded["latency_p95"] = observation.latency_p95_ms
        if observation.tokens_per_sec is not None:
            ledger.state.metrics.recorded["tokens_per_sec"] = observation.tokens_per_sec
        ledger.state.gates.evidence_reliable = observation.reliability == "valid"
        self.state.save_ledger(ledger)
        return ledger

    def record_reflection(self, reflection: ReflectionRecord) -> Ledger:
        """Persist the user's reflection. A buggy / untrustworthy reflection
        clears the evidence_reliable gate so the week cannot advance on stale
        confidence."""
        ledger = self.state.load_ledger()
        ledger.state.reflection = reflection
        if reflection.buggy or reflection.trustworthy is False:
            ledger.state.gates.evidence_reliable = False
        self.state.save_ledger(ledger)
        return ledger

    def record_verification(self, passed: bool, summary: str) -> Ledger:
        """Record a verification pass/fail. Requires a task session to exist so
        verification is always tied back to a concrete build brief."""
        ledger = self.state.load_ledger()
        if not self.state.task_path.exists():
            raise CoachError("Generate a task before recording verification.")
        record = VerificationRecord(passed=passed, summary=summary)
        self.state.update_task_verification(record)
        ledger.state.verification = record
        ledger.state.gates.verification_passed = passed
        self.state.save_ledger(ledger)
        return ledger

    # -- Policy questions --------------------------------------------------

    def requires_evidence(self, ledger: Ledger) -> bool:
        """A week requires evidence iff it declares one or more required metrics."""
        return bool(ledger.state.metrics.required)

    # -- Checkpoint card ---------------------------------------------------

    def build_checkpoint(
        self, ledger: Ledger, learning_session: LearningSession | None
    ) -> CheckpointState:
        """Render the Evidence Reliability checkpoint for the status payload."""
        if ledger.state.observation is None and ledger.state.reflection is None:
            return CheckpointState(
                id="evidence_reliability",
                title="Evidence Reliability",
                description="Record a structured observation and capture a reflection.",
                status="not_started",
                reason="Observation and reflection are still missing.",
            )
        if ledger.state.observation is not None and ledger.state.observation.reliability != "valid":
            return CheckpointState(
                id="evidence_reliability",
                title="Evidence Reliability",
                description="Record a structured observation and capture a reflection.",
                status="failed",
                reason=f"Observation marked as {ledger.state.observation.reliability}.",
            )
        if ledger.state.reflection is not None and (
            ledger.state.reflection.buggy or ledger.state.reflection.trustworthy is False
        ):
            return CheckpointState(
                id="evidence_reliability",
                title="Evidence Reliability",
                description="Record a structured observation and capture a reflection.",
                status="failed",
                reason="Reflection reports unreliable or buggy evidence.",
            )
        if ledger.state.gates.evidence_reliable and ledger.state.reflection is not None:
            return CheckpointState(
                id="evidence_reliability",
                title="Evidence Reliability",
                description="Record a structured observation and capture a reflection.",
                status="passed",
                reason="Reliable observation recorded and reflection captured.",
            )
        return CheckpointState(
            id="evidence_reliability",
            title="Evidence Reliability",
            description="Record a structured observation and capture a reflection.",
            status="in_progress",
            reason="Evidence is partially recorded but not fully trusted yet.",
        )

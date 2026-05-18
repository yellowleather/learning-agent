"""Build stage.

Owns the current-week implementation brief and the artifact-completion gate.
Today its work is small: generate the structured Junior SWE task brief and
scan the target repo for the brief's required files. This is the module
where the upcoming BuildAgent (multi-turn loop with tools) will land.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from build.agent.runner import BuildAgent
from build.models import BuildSession
from curriculum.access import CurriculumAccess
from engine.errors import EngineError
from engine.models import CheckpointState, Ledger, TaskSession
from engine.providers.base import LLMProvider
from engine.state import StateStore


class BuildStage:
    """Stage controller for build-side artefacts and gates."""

    def __init__(
        self,
        state: StateStore,
        curriculum: CurriculumAccess,
        provider_factory: Callable[[], LLMProvider],
        target_repo_path: Path,
        roadmap_path: Path | None = None,
    ):
        self.state = state
        self.curriculum = curriculum
        self.provider_factory = provider_factory
        self.target_repo_path = target_repo_path
        self.roadmap_path = roadmap_path

    # -- Public actions ----------------------------------------------------

    def generate_task(self) -> TaskSession:
        """Generate the current week's scoped implementation brief.

        Gated on learning_check_passed — the build cannot start until the
        learner has demonstrated conceptual coverage for the week.
        """
        ledger = self.state.load_ledger()
        if not ledger.state.gates.learning_check_passed:
            raise EngineError("Cannot generate a task before the learning check passes.")
        week_spec = self.curriculum.current_week(ledger.state.current_week)
        provider = self.provider_factory()
        task = provider.generate_task(week_spec, ledger.state)
        session = TaskSession(task=task)
        self.state.save_task(session)
        return session

    def sync_artifacts(self) -> Ledger:
        """Scan the target repo for the brief's required files and flip the
        implementation_complete gate iff every required file is present."""
        ledger = self.state.load_ledger()
        completed = []
        for relative_path in ledger.state.artifacts.required_files:
            if (self.target_repo_path / relative_path).exists():
                completed.append(relative_path)
        ledger.state.artifacts.completed_files = completed
        required = ledger.state.artifacts.required_files
        ledger.state.gates.implementation_complete = bool(required) and len(completed) == len(required)
        self.state.save_ledger(ledger)
        return ledger

    def start_agent(self) -> BuildSession:
        """Run the BuildAgent against the current generated task brief."""
        ledger = self.state.load_ledger()
        if not ledger.state.gates.learning_check_passed:
            raise EngineError("Cannot start the build agent before the learning check passes.")
        if not self.state.task_path.exists():
            raise EngineError("Generate a task before starting the build agent.")

        task_session = self.state.load_task()
        session = BuildSession(
            week=task_session.task.week,
            started_at_utc=datetime.now(timezone.utc).isoformat(),
        )
        self.state.save_build_session(session)
        agent = BuildAgent(
            state=self.state,
            provider=self.provider_factory(),
            target_repo_path=self.target_repo_path,
            roadmap_path=self.roadmap_path,
        )
        session = agent.run(
            task=task_session.task,
            required_metrics=ledger.state.metrics.required,
            session=session,
        )
        self.sync_artifacts()
        return session

    def get_task_session(self) -> Optional[TaskSession]:
        """Return the current task session if one has been generated, else None."""
        if not self.state.task_path.exists():
            return None
        return self.state.load_task()

    # -- Checkpoint card ---------------------------------------------------

    def build_checkpoint(self, ledger: Ledger) -> CheckpointState:
        """Render the Implementation checkpoint for the status payload."""
        if ledger.state.gates.implementation_complete and ledger.state.gates.verification_passed:
            return CheckpointState(
                id="implementation",
                title="Implementation",
                description="Complete the required files and verification checks for the active week.",
                status="passed",
                reason="Required files are present and verification passed.",
            )
        if ledger.state.verification is not None and not ledger.state.gates.verification_passed:
            return CheckpointState(
                id="implementation",
                title="Implementation",
                description="Complete the required files and verification checks for the active week.",
                status="failed",
                reason="Verification was recorded as failed.",
            )
        if self.state.task_path.exists() or ledger.state.artifacts.completed_files:
            return CheckpointState(
                id="implementation",
                title="Implementation",
                description="Complete the required files and verification checks for the active week.",
                status="in_progress",
                reason=(
                    f"{len(ledger.state.artifacts.completed_files)}/"
                    f"{len(ledger.state.artifacts.required_files)} required files present."
                ),
            )
        return CheckpointState(
            id="implementation",
            title="Implementation",
            description="Complete the required files and verification checks for the active week.",
            status="not_started",
            reason="Generate the task and start building the required artifacts.",
        )

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, Dict

from coach.config import resolve_repo_path
from curriculum.access import CurriculumAccess
from coach.errors import CoachError
from coach.models import (
    AppConfig,
    CheckpointState,
    CurriculumMetadata,
    Ledger,
    LearningSession,
    ObservationRecord,
    ReflectionRecord,
    TopicChatTurn,
)
from coach.providers.base import LLMProvider
from coach.providers.factory import get_provider
from coach.stages.build import BuildStage
from coach.stages.learn import LearnStage
from coach.stages.verify import VerifyStage
from coach.state import StateStore
from coach.topic_chat import TopicChat


class WeekOrchestrator:
    def __init__(self, repo_root: Path, config: AppConfig):
        self.repo_root = repo_root
        self.config = config
        self.state = StateStore(repo_root, config)
        self.roadmap_path = resolve_repo_path(repo_root, config.roadmap_path)
        self.target_repo_path = resolve_repo_path(repo_root, config.target_repo_path)
        self.curriculum = CurriculumAccess(self.roadmap_path, config.target_repo_path)
        self.topic_chat = TopicChat(provider_factory=self._provider)
        self.verify = VerifyStage(self.state)
        self.build = BuildStage(
            state=self.state,
            curriculum=self.curriculum,
            provider_factory=self._provider,
            target_repo_path=self.target_repo_path,
        )
        self.learn = LearnStage(
            state=self.state,
            curriculum=self.curriculum,
            provider_factory=self._provider,
        )

    def initialize(self) -> Ledger:
        metadata = self.curriculum.metadata()
        week_one = self.curriculum.week_by_number(1)
        return self.state.initialize_ledger(metadata, week_one)

    def curriculum_metadata(self) -> CurriculumMetadata:
        return self.curriculum.metadata()

    def status(self) -> Dict[str, Any]:
        ledger = self.state.load_ledger()
        week_spec = self.curriculum.current_week(ledger.state.current_week)
        blockers = self._approval_blockers(ledger)
        task_exists = self.state.task_path.exists()
        learning_exists = self.state.learning_path.exists()
        task_session = self.build.get_task_session()
        learning_session = self.learn.get_session()
        checkpoints = self._build_checkpoints(ledger, learning_session)
        return {
            "week": int(week_spec["number"]),
            "total_weeks": ledger.curriculum_metadata.total_weeks,
            "title": str(week_spec["short_title"]),
            "goal": str(week_spec["goal"]),
            "key_resources": list(week_spec.get("key_resources", [])),
            "active_dirs": ledger.state.active_dirs,
            "required_files": ledger.state.artifacts.required_files,
            "completed_files": ledger.state.artifacts.completed_files,
            "required_metrics": ledger.state.metrics.required,
            "recorded_metrics": ledger.state.metrics.recorded,
            "gates": ledger.state.gates.model_dump(mode="json"),
            "task_generated": task_exists,
            "learning_generated": learning_exists,
            "verification": ledger.state.verification.model_dump(mode="json") if ledger.state.verification else None,
            "observation": ledger.state.observation.model_dump(mode="json") if ledger.state.observation else None,
            "reflection": ledger.state.reflection.model_dump(mode="json") if ledger.state.reflection else None,
            "evidence_required": self.verify.requires_evidence(ledger),
            "checkpoints": [checkpoint.model_dump(mode="json") for checkpoint in checkpoints],
            "question_progress": self.learn.question_progress(learning_session),
            "can_generate_task": ledger.state.gates.learning_check_passed,
            "can_approve": not blockers,
            "approval_blockers": blockers,
            "task_session": task_session.model_dump(mode="json") if task_session else None,
            "learning_session": learning_session.model_dump(mode="json") if learning_session else None,
        }

    def approve_week(self) -> Ledger:
        ledger = self.state.load_ledger()
        blockers = self._approval_blockers(ledger)
        if blockers:
            joined = "; ".join(blockers)
            raise CoachError(f"Week cannot be approved yet: {joined}.")
        ledger.state.gates.week_approved = True
        self.state.save_ledger(ledger)
        return ledger

    def advance_week(self) -> Ledger:
        ledger = self.state.load_ledger()
        if not ledger.state.gates.week_approved:
            raise CoachError("Approve the current week before advancing.")
        outgoing_week = ledger.state.current_week
        metadata = self.curriculum.metadata()
        next_week = self.curriculum.week_by_number(outgoing_week + 1)
        ledger = Ledger(
            curriculum_metadata=metadata,
            state={
                "current_week": int(next_week["number"]),
                "active_dirs": list(next_week["active_dirs"]),
                "artifacts": {
                    "required_files": list(next_week["required_files"]),
                    "completed_files": [],
                },
                "metrics": {
                    "required": list(next_week["required_metrics"]),
                    "recorded": {},
                },
            },
        )
        # Archive the outgoing week's ephemeral files (learning, task, build,
        # transcript) into state/archive/week_N/ before bumping the ledger,
        # so each week's run record stays available for later debugging.
        self.state.archive_week_state(outgoing_week)
        self.state.save_ledger(ledger)
        return ledger

    def answer_topic_chat(
        self,
        message: str,
        history: list[dict[str, str]] | list[TopicChatTurn],
        current_step: str,
        selected_question_id: str | None = None,
        selection_context: str | None = None,
    ) -> dict[str, Any]:
        inputs = self._topic_chat_inputs()
        return self.topic_chat.answer(
            **inputs,
            message=message,
            history=history,
            current_step=current_step,
            selected_question_id=selected_question_id,
            selection_context=selection_context,
        )

    def stream_topic_chat(
        self,
        message: str,
        history: list[dict[str, str]] | list[TopicChatTurn],
        current_step: str,
        selected_question_id: str | None = None,
        selection_context: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        inputs = self._topic_chat_inputs()
        return self.topic_chat.stream(
            **inputs,
            message=message,
            history=history,
            current_step=current_step,
            selected_question_id=selected_question_id,
            selection_context=selection_context,
        )

    def _topic_chat_inputs(self) -> dict[str, Any]:
        """Gather the cross-stage facts TopicChat needs. Kept here so the chat
        service stays state-loading-free; once stages exist they will own these
        computations and the orchestrator will collect them per-stage."""
        ledger = self.state.load_ledger()
        session = self.learn.get_session()
        return {
            "ledger": ledger,
            "week_spec": self.curriculum.current_week(ledger.state.current_week),
            "learning_session": session,
            "default_step_fallback": self._default_step_for_topic_chat(ledger, session),
            "blockers": self._approval_blockers(ledger),
            "question_progress": self.learn.question_progress(session),
        }

    def _provider(self):
        return get_provider(self.config)

    def _default_step_for_topic_chat(self, ledger: Ledger, learning_session: LearningSession | None) -> str:
        if learning_session is None or not self.learn.required_questions_passed(learning_session):
            return "learn"
        if not ledger.state.gates.implementation_complete:
            return "build"
        if not ledger.state.gates.verification_passed or (
            self.verify.requires_evidence(ledger) and not ledger.state.gates.evidence_reliable
        ):
            return "verify"
        return "approve"

    def _approval_blockers(self, ledger: Ledger) -> list[str]:
        blockers = []
        if not ledger.state.gates.learning_check_passed:
            blockers.append("learning check not passed")
        if not ledger.state.gates.implementation_complete:
            blockers.append("required files are incomplete")
        if not ledger.state.gates.verification_passed:
            blockers.append("verification has not passed")
        missing_metrics = [
            metric for metric in ledger.state.metrics.required if metric not in ledger.state.metrics.recorded
        ]
        if missing_metrics:
            blockers.append(f"missing metrics: {', '.join(missing_metrics)}")
        if self.verify.requires_evidence(ledger):
            if ledger.state.observation is None:
                blockers.append("structured observation has not been recorded")
            if not ledger.state.gates.evidence_reliable:
                blockers.append("evidence is not reliable yet")
            if ledger.state.reflection is None:
                blockers.append("reflection has not been recorded")
        return blockers

    def _build_checkpoints(self, ledger: Ledger, learning_session: LearningSession | None) -> list[CheckpointState]:
        checkpoints = [self.learn.build_checkpoint(ledger, learning_session), self.build.build_checkpoint(ledger)]
        if self.verify.requires_evidence(ledger):
            checkpoints.append(self.verify.build_checkpoint(ledger, learning_session))
        return checkpoints


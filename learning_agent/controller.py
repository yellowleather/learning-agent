from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from learning_agent.config import resolve_repo_path
from learning_agent.curriculum import get_week_spec, load_curriculum
from learning_agent.errors import LearningAgentError
from learning_agent.models import (
    AppConfig,
    CheckpointState,
    EvidenceQuestionPayload,
    GateSession,
    Ledger,
    LearningAssistPayload,
    LearningQuestion,
    LearningSession,
    ObservationRecord,
    QuestionAttempt,
    ReflectionRecord,
    TaskSession,
    VerificationRecord,
    WeekSpec,
)
from learning_agent.providers.factory import get_provider
from learning_agent.state import StateStore


class LearningController:
    def __init__(self, repo_root: Path, config: AppConfig):
        self.repo_root = repo_root
        self.config = config
        self.state = StateStore(repo_root, config)
        self.roadmap_path = resolve_repo_path(repo_root, config.roadmap_path)
        self.target_repo_path = resolve_repo_path(repo_root, config.target_repo_path)

    def initialize(self) -> Ledger:
        metadata, weeks = load_curriculum(self.roadmap_path, self.config.target_repo_path)
        week_one = get_week_spec(weeks, 1)
        return self.state.initialize_ledger(metadata, week_one)

    def status(self) -> Dict[str, Any]:
        ledger = self.state.load_ledger()
        week_spec = self._load_current_week_spec(ledger)
        blockers = self._approval_blockers(ledger)
        gate_exists = self.state.gate_path.exists()
        task_exists = self.state.task_path.exists()
        learning_exists = self.state.learning_path.exists()
        gate_session = self.get_gate_session()
        task_session = self.get_task_session()
        learning_session = self.get_learning_session()
        checkpoints = self._build_checkpoints(ledger, learning_session)
        return {
            "week": week_spec.number,
            "title": week_spec.title,
            "goal": week_spec.goal,
            "active_dirs": ledger.state.active_functional_dirs,
            "learning_assist_enabled": ledger.state.learning_assist_enabled,
            "required_files": ledger.state.artifacts.required_files,
            "completed_files": ledger.state.artifacts.completed_files,
            "required_metrics": ledger.state.metrics.required,
            "recorded_metrics": ledger.state.metrics.recorded,
            "gates": ledger.state.gates.model_dump(mode="json"),
            "gate_asked": gate_exists,
            "task_generated": task_exists,
            "learning_generated": learning_exists,
            "verification": ledger.state.verification.model_dump(mode="json") if ledger.state.verification else None,
            "observation": ledger.state.observation.model_dump(mode="json") if ledger.state.observation else None,
            "reflection": ledger.state.reflection.model_dump(mode="json") if ledger.state.reflection else None,
            "evidence_required": self._requires_evidence(ledger),
            "checkpoints": [checkpoint.model_dump(mode="json") for checkpoint in checkpoints],
            "question_progress": self._question_progress(learning_session),
            "can_generate_task": ledger.state.gates.socratic_check_passed,
            "can_approve": not blockers,
            "approval_blockers": blockers,
            "gate_session": gate_session.model_dump(mode="json") if gate_session else None,
            "task_session": task_session.model_dump(mode="json") if task_session else None,
            "learning_session": learning_session.model_dump(mode="json") if learning_session else None,
        }

    def ask_gate(self):
        ledger = self.state.load_ledger()
        week_spec = self._load_current_week_spec(ledger)
        provider = self._provider()
        question = provider.generate_gate_question(week_spec)
        session = GateSession(prompt=question)
        self.state.save_gate(session)
        return session

    def submit_gate(self, answer: str):
        ledger = self.state.load_ledger()
        week_spec = self._load_current_week_spec(ledger)
        gate_session = self.state.load_gate()
        provider = self._provider()
        result = provider.score_gate_answer(week_spec, gate_session.prompt, answer)
        gate_session.last_answer = answer
        gate_session.result = result
        self.state.save_gate(gate_session)
        ledger.state.gates.socratic_check_passed = result.passed
        self.state.save_ledger(ledger)
        return result

    def set_learning_assist_enabled(self, enabled: bool) -> Ledger:
        ledger = self.state.load_ledger()
        ledger.state.learning_assist_enabled = enabled
        self.state.save_ledger(ledger)
        return ledger

    def generate_learning_assist(self) -> LearningSession:
        ledger = self.state.load_ledger()
        week_spec = self._load_current_week_spec(ledger)
        provider = self._provider()
        payload = provider.generate_learning_assist(week_spec, ledger.state)
        if not isinstance(payload, LearningAssistPayload):
            payload = LearningAssistPayload.model_validate(payload)
        session = LearningSession(
            week=payload.week,
            concept_cards=payload.concept_cards,
            questions=payload.questions,
        )
        self.state.save_learning(session)
        self._sync_learning_progress(ledger, session)
        self.state.save_ledger(ledger)
        return session

    def answer_learning_question(self, question_id: str, answer: str):
        ledger = self.state.load_ledger()
        session = self.state.load_learning()
        question = self._question_by_id(session, question_id)
        if question.observation_required and not self._observation_ready_for_questions(ledger):
            raise LearningAgentError("This question requires a valid observation before it can be answered.")
        week_spec = self._load_current_week_spec(ledger)
        provider = self._provider()
        result = provider.score_learning_question(week_spec, question, answer, ledger.state.observation)
        session.attempts.append(QuestionAttempt(question_id=question_id, answer=answer, result=result))
        self.state.save_learning(session)
        self._sync_learning_progress(ledger, session)
        self.state.save_ledger(ledger)
        return result

    def generate_task(self):
        ledger = self.state.load_ledger()
        if not ledger.state.gates.socratic_check_passed:
            raise LearningAgentError("Cannot generate a task before the concept gate passes.")
        week_spec = self._load_current_week_spec(ledger)
        provider = self._provider()
        task = provider.generate_task(week_spec, ledger.state)
        session = TaskSession(task=task)
        self.state.save_task(session)
        return session

    def sync_artifacts(self) -> Ledger:
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

    def record_metric(self, key: str, value: Any) -> Ledger:
        ledger = self.state.load_ledger()
        ledger.state.metrics.recorded[key] = value
        self.state.save_ledger(ledger)
        return ledger

    def record_observation(self, observation: ObservationRecord) -> Ledger:
        ledger = self.state.load_ledger()
        ledger.state.observation = observation
        if observation.latency_p95_ms is not None:
            ledger.state.metrics.recorded["latency_p95"] = observation.latency_p95_ms
        if observation.tokens_per_sec is not None:
            ledger.state.metrics.recorded["tokens_per_sec"] = observation.tokens_per_sec
        ledger.state.gates.evidence_reliable = observation.reliability == "valid"
        if self.state.learning_path.exists() and observation.reliability == "valid":
            session = self.state.load_learning()
            if not any(question.type == "evidence_based" for question in session.questions):
                week_spec = self._load_current_week_spec(ledger)
                provider = self._provider()
                payload = provider.generate_evidence_questions(week_spec, observation, session)
                if not isinstance(payload, EvidenceQuestionPayload):
                    payload = EvidenceQuestionPayload.model_validate(payload)
                session.questions.extend(payload.questions)
                self.state.save_learning(session)
        self.state.save_ledger(ledger)
        return ledger

    def record_reflection(self, reflection: ReflectionRecord) -> Ledger:
        ledger = self.state.load_ledger()
        ledger.state.reflection = reflection
        if reflection.buggy or reflection.trustworthy is False:
            ledger.state.gates.evidence_reliable = False
        self.state.save_ledger(ledger)
        return ledger

    def record_verification(self, passed: bool, summary: str) -> Ledger:
        ledger = self.state.load_ledger()
        if not self.state.task_path.exists():
            raise LearningAgentError("Generate a task before recording verification.")
        record = VerificationRecord(passed=passed, summary=summary)
        self.state.update_task_verification(record)
        ledger.state.verification = record
        ledger.state.gates.verification_passed = passed
        self.state.save_ledger(ledger)
        return ledger

    def approve_week(self) -> Ledger:
        ledger = self.state.load_ledger()
        blockers = self._approval_blockers(ledger)
        if blockers:
            joined = "; ".join(blockers)
            raise LearningAgentError(f"Week cannot be approved yet: {joined}.")
        ledger.state.gates.week_approved = True
        self.state.save_ledger(ledger)
        return ledger

    def advance_week(self) -> Ledger:
        ledger = self.state.load_ledger()
        if not ledger.state.gates.week_approved:
            raise LearningAgentError("Approve the current week before advancing.")
        metadata, weeks = load_curriculum(self.roadmap_path, self.config.target_repo_path)
        next_week = get_week_spec(weeks, ledger.state.current_week + 1)
        ledger = Ledger(
            curriculum_metadata=metadata,
            state={
                "current_week": next_week.number,
                "active_functional_dirs": next_week.active_dirs,
                "learning_assist_enabled": ledger.state.learning_assist_enabled,
                "artifacts": {
                    "required_files": next_week.required_files,
                    "completed_files": [],
                },
                "metrics": {
                    "required": next_week.required_metrics,
                    "recorded": {},
                },
            },
        )
        self.state.save_ledger(ledger)
        self.state.clear_ephemeral_state()
        return ledger

    def get_gate_session(self):
        if not self.state.gate_path.exists():
            return None
        return self.state.load_gate()

    def get_task_session(self):
        if not self.state.task_path.exists():
            return None
        return self.state.load_task()

    def get_learning_session(self):
        if not self.state.learning_path.exists():
            return None
        return self.state.load_learning()

    def _load_current_week_spec(self, ledger: Ledger) -> WeekSpec:
        _, weeks = load_curriculum(self.roadmap_path, self.config.target_repo_path)
        return get_week_spec(weeks, ledger.state.current_week)

    def _provider(self):
        return get_provider(self.config)

    def _approval_blockers(self, ledger: Ledger) -> list[str]:
        blockers = []
        if not ledger.state.gates.socratic_check_passed:
            blockers.append("concept gate not passed")
        if not ledger.state.gates.implementation_complete:
            blockers.append("required files are incomplete")
        if not ledger.state.gates.verification_passed:
            blockers.append("verification has not passed")
        missing_metrics = [
            metric for metric in ledger.state.metrics.required if metric not in ledger.state.metrics.recorded
        ]
        if missing_metrics:
            blockers.append(f"missing metrics: {', '.join(missing_metrics)}")
        if self._requires_evidence(ledger):
            if ledger.state.observation is None:
                blockers.append("structured observation has not been recorded")
            if not ledger.state.gates.evidence_reliable:
                blockers.append("evidence is not reliable yet")
            if ledger.state.reflection is None:
                blockers.append("reflection has not been recorded")
        return blockers

    def _sync_learning_progress(self, ledger: Ledger, session: LearningSession) -> None:
        if self._required_question_ids(session) and self._required_questions_passed(session):
            ledger.state.gates.socratic_check_passed = True

    def _required_question_ids(self, session: LearningSession) -> list[str]:
        return [
            question.id
            for question in session.questions
            if question.scope == "core" and question.depth == "baseline" and not question.observation_required
        ]

    def _question_progress(self, session: LearningSession | None) -> dict[str, Any]:
        if session is None:
            return {
                "required_total": 0,
                "required_passed": 0,
                "required_pending": 0,
                "evidence_total": 0,
                "evidence_answered": 0,
            }
        latest_attempts = self._latest_attempts(session)
        required_ids = self._required_question_ids(session)
        required_passed = sum(1 for question_id in required_ids if latest_attempts.get(question_id, None) and latest_attempts[question_id].result.passed)
        evidence_ids = [question.id for question in session.questions if question.type == "evidence_based"]
        evidence_answered = sum(1 for question_id in evidence_ids if question_id in latest_attempts)
        return {
            "required_total": len(required_ids),
            "required_passed": required_passed,
            "required_pending": max(len(required_ids) - required_passed, 0),
            "evidence_total": len(evidence_ids),
            "evidence_answered": evidence_answered,
        }

    def _required_questions_passed(self, session: LearningSession) -> bool:
        required_ids = self._required_question_ids(session)
        if not required_ids:
            return False
        latest_attempts = self._latest_attempts(session)
        return all(
            question_id in latest_attempts and latest_attempts[question_id].result.passed for question_id in required_ids
        )

    def _latest_attempts(self, session: LearningSession) -> dict[str, QuestionAttempt]:
        attempts: dict[str, QuestionAttempt] = {}
        for attempt in session.attempts:
            attempts[attempt.question_id] = attempt
        return attempts

    def _question_by_id(self, session: LearningSession, question_id: str) -> LearningQuestion:
        for question in session.questions:
            if question.id == question_id:
                return question
        raise LearningAgentError(f"Question `{question_id}` does not exist in the current learning session.")

    def _requires_evidence(self, ledger: Ledger) -> bool:
        return bool(ledger.state.metrics.required)

    def _observation_ready_for_questions(self, ledger: Ledger) -> bool:
        return ledger.state.observation is not None and ledger.state.gates.evidence_reliable

    def _build_checkpoints(self, ledger: Ledger, learning_session: LearningSession | None) -> list[CheckpointState]:
        checkpoints = [self._build_core_checkpoint(ledger, learning_session), self._build_implementation_checkpoint(ledger)]
        if self._requires_evidence(ledger):
            checkpoints.append(self._build_evidence_checkpoint(ledger, learning_session))
        return checkpoints

    def _build_core_checkpoint(self, ledger: Ledger, learning_session: LearningSession | None) -> CheckpointState:
        if learning_session is None:
            return CheckpointState(
                id="core_concepts",
                title="Core Concepts",
                description="Generate Learning Assist content and pass the required baseline core questions.",
                status="not_started" if not ledger.state.gates.socratic_check_passed else "passed",
                reason="Generate Learning Assist to load concept cards and questions."
                if not ledger.state.gates.socratic_check_passed
                else "Concept coverage satisfied through the concept gate.",
            )

        progress = self._question_progress(learning_session)
        latest_attempts = self._latest_attempts(learning_session)
        required_ids = set(self._required_question_ids(learning_session))
        attempted_required = [question_id for question_id in required_ids if question_id in latest_attempts]
        status = "not_started"
        if self._required_questions_passed(learning_session):
            status = "passed"
        elif attempted_required and any(not latest_attempts[question_id].result.passed for question_id in attempted_required):
            status = "failed"
        elif attempted_required:
            status = "in_progress"
        reason = f"{progress['required_passed']}/{progress['required_total']} required questions passed."
        return CheckpointState(
            id="core_concepts",
            title="Core Concepts",
            description="Cover the current week's core concept and implementation questions.",
            status=status,
            reason=reason,
        )

    def _build_implementation_checkpoint(self, ledger: Ledger) -> CheckpointState:
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
                reason=f"{len(ledger.state.artifacts.completed_files)}/{len(ledger.state.artifacts.required_files)} required files present.",
            )
        return CheckpointState(
            id="implementation",
            title="Implementation",
            description="Complete the required files and verification checks for the active week.",
            status="not_started",
            reason="Generate the task and start building the required artifacts.",
        )

    def _build_evidence_checkpoint(
        self, ledger: Ledger, learning_session: LearningSession | None
    ) -> CheckpointState:
        if ledger.state.observation is None and ledger.state.reflection is None:
            return CheckpointState(
                id="evidence_reliability",
                title="Evidence Reliability",
                description="Record a structured observation, generate evidence questions, and capture a reflection.",
                status="not_started",
                reason="Observation and reflection are still missing.",
            )
        if ledger.state.observation is not None and ledger.state.observation.reliability != "valid":
            return CheckpointState(
                id="evidence_reliability",
                title="Evidence Reliability",
                description="Record a structured observation, generate evidence questions, and capture a reflection.",
                status="failed",
                reason=f"Observation marked as {ledger.state.observation.reliability}.",
            )
        if ledger.state.reflection is not None and (
            ledger.state.reflection.buggy or ledger.state.reflection.trustworthy is False
        ):
            return CheckpointState(
                id="evidence_reliability",
                title="Evidence Reliability",
                description="Record a structured observation, generate evidence questions, and capture a reflection.",
                status="failed",
                reason="Reflection reports unreliable or buggy evidence.",
            )
        if ledger.state.gates.evidence_reliable and ledger.state.reflection is not None:
            reason = "Reliable observation recorded and reflection captured."
            if learning_session is not None:
                progress = self._question_progress(learning_session)
                if progress["evidence_total"]:
                    reason = f"{reason} {progress['evidence_answered']}/{progress['evidence_total']} evidence questions answered."
            return CheckpointState(
                id="evidence_reliability",
                title="Evidence Reliability",
                description="Record a structured observation, generate evidence questions, and capture a reflection.",
                status="passed",
                reason=reason,
            )
        return CheckpointState(
            id="evidence_reliability",
            title="Evidence Reliability",
            description="Record a structured observation, generate evidence questions, and capture a reflection.",
            status="in_progress",
            reason="Evidence is partially recorded but not fully trusted yet.",
        )

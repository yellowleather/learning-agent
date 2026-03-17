from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from learning_agent.config import resolve_repo_path
from learning_agent.curriculum import get_week_spec, load_curriculum
from learning_agent.errors import LearningAgentError
from learning_agent.models import AppConfig, GateSession, Ledger, TaskSession, VerificationRecord, WeekSpec
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
        gate_session = self.get_gate_session()
        task_session = self.get_task_session()
        return {
            "week": week_spec.number,
            "title": week_spec.title,
            "goal": week_spec.goal,
            "active_dirs": ledger.state.active_functional_dirs,
            "required_files": ledger.state.artifacts.required_files,
            "completed_files": ledger.state.artifacts.completed_files,
            "required_metrics": ledger.state.metrics.required,
            "recorded_metrics": ledger.state.metrics.recorded,
            "gates": ledger.state.gates.model_dump(mode="json"),
            "gate_asked": gate_exists,
            "task_generated": task_exists,
            "verification": ledger.state.verification.model_dump(mode="json") if ledger.state.verification else None,
            "can_generate_task": ledger.state.gates.socratic_check_passed,
            "can_approve": not blockers,
            "approval_blockers": blockers,
            "gate_session": gate_session.model_dump(mode="json") if gate_session else None,
            "task_session": task_session.model_dump(mode="json") if task_session else None,
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
        return blockers

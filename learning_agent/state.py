from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Type, TypeVar

from pydantic import BaseModel

from learning_agent.errors import LearningAgentError
from learning_agent.models import AppConfig, GateSession, GeneratedTask, Ledger, TaskSession, VerificationRecord, WeekSpec


ModelT = TypeVar("ModelT", bound=BaseModel)


class StateStore:
    def __init__(self, repo_root: Path, config: AppConfig):
        self.repo_root = repo_root
        self.config = config
        self.state_dir = repo_root / config.state_dir

    @property
    def ledger_path(self) -> Path:
        return self.state_dir / "progress_ledger.json"

    @property
    def gate_path(self) -> Path:
        return self.state_dir / "current_gate.json"

    @property
    def task_path(self) -> Path:
        return self.state_dir / "current_task.json"

    def ensure_state_dir(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def load_ledger(self) -> Ledger:
        return self._load_model(self.ledger_path, Ledger)

    def save_ledger(self, ledger: Ledger) -> None:
        self.ensure_state_dir()
        self._write_json(self.ledger_path, ledger.model_dump(mode="json"))

    def initialize_ledger(self, metadata, week_spec: WeekSpec) -> Ledger:
        if self.ledger_path.exists():
            raise LearningAgentError(f"Ledger already exists at {self.ledger_path}.")
        ledger = Ledger(
            curriculum_metadata=metadata,
            state={
                "current_week": week_spec.number,
                "active_functional_dirs": week_spec.active_dirs,
                "artifacts": {
                    "required_files": week_spec.required_files,
                    "completed_files": [],
                },
                "metrics": {
                    "required": week_spec.required_metrics,
                    "recorded": {},
                },
            },
        )
        self.save_ledger(ledger)
        self.clear_ephemeral_state()
        return ledger

    def load_gate(self) -> GateSession:
        return self._load_model(self.gate_path, GateSession)

    def save_gate(self, gate_session: GateSession) -> None:
        self.ensure_state_dir()
        self._write_json(self.gate_path, gate_session.model_dump(mode="json"))

    def load_task(self) -> TaskSession:
        return self._load_model(self.task_path, TaskSession)

    def save_task(self, task_session: TaskSession) -> None:
        self.ensure_state_dir()
        self._write_json(self.task_path, task_session.model_dump(mode="json"))

    def update_task_verification(self, record: VerificationRecord) -> None:
        task_session = self.load_task()
        task_session.verification = record
        self.save_task(task_session)

    def clear_ephemeral_state(self) -> None:
        for path in (self.gate_path, self.task_path):
            if path.exists():
                path.unlink()

    def _load_model(self, path: Path, model: Type[ModelT]) -> ModelT:
        try:
            raw = json.loads(path.read_text())
        except FileNotFoundError as exc:
            raise LearningAgentError(f"Missing state file at {path}.") from exc
        except json.JSONDecodeError as exc:
            raise LearningAgentError(f"State file {path} is not valid JSON: {exc}") from exc
        return model.model_validate(raw)

    def _write_json(self, path: Path, payload: dict) -> None:
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        temp_path.replace(path)

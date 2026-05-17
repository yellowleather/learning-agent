from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Optional, Type, TypeVar

from pydantic import BaseModel

from build.models import BuildSession, TranscriptEvent
from engine.errors import EngineError
from engine.models import (
    AppConfig,
    GeneratedTask,
    Ledger,
    TaskSession,
)
from verify.models import (
    VerificationRecord,
)
from learn.models import (
    LearningSession,
)


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
    def task_path(self) -> Path:
        return self.state_dir / "current_task.json"

    @property
    def learning_path(self) -> Path:
        return self.state_dir / "current_learning.json"

    @property
    def build_session_path(self) -> Path:
        return self.state_dir / "current_build.json"

    @property
    def build_transcript_path(self) -> Path:
        return self.state_dir / "current_build.transcript.jsonl"

    @property
    def archive_dir(self) -> Path:
        return self.state_dir / "archive"

    def ensure_state_dir(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def load_ledger(self) -> Ledger:
        return self._load_model(self.ledger_path, Ledger)

    def save_ledger(self, ledger: Ledger) -> None:
        self.ensure_state_dir()
        self._write_json(self.ledger_path, ledger.model_dump(mode="json"))

    def initialize_ledger(self, metadata, week: dict) -> Ledger:
        if self.ledger_path.exists():
            raise EngineError(f"Ledger already exists at {self.ledger_path}.")
        ledger = Ledger(
            curriculum_metadata=metadata,
            state={
                "current_week": int(week["number"]),
                "active_dirs": list(week["active_dirs"]),
                "artifacts": {
                    "required_files": list(week["required_files"]),
                    "completed_files": [],
                },
                "metrics": {
                    "required": list(week["required_metrics"]),
                    "recorded": {},
                },
            },
        )
        self.save_ledger(ledger)
        self.clear_ephemeral_state()
        return ledger

    def load_task(self) -> TaskSession:
        return self._load_model(self.task_path, TaskSession)

    def save_task(self, task_session: TaskSession) -> None:
        self.ensure_state_dir()
        self._write_json(self.task_path, task_session.model_dump(mode="json"))

    def load_learning(self) -> LearningSession:
        return self._load_model(self.learning_path, LearningSession)

    def save_learning(self, learning_session: LearningSession) -> None:
        self.ensure_state_dir()
        self._write_json(self.learning_path, learning_session.model_dump(mode="json"))

    def update_task_verification(self, record: VerificationRecord) -> None:
        task_session = self.load_task()
        task_session.verification = record
        self.save_task(task_session)

    def load_build_session(self) -> BuildSession:
        return self._load_model(self.build_session_path, BuildSession)

    def save_build_session(self, session: BuildSession) -> None:
        self.ensure_state_dir()
        self._write_json(self.build_session_path, session.model_dump(mode="json"))

    def append_transcript_event(self, event: TranscriptEvent) -> None:
        """Append one event to the build transcript JSONL file.

        Single-writer (the agent loop). Each event is one line of JSON;
        appending avoids rewriting a growing file every iteration."""
        self.ensure_state_dir()
        line = json.dumps(event.model_dump(mode="json"), sort_keys=True)
        with self.build_transcript_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def iter_transcript_events(self) -> Iterator[TranscriptEvent]:
        """Replay the persisted transcript event by event.

        Used by debugging tools / archive readers; the live agent loop does
        not read its own transcript back."""
        if not self.build_transcript_path.exists():
            return
        with self.build_transcript_path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise EngineError(
                        f"Transcript line is not valid JSON in {self.build_transcript_path}: {exc}"
                    ) from exc
                yield TranscriptEvent.model_validate(payload)

    @property
    def _ephemeral_paths(self) -> tuple[Path, ...]:
        """The set of files cleared on reset and moved on archive."""
        return (
            self.task_path,
            self.learning_path,
            self.build_session_path,
            self.build_transcript_path,
        )

    def clear_ephemeral_state(self) -> None:
        """Delete the current week's ephemeral working files outright.

        Used when re-running the same week from scratch (LearnStage.reset_pipeline)
        and on initialize_ledger. For week advancement, use archive_week_state."""
        for path in self._ephemeral_paths:
            if path.exists():
                path.unlink()

    def archive_week_state(self, week_number: int) -> Path:
        """Move the outgoing week's ephemeral files into state/archive/week_N/.

        Used by advance_week so build sessions, transcripts, learning sessions,
        and task sessions remain available for later debugging and review.
        Returns the archive directory path for the week."""
        target = self.archive_dir / f"week_{int(week_number)}"
        target.mkdir(parents=True, exist_ok=True)
        for path in self._ephemeral_paths:
            if path.exists():
                path.rename(target / path.name)
        return target

    def _load_model(self, path: Path, model: Type[ModelT]) -> ModelT:
        try:
            raw = json.loads(path.read_text())
        except FileNotFoundError as exc:
            raise EngineError(f"Missing state file at {path}.") from exc
        except json.JSONDecodeError as exc:
            raise EngineError(f"State file {path} is not valid JSON: {exc}") from exc
        return model.model_validate(raw)

    def _write_json(self, path: Path, payload: dict) -> None:
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        temp_path.replace(path)

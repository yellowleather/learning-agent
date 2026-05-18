from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from build.models import CommandRun
from engine.errors import EngineError


DEFAULT_COMMAND_TIMEOUT_SECONDS = 300
DEFAULT_OUTPUT_TAIL_CHARS = 8000


@dataclass(frozen=True)
class LocalExecutor:
    target_repo_path: Path
    command_timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS
    output_tail_chars: int = DEFAULT_OUTPUT_TAIL_CHARS

    def run(self, argv: list[str]) -> CommandRun:
        if not argv or not all(isinstance(part, str) and part for part in argv):
            raise EngineError("Command must be a non-empty argv list of strings.")

        display_cmd = " ".join(argv)
        run_argv = [sys.executable, *argv[1:]] if argv[0] == "python" else argv
        started = time.monotonic()
        try:
            completed = subprocess.run(
                run_argv,
                cwd=str(self.target_repo_path),
                capture_output=True,
                text=True,
                timeout=self.command_timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise EngineError(f"Command executable not found: {argv[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            stdout = self._tail(exc.stdout or "")
            stderr = self._tail(exc.stderr or "")
            return CommandRun(
                cmd=display_cmd,
                exit_code=124,
                stdout_tail=stdout,
                stderr_tail=stderr or f"Command timed out after {self.command_timeout_seconds}s.",
                duration_ms=duration_ms,
                truncated=self._was_truncated(exc.stdout or "") or self._was_truncated(exc.stderr or ""),
            )

        duration_ms = int((time.monotonic() - started) * 1000)
        return CommandRun(
            cmd=display_cmd,
            exit_code=int(completed.returncode),
            stdout_tail=self._tail(completed.stdout),
            stderr_tail=self._tail(completed.stderr),
            duration_ms=duration_ms,
            truncated=self._was_truncated(completed.stdout) or self._was_truncated(completed.stderr),
        )

    def _tail(self, value: str | bytes) -> str:
        text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
        if len(text) <= self.output_tail_chars:
            return text
        return text[-self.output_tail_chars :]

    def _was_truncated(self, value: str | bytes) -> bool:
        text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
        return len(text) > self.output_tail_chars

from __future__ import annotations

import difflib
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from build.agent.executor import LocalExecutor
from build.models import CommandRun, FileTouched
from engine.errors import EngineError


DIFF_TAIL_CHARS = 12000


def tool_schemas() -> list[dict[str, Any]]:
    return [
        _schema("read_file", "Read a file under the target repository.", {"path": {"type": "string"}}, ["path"]),
        _schema("list_dir", "List a directory under the target repository.", {"path": {"type": "string"}}, ["path"]),
        _schema(
            "write_file",
            "Create or overwrite a file under an allowed directory.",
            {"path": {"type": "string"}, "content": {"type": "string"}},
            ["path", "content"],
        ),
        _schema(
            "edit_file",
            "Replace existing text in a file under an allowed directory.",
            {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
            ["path", "old", "new"],
        ),
        _schema(
            "run_command",
            "Run an allowlisted argv-list command.",
            {"cmd": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
            ["cmd"],
        ),
        _schema(
            "record_metric",
            "Record a required numeric metric.",
            {"key": {"type": "string"}, "value": {"type": "number"}},
            ["key", "value"],
        ),
        _schema(
            "done",
            "Finish the run.",
            {
                "status": {"type": "string", "enum": ["completed", "gave_up"]},
                "summary": {"type": "string"},
                "notes": {"type": "string"},
            },
            ["status", "summary"],
        ),
    ]


def _schema(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


@dataclass
class BuildToolContext:
    target_repo_path: Path
    allowed_dirs: list[str]
    required_metrics: list[str]
    verification_command: str
    roadmap_path: Path | None = None
    executor: LocalExecutor | None = None
    commands_run: list[CommandRun] = field(default_factory=list)
    metrics_recorded: dict[str, float] = field(default_factory=dict)
    done_payload: dict[str, str] | None = None
    _original_files: dict[str, str | None] = field(default_factory=dict)
    _touched_paths: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.target_repo_path = self.target_repo_path.resolve()
        self.allowed_dirs = [item.strip().strip("/") for item in self.allowed_dirs if item.strip()]
        self.executor = self.executor or LocalExecutor(self.target_repo_path)

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "read_file":
            return {"content": self.read_file(str(arguments.get("path") or ""))}
        if name == "list_dir":
            return {"entries": self.list_dir(str(arguments.get("path") or ""))}
        if name == "write_file":
            self.write_file(str(arguments.get("path") or ""), str(arguments.get("content") or ""))
            return {"ok": True}
        if name == "edit_file":
            self.edit_file(
                str(arguments.get("path") or ""),
                str(arguments.get("old") or ""),
                str(arguments.get("new") or ""),
            )
            return {"ok": True}
        if name == "run_command":
            return {"command": self.run_command(arguments.get("cmd")).model_dump(mode="json")}
        if name == "record_metric":
            self.record_metric(str(arguments.get("key") or ""), arguments.get("value"))
            return {"ok": True}
        if name == "done":
            self.done(
                str(arguments.get("status") or ""),
                str(arguments.get("summary") or ""),
                str(arguments.get("notes") or ""),
            )
            return {"ok": True}
        raise EngineError(f"Unknown build tool: {name}")

    def read_file(self, path: str) -> str:
        resolved = self._resolve_repo_path(path)
        if self.roadmap_path is not None and resolved == self.roadmap_path.resolve():
            raise EngineError("The roadmap file is not available to the build agent.")
        if not resolved.is_file():
            raise EngineError(f"File does not exist: {path}")
        return resolved.read_text(encoding="utf-8")

    def list_dir(self, path: str) -> list[str]:
        resolved = self._resolve_repo_path(path)
        if not resolved.is_dir():
            raise EngineError(f"Directory does not exist: {path}")
        return sorted(child.name + ("/" if child.is_dir() else "") for child in resolved.iterdir())

    def write_file(self, path: str, content: str) -> None:
        resolved = self._resolve_allowed_path(path)
        self._remember_original(path, resolved)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        self._touched_paths.add(self._normalize_relative(path))

    def edit_file(self, path: str, old: str, new: str) -> None:
        if not old:
            raise EngineError("edit_file requires a non-empty old string.")
        resolved = self._resolve_allowed_path(path)
        if not resolved.is_file():
            raise EngineError(f"File does not exist: {path}")
        content = resolved.read_text(encoding="utf-8")
        if old not in content:
            raise EngineError(f"Could not find requested text in {path}.")
        self._remember_original(path, resolved)
        resolved.write_text(content.replace(old, new, 1), encoding="utf-8")
        self._touched_paths.add(self._normalize_relative(path))

    def run_command(self, cmd: Any) -> CommandRun:
        argv = self._coerce_argv(cmd)
        self._assert_command_allowed(argv)
        assert self.executor is not None
        result = self.executor.run(argv)
        self.commands_run.append(result)
        return result

    def record_metric(self, key: str, value: Any) -> None:
        if key not in self.required_metrics:
            raise EngineError(f"Metric is not required for this week: {key}")
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise EngineError("Metric value must be numeric.") from exc
        self.metrics_recorded[key] = parsed

    def done(self, status: str, summary: str, notes: str = "") -> None:
        if status not in {"completed", "gave_up"}:
            raise EngineError("done status must be completed or gave_up.")
        if not summary.strip():
            raise EngineError("done summary cannot be empty.")
        self.done_payload = {"status": status, "summary": summary.strip(), "notes": notes.strip()}

    def files_touched(self) -> list[FileTouched]:
        records = []
        for relative in sorted(self._touched_paths):
            path = self.target_repo_path / relative
            before = self._original_files.get(relative)
            after = path.read_text(encoding="utf-8") if path.exists() else None
            if before is None and after is not None:
                action = "create"
            elif before is not None and after is None:
                action = "delete"
            else:
                action = "modify"
            diff = self._diff(relative, before or "", after or "")
            truncated = len(diff) > DIFF_TAIL_CHARS
            records.append(
                FileTouched(
                    path=relative,
                    action=action,
                    diff=diff[-DIFF_TAIL_CHARS:] if truncated else diff,
                    diff_truncated=truncated,
                )
            )
        return records

    def _resolve_repo_path(self, path: str) -> Path:
        relative = self._normalize_relative(path)
        resolved = (self.target_repo_path / relative).resolve()
        if resolved != self.target_repo_path and self.target_repo_path not in resolved.parents:
            raise EngineError(f"Path escapes target repository: {path}")
        return resolved

    def _resolve_allowed_path(self, path: str) -> Path:
        relative = self._normalize_relative(path)
        if not self._is_allowed(relative):
            raise EngineError(f"Path is outside allowed directories: {path}")
        return self._resolve_repo_path(relative)

    def _is_allowed(self, relative: str) -> bool:
        if not self.allowed_dirs:
            return False
        return any(relative == allowed or relative.startswith(f"{allowed}/") for allowed in self.allowed_dirs)

    def _normalize_relative(self, path: str) -> str:
        if not path.strip():
            raise EngineError("Path cannot be empty.")
        candidate = Path(path)
        if candidate.is_absolute():
            raise EngineError(f"Absolute paths are not allowed: {path}")
        parts = [part for part in candidate.parts if part != "."]
        if not parts or ".." in parts:
            raise EngineError(f"Invalid relative path: {path}")
        return Path(*parts).as_posix()

    def _remember_original(self, relative: str, resolved: Path) -> None:
        normalized = self._normalize_relative(relative)
        if normalized in self._original_files:
            return
        self._original_files[normalized] = resolved.read_text(encoding="utf-8") if resolved.exists() else None

    def _diff(self, relative: str, before: str, after: str) -> str:
        return "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{relative}",
                tofile=f"b/{relative}",
            )
        )

    def _coerce_argv(self, cmd: Any) -> list[str]:
        if isinstance(cmd, str):
            argv = shlex.split(cmd)
        elif isinstance(cmd, list):
            argv = [str(part) for part in cmd]
        else:
            raise EngineError("Command must be an argv list.")
        if not argv:
            raise EngineError("Command cannot be empty.")
        return argv

    def _assert_command_allowed(self, argv: list[str]) -> None:
        verification_argv = shlex.split(self.verification_command)
        if argv == verification_argv:
            return
        if argv[0] in {"pytest", "python", "uv"}:
            return
        raise EngineError(f"Command is not allowlisted: {argv[0]}")

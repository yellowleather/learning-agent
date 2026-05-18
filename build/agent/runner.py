from __future__ import annotations

from pathlib import Path
from typing import Any

from build.agent.loop import BuildAgentLoop
from build.agent.tools import BuildToolContext
from build.models import BuildSession
from build.prompts import load_prompt, render_prompt
from engine.models import GeneratedTask
from engine.providers.base import LLMProvider
from engine.state import StateStore


DEFAULT_WALL_CLOCK_SECONDS = 30 * 60
DEFAULT_MAX_TURNS = 80


class BuildAgent:
    def __init__(
        self,
        *,
        state: StateStore,
        provider: LLMProvider,
        target_repo_path: Path,
        roadmap_path: Path | None = None,
        wall_clock_seconds: int = DEFAULT_WALL_CLOCK_SECONDS,
        max_turns: int = DEFAULT_MAX_TURNS,
    ):
        self.state = state
        self.provider = provider
        self.target_repo_path = target_repo_path
        self.roadmap_path = roadmap_path
        self.wall_clock_seconds = wall_clock_seconds
        self.max_turns = max_turns

    def run(
        self,
        *,
        task: GeneratedTask,
        required_metrics: list[str],
        session: BuildSession,
    ) -> BuildSession:
        tools = BuildToolContext(
            target_repo_path=self.target_repo_path,
            allowed_dirs=task.allowed_dirs,
            required_metrics=required_metrics,
            verification_command=task.verification_command,
            roadmap_path=self.roadmap_path,
        )
        system_prompt = load_prompt("build_agent_system.md")
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": self._render_user_prompt(task, required_metrics),
            }
        ]
        loop = BuildAgentLoop(
            state=self.state,
            provider=self.provider,
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
            wall_clock_seconds=self.wall_clock_seconds,
            max_turns=self.max_turns,
        )
        return loop.run(session)

    def _render_user_prompt(self, task: GeneratedTask, required_metrics: list[str]) -> str:
        return render_prompt(
            "build_agent_user.md",
            {
                "WEEK": str(task.week),
                "TITLE": task.title,
                "OBJECTIVE": task.objective,
                "ALLOWED_DIRS": ", ".join(task.allowed_dirs) or "(none)",
                "REQUIRED_FILES": ", ".join(task.required_files) or "(none)",
                "IMPLEMENTATION_STEPS": _numbered(task.implementation_steps),
                "ACCEPTANCE_CHECKS": _bullets(task.acceptance_checks),
                "VERIFICATION_EXPECTATIONS": _bullets(task.verification_expectations),
                "REQUIRED_METRICS": ", ".join(required_metrics) or "(none)",
                "VERIFICATION_COMMAND": task.verification_command,
            },
        )


def _numbered(items: list[str]) -> str:
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1)) or "1. (none)"


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) or "- (none)"

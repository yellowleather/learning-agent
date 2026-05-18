from __future__ import annotations

from pathlib import Path

from build.agent.runner import BuildAgent
from build.models import BuildSession
from engine.config import AppConfig
from engine.models import GeneratedTask
from engine.providers.base import AgentToolCall, AgentTurnResult
from engine.state import StateStore


class _Provider:
    def __init__(self):
        self.turns = 0

    def run_agent_turn(self, system_prompt, messages, tools, deep_reasoning=True):
        del system_prompt, messages, tools, deep_reasoning
        self.turns += 1
        if self.turns == 1:
            return AgentTurnResult(
                text="I will create the file and run verification.",
                tool_calls=[
                    AgentToolCall(
                        id="call-1",
                        name="write_file",
                        arguments={"path": "src/app.py", "content": "print('ok')\n"},
                    ),
                    AgentToolCall(
                        id="call-2",
                        name="run_command",
                        arguments={"cmd": ["python", "--version"]},
                    ),
                    AgentToolCall(
                        id="call-3",
                        name="record_metric",
                        arguments={"key": "latency_p95", "value": 3.2},
                    ),
                    AgentToolCall(
                        id="call-4",
                        name="done",
                        arguments={"status": "completed", "summary": "Built the week.", "notes": ""},
                    ),
                ],
            )
        raise AssertionError("BuildAgent should have stopped after done.")


def _store(tmp_path: Path) -> StateStore:
    config = AppConfig(
        provider="openai",
        model="test",
        roadmap_path="docs/plan.md",
        target_repo_path="target",
        state_dir="state",
    )
    store = StateStore(tmp_path, config)
    store.ensure_state_dir()
    return store


def _task() -> GeneratedTask:
    return GeneratedTask(
        week=1,
        title="Build a thing",
        objective="Make a tiny app.",
        allowed_dirs=["src"],
        required_files=["src/app.py"],
        implementation_steps=["Create the app."],
        acceptance_checks=["pytest passes."],
        verification_expectations=["pytest exits 0."],
        verification_command="python --version",
        summary="Build a tiny app.",
    )


def test_build_agent_writes_session_transcript_and_report(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    store = _store(tmp_path)

    initial_session = BuildSession(week=1, started_at_utc="2026-05-18T00:00:00+00:00")
    agent = BuildAgent(
        state=store,
        provider=_Provider(),  # type: ignore[arg-type]
        target_repo_path=target,
        wall_clock_seconds=30,
    )

    result = agent.run(task=_task(), required_metrics=["latency_p95"], session=initial_session)

    assert result.report is not None
    assert result.report.status == "completed"
    assert result.report.commands_run[0].cmd == "python --version"
    assert result.report.metrics_recorded == {"latency_p95": 3.2}
    assert result.report.files_touched[0].path == "src/app.py"
    assert (target / "src" / "app.py").exists()
    assert store.build_session_path.exists()

    events = list(store.iter_transcript_events())
    assert [event.kind for event in events] == [
        "thought",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
    ]
    assert events[0].payload["text"] == "I will create the file and run verification."
    assert events[1].payload["name"] == "write_file"
    assert events[3].payload["name"] == "run_command"
    assert events[5].payload["name"] == "record_metric"
    assert events[7].payload["name"] == "done"

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

from learning_agent.config import load_config, load_dotenv, locate_repo_root
from learning_agent.controller import LearningController
from learning_agent.curriculum_bootstrap import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_CURRICULUM_PROMPT_PATH,
    bootstrap_curriculum_workspace,
)
from learning_agent.errors import LearningAgentError
from learning_agent.models import ObservationRecord, ReflectionRecord
from learning_agent.providers.anthropic_provider import AnthropicProvider
from learning_agent.providers.openai_provider import OpenAIProvider
from learning_agent.ui import DEFAULT_UI_HOST, DEFAULT_UI_PORT, serve_ui


app = typer.Typer(help="Guided single-controller learning agent.")
learn_app = typer.Typer(help="Run the Learning Assist flow.")
task_app = typer.Typer(help="Generate the Junior SWE task.")
record_app = typer.Typer(help="Record execution progress.")
curriculum_app = typer.Typer(help="Generate standalone curriculum workspaces.")

app.add_typer(learn_app, name="learn")
app.add_typer(task_app, name="task")
app.add_typer(record_app, name="record")
app.add_typer(curriculum_app, name="curriculum")

RELOAD_POLL_INTERVAL_SECONDS = 0.75
RELOAD_WATCH_TARGETS = (
    "learning_agent",
    "learning_agent.config.json",
    "pyproject.toml",
    ".env",
)


def get_controller() -> LearningController:
    repo_root, config = load_config()
    return LearningController(repo_root, config)


def exit_on_error(exc: LearningAgentError) -> None:
    typer.secho(str(exc), fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def iter_reload_files(repo_root: Path):
    for relative in RELOAD_WATCH_TARGETS:
        path = repo_root / relative
        if not path.exists():
            continue
        if path.is_file():
            yield path
            continue
        for file_path in path.rglob("*"):
            if not file_path.is_file():
                continue
            if "__pycache__" in file_path.parts:
                continue
            yield file_path


def snapshot_reload_state(repo_root: Path) -> dict[str, int]:
    snapshot = {}
    for file_path in iter_reload_files(repo_root):
        snapshot[str(file_path.relative_to(repo_root))] = file_path.stat().st_mtime_ns
    return snapshot


def build_reload_command(host: str, port: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "learning_agent",
        "serve",
        "--host",
        host,
        "--port",
        str(port),
        "--no-reload",
    ]


def stop_child_process(child: subprocess.Popen) -> None:
    if child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=3)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=3)


def serve_with_reload(repo_root: Path, host: str, port: int) -> None:
    command = build_reload_command(host, port)
    typer.echo(f"Starting UI server with reload on http://{host}:{port}")
    child = subprocess.Popen(command, cwd=str(repo_root))
    watch_state = snapshot_reload_state(repo_root)

    try:
        while True:
            time.sleep(RELOAD_POLL_INTERVAL_SECONDS)
            if child.poll() is not None:
                raise typer.Exit(code=child.returncode or 0)

            current_state = snapshot_reload_state(repo_root)
            if current_state == watch_state:
                continue

            typer.echo("Detected code/config changes. Reloading UI server...")
            stop_child_process(child)
            child = subprocess.Popen(command, cwd=str(repo_root))
            watch_state = current_state
    except KeyboardInterrupt:
        stop_child_process(child)
    except typer.Exit:
        stop_child_process(child)
        raise


@app.command("init")
def init_command() -> None:
    try:
        controller = get_controller()
        ledger = controller.initialize()
        typer.echo(f"Initialized Week {ledger.state.current_week} in {controller.state.ledger_path}.")
    except LearningAgentError as exc:
        exit_on_error(exc)


@curriculum_app.command("bootstrap")
def curriculum_bootstrap_command(
    prompt_path: str = typer.Option(
        DEFAULT_CURRICULUM_PROMPT_PATH,
        help="Prompt asset path, relative to the source repo root unless absolute.",
    ),
    output_repo_path: str = typer.Option(
        ...,
        help="Output repository path, relative to the source repo root unless absolute.",
    ),
    model: str = typer.Option(
        DEFAULT_ANTHROPIC_MODEL,
        help="Anthropic model name to use for roadmap generation.",
    ),
) -> None:
    try:
        repo_root = locate_repo_root()
        load_dotenv(repo_root / ".env")
        resolved_prompt_path = Path(prompt_path)
        if not resolved_prompt_path.is_absolute():
            resolved_prompt_path = repo_root / resolved_prompt_path
        resolved_output_repo_path = Path(output_repo_path)
        result = bootstrap_curriculum_workspace(
            repo_root=repo_root,
            prompt_path=resolved_prompt_path,
            output_repo_path=resolved_output_repo_path,
            model=model,
        )
        typer.echo(f"Created workspace: {result.workspace_root}")
        typer.echo(f"Plan: {result.plan_path}")
        typer.echo(f"Prompt: {result.prompt_path}")
        typer.echo(f"Model: {result.model}")
    except LearningAgentError as exc:
        exit_on_error(exc)


@app.command("status")
def status_command() -> None:
    try:
        controller = get_controller()
        status = controller.status()
        typer.echo(f"Week {status['week']}: {status['title']}")
        typer.echo(f"Goal: {status['goal']}")
        typer.echo(f"Active dirs: {', '.join(status['active_dirs']) or '(none)'}")
        typer.echo(f"Required files: {', '.join(status['required_files']) or '(none)'}")
        typer.echo(f"Completed files: {', '.join(status['completed_files']) or '(none)'}")
        typer.echo(f"Required metrics: {', '.join(status['required_metrics']) or '(none)'}")
        if status["recorded_metrics"]:
            typer.echo(f"Recorded metrics: {json.dumps(status['recorded_metrics'], sort_keys=True)}")
        typer.echo(f"Gates: {json.dumps(status['gates'], sort_keys=True)}")
        progress = status["question_progress"]
        typer.echo(
            "Question coverage: "
            f"{progress['required_passed']}/{progress['required_total']} required questions passed"
        )
        typer.echo(f"Learning generated: {'yes' if status['learning_generated'] else 'no'}")
        typer.echo(f"Task generated: {'yes' if status['task_generated'] else 'no'}")
        if status["verification"]:
            typer.echo(f"Verification: {json.dumps(status['verification'], sort_keys=True)}")
        if status["observation"]:
            typer.echo(f"Observation: {json.dumps(status['observation'], sort_keys=True)}")
        if status["reflection"]:
            typer.echo(f"Reflection: {json.dumps(status['reflection'], sort_keys=True)}")
        if status["checkpoints"]:
            typer.echo("Checkpoints:")
            for checkpoint in status["checkpoints"]:
                typer.echo(f"- {checkpoint['title']}: {checkpoint['status']} ({checkpoint['reason']})")
        if status["approval_blockers"]:
            typer.echo(f"Approval blockers: {'; '.join(status['approval_blockers'])}")
    except LearningAgentError as exc:
        exit_on_error(exc)


@learn_app.command("generate")
def learn_generate_command() -> None:
    try:
        controller = get_controller()
        session = controller.generate_learning_assist()
        typer.echo(f"Generated Learning Assist for Week {session.week}.")
        typer.echo(f"Concept cards: {len(session.concept_cards)}")
        typer.echo(f"Questions: {len(session.questions)}")
        for question in session.questions:
            typer.echo(
                f"- {question.id} [{question.depth}] "
                f"{question.prompt_text}"
            )
    except LearningAgentError as exc:
        exit_on_error(exc)


@learn_app.command("compare-models")
def learn_compare_models_command(
    gpt_model: str = typer.Option(
        "",
        help="OpenAI model name for the GPT comparison pass. Defaults to the configured OpenAI model or `gpt-4o`.",
    ),
    claude_model: str = typer.Option(
        DEFAULT_ANTHROPIC_MODEL,
        help="Anthropic model name for the Claude comparison pass.",
    ),
    output_dir: str = typer.Option(
        "tmp/learning_compare",
        help="Repo-relative directory where comparison artifacts will be written.",
    ),
) -> None:
    try:
        controller = get_controller()
        configured_model = controller.config.model.strip()
        resolved_gpt_model = (
            gpt_model.strip()
            or (configured_model if controller.config.provider == "openai" and configured_model else "gpt-4o")
        )
        resolved_claude_model = (
            claude_model.strip()
            or (configured_model if controller.config.provider == "anthropic" and configured_model else DEFAULT_ANTHROPIC_MODEL)
        )
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        comparison_root = (controller.repo_root / output_dir / timestamp).resolve()
        result = controller.compare_learning_providers(
            providers=[
                ("claude", resolved_claude_model, AnthropicProvider(model=resolved_claude_model)),
                ("gpt", resolved_gpt_model, OpenAIProvider(model=resolved_gpt_model)),
            ],
            output_dir=comparison_root,
        )
        typer.echo("Cleared existing learning/task state and downstream progress.")
        typer.echo(f"Comparison artifacts written to {result['output_dir']}")
        for provider_result in result["providers"]:
            typer.echo(
                f"- {provider_result['provider_label']} ({provider_result['model']}) [{provider_result.get('status', 'unknown')}]: "
                f"{provider_result['output_dir']}"
            )
            if provider_result.get("error"):
                typer.echo(f"  error: {provider_result['error']}")
    except LearningAgentError as exc:
        exit_on_error(exc)


@learn_app.command("answer")
def learn_answer_command(
    question_id: str = typer.Option(..., help="Question id from the current Learning Assist session."),
    answer: str = typer.Option(..., help="Your free-text answer."),
) -> None:
    try:
        controller = get_controller()
        result = controller.answer_learning_question(question_id, answer)
        typer.echo("Pass" if result.passed else "Fail")
        typer.echo(result.score_rationale)
        if result.missing_concepts:
            typer.echo(f"Missing concepts: {', '.join(result.missing_concepts)}")
    except LearningAgentError as exc:
        exit_on_error(exc)


@task_app.command("generate")
def task_generate_command() -> None:
    try:
        controller = get_controller()
        task_session = controller.generate_task()
        typer.echo(task_session.task.summary)
        typer.echo(json.dumps(task_session.task.model_dump(mode="json"), indent=2, sort_keys=True))
    except LearningAgentError as exc:
        exit_on_error(exc)


@record_app.command("sync")
def record_sync_command() -> None:
    try:
        controller = get_controller()
        ledger = controller.sync_artifacts()
        typer.echo(
            f"Completed {len(ledger.state.artifacts.completed_files)}/{len(ledger.state.artifacts.required_files)} required files."
        )
    except LearningAgentError as exc:
        exit_on_error(exc)


@record_app.command("metric")
def record_metric_command(
    key: str = typer.Option(..., help="Metric name."),
    value: float = typer.Option(..., help="Metric value."),
) -> None:
    try:
        controller = get_controller()
        ledger = controller.record_metric(key, value)
        typer.echo(f"Recorded metric {key}={ledger.state.metrics.recorded[key]}.")
    except LearningAgentError as exc:
        exit_on_error(exc)


@record_app.command("verify")
def record_verify_command(
    passed: bool = typer.Option(True, "--passed/--failed", help="Whether verification passed."),
    summary: str = typer.Option(..., help="Short verification summary."),
) -> None:
    try:
        controller = get_controller()
        ledger = controller.record_verification(passed, summary)
        typer.echo(f"Verification recorded: {'passed' if ledger.state.gates.verification_passed else 'failed'}.")
    except LearningAgentError as exc:
        exit_on_error(exc)


@record_app.command("observation")
def record_observation_command(
    command: str = typer.Option(..., help="Command that produced the observation."),
    artifact_path: str = typer.Option(..., help="Artifact path where results were recorded."),
    reliability: str = typer.Option(
        "uncertain",
        help="One of: valid, invalid_due_to_bug, invalid_due_to_bad_measurement, uncertain.",
    ),
    prompt_tokens: Optional[int] = typer.Option(None, help="Prompt token count."),
    output_tokens: Optional[int] = typer.Option(None, help="Output token count."),
    latency_p95_ms: Optional[float] = typer.Option(None, help="Observed p95 latency in milliseconds."),
    tokens_per_sec: Optional[float] = typer.Option(None, help="Observed tokens per second."),
    notes: str = typer.Option("", help="Short observation notes."),
) -> None:
    try:
        controller = get_controller()
        observation = ObservationRecord(
            command=command,
            artifact_path=artifact_path,
            reliability=reliability,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            latency_p95_ms=latency_p95_ms,
            tokens_per_sec=tokens_per_sec,
            notes=notes,
        )
        ledger = controller.record_observation(observation)
        typer.echo(
            "Observation recorded. "
            f"Evidence reliability is {'valid' if ledger.state.gates.evidence_reliable else 'blocked'}."
        )
    except LearningAgentError as exc:
        exit_on_error(exc)


@record_app.command("reflection")
def record_reflection_command(
    text: str = typer.Option(..., help="Your reflection on the observed result."),
    trustworthy: Optional[bool] = typer.Option(
        None,
        "--trustworthy/--not-trustworthy",
        help="Whether the evidence is trustworthy.",
    ),
    buggy: bool = typer.Option(False, "--buggy/--not-buggy", help="Whether the implementation or measurement appears buggy."),
    next_fix: str = typer.Option("", help="Next fix to try if the evidence is unreliable."),
) -> None:
    try:
        controller = get_controller()
        reflection = ReflectionRecord(text=text, trustworthy=trustworthy, buggy=buggy, next_fix=next_fix)
        controller.record_reflection(reflection)
        typer.echo("Reflection recorded.")
    except LearningAgentError as exc:
        exit_on_error(exc)


@app.command("approve")
def approve_command() -> None:
    try:
        controller = get_controller()
        ledger = controller.approve_week()
        typer.echo(f"Week {ledger.state.current_week} approved.")
    except LearningAgentError as exc:
        exit_on_error(exc)


@app.command("advance")
def advance_command() -> None:
    try:
        controller = get_controller()
        ledger = controller.advance_week()
        typer.echo(f"Advanced to Week {ledger.state.current_week}.")
    except LearningAgentError as exc:
        exit_on_error(exc)


@app.command("serve")
def serve_command(
    host: str = typer.Option(DEFAULT_UI_HOST, help="Host interface to bind the UI server."),
    port: int = typer.Option(DEFAULT_UI_PORT, help="Port to bind the UI server."),
    reload: bool = typer.Option(True, "--reload/--no-reload", help="Restart the UI server when app/config files change."),
) -> None:
    try:
        repo_root, _config = load_config()
        if reload:
            serve_with_reload(repo_root, host=host, port=port)
        else:
            serve_ui(host=host, port=port)
    except LearningAgentError as exc:
        exit_on_error(exc)

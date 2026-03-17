from __future__ import annotations

import json

import typer

from learning_agent.config import load_config
from learning_agent.controller import LearningController
from learning_agent.errors import LearningAgentError
from learning_agent.ui import DEFAULT_UI_HOST, DEFAULT_UI_PORT, serve_ui


app = typer.Typer(help="Guided single-controller learning agent.")
gate_app = typer.Typer(help="Run the concept gate flow.")
task_app = typer.Typer(help="Generate the Junior SWE task.")
record_app = typer.Typer(help="Record execution progress.")

app.add_typer(gate_app, name="gate")
app.add_typer(task_app, name="task")
app.add_typer(record_app, name="record")


def get_controller() -> LearningController:
    repo_root, config = load_config()
    return LearningController(repo_root, config)


def exit_on_error(exc: LearningAgentError) -> None:
    typer.secho(str(exc), fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


@app.command("init")
def init_command() -> None:
    try:
        controller = get_controller()
        ledger = controller.initialize()
        typer.echo(f"Initialized Week {ledger.state.current_week} in {controller.state.ledger_path}.")
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
        typer.echo(f"Gate asked: {'yes' if status['gate_asked'] else 'no'}")
        typer.echo(f"Task generated: {'yes' if status['task_generated'] else 'no'}")
        if status["verification"]:
            typer.echo(f"Verification: {json.dumps(status['verification'], sort_keys=True)}")
        if status["approval_blockers"]:
            typer.echo(f"Approval blockers: {'; '.join(status['approval_blockers'])}")
    except LearningAgentError as exc:
        exit_on_error(exc)


@gate_app.command("ask")
def gate_ask_command() -> None:
    try:
        controller = get_controller()
        gate = controller.ask_gate()
        typer.echo(f"Week {gate.prompt.week} concept gate")
        typer.echo(gate.prompt.question)
        if gate.prompt.rubric:
            typer.echo("Rubric:")
            for item in gate.prompt.rubric:
                typer.echo(f"- {item}")
    except LearningAgentError as exc:
        exit_on_error(exc)


@gate_app.command("submit")
def gate_submit_command(answer: str = typer.Option(..., help="Your answer to the current gate question.")) -> None:
    try:
        controller = get_controller()
        result = controller.submit_gate(answer)
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
) -> None:
    try:
        get_controller()
        serve_ui(host=host, port=port)
    except LearningAgentError as exc:
        exit_on_error(exc)

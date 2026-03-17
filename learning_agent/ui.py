from __future__ import annotations

import html
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import parse_qs, quote_plus, urlparse

from learning_agent.config import load_config
from learning_agent.controller import LearningController
from learning_agent.errors import LearningAgentError


DEFAULT_UI_HOST = "127.0.0.1"
DEFAULT_UI_PORT = 4010
ICON_PATH = Path(__file__).resolve().parent / "assets" / "icon.png"


def serve_ui(host: str = DEFAULT_UI_HOST, port: int = DEFAULT_UI_PORT) -> None:
    handler = build_handler()
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Learning Agent UI listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def build_handler():
    class LearningAgentHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path in {"/favicon.ico", "/assets/icon.png"}:
                self._send_asset(ICON_PATH, "image/png")
                return
            if parsed.path != "/":
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            params = parse_qs(parsed.query)
            message = first_param(params, "message")
            error = first_param(params, "error")
            page = render_page(message=message, error=error)
            self._send_html(page)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/action":
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            length = int(self.headers.get("Content-Length", "0"))
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            action = first_param(form, "action")
            try:
                message = run_action(action, form)
                self._redirect(message=message)
            except LearningAgentError as exc:
                self._redirect(error=str(exc))
            except Exception as exc:  # pragma: no cover
                self._redirect(error=f"Unexpected error: {exc}")

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def _send_html(self, body: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _redirect(self, message: Optional[str] = None, error: Optional[str] = None) -> None:
            query_parts = []
            if message:
                query_parts.append(f"message={quote_plus(message)}")
            if error:
                query_parts.append(f"error={quote_plus(error)}")
            location = "/" if not query_parts else f"/?{'&'.join(query_parts)}"
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", location)
            self.end_headers()

        def _send_asset(self, path: Path, content_type: str) -> None:
            try:
                payload = path.read_bytes()
            except FileNotFoundError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(payload)

    return LearningAgentHandler


def get_controller() -> LearningController:
    repo_root, config = load_config()
    return LearningController(repo_root, config)


def run_action(action: str, form: Dict[str, list[str]]) -> str:
    if not action:
        raise LearningAgentError("Missing action.")

    controller = get_controller()
    if action == "init":
        ledger = controller.initialize()
        return f"Initialized Week {ledger.state.current_week}."
    if action == "gate_ask":
        session = controller.ask_gate()
        return f"Generated concept gate for Week {session.prompt.week}."
    if action == "gate_submit":
        answer = first_param(form, "answer")
        if not answer.strip():
            raise LearningAgentError("Gate answer cannot be empty.")
        result = controller.submit_gate(answer)
        return "Gate passed." if result.passed else "Gate failed."
    if action == "task_generate":
        task = controller.generate_task()
        return f"Generated task for Week {task.task.week}."
    if action == "record_sync":
        ledger = controller.sync_artifacts()
        completed = len(ledger.state.artifacts.completed_files)
        total = len(ledger.state.artifacts.required_files)
        return f"Synced artifacts: {completed}/{total} required files present."
    if action == "record_metric":
        key = first_param(form, "metric_key").strip()
        value = first_param(form, "metric_value").strip()
        if not key:
            raise LearningAgentError("Metric key cannot be empty.")
        if not value:
            raise LearningAgentError("Metric value cannot be empty.")
        try:
            parsed_value = float(value)
        except ValueError as exc:
            raise LearningAgentError("Metric value must be numeric.") from exc
        controller.record_metric(key, parsed_value)
        return f"Recorded metric {key}={parsed_value}."
    if action == "record_verify":
        summary = first_param(form, "verification_summary").strip()
        passed = first_param(form, "verification_passed", default="true") == "true"
        if not summary:
            raise LearningAgentError("Verification summary cannot be empty.")
        controller.record_verification(passed, summary)
        return "Recorded verification result."
    if action == "approve":
        ledger = controller.approve_week()
        return f"Approved Week {ledger.state.current_week}."
    if action == "advance":
        ledger = controller.advance_week()
        return f"Advanced to Week {ledger.state.current_week}."

    raise LearningAgentError(f"Unknown action: {action}")


def render_page(message: Optional[str] = None, error: Optional[str] = None) -> str:
    try:
        status = get_controller().status()
        initialized = True
    except LearningAgentError as exc:
        initialized = False
        status = None
        if not error:
            error = str(exc)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Learning Agent</title>
  <link rel="icon" type="image/png" href="/favicon.ico">
  <style>
    :root {{
      --bg: #f3efe7;
      --surface: #fffaf1;
      --surface-alt: #efe7d7;
      --border: #d7c7a8;
      --text: #241e14;
      --muted: #645844;
      --accent: #0f766e;
      --accent-dark: #115e59;
      --danger: #9f1239;
      --success: #166534;
      --shadow: 0 18px 50px rgba(36, 30, 20, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif;
      background:
        radial-gradient(circle at top left, rgba(15, 118, 110, 0.08), transparent 28%),
        linear-gradient(180deg, #f8f3e9 0%, var(--bg) 100%);
      color: var(--text);
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 32px 20px 56px;
    }}
    .brand {{
      display: inline-flex;
      align-items: center;
      gap: 14px;
      color: inherit;
      text-decoration: none;
    }}
    .brand-mark {{
      width: 64px;
      height: 64px;
      border-radius: 18px;
      border: 1px solid var(--border);
      background: linear-gradient(180deg, rgba(255,255,255,0.9), rgba(239,231,215,0.95));
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.65);
      object-fit: cover;
    }}
    .brand-copy {{
      display: grid;
      gap: 4px;
    }}
    .brand-label {{
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.8rem;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: var(--accent-dark);
    }}
    h1, h2, h3 {{
      margin: 0 0 12px;
      line-height: 1.1;
    }}
    h1 {{
      font-size: clamp(2rem, 4vw, 3.2rem);
      letter-spacing: -0.03em;
    }}
    h2 {{
      font-size: 1.2rem;
    }}
    p, li, label, input, textarea, button, select {{
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
    }}
    .hero {{
      display: grid;
      grid-template-columns: 1.4fr 1fr;
      gap: 20px;
      align-items: stretch;
      margin-bottom: 24px;
    }}
    .hero-card, .panel {{
      background: rgba(255, 250, 241, 0.94);
      border: 1px solid var(--border);
      border-radius: 22px;
      box-shadow: var(--shadow);
      padding: 22px;
      backdrop-filter: blur(8px);
    }}
    .hero-meta {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 16px;
    }}
    .pill {{
      border-radius: 999px;
      padding: 8px 12px;
      background: var(--surface-alt);
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .status-grid, .action-grid {{
      display: grid;
      gap: 18px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      margin-bottom: 18px;
    }}
    .full {{
      grid-column: 1 / -1;
    }}
    .notice {{
      border-radius: 16px;
      padding: 14px 16px;
      margin-bottom: 18px;
      border: 1px solid var(--border);
      background: #f7f0df;
    }}
    .notice.success {{
      border-color: #8fd3ad;
      background: #ecfdf3;
      color: var(--success);
    }}
    .notice.error {{
      border-color: #f2a7b8;
      background: #fff1f5;
      color: var(--danger);
    }}
    .metric-list, .gate-list, .artifact-list {{
      margin: 0;
      padding-left: 18px;
    }}
    .form-grid {{
      display: grid;
      gap: 12px;
    }}
    label {{
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 0.95rem;
    }}
    input, textarea, select {{
      width: 100%;
      border: 1px solid var(--border);
      background: #fffdf7;
      border-radius: 12px;
      padding: 10px 12px;
      color: var(--text);
      font-size: 0.96rem;
    }}
    textarea {{ min-height: 110px; resize: vertical; }}
    button {{
      border: 0;
      border-radius: 14px;
      background: var(--accent);
      color: white;
      padding: 11px 16px;
      font-weight: 600;
      cursor: pointer;
    }}
    button.secondary {{
      background: #433423;
    }}
    button.warn {{
      background: var(--danger);
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      background: #fcf8ef;
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 14px;
      overflow-x: auto;
      font-size: 0.92rem;
    }}
    .muted {{ color: var(--muted); }}
    @media (max-width: 920px) {{
      .hero, .status-grid, .action-grid {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div class="hero-card">
        <a class="brand" href="/" aria-label="Learning Agent home">
          <img class="brand-mark" src="/assets/icon.png" alt="Learning Agent icon">
          <span class="brand-copy">
            <span class="brand-label">Learning Agent</span>
            <h1>Mentor Control Surface</h1>
          </span>
        </a>
        <p class="muted">Phase 1 control surface for the Mentor / Junior SWE workflow. This UI drives the same state machine as the CLI.</p>
        <div class="hero-meta">
          <span class="pill">Local only</span>
          <span class="pill">Port {DEFAULT_UI_PORT}</span>
          <span class="pill">Week-gated flow</span>
        </div>
      </div>
      <div class="hero-card">
        <h2>Current State</h2>
        {render_state_summary(status, initialized)}
      </div>
    </section>
    {render_notice(message, error)}
    {render_body(status, initialized)}
  </main>
</body>
</html>"""


def render_state_summary(status: Optional[dict], initialized: bool) -> str:
    if not initialized or not status:
        return "<p class='muted'>No ledger loaded yet. Initialize Week 1 to begin.</p>"

    gates = status["gates"]
    return (
        f"<p><strong>Week {status['week']}</strong>: {escape(status['title'])}</p>"
        f"<p class='muted'>{escape(status['goal'])}</p>"
        f"<ul class='gate-list'>"
        f"<li>Concept gate: {'passed' if gates['socratic_check_passed'] else 'pending'}</li>"
        f"<li>Implementation: {'complete' if gates['implementation_complete'] else 'pending'}</li>"
        f"<li>Verification: {'passed' if gates['verification_passed'] else 'pending'}</li>"
        f"<li>Approval: {'granted' if gates['week_approved'] else 'pending'}</li>"
        f"</ul>"
    )


def render_notice(message: Optional[str], error: Optional[str]) -> str:
    notices = []
    if message:
        notices.append(f"<div class='notice success'>{escape(message)}</div>")
    if error:
        notices.append(f"<div class='notice error'>{escape(error)}</div>")
    return "".join(notices)


def render_body(status: Optional[dict], initialized: bool) -> str:
    if not initialized or not status:
        return (
            "<section class='action-grid'>"
            f"{render_button_panel('Initialize Week 1', 'Create the ledger and derive the first week from the roadmap.', 'init', 'Start')}"
            "</section>"
        )

    gate_session = status.get("gate_session")
    task_session = status.get("task_session")
    return (
        "<section class='status-grid'>"
        f"{render_status_panel(status)}"
        f"{render_gate_panel(gate_session)}"
        f"{render_task_panel(task_session)}"
        f"{render_blocker_panel(status)}"
        "</section>"
        "<section class='action-grid'>"
        f"{render_button_panel('Initialize', 'Re-run init only if you delete the current ledger first.', 'init', 'Init Again', secondary=True)}"
        f"{render_button_panel('Ask Gate Question', 'Generate the Mentor question for the current week.', 'gate_ask', 'Ask Gate')}"
        f"{render_gate_submit_panel()}"
        f"{render_button_panel('Generate Task', 'Create the structured Junior SWE task once the gate passes.', 'task_generate', 'Generate Task')}"
        f"{render_button_panel('Sync Artifacts', 'Scan the target repo for the required files.', 'record_sync', 'Sync Files', secondary=True)}"
        f"{render_metric_panel()}"
        f"{render_verify_panel()}"
        f"{render_button_panel('Approve Week', 'Mark the current week approved once all blockers are cleared.', 'approve', 'Approve')}"
        f"{render_button_panel('Advance Week', 'Move to the next week and reset week-local state.', 'advance', 'Advance', warn=True)}"
        "</section>"
    )


def render_status_panel(status: dict) -> str:
    metrics = "".join(
        f"<li><strong>{escape(key)}</strong>: {escape(str(value))}</li>"
        for key, value in status["recorded_metrics"].items()
    ) or "<li class='muted'>No metrics recorded yet.</li>"
    required = "".join(f"<li>{escape(item)}</li>" for item in status["required_files"]) or "<li>(none)</li>"
    completed = "".join(f"<li>{escape(item)}</li>" for item in status["completed_files"]) or "<li class='muted'>(none)</li>"
    return f"""
    <article class="panel">
      <h2>Week Scope</h2>
      <p class="muted">Active dirs: {escape(', '.join(status['active_dirs']) or '(none)')}</p>
      <h3>Required Files</h3>
      <ul class="artifact-list">{required}</ul>
      <h3>Completed Files</h3>
      <ul class="artifact-list">{completed}</ul>
      <h3>Recorded Metrics</h3>
      <ul class="metric-list">{metrics}</ul>
    </article>
    """


def render_gate_panel(gate_session: Optional[dict]) -> str:
    if not gate_session:
        body = "<p class='muted'>No gate question generated yet.</p>"
    else:
        prompt = gate_session["prompt"]
        rubric = "".join(f"<li>{escape(item)}</li>" for item in prompt.get("rubric", [])) or "<li>(none)</li>"
        result = gate_session.get("result")
        result_html = "<p class='muted'>No answer submitted yet.</p>"
        if result:
            result_html = (
                f"<p><strong>{'Pass' if result['passed'] else 'Fail'}</strong></p>"
                f"<p class='muted'>{escape(result['score_rationale'])}</p>"
            )
        body = (
            f"<p>{escape(prompt['question'])}</p>"
            f"<h3>Rubric</h3><ul class='gate-list'>{rubric}</ul>"
            f"<h3>Result</h3>{result_html}"
        )
    return f"<article class='panel'>{'<h2>Concept Gate</h2>'}{body}</article>"


def render_task_panel(task_session: Optional[dict]) -> str:
    if not task_session:
        body = "<p class='muted'>No task generated yet.</p>"
    else:
        body = f"<pre>{escape(json.dumps(task_session['task'], indent=2, sort_keys=True))}</pre>"
    return f"<article class='panel full'><h2>Junior SWE Task</h2>{body}</article>"


def render_blocker_panel(status: dict) -> str:
    blockers = status["approval_blockers"]
    if blockers:
        body = "".join(f"<li>{escape(item)}</li>" for item in blockers)
    else:
        body = "<li>No blockers. You can approve this week.</li>"
    return f"<article class='panel'><h2>Approval Blockers</h2><ul class='gate-list'>{body}</ul></article>"


def render_button_panel(title: str, description: str, action: str, button_label: str, secondary: bool = False, warn: bool = False) -> str:
    button_class = "warn" if warn else "secondary" if secondary else ""
    return f"""
    <article class="panel">
      <h2>{escape(title)}</h2>
      <p class="muted">{escape(description)}</p>
      <form method="post" action="/action" class="form-grid">
        <input type="hidden" name="action" value="{escape(action)}">
        <button type="submit" class="{button_class}">{escape(button_label)}</button>
      </form>
    </article>
    """


def render_gate_submit_panel() -> str:
    return """
    <article class="panel">
      <h2>Submit Gate Answer</h2>
      <form method="post" action="/action" class="form-grid">
        <input type="hidden" name="action" value="gate_submit">
        <label>Answer
          <textarea name="answer" placeholder="Explain your Week 1 concepts here..."></textarea>
        </label>
        <button type="submit">Submit Answer</button>
      </form>
    </article>
    """


def render_metric_panel() -> str:
    return """
    <article class="panel">
      <h2>Record Metric</h2>
      <form method="post" action="/action" class="form-grid">
        <input type="hidden" name="action" value="record_metric">
        <label>Metric key
          <input name="metric_key" placeholder="latency_p95">
        </label>
        <label>Metric value
          <input name="metric_value" type="number" step="any" placeholder="420">
        </label>
        <button type="submit">Record Metric</button>
      </form>
    </article>
    """


def render_verify_panel() -> str:
    return """
    <article class="panel">
      <h2>Record Verification</h2>
      <form method="post" action="/action" class="form-grid">
        <input type="hidden" name="action" value="record_verify">
        <label>Status
          <select name="verification_passed">
            <option value="true">Passed</option>
            <option value="false">Failed</option>
          </select>
        </label>
        <label>Summary
          <textarea name="verification_summary" placeholder="Local verification passed, benchmark output recorded..."></textarea>
        </label>
        <button type="submit">Record Verification</button>
      </form>
    </article>
    """


def first_param(params: Dict[str, list[str]], key: str, default: str = "") -> str:
    values = params.get(key)
    if not values:
        return default
    return values[0]


def escape(value: str) -> str:
    return html.escape(value, quote=True)

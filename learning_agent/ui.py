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
from learning_agent.models import ObservationRecord, ReflectionRecord


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
    if action == "learning_toggle":
        enabled = first_param(form, "learning_enabled", default="true") == "true"
        controller.set_learning_assist_enabled(enabled)
        return f"Learning Assist {'enabled' if enabled else 'hidden'}."
    if action == "learning_generate":
        session = controller.generate_learning_assist()
        return f"Generated Learning Assist for Week {session.week}."
    if action == "learning_answer":
        question_id = first_param(form, "question_id").strip()
        answer = first_param(form, "learning_answer").strip()
        if not question_id:
            raise LearningAgentError("Question id cannot be empty.")
        if not answer:
            raise LearningAgentError("Learning answer cannot be empty.")
        result = controller.answer_learning_question(question_id, answer)
        return "Question passed." if result.passed else "Question failed."
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
    if action == "record_observation":
        command = first_param(form, "observation_command").strip()
        artifact_path = first_param(form, "observation_artifact_path").strip()
        reliability = first_param(form, "observation_reliability", default="uncertain").strip() or "uncertain"
        if not command:
            raise LearningAgentError("Observation command cannot be empty.")
        if not artifact_path:
            raise LearningAgentError("Observation artifact path cannot be empty.")
        observation = ObservationRecord(
            command=command,
            artifact_path=artifact_path,
            reliability=reliability,
            prompt_tokens=parse_optional_int(first_param(form, "observation_prompt_tokens")),
            output_tokens=parse_optional_int(first_param(form, "observation_output_tokens")),
            latency_p95_ms=parse_optional_float(first_param(form, "observation_latency_p95_ms")),
            tokens_per_sec=parse_optional_float(first_param(form, "observation_tokens_per_sec")),
            notes=first_param(form, "observation_notes").strip(),
        )
        controller.record_observation(observation)
        return "Recorded structured observation."
    if action == "record_verify":
        summary = first_param(form, "verification_summary").strip()
        passed = first_param(form, "verification_passed", default="true") == "true"
        if not summary:
            raise LearningAgentError("Verification summary cannot be empty.")
        controller.record_verification(passed, summary)
        return "Recorded verification result."
    if action == "record_reflection":
        text = first_param(form, "reflection_text").strip()
        if not text:
            raise LearningAgentError("Reflection text cannot be empty.")
        trustworthy = parse_optional_bool(first_param(form, "reflection_trustworthy"))
        buggy = first_param(form, "reflection_buggy", default="false") == "true"
        next_fix = first_param(form, "reflection_next_fix").strip()
        controller.record_reflection(
            ReflectionRecord(text=text, trustworthy=trustworthy, buggy=buggy, next_fix=next_fix)
        )
        return "Recorded reflection."
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
    .info-grid {{
      display: grid;
      gap: 18px;
      grid-template-columns: 1.1fr 0.9fr;
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
    .tour-list {{
      margin: 0;
      padding-left: 18px;
      display: grid;
      gap: 8px;
    }}
    .tour-list strong {{
      color: var(--accent-dark);
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
      .hero, .info-grid, .status-grid, .action-grid {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
  {render_flash_cleanup_script(message, error)}
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
    {render_info_sections()}
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
        f"<li>Concept coverage: {'passed' if gates['socratic_check_passed'] else 'pending'}</li>"
        f"<li>Implementation: {'complete' if gates['implementation_complete'] else 'pending'}</li>"
        f"<li>Verification: {'passed' if gates['verification_passed'] else 'pending'}</li>"
        f"<li>Evidence: {'reliable' if gates['evidence_reliable'] else 'pending'}</li>"
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


def render_flash_cleanup_script(message: Optional[str], error: Optional[str]) -> str:
    if not message and not error:
        return ""
    return """
  <script>
    window.addEventListener("DOMContentLoaded", function () {
      const url = new URL(window.location.href);
      url.searchParams.delete("message");
      url.searchParams.delete("error");
      const nextUrl = url.pathname + (url.search ? url.search : "") + url.hash;
      window.history.replaceState({}, document.title, nextUrl || "/");
    });
  </script>
"""


def render_info_sections() -> str:
    return """
    <section class="info-grid">
      <article class="panel">
        <h2>About This Platform</h2>
        <p>This platform is a curriculum-driven learning agent for a senior software engineer who wants to learn a new domain by building real artifacts instead of just reading or generating code blindly.</p>
        <p>Its core job is to keep the learning loop disciplined. The platform tracks progress outside model context, hides future material until it is unlocked, teaches the current week with Learning Assist, turns the current scope into a focused Junior SWE task, and blocks progression when evidence is untrustworthy.</p>
        <p>In Phase 1, this UI is the operational control surface for that workflow. You can use it to initialize the current week, generate concept cards and question banks, answer scoped questions, generate the implementation brief, record structured observations from your work in the target repo, and approve progression only when the week is actually complete.</p>
        <p><strong>What you can do with it now:</strong> run the Week 1 concept flow, generate the current implementation task, track required files and metrics, record observations and reflections, record verification results, and manage week advancement with an explicit state machine.</p>
        <p><strong>What it is useful for:</strong> keeping your learning structured, making each week auditable, reducing context drift between sessions, and forcing a clean separation between understanding a topic and implementing it.</p>
      </article>
      <article class="panel">
        <h2>UI Walkthrough Tour</h2>
        <ol class="tour-list">
          <li><strong>Hero + Current State:</strong> shows whether the current week is initialized and whether concept, implementation, verification, evidence, and approval gates are complete.</li>
          <li><strong>Week Scope:</strong> shows the allowed directories, required files, completed files, metrics, and checkpoint progression.</li>
          <li><strong>Learning Assist:</strong> shows concept cards, the current question bank, and whether required question coverage has been satisfied.</li>
          <li><strong>Junior SWE Task:</strong> shows the structured implementation brief generated for the current unlocked week.</li>
          <li><strong>Observation + Reflection:</strong> capture the benchmark outcome, its reliability, and your interpretation of what happened.</li>
          <li><strong>Approval Blockers:</strong> tells you exactly why the week cannot yet be approved.</li>
          <li><strong>Initialize / Generate Learning Assist / Answer Questions:</strong> start the week, load the current learning content, and submit answers by question id.</li>
          <li><strong>Generate Task / Sync Artifacts:</strong> create the implementation brief and then rescan the target repo to detect completed deliverables.</li>
          <li><strong>Record Observation / Reflection / Verification:</strong> log the evidence that proves the current week was actually completed and trustworthy.</li>
          <li><strong>Approve / Advance:</strong> explicitly finish the week and unlock the next one only after all blockers are cleared.</li>
        </ol>
      </article>
    </section>
    """


def render_body(status: Optional[dict], initialized: bool) -> str:
    if not initialized or not status:
        return (
            "<section class='action-grid'>"
            f"{render_button_panel('Initialize Week 1', 'Create the ledger and derive the first week from the roadmap.', 'init', 'Start')}"
            "</section>"
        )

    gate_session = status.get("gate_session")
    task_session = status.get("task_session")
    learning_session = status.get("learning_session")
    return (
        "<section class='status-grid'>"
        f"{render_status_panel(status)}"
        f"{render_learning_panel(status, learning_session, gate_session)}"
        f"{render_task_panel(task_session)}"
        f"{render_observation_status_panel(status)}"
        f"{render_blocker_panel(status)}"
        "</section>"
        "<section class='action-grid'>"
        f"{render_button_panel('Initialize', 'Re-run init only if you delete the current ledger first.', 'init', 'Init Again', secondary=True)}"
        f"{render_learning_toggle_panel(status)}"
        f"{render_button_panel('Generate Learning Assist', 'Load concept cards and the current week question bank.', 'learning_generate', 'Generate Learning Assist')}"
        f"{render_learning_answer_panel(learning_session)}"
        f"{render_button_panel('Ask Legacy Gate', 'Generate the older single-question concept gate if you still want it.', 'gate_ask', 'Ask Gate', secondary=True)}"
        f"{render_gate_submit_panel()}"
        f"{render_button_panel('Generate Task', 'Create the structured Junior SWE task once the gate passes.', 'task_generate', 'Generate Task')}"
        f"{render_button_panel('Sync Artifacts', 'Scan the target repo for the required files.', 'record_sync', 'Sync Files', secondary=True)}"
        f"{render_metric_panel()}"
        f"{render_observation_panel()}"
        f"{render_reflection_panel()}"
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
    checkpoints = "".join(
        f"<li><strong>{escape(item['title'])}</strong>: {escape(item['status'])} "
        f"<span class='muted'>{escape(item['reason'])}</span></li>"
        for item in status.get("checkpoints", [])
    ) or "<li class='muted'>No checkpoints derived yet.</li>"
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
      <h3>Checkpoints</h3>
      <ul class="gate-list">{checkpoints}</ul>
    </article>
    """


def render_learning_panel(status: dict, learning_session: Optional[dict], gate_session: Optional[dict]) -> str:
    progress = status.get("question_progress", {})
    cards_html = "<p class='muted'>Learning Assist is hidden.</p>"
    if status.get("learning_assist_enabled"):
        empty_cards_html = "<li class='muted'>No concept cards generated yet.</li>"
        cards = []
        for card in (learning_session or {}).get("concept_cards", []):
            cards.append(
                "<li>"
                f"<strong>{escape(card['concept'])}</strong>: {escape(card['explanation'])} "
                f"<span class='muted'>Why it matters: {escape(card['why_it_matters'])}</span>"
                "</li>"
            )
        cards_html = f"<ul class='gate-list'>{''.join(cards) or empty_cards_html}</ul>"

    questions_html = "<li class='muted'>No Learning Assist questions generated yet.</li>"
    if learning_session:
        attempts = {}
        for attempt in learning_session.get("attempts", []):
            attempts[attempt["question_id"]] = attempt
        question_items = []
        for question in learning_session.get("questions", []):
            result = attempts.get(question["id"], {}).get("result")
            status_text = "unanswered"
            if result:
                status_text = "passed" if result["passed"] else "failed"
            question_items.append(
                "<li>"
                f"<strong>{escape(question['id'])}</strong> "
                f"[{escape(question['type'])}/{escape(question['scope'])}/{escape(question['depth'])}] "
                f"{escape(question['prompt_text'])} "
                f"<span class='muted'>Status: {escape(status_text)}</span>"
                "</li>"
            )
        questions_html = "".join(question_items)

    legacy_gate = ""
    if gate_session:
        legacy_gate = f"<p class='muted'>Legacy gate loaded: {escape(gate_session['prompt']['question'])}</p>"

    body = (
        f"<p class='muted'>Required coverage: {progress.get('required_passed', 0)}/{progress.get('required_total', 0)} "
        "baseline core questions passed.</p>"
        f"<h3>Concept Cards</h3>{cards_html}"
        f"<h3>Question Bank</h3><ul class='gate-list'>{questions_html}</ul>"
        f"{legacy_gate}"
    )
    return f"<article class='panel full'><h2>Learning Assist</h2>{body}</article>"


def render_task_panel(task_session: Optional[dict]) -> str:
    if not task_session:
        body = "<p class='muted'>No task generated yet.</p>"
    else:
        body = f"<pre>{escape(json.dumps(task_session['task'], indent=2, sort_keys=True))}</pre>"
    return f"<article class='panel full'><h2>Junior SWE Task</h2>{body}</article>"


def render_observation_status_panel(status: dict) -> str:
    observation = status.get("observation")
    reflection = status.get("reflection")
    if not observation and not reflection:
        return "<article class='panel'><h2>Evidence State</h2><p class='muted'>No observation or reflection recorded yet.</p></article>"
    parts = []
    if observation:
        parts.append(f"<pre>{escape(json.dumps(observation, indent=2, sort_keys=True))}</pre>")
    if reflection:
        parts.append(f"<pre>{escape(json.dumps(reflection, indent=2, sort_keys=True))}</pre>")
    return f"<article class='panel'><h2>Evidence State</h2>{''.join(parts)}</article>"


def render_blocker_panel(status: dict) -> str:
    blockers = status["approval_blockers"]
    if blockers:
        body = "".join(f"<li>{escape(item)}</li>" for item in blockers)
    else:
        body = "<li>No blockers. You can approve this week.</li>"
    return f"<article class='panel'><h2>Approval Blockers</h2><ul class='gate-list'>{body}</ul></article>"


def render_learning_toggle_panel(status: dict) -> str:
    current_value = "true" if status.get("learning_assist_enabled") else "false"
    button_label = "Hide Concept Cards" if current_value == "true" else "Show Concept Cards"
    next_value = "false" if current_value == "true" else "true"
    return f"""
    <article class="panel">
      <h2>Learning Assist Toggle</h2>
      <p class="muted">Concept cards are currently {'visible' if current_value == 'true' else 'hidden'} in the UI.</p>
      <form method="post" action="/action" class="form-grid">
        <input type="hidden" name="action" value="learning_toggle">
        <input type="hidden" name="learning_enabled" value="{next_value}">
        <button type="submit" class="secondary">{escape(button_label)}</button>
      </form>
    </article>
    """


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


def render_learning_answer_panel(learning_session: Optional[dict]) -> str:
    options = []
    for question in (learning_session or {}).get("questions", []):
        options.append(
            f"<option value=\"{escape(question['id'])}\">{escape(question['id'])} - {escape(question['prompt_text'])}</option>"
        )
    options_html = "".join(options) or "<option value=\"\">Generate Learning Assist first</option>"
    return f"""
    <article class="panel">
      <h2>Answer Learning Question</h2>
      <form method="post" action="/action" class="form-grid">
        <input type="hidden" name="action" value="learning_answer">
        <label>Question
          <select name="question_id">{options_html}</select>
        </label>
        <label>Answer
          <textarea name="learning_answer" placeholder="Answer the selected question here..."></textarea>
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


def render_observation_panel() -> str:
    return """
    <article class="panel">
      <h2>Record Observation</h2>
      <form method="post" action="/action" class="form-grid">
        <input type="hidden" name="action" value="record_observation">
        <label>Command
          <input name="observation_command" placeholder=".venv/bin/python simple_server/benchmark.py">
        </label>
        <label>Artifact path
          <input name="observation_artifact_path" placeholder="docs/baseline_results.md">
        </label>
        <label>Reliability
          <select name="observation_reliability">
            <option value="uncertain">uncertain</option>
            <option value="valid">valid</option>
            <option value="invalid_due_to_bug">invalid_due_to_bug</option>
            <option value="invalid_due_to_bad_measurement">invalid_due_to_bad_measurement</option>
          </select>
        </label>
        <label>Prompt tokens
          <input name="observation_prompt_tokens" type="number" step="1" placeholder="512">
        </label>
        <label>Output tokens
          <input name="observation_output_tokens" type="number" step="1" placeholder="128">
        </label>
        <label>Latency p95 ms
          <input name="observation_latency_p95_ms" type="number" step="any" placeholder="840">
        </label>
        <label>Tokens per second
          <input name="observation_tokens_per_sec" type="number" step="any" placeholder="32.4">
        </label>
        <label>Notes
          <textarea name="observation_notes" placeholder="Observed behavior, run conditions, repeatability notes..."></textarea>
        </label>
        <button type="submit">Record Observation</button>
      </form>
    </article>
    """


def render_reflection_panel() -> str:
    return """
    <article class="panel">
      <h2>Record Reflection</h2>
      <form method="post" action="/action" class="form-grid">
        <input type="hidden" name="action" value="record_reflection">
        <label>Reflection
          <textarea name="reflection_text" placeholder="What happened, does it match expectation, and do you trust it?"></textarea>
        </label>
        <label>Trustworthiness
          <select name="reflection_trustworthy">
            <option value="">not set</option>
            <option value="true">trustworthy</option>
            <option value="false">not trustworthy</option>
          </select>
        </label>
        <label>Buggy
          <select name="reflection_buggy">
            <option value="false">no</option>
            <option value="true">yes</option>
          </select>
        </label>
        <label>Next fix
          <textarea name="reflection_next_fix" placeholder="What should be fixed next if the evidence is unreliable?"></textarea>
        </label>
        <button type="submit">Record Reflection</button>
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


def parse_optional_float(value: str) -> float | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError as exc:
        raise LearningAgentError("Expected a numeric value.") from exc


def parse_optional_int(value: str) -> int | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError as exc:
        raise LearningAgentError("Expected an integer value.") from exc


def parse_optional_bool(value: str) -> bool | None:
    stripped = value.strip().lower()
    if not stripped:
        return None
    if stripped == "true":
        return True
    if stripped == "false":
        return False
    raise LearningAgentError("Expected a boolean value.")


def escape(value: str) -> str:
    return html.escape(value, quote=True)

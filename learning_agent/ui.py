from __future__ import annotations

import html
import json
import re
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
ASSET_ROOT = Path(__file__).resolve().parent / "assets"
ICON_PATH = ASSET_ROOT / "icon.png"


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
            if parsed.path == "/favicon.ico":
                self._send_asset(ICON_PATH, "image/png")
                return
            if parsed.path.startswith("/assets/"):
                self._send_named_asset(parsed.path)
                return
            if parsed.path != "/":
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            params = parse_qs(parsed.query)
            message = first_param(params, "message")
            error = first_param(params, "error")
            selected_question_id = first_param(params, "question_id")
            page = render_page(message=message, error=error, selected_question_id=selected_question_id)
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
                self._redirect(message=message, query={"question_id": first_param(form, "question_id")})
            except LearningAgentError as exc:
                self._redirect(error=str(exc), query={"question_id": first_param(form, "question_id")})
            except Exception as exc:  # pragma: no cover
                self._redirect(error=f"Unexpected error: {exc}", query={"question_id": first_param(form, "question_id")})

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def _send_html(self, body: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _redirect(
            self,
            message: Optional[str] = None,
            error: Optional[str] = None,
            query: Optional[dict[str, str]] = None,
        ) -> None:
            query_parts = []
            if message:
                query_parts.append(f"message={quote_plus(message)}")
            if error:
                query_parts.append(f"error={quote_plus(error)}")
            for key, value in (query or {}).items():
                if value:
                    query_parts.append(f"{quote_plus(key)}={quote_plus(value)}")
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

        def _send_named_asset(self, request_path: str) -> None:
            relative = request_path.removeprefix("/assets/")
            candidate = (ASSET_ROOT / relative).resolve()
            if ASSET_ROOT not in candidate.parents and candidate != ASSET_ROOT:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = asset_content_type(candidate)
            self._send_asset(candidate, content_type)

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


def render_page(
    message: Optional[str] = None,
    error: Optional[str] = None,
    selected_question_id: Optional[str] = None,
) -> str:
    try:
        status = get_controller().status()
        initialized = True
    except LearningAgentError as exc:
        initialized = False
        status = None
        if not error:
            error = str(exc)
    else:
        status, auto_error = maybe_autoload_learning_assist(status)
        if not error and auto_error:
            error = auto_error

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Learning Agent</title>
  <link rel="icon" type="image/png" href="/favicon.ico">
  <style>
    :root {{
      --bg: #f2efe7;
      --surface: rgba(255, 252, 245, 0.92);
      --surface-strong: #fffdf9;
      --surface-alt: #e6edf2;
      --border: #c7d2da;
      --text: #17212b;
      --muted: #5d6b79;
      --accent: #0f5f8c;
      --accent-dark: #0b4667;
      --accent-soft: #dcebf4;
      --danger: #a61b39;
      --danger-soft: #fff0f3;
      --success: #1f6a43;
      --success-soft: #edf9f1;
      --warning: #9a5a0a;
      --warning-soft: #fff6e8;
      --shadow: 0 22px 60px rgba(23, 33, 43, 0.10);
      --sidebar-width: 380px;
      --course-bar-space: 104px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif;
      background:
        radial-gradient(circle at top left, rgba(15, 95, 140, 0.12), transparent 28%),
        radial-gradient(circle at top right, rgba(166, 27, 57, 0.06), transparent 26%),
        linear-gradient(180deg, #f8f5ef 0%, var(--bg) 100%);
      color: var(--text);
    }}
    main {{
      width: min(1320px, calc(100vw - 40px));
      margin: 0 auto;
      padding: 28px 20px calc(var(--course-bar-space) + 24px);
      transition: width 180ms ease, margin-left 180ms ease, margin-right 180ms ease;
    }}
    body:not(.sidebar-collapsed) main {{
      width: min(1320px, calc(100vw - var(--sidebar-width) - 72px));
      margin-left: calc(var(--sidebar-width) + 36px);
      margin-right: 36px;
    }}
    .brand {{
      display: inline-flex;
      align-items: center;
      gap: 14px;
      color: inherit;
      text-decoration: none;
    }}
    .course-bar {{
      position: fixed;
      left: 0;
      right: 0;
      bottom: 0;
      z-index: 35;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      padding: 12px 32px max(12px, env(safe-area-inset-bottom, 0px));
      border: 1px solid rgba(118, 156, 181, 0.45);
      border-bottom: 0;
      border-radius: 18px 18px 0 0;
      background: rgba(255, 252, 245, 0.98);
      box-shadow: 0 20px 50px rgba(23, 33, 43, 0.14);
      backdrop-filter: blur(10px);
    }}
    .course-bar-copy {{
      min-width: 0;
      display: grid;
      gap: 4px;
    }}
    .course-bar-title {{
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-weight: 700;
      color: var(--text);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .course-bar-meta {{
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.84rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--accent-dark);
    }}
    .course-bar-step {{
      flex-shrink: 0;
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
    a {{
      color: inherit;
    }}
    .topbar {{
      display: grid;
      grid-template-columns: 1.4fr 0.9fr;
      gap: 20px;
      align-items: stretch;
      margin-bottom: 18px;
    }}
    .hero-card, .panel, .workflow-step, .subpanel {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 22px;
      box-shadow: var(--shadow);
      padding: 22px;
      backdrop-filter: blur(8px);
    }}
    .topbar-main {{
      display: grid;
      gap: 18px;
    }}
    .hero-copy {{
      display: grid;
      gap: 14px;
    }}
    .hero-copy p {{
      margin: 0;
    }}
    .hero-meta {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .pill {{
      border-radius: 999px;
      padding: 8px 12px;
      background: var(--surface-alt);
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .pill strong {{
      color: var(--text);
    }}
    .status-badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 999px;
      padding: 6px 12px;
      font-size: 0.82rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      font-weight: 700;
      border: 1px solid var(--border);
      background: #f4f7fa;
      color: var(--muted);
    }}
    .status-badge.passed {{
      background: var(--success-soft);
      border-color: #9fd0b1;
      color: var(--success);
    }}
    .status-badge.in_progress {{
      background: var(--accent-soft);
      border-color: #a8c8db;
      color: var(--accent-dark);
    }}
    .status-badge.failed {{
      background: var(--danger-soft);
      border-color: #ecb6c1;
      color: var(--danger);
    }}
    .status-badge.not_started {{
      background: #f4f7fa;
      border-color: var(--border);
      color: var(--muted);
    }}
    .status-badge.draft {{
      background: var(--warning-soft);
      border-color: #e7c38d;
      color: var(--warning);
    }}
    .cta-card {{
      display: grid;
      gap: 14px;
      align-content: space-between;
    }}
    .cta-card p {{
      margin: 0;
    }}
    .sidebar-edge-toggle {{
      position: fixed;
      top: 18px;
      left: calc(var(--sidebar-width) + 28px);
      z-index: 40;
      appearance: none;
      border: 1px solid var(--border);
      border-radius: 14px;
      width: 42px;
      height: 42px;
      padding: 0;
      background: rgba(255, 255, 255, 0.92);
      box-shadow: 0 16px 40px rgba(23, 33, 43, 0.14);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      transition: left 180ms ease, background 160ms ease, border-color 160ms ease;
    }}
    .sidebar-icon {{
      position: relative;
      display: inline-block;
      width: 20px;
      height: 18px;
      transition: transform 160ms ease;
    }}
    .sidebar-icon::before {{
      content: "";
      position: absolute;
      top: 1px;
      bottom: 1px;
      left: 2px;
      width: 4px;
      border-radius: 999px;
      background: var(--accent-dark);
      transition: opacity 160ms ease, background 160ms ease;
    }}
    .sidebar-icon::after {{
      content: "";
      position: absolute;
      top: 50%;
      right: 2px;
      width: 7px;
      height: 7px;
      border-top: 2px solid var(--accent-dark);
      border-right: 2px solid var(--accent-dark);
      transform: translateY(-50%) rotate(45deg);
      transform-origin: center;
      transition: transform 160ms ease, right 160ms ease, border-color 160ms ease;
    }}
    body.sidebar-collapsed .sidebar-edge-toggle {{
      left: 16px;
      background: rgba(220, 235, 244, 0.96);
      border-color: rgba(118, 156, 181, 0.65);
    }}
    body.sidebar-collapsed .sidebar-icon::before {{
      opacity: 0.45;
    }}
    body.sidebar-collapsed .sidebar-icon::after {{
      transform: translateY(-50%) rotate(225deg);
    }}
    body:not(.sidebar-collapsed) .sidebar-edge-toggle:hover,
    body.sidebar-collapsed .sidebar-edge-toggle:hover {{
      background: rgba(234, 243, 248, 0.98);
      border-color: rgba(118, 156, 181, 0.75);
      align-items: center;
    }}
    .workflow-shell {{
      display: block;
    }}
    .workflow-main {{
      display: grid;
      gap: 18px;
    }}
    .left-sidebar {{
      position: fixed;
      top: 24px;
      left: 20px;
      bottom: calc(var(--course-bar-space) + 20px);
      width: min(var(--sidebar-width), calc(100vw - 40px));
      overflow: hidden;
      z-index: 30;
      transition: opacity 180ms ease, transform 180ms ease;
    }}
    .left-sidebar-scroll {{
      display: grid;
      gap: 18px;
      align-content: start;
      overflow-y: auto;
      height: 100%;
      padding-right: 4px;
    }}
    body.sidebar-collapsed .left-sidebar {{
      transform: translateX(calc(-100% - 32px));
      opacity: 0;
      pointer-events: none;
    }}
    body.sidebar-collapsed .sidebar-edge-toggle {{
      left: 16px;
    }}
    .left-sidebar .subgrid {{
      grid-template-columns: 1fr;
    }}
    .left-sidebar .subpanel {{
      min-width: 0;
    }}
    .summary-list li, .metric-list li, .gate-list li, .artifact-list li {{
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .step-nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .step-link {{
      text-decoration: none;
      border-radius: 999px;
      padding: 10px 14px;
      border: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.65);
      display: inline-flex;
      align-items: center;
      gap: 10px;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.92rem;
    }}
    .step-link.current {{
      background: var(--accent-soft);
      border-color: #9ebfd4;
    }}
    .workflow-step {{
      padding: 0;
      overflow: hidden;
    }}
    .workflow-step[open] {{
      background: var(--surface-strong);
    }}
    .workflow-step.current {{
      border-color: #8db4cb;
      box-shadow: 0 26px 70px rgba(15, 95, 140, 0.14);
    }}
    .step-summary {{
      list-style: none;
      cursor: pointer;
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 10px;
      padding: 20px 22px;
      align-items: start;
    }}
    .step-summary::-webkit-details-marker {{
      display: none;
    }}
    .step-summary::before {{
      content: "▶";
      width: 16px;
      margin-top: 2px;
      font-size: 0.95rem;
      line-height: 1;
      color: var(--accent-dark);
      transition: transform 140ms ease;
      opacity: 0.9;
    }}
    .workflow-step[open] .step-summary::before {{
      transform: rotate(90deg);
    }}
    .step-title-row {{
      display: flex;
      gap: 12px;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
    }}
    .step-kicker {{
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      color: var(--accent-dark);
      letter-spacing: 0.12em;
      text-transform: uppercase;
      font-size: 0.78rem;
      font-weight: 700;
    }}
    .step-summary p {{
      grid-column: 2;
      margin: 0;
    }}
    .step-body {{
      border-top: 1px solid rgba(199, 210, 218, 0.8);
      padding: 0 22px 22px;
      display: grid;
      gap: 18px;
    }}
    .step-intro {{
      display: grid;
      gap: 8px;
      padding-top: 18px;
    }}
    .step-intro p {{
      margin: 0;
    }}
    .subgrid {{
      display: grid;
      gap: 16px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .learn-workspace {{
      display: grid;
      grid-template-columns: minmax(0, 1.5fr) minmax(280px, 0.78fr);
      gap: 18px;
      align-items: start;
    }}
    .reading-column, .reading-column-scroll, .questions-column, .reading-stack {{
      display: grid;
      gap: 16px;
    }}
    .questions-column {{
      align-content: start;
      padding-right: 6px;
      overflow: visible;
    }}
    .reading-column {{
      position: sticky;
      top: 18px;
      align-self: start;
      max-height: calc(100vh - 36px);
      overflow: hidden;
      border: 1px solid rgba(199, 210, 218, 0.9);
      border-radius: 20px;
      background: rgba(255, 255, 255, 0.24);
    }}
    .reading-column-scroll {{
      max-height: calc(100vh - 36px);
      overflow-y: auto;
      padding: 12px 10px 12px 12px;
    }}
    .subpanel {{
      border-radius: 18px;
      padding: 18px;
      box-shadow: none;
      background: rgba(255, 255, 255, 0.55);
    }}
    .subpanel h3 {{
      margin-bottom: 10px;
      font-size: 1rem;
    }}
    .stack {{
      display: grid;
      gap: 10px;
    }}
    .summary-list, .metric-list, .gate-list, .artifact-list {{
      margin: 0;
      padding-left: 18px;
      display: grid;
      gap: 8px;
    }}
    .summary-list.tight, .metric-list.tight, .gate-list.tight, .artifact-list.tight {{
      gap: 6px;
    }}
    .notice {{
      border-radius: 16px;
      padding: 14px 16px;
      margin-bottom: 18px;
      border: 1px solid var(--border);
      background: #f6f2e8;
    }}
    .notice.success {{
      border-color: #8fd3ad;
      background: var(--success-soft);
      color: var(--success);
    }}
    .notice.error {{
      border-color: #f2a7b8;
      background: var(--danger-soft);
      color: var(--danger);
    }}
    .help-panel {{
      margin-bottom: 18px;
    }}
    .help-panel summary {{
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 10px;
      list-style: none;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-weight: 600;
      color: var(--accent-dark);
    }}
    .help-panel summary::-webkit-details-marker {{
      display: none;
    }}
    .help-panel summary::before {{
      content: "▶";
      font-size: 0.95rem;
      line-height: 1;
      color: var(--accent-dark);
      transition: transform 140ms ease;
      opacity: 0.9;
    }}
    .help-panel[open] summary::before {{
      transform: rotate(90deg);
    }}
    .help-grid {{
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      margin-top: 14px;
    }}
    .help-grid p {{
      margin: 0;
    }}
    .form-grid {{
      display: grid;
      gap: 12px;
    }}
    .action-grid {{
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
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
      background: #fffdf9;
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
    button:disabled {{
      cursor: not-allowed;
      opacity: 0.55;
    }}
    button.secondary {{
      background: #334155;
    }}
    button.warn {{
      background: var(--danger);
    }}
    .button-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 44px;
      padding: 11px 16px;
      border-radius: 14px;
      text-decoration: none;
      background: var(--accent);
      color: white;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-weight: 600;
    }}
    .button-link.secondary {{
      background: #334155;
    }}
    .button-link.is-disabled {{
      background: #cbd5e1;
      color: #607081;
      cursor: not-allowed;
      pointer-events: none;
    }}
    .inline-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .key-value {{
      display: grid;
      gap: 10px;
    }}
    .key-value-item {{
      border: 1px solid rgba(199, 210, 218, 0.8);
      border-radius: 14px;
      padding: 12px 14px;
      background: rgba(255, 255, 255, 0.55);
    }}
    .key-value-item strong {{
      display: block;
      margin-bottom: 4px;
    }}
    .concept-card-grid {{
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .concept-card {{
      overflow: hidden;
      border: 1px solid rgba(199, 210, 218, 0.9);
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.84);
    }}
    .concept-card figure, .reading-figure {{
      margin: 0;
    }}
    .concept-card-figure {{
      aspect-ratio: 16 / 10;
      background: linear-gradient(180deg, #eef5f8, #ffffff);
      border-bottom: 1px solid rgba(199, 210, 218, 0.9);
    }}
    .concept-card-figure img, .reading-figure img {{
      display: block;
      width: 100%;
      height: 100%;
      object-fit: cover;
    }}
    .concept-card-body {{
      padding: 16px;
      display: grid;
      gap: 10px;
    }}
    .card-chip {{
      display: inline-flex;
      width: fit-content;
      padding: 6px 10px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent-dark);
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.8rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    .reading-section {{
      border-top: 1px solid rgba(199, 210, 218, 0.85);
      padding-top: 16px;
      scroll-margin-top: 16px;
    }}
    .reading-section:first-child {{
      border-top: 0;
      padding-top: 0;
    }}
    .reading-figure {{
      border: 1px solid rgba(199, 210, 218, 0.9);
      border-radius: 16px;
      overflow: hidden;
      background: #f8fbfd;
      margin-bottom: 12px;
    }}
    .reading-caption {{
      padding: 10px 12px;
      font-size: 0.88rem;
      color: var(--muted);
      border-top: 1px solid rgba(199, 210, 218, 0.85);
      background: rgba(255, 255, 255, 0.8);
    }}
    .rendered-markdown {{
      display: grid;
      gap: 10px;
    }}
    .rendered-markdown p, .rendered-markdown ul {{
      margin: 0;
    }}
    .rendered-markdown ul {{
      padding-left: 18px;
    }}
    .question-column {{
      display: grid;
      gap: 14px;
      align-content: start;
      background: linear-gradient(180deg, rgba(236, 245, 250, 0.96), rgba(250, 252, 253, 0.92));
      border: 1px solid rgba(118, 156, 181, 0.55);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.8);
    }}
    .question-stepper {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }}
    .question-step-link, .question-stepper .is-disabled {{
      min-width: 44px;
    }}
    .question-nav-arrow {{
      width: 44px;
      min-width: 44px;
      min-height: 44px;
      padding: 0;
      border-radius: 999px;
      font-size: 1.2rem;
      line-height: 1;
    }}
    .question-stepper .is-disabled.question-nav-arrow {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }}
    .progress-block {{
      display: grid;
      gap: 8px;
    }}
    .progress-meta {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 8px;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.9rem;
      color: var(--muted);
    }}
    .progress-track {{
      width: 100%;
      height: 12px;
      overflow: hidden;
      border-radius: 999px;
      background: rgba(174, 194, 208, 0.45);
      border: 1px solid rgba(118, 156, 181, 0.35);
    }}
    .progress-fill {{
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, var(--accent) 0%, #4f8db0 100%);
      transition: width 180ms ease;
    }}
    .question-modal {{
      width: min(760px, calc(100vw - 32px));
      max-height: min(84vh, 920px);
      padding: 0;
      border: 1px solid rgba(118, 156, 181, 0.45);
      border-radius: 22px;
      background: #fffdf9;
      box-shadow: 0 30px 90px rgba(23, 33, 43, 0.22);
      color: var(--text);
    }}
    .question-modal::backdrop {{
      background: rgba(23, 33, 43, 0.45);
      backdrop-filter: blur(3px);
    }}
    .question-modal-body {{
      display: grid;
      gap: 18px;
      padding: 22px;
    }}
    .question-modal-header {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: start;
    }}
    .question-modal-header p {{
      margin: 0;
    }}
    .question-modal-close {{
      min-width: 44px;
      min-height: 44px;
      padding: 0 14px;
      font-size: 1.2rem;
      line-height: 1;
    }}
    .question-modal-list {{
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 10px;
      overflow-y: auto;
      max-height: min(60vh, 640px);
    }}
    .question-modal-item {{
      display: grid;
    }}
    .question-modal-link {{
      display: grid;
      gap: 10px;
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid rgba(199, 210, 218, 0.9);
      background: rgba(245, 249, 252, 0.92);
      text-decoration: none;
      color: inherit;
    }}
    .question-modal-link.current {{
      background: linear-gradient(180deg, rgba(220, 235, 244, 0.95), rgba(239, 247, 251, 0.94));
      border-color: rgba(118, 156, 181, 0.7);
    }}
    .question-modal-meta {{
      display: flex;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }}
    .question-modal-index {{
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.82rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--accent-dark);
    }}
    .question-modal-prompt {{
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.96rem;
      line-height: 1.45;
      color: var(--text);
    }}
    .question-links {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .question-links a {{
      display: inline-flex;
      align-items: center;
      padding: 8px 10px;
      border-radius: 999px;
      background: rgba(255,255,255,0.88);
      border: 1px solid rgba(199, 210, 218, 0.9);
      text-decoration: none;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.86rem;
    }}
    .details-block {{
      border: 1px solid rgba(199, 210, 218, 0.9);
      border-radius: 16px;
      padding: 14px 16px;
      background: rgba(255, 255, 255, 0.62);
    }}
    .details-block summary {{
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 10px;
      list-style: none;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-weight: 600;
      color: var(--accent-dark);
    }}
    .details-block summary::-webkit-details-marker {{
      display: none;
    }}
    .details-block summary::before {{
      content: "▶";
      font-size: 0.95rem;
      line-height: 1;
      color: var(--accent-dark);
      transition: transform 140ms ease;
      opacity: 0.9;
    }}
    .details-block[open] summary::before {{
      transform: rotate(90deg);
    }}
    .rubric-inline {{
      margin: 0;
      padding: 0;
      border: 0;
      background: transparent;
      box-shadow: none;
    }}
    .rubric-inline summary {{
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 10px;
      list-style: none;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-weight: 600;
      color: var(--accent-dark);
    }}
    .rubric-inline summary::-webkit-details-marker {{
      display: none;
    }}
    .rubric-inline summary::before {{
      content: "▶";
      font-size: 0.95rem;
      line-height: 1;
      color: var(--accent-dark);
      transition: transform 140ms ease;
      opacity: 0.9;
    }}
    .rubric-inline[open] summary::before {{
      transform: rotate(90deg);
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      background: #f8fbfd;
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 14px;
      overflow-x: auto;
      font-size: 0.92rem;
    }}
    .muted {{ color: var(--muted); }}
    .fine-print {{
      margin: 0;
      font-size: 0.88rem;
      color: var(--muted);
    }}
    @media (max-width: 920px) {{
      .topbar, .workflow-shell, .subgrid, .help-grid, .action-grid, .learn-workspace, .concept-card-grid {{
        grid-template-columns: 1fr;
      }}
      main, body:not(.sidebar-collapsed) main {{
        width: min(1320px, calc(100vw - 24px));
        margin-left: 12px;
        margin-right: 12px;
      }}
      :root {{
        --course-bar-space: 118px;
      }}
      .course-bar {{
        left: 0;
        right: 0;
        bottom: 0;
        align-items: start;
        padding-left: 16px;
        padding-right: 16px;
      }}
      .learn-workspace {{
        height: auto;
      }}
      .reading-column, .reading-column-scroll, .questions-column {{
        position: static;
        max-height: none;
        overflow: visible;
        padding-right: 0;
      }}
      .question-modal {{
        width: min(100vw - 20px, 760px);
      }}
      .questions-column {{
        position: static;
      }}
      .left-sidebar {{
        top: 12px;
        left: 12px;
        bottom: calc(var(--course-bar-space) + 12px);
        width: min(92vw, 420px);
      }}
      .left-sidebar-scroll {{
        padding: 8px 2px 8px 0;
      }}
      .sidebar-edge-toggle {{
        left: 16px;
      }}
    }}
  </style>
  {render_flash_cleanup_script(message, error)}
  {render_sidebar_script()}
  {render_summary_selection_script()}
  {render_question_navigation_script(status.get("week") if status else None, message)}
</head>
<body>
  <button id="sidebar-edge-toggle" class="sidebar-edge-toggle" type="button" data-sidebar-toggle aria-controls="left-sidebar" aria-pressed="false" aria-label="Hide sidebar" title="Hide sidebar"><span class="sidebar-icon" aria-hidden="true"><span></span><span></span></span></button>
  <main>
    {render_header(status, initialized)}
    {render_notice(message, error)}
    {render_info_sections()}
    {render_body(status, initialized, selected_question_id=selected_question_id)}
  </main>
  {render_course_bar(status, initialized)}
  {render_sidebar(status, initialized)}
</body>
</html>"""


def maybe_autoload_learning_assist(status: Optional[dict]) -> tuple[Optional[dict], Optional[str]]:
    if not status or status.get("learning_generated"):
        return status, None

    controller = get_controller()
    try:
        controller.ensure_learning_assist()
        return controller.status(), None
    except Exception as exc:  # pragma: no cover - defensive UI fallback
        if suppress_autoload_error(exc):
            return status, None
        return status, f"Learning Assist could not auto-load: {exc}"


def suppress_autoload_error(exc: Exception) -> bool:
    message = str(exc)
    suppressed_prefixes = (
        "OPENAI_API_KEY must be set",
        "Config field `model` must be set",
        "The `openai` package is not installed.",
    )
    suppressed_types = {"APIConnectionError", "APITimeoutError", "ConnectError", "TimeoutException"}
    return any(message.startswith(prefix) for prefix in suppressed_prefixes) or exc.__class__.__name__ in suppressed_types


def render_header(status: Optional[dict], initialized: bool) -> str:
    current_step = current_workflow_step(status) if initialized and status else None
    current_label = workflow_label(current_step) if current_step else "Set Up"
    current_reason = workflow_reason(status, current_step) if current_step else "Initialize Week 1 to begin."
    return f"""
    <section class="topbar">
      <div class="hero-card topbar-main">
        <div class="hero-copy">
          <a class="brand" href="/" aria-label="Learning Agent home">
            <img class="brand-mark" src="/assets/icon.png" alt="Learning Agent icon">
            <span class="brand-copy">
              <span class="brand-label">Learning Agent</span>
              <h1>Mentor Control Surface</h1>
            </span>
          </a>
          <p class="muted">A calmer, guided workflow for the Phase 1 learning loop. The page now focuses on the current step instead of showing every control at once.</p>
          <div class="hero-meta">
            <span class="pill">Local only</span>
            <span class="pill">Port {DEFAULT_UI_PORT}</span>
            <span class="pill">Current step: <strong>{escape(current_label)}</strong></span>
          </div>
        </div>
        {render_state_summary(status, initialized)}
      </div>
      <div class="hero-card cta-card">
        <div class="stack">
          <span class="brand-label">Next Action</span>
          <h2>{escape(current_label)}</h2>
          <p class="muted">{escape(current_reason)}</p>
        </div>
        {render_primary_action(status, initialized)}
      </div>
    </section>
    """


def render_state_summary(status: Optional[dict], initialized: bool) -> str:
    if not initialized or not status:
        return """
        <div class="stack">
          <h2>Current State</h2>
          <p class="muted">No ledger loaded yet. Initialize Week 1 to begin.</p>
        </div>
        """

    gates = status["gates"]
    complete_count = sum(1 for value in gates.values() if value)
    return (
        f"<div class='stack'>"
        f"<h2>Week {status['week']}</h2>"
        f"<p><strong>{escape(status['title'])}</strong></p>"
        f"<p class='muted'>{escape(status['goal'])}</p>"
        f"<div class='inline-meta'>"
        f"<span class='pill'>{complete_count}/5 gate checks complete</span>"
        f"<span class='pill'>{len(status['completed_files'])}/{len(status['required_files'])} files present</span>"
        f"</div>"
        f"</div>"
    )


def render_course_bar(status: Optional[dict], initialized: bool) -> str:
    if not initialized or not status:
        return """
        <div class="course-bar" data-course-bar>
          <div class="course-bar-copy">
            <span class="course-bar-meta">Course Position</span>
            <span class="course-bar-title">Initialize Week 1 to start the course</span>
          </div>
        </div>
        """

    current_step = current_workflow_step(status)
    return f"""
    <div class="course-bar" data-course-bar>
      <div class="course-bar-copy">
        <span class="course-bar-meta">Course Position</span>
        <span class="course-bar-title">Week {status['week']} - {escape(status['title'])}</span>
      </div>
      <div class="course-bar-step">{render_status_badge(step_status(status, current_step))} <span class="fine-print">Current step: {escape(workflow_label(current_step))}</span></div>
    </div>
    """


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


def render_sidebar_script() -> str:
    return """
  <script>
    (function () {
      const storageKey = "learning-agent-sidebar-collapsed";

      function setSidebarState(collapsed) {
        document.body.classList.toggle("sidebar-collapsed", collapsed);
        const buttons = document.querySelectorAll("[data-sidebar-toggle]");
        buttons.forEach(function (button) {
          button.setAttribute("aria-pressed", collapsed ? "true" : "false");
          button.setAttribute("aria-expanded", collapsed ? "false" : "true");
          const label = collapsed ? "Show sidebar" : "Hide sidebar";
          button.setAttribute("aria-label", label);
          button.setAttribute("title", label);
        });
      }

      window.addEventListener("DOMContentLoaded", function () {
        const collapsed = window.localStorage.getItem(storageKey) === "true";
        setSidebarState(collapsed);

        const buttons = document.querySelectorAll("[data-sidebar-toggle]");
        buttons.forEach(function (button) {
          button.addEventListener("click", function () {
            const nextCollapsed = !document.body.classList.contains("sidebar-collapsed");
            window.localStorage.setItem(storageKey, String(nextCollapsed));
            setSidebarState(nextCollapsed);
          });
        });
      });
    })();
  </script>
"""


def render_summary_selection_script() -> str:
    return """
  <script>
    (function () {
      function clearSelection() {
        const selection = window.getSelection ? window.getSelection() : null;
        if (selection && selection.removeAllRanges) {
          selection.removeAllRanges();
        }
      }

      window.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll("details > summary").forEach(function (summary) {
          summary.addEventListener("click", function () {
            window.requestAnimationFrame(clearSelection);
          });
        });
      });
    })();
  </script>
"""


def render_question_navigation_script(current_week: Optional[int], message: Optional[str]) -> str:
    week_literal = "null" if current_week is None else str(current_week)
    message_literal = json.dumps(message or "")
    script = """
  <script>
    (function () {
      const pageScrollKey = "learning-agent-page-scroll";
      const pendingQuestionKey = "learning-agent-pending-question";
      const submittedQuestionKey = "learning-agent-submitted-question";
      const currentWeek = __CURRENT_WEEK__;
      const currentMessage = __CURRENT_MESSAGE__;
      let draftSaveTimer = null;

      function currentQuestionId() {
        return new URL(window.location.href).searchParams.get("question_id") || "";
      }

      function draftKey(questionId) {
        if (!questionId) {
          return "";
        }
        return "learning-agent-draft-week-" + String(currentWeek || "unknown") + "-" + questionId;
      }

      function answerTextarea() {
        return document.querySelector("[data-learning-answer-textarea]");
      }

      function draftStatusNode() {
        return document.querySelector("[data-draft-status]");
      }

      function setDraftStatus(text) {
        const node = draftStatusNode();
        if (node) {
          node.textContent = text || "";
        }
      }

      function questionHasDraft(questionId) {
        if (!questionId) {
          return false;
        }
        const raw = window.localStorage.getItem(draftKey(questionId));
        if (!raw) {
          return false;
        }
        try {
          const payload = JSON.parse(raw);
          return Boolean((payload.value || "").trim());
        } catch (_error) {
          window.localStorage.removeItem(draftKey(questionId));
          return false;
        }
      }

      function badgeLabel(status) {
        const labels = {
          passed: "Done",
          in_progress: "In Progress",
          failed: "Blocked",
          not_started: "Not Started",
          draft: "Draft",
        };
        return labels[status] || status.replaceAll("_", " ");
      }

      function refreshDraftStatuses() {
        document.querySelectorAll("[data-question-status-badge]").forEach(function (badge) {
          const baseStatus = badge.getAttribute("data-base-status") || "not_started";
          const questionId = badge.getAttribute("data-question-id") || "";
          const nextStatus = baseStatus === "not_started" && questionHasDraft(questionId) ? "draft" : baseStatus;
          badge.className = "status-badge " + nextStatus;
          badge.textContent = badgeLabel(nextStatus);
        });
      }

      function saveDraftNow() {
        const questionId = currentQuestionId();
        const textarea = answerTextarea();
        if (!questionId || !textarea) {
          return;
        }
        const key = draftKey(questionId);
        const value = textarea.value;
        if (!value.trim()) {
          window.localStorage.removeItem(key);
          setDraftStatus("");
          refreshDraftStatuses();
          return;
        }
        window.localStorage.setItem(key, JSON.stringify({ value: value, savedAt: Date.now() }));
        setDraftStatus("Draft saved locally");
        refreshDraftStatuses();
      }

      function queueDraftSave() {
        if (draftSaveTimer) {
          window.clearTimeout(draftSaveTimer);
        }
        draftSaveTimer = window.setTimeout(function () {
          saveDraftNow();
          draftSaveTimer = null;
        }, 350);
      }

      function restoreDraft() {
        const questionId = currentQuestionId();
        const textarea = answerTextarea();
        if (!questionId || !textarea) {
          return;
        }
        const raw = window.localStorage.getItem(draftKey(questionId));
        if (!raw) {
          return;
        }
        try {
          const payload = JSON.parse(raw);
          if (!textarea.value) {
            textarea.value = payload.value || "";
          }
          if (payload.value) {
            setDraftStatus("Draft restored");
          }
        } catch (_error) {
          window.localStorage.removeItem(draftKey(questionId));
        }
      }

      function persistQuestionNavigationState(questionId) {
        window.sessionStorage.setItem(pageScrollKey, String(window.scrollY));
        if (questionId) {
          window.sessionStorage.setItem(pendingQuestionKey, questionId);
        }
      }

      window.addEventListener("DOMContentLoaded", function () {
        const pendingQuestionId = window.sessionStorage.getItem(pendingQuestionKey);
        const submittedQuestionId = window.sessionStorage.getItem(submittedQuestionKey);
        const currentId = currentQuestionId();
        const questionModal = document.getElementById("question-list-modal");

        if (pendingQuestionId && pendingQuestionId === currentId) {
          const savedPageScroll = window.sessionStorage.getItem(pageScrollKey);

          if (savedPageScroll !== null) {
            window.scrollTo(0, Number(savedPageScroll));
          }

          window.sessionStorage.removeItem(pageScrollKey);
          window.sessionStorage.removeItem(pendingQuestionKey);
        }

        if (submittedQuestionId && submittedQuestionId === currentId && currentMessage === "Question passed.") {
          window.localStorage.removeItem(draftKey(currentId));
          setDraftStatus("");
          refreshDraftStatuses();
        }
        if (submittedQuestionId && submittedQuestionId === currentId) {
          window.sessionStorage.removeItem(submittedQuestionKey);
        }

        restoreDraft();
        refreshDraftStatuses();

        document.querySelectorAll("[data-question-step-link]").forEach(function (link) {
          link.addEventListener("click", function () {
            saveDraftNow();
            const href = link.getAttribute("href") || "";
            const questionId = new URL(href, window.location.origin).searchParams.get("question_id") || "";
            persistQuestionNavigationState(questionId);
          });
        });

        document.querySelectorAll("[data-question-modal-link]").forEach(function (link) {
          link.addEventListener("click", function (event) {
            event.preventDefault();
            saveDraftNow();
            const href = link.getAttribute("href") || "";
            const questionId = new URL(href, window.location.origin).searchParams.get("question_id") || "";
            persistQuestionNavigationState(questionId);
            if (questionModal && questionModal.open) {
              questionModal.close();
            }
            window.location.href = href;
          });
        });

        document.querySelectorAll("[data-learning-answer-form]").forEach(function (form) {
          form.addEventListener("submit", function () {
            saveDraftNow();
            persistQuestionNavigationState(currentId);
            if (currentId) {
              window.sessionStorage.setItem(submittedQuestionKey, currentId);
            }
          });
        });

        const textarea = answerTextarea();
        if (textarea) {
          textarea.addEventListener("input", function () {
            setDraftStatus("Saving draft...");
            queueDraftSave();
          });
        }

        window.addEventListener("beforeunload", function () {
          saveDraftNow();
        });

        if (questionModal && typeof questionModal.showModal === "function") {
          document.querySelectorAll("[data-question-modal-open]").forEach(function (button) {
            button.addEventListener("click", function () {
              questionModal.showModal();
            });
          });

          document.querySelectorAll("[data-question-modal-close]").forEach(function (button) {
            button.addEventListener("click", function () {
              questionModal.close();
            });
          });

          questionModal.addEventListener("click", function (event) {
            const bounds = questionModal.getBoundingClientRect();
            const inside =
              event.clientX >= bounds.left &&
              event.clientX <= bounds.right &&
              event.clientY >= bounds.top &&
              event.clientY <= bounds.bottom;
            if (!inside) {
              questionModal.close();
            }
          });
        }
      });
    })();
  </script>
"""
    return script.replace("__CURRENT_WEEK__", week_literal).replace("__CURRENT_MESSAGE__", message_literal)


def render_info_sections() -> str:
    return """
    <details class="panel help-panel">
      <summary>How It Works</summary>
      <div class="help-grid">
        <div class="stack">
          <h3>Workflow</h3>
          <p>This platform is a curriculum-driven learning agent for a senior software engineer who wants to learn a new domain by building real artifacts instead of generating code blindly.</p>
          <p>The UI follows the same state machine as the CLI, but presents it as a guided sequence: learn the current week, build the scoped task, verify the evidence, then approve and advance.</p>
        </div>
        <div class="stack">
          <h3>What Changed</h3>
          <p>Long onboarding copy, status readouts, and every form no longer compete for attention on first load. The main column highlights the current step, while the rail keeps scope, checkpoints, and blockers visible.</p>
          <p>Advanced controls such as the legacy gate stay available, but they are tucked into expandable sections instead of dominating the page.</p>
        </div>
      </div>
    </details>
    """


def render_body(status: Optional[dict], initialized: bool, selected_question_id: Optional[str] = None) -> str:
    if not initialized or not status:
        return (
            "<section class='workflow-shell'>"
            "<div class='workflow-main'>"
            "<article class='panel'>"
            "<h2>Quick Start</h2>"
            "<p class='muted'>Create the ledger, load Week 1 from the roadmap, and unlock the workflow rail.</p>"
            f"{render_button_panel('Initialize Week 1', 'Create the ledger and derive the first week from the roadmap.', 'init', 'Start')}"
            "</article>"
            "</div>"
            "</section>"
        )

    gate_session = status.get("gate_session")
    task_session = status.get("task_session")
    learning_session = status.get("learning_session")
    current_step = current_workflow_step(status)
    return (
        "<section class='workflow-shell'>"
        "<div class='workflow-main'>"
        f"{render_workflow_nav(status, current_step)}"
        f"{render_learning_panel(status, learning_session, gate_session, current_step, selected_question_id)}"
        f"{render_task_panel(status, task_session, current_step)}"
        f"{render_observation_status_panel(status, current_step)}"
        f"{render_approval_section(status, current_step)}"
        "</div>"
        "</section>"
    )


def render_sidebar(status: Optional[dict], initialized: bool) -> str:
    if not initialized or not status:
        body = "<article class='panel'><h2>What You Will See</h2><ul class='summary-list tight'><li><strong>Learn:</strong> concept cards and question answering.</li><li><strong>Build:</strong> the generated Junior SWE task and file sync.</li><li><strong>Verify:</strong> metrics, observation, reflection, and verification.</li><li><strong>Approve:</strong> blockers, approval, and week advancement.</li></ul></article>"
    else:
        body = f"{render_blocker_panel(status)}{render_status_panel(status)}{render_checkpoint_panel(status)}"
    return f"<aside id='left-sidebar' class='left-sidebar'><div class='left-sidebar-scroll'>{body}</div></aside>"


def render_workflow_nav(status: dict, current_step: str) -> str:
    items = []
    for step in workflow_steps(status):
        current_class = " current" if step["id"] == current_step else ""
        items.append(
            f"<a class='step-link{current_class}' href='#step-{escape(step['id'])}'>"
            f"<span>{escape(step['label'])}</span>"
            f"{render_status_badge(step['status'])}"
            "</a>"
        )
    return f"<nav class='step-nav'>{''.join(items)}</nav>"


def render_status_panel(status: dict) -> str:
    recorded_metrics = "".join(
        f"<li><strong>{escape(key)}</strong>: {escape(str(value))}</li>" for key, value in status["recorded_metrics"].items()
    ) or "<li class='muted'>(none)</li>"
    required_metrics = "".join(f"<li>{escape(item)}</li>" for item in status["required_metrics"]) or "<li>(none)</li>"
    required = "".join(f"<li>{escape(item)}</li>" for item in status["required_files"]) or "<li>(none)</li>"
    completed = "".join(f"<li>{escape(item)}</li>" for item in status["completed_files"]) or "<li class='muted'>(none)</li>"
    return f"""
    <article class="panel">
      <h2>Week Scope</h2>
      <p class="muted">Active dirs: {escape(', '.join(status['active_dirs']) or '(none)')}</p>
      <div class="subgrid">
        <div class="subpanel">
          <h3>Required Files</h3>
          <ul class="artifact-list tight">{required}</ul>
        </div>
        <div class="subpanel">
          <h3>Completed Files</h3>
          <ul class="artifact-list tight">{completed}</ul>
        </div>
      </div>
      <div class="subgrid">
        <div class="subpanel">
          <h3>Required Metrics</h3>
          <ul class="metric-list tight">{required_metrics}</ul>
        </div>
        <div class="subpanel">
          <h3>Recorded Metrics</h3>
          <ul class="metric-list tight">{recorded_metrics}</ul>
        </div>
      </div>
    </article>
    """


def render_checkpoint_panel(status: dict) -> str:
    checkpoints = "".join(
        "<li>"
        f"<strong>{escape(item['title'])}</strong> {render_status_badge(item['status'])}"
        f"<div class='fine-print'>{escape(item['reason'])}</div>"
        "</li>"
        for item in status.get("checkpoints", [])
    ) or "<li class='muted'>No checkpoints derived yet.</li>"
    return f"""
    <article class="panel">
      <h2>Checkpoint Status</h2>
      <ul class="gate-list tight">{checkpoints}</ul>
    </article>
    """


def render_learning_panel(
    status: dict,
    learning_session: Optional[dict],
    gate_session: Optional[dict],
    current_step: str,
    selected_question_id: Optional[str],
) -> str:
    progress = status.get("question_progress", {})
    questions = (learning_session or {}).get("questions", [])
    attempts = latest_attempts(learning_session)
    figures = {figure["id"]: figure for figure in (learning_session or {}).get("figures", [])}
    reading_sections = (learning_session or {}).get("reading_sections", [])
    selected_question = select_learning_question(questions, selected_question_id)

    cards_html = "".join(render_concept_card(card) for card in (learning_session or {}).get("concept_cards", []))
    if not cards_html:
        cards_html = "<p class='muted'>No concept cards generated yet.</p>"

    sections_html = "".join(
        render_reading_section(section, figures) for section in reading_sections
    ) or "<p class='muted'>No reading material generated yet.</p>"

    workspace_html = render_learning_workspace(selected_question, questions, attempts, figures, progress) if selected_question else """
      <article class="subpanel question-column">
        <h3>Answer Question</h3>
        <p class="muted">Learning content will load automatically for the current week. Once it is ready, this answer workspace will show the current question here.</p>
      </article>
    """
    question_modal_html = render_question_list_modal(questions, attempts, selected_question["id"] if selected_question else None)

    legacy_gate = (
        f"<p class='fine-print'>Legacy gate loaded: {escape(gate_session['prompt']['question'])}</p>" if gate_session else ""
    )
    return f"""
    <details id="step-learn" class="workflow-step {'current' if current_step == 'learn' else ''}" {'open' if current_step == 'learn' else ''}>
      <summary class="step-summary">
        <div class="step-title-row">
          <div>
            <div class="step-kicker">Step 1</div>
            <h2>Learn</h2>
          </div>
          {render_status_badge(step_status(status, 'learn'))}
        </div>
        <p class="muted">{escape(workflow_reason(status, 'learn'))}</p>
      </summary>
      <div class="step-body">
        <div class="step-intro">
          <p><strong>Required coverage:</strong> {progress.get('required_passed', 0)}/{progress.get('required_total', 0)} baseline core questions passed.</p>
          <p class="muted">This step now behaves like an open-book exam: keep the concept cards and reading material open on the left while you answer questions on the right.</p>
        </div>
        <section class="learn-workspace">
          <div class="reading-column">
            <div class="reading-column-scroll">
              <article class="subpanel">
                <h3>Concept Cards</h3>
                <div class="concept-card-grid">{cards_html}</div>
              </article>
              <article class="subpanel">
                <h3>Reading Material</h3>
                <div class="reading-stack">{sections_html}</div>
              </article>
            </div>
          </div>
          <div class="questions-column">
            {workspace_html}
          </div>
        </section>
        {question_modal_html}
        <details class="details-block">
          <summary>Advanced</summary>
          <div class="action-grid" style="margin-top: 14px;">
            {render_button_panel('Ask Legacy Gate', 'Generate the older single-question concept gate if you still want it.', 'gate_ask', 'Ask Gate', secondary=True)}
            {render_gate_submit_panel()}
          </div>
          {legacy_gate}
        </details>
      </div>
    </details>
    """


def render_concept_card(card: dict) -> str:
    figure = ""
    if card.get("image_path"):
        figure = (
            "<figure class='concept-card-figure'>"
            f"<img src=\"{escape(card['image_path'])}\" alt=\"{escape(card.get('image_alt') or card.get('title') or card.get('concept', ''))}\">"
            "</figure>"
        )
    quick_check = (
        f"<div class='fine-print'><strong>Quick check:</strong> {escape(card['quick_check_question'])}</div>"
        if card.get("quick_check_question")
        else ""
    )
    return (
        "<article class='concept-card' id='card-"
        f"{escape(card.get('id') or card.get('concept', 'concept'))}'>"
        f"{figure}"
        "<div class='concept-card-body'>"
        f"<span class='card-chip'>{escape(card.get('title') or card.get('concept', 'Concept'))}</span>"
        f"<div>{escape(card['explanation'])}</div>"
        f"<div class='fine-print'><strong>Why it matters:</strong> {escape(card['why_it_matters'])}</div>"
        f"<div class='fine-print'><strong>Common mistake:</strong> {escape(card['common_mistake'])}</div>"
        f"{quick_check}"
        "</div>"
        "</article>"
    )


def render_reading_section(section: dict, figures: dict[str, dict]) -> str:
    figures_html = ""
    for figure_id in section.get("figure_ids", []):
        figure = figures.get(figure_id)
        if not figure:
            continue
        figures_html += (
            "<figure class='reading-figure'>"
            f"<img src=\"{escape(figure['image_path'])}\" alt=\"{escape(figure['alt_text'])}\">"
            f"<figcaption class='reading-caption'>{escape(figure['caption'])}</figcaption>"
            "</figure>"
        )
    return (
        f"<section class='reading-section' id='{escape(section['id'])}'>"
        f"<h4>{escape(section['title'])}</h4>"
        f"{figures_html}"
        f"{render_markdown_block(section['body_markdown'])}"
        "</section>"
    )


def render_learning_workspace(
    selected_question: dict,
    questions: list[dict],
    attempts: dict[str, dict],
    figures: dict[str, dict],
    progress: dict,
) -> str:
    question_index = next((index for index, question in enumerate(questions) if question["id"] == selected_question["id"]), 0)
    previous_question = questions[question_index - 1] if question_index > 0 else None
    next_question = questions[question_index + 1] if question_index < len(questions) - 1 else None
    required_passed = int(progress.get("required_passed", 0))
    required_total = int(progress.get("required_total", 0))
    progress_percent = 0 if required_total == 0 else round((required_passed / required_total) * 100)
    related_sections = "".join(
        f"<a href='/?question_id={quote_plus(selected_question['id'])}#{escape(section_id)}'>{escape(humanize_section_label(section_id))}</a>"
        for section_id in selected_question.get("related_section_ids", [])
    ) or "<span class='muted'>No linked reading yet.</span>"
    related_cards = "".join(
        f"<a href='/?question_id={quote_plus(selected_question['id'])}#card-{escape(card_id)}'>{escape(humanize_section_label(card_id))}</a>"
        for card_id in selected_question.get("related_concept_ids", [])
    ) or "<span class='muted'>No linked concepts yet.</span>"
    rubric = render_items(selected_question.get("scoring_rubric", []))
    status = question_attempt_status(attempts, selected_question["id"])
    return f"""
    <article class="subpanel question-column" id="question-workspace">
      <div class="step-title-row">
        <div>
          <h3>Answer Question</h3>
          <p class="fine-print">Question {question_index + 1} of {len(questions)}</p>
          <p>{escape(selected_question['prompt_text'])}</p>
        </div>
        {render_question_status_badge(selected_question['id'], status)}
      </div>
      <div class="question-stepper">
        {render_question_step_link(previous_question, "Previous Question", "previous")}
        {render_question_step_link(next_question, "Next Question", "next")}
        <button type="button" class="button-link secondary" data-question-modal-open>See Full Question List</button>
      </div>
      <div class="progress-block" aria-label="Question progress">
        <div class="progress-meta">
          <strong>Correct So Far</strong>
          <span>{required_passed}/{required_total} baseline questions passed</span>
        </div>
        <div class="progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="{required_total}" aria-valuenow="{required_passed}" aria-valuetext="{progress_percent}% complete">
          <div class="progress-fill" style="width: {progress_percent}%;"></div>
        </div>
      </div>
      <div class="question-links">
        {related_sections}
      </div>
      <div class="question-links">
        {related_cards}
      </div>
      <details class="rubric-inline">
        <summary>What A Good Answer Should Cover</summary>
        <ul class="summary-list tight" style="margin-top: 14px;">{rubric}</ul>
      </details>
      <form method="post" action="/action" class="form-grid" data-learning-answer-form>
        <input type="hidden" name="action" value="learning_answer">
        <input type="hidden" name="question_id" value="{escape(selected_question['id'])}">
        <label>Answer
          <textarea name="learning_answer" placeholder="Answer this question while using the material on the left as reference." data-learning-answer-textarea></textarea>
        </label>
        <p class="fine-print" data-draft-status></p>
        <button type="submit">Submit Answer</button>
      </form>
    </article>
    """


def render_question_step_link(question: Optional[dict], label: str, direction: str) -> str:
    icon = "←" if direction == "previous" else "→"
    classes = "button-link secondary question-step-link question-nav-arrow"
    if not question:
        return (
            f"<span class='{classes} is-disabled' aria-label='{escape(label)}' title='{escape(label)}'>"
            f"{icon}"
            "</span>"
        )
    return (
        f"<a class='{classes}' href='/?question_id={quote_plus(question['id'])}' "
        f"data-question-step-link aria-label='{escape(label)}' title='{escape(label)}'>{icon}</a>"
    )


def render_question_list_modal(
    questions: list[dict],
    attempts: dict[str, dict],
    selected_question_id: Optional[str],
) -> str:
    if not questions:
        return ""

    items = []
    for index, question in enumerate(questions, start=1):
        current_class = " current" if question["id"] == selected_question_id else ""
        items.append(
            "<li class='question-modal-item'>"
            f"<a class='question-modal-link{current_class}' href='/?question_id={quote_plus(question['id'])}' data-question-step-link data-question-modal-link>"
            "<div class='question-modal-meta'>"
            f"<span class='question-modal-index'>Question {index}</span>"
            f"{render_question_status_badge(question['id'], question_attempt_status(attempts, question['id']))}"
            "</div>"
            f"<div class='question-modal-prompt'>{escape(question['prompt_text'])}</div>"
            "</a>"
            "</li>"
        )

    return f"""
    <dialog id="question-list-modal" class="question-modal" aria-label="Full question list">
      <div class="question-modal-body">
        <div class="question-modal-header">
          <div class="stack">
            <h3>Full Question List</h3>
            <p class="muted">Browse every question and see which ones are passed, failed, or not started.</p>
          </div>
          <button type="button" class="button-link secondary question-modal-close" data-question-modal-close aria-label="Close question list">×</button>
        </div>
        <ul class="question-modal-list">
          {''.join(items)}
        </ul>
      </div>
    </dialog>
    """


def select_learning_question(questions: list[dict], selected_question_id: Optional[str]) -> Optional[dict]:
    if not questions:
        return None
    if selected_question_id:
        for question in questions:
            if question["id"] == selected_question_id:
                return question
    return questions[0]


def render_task_panel(status: dict, task_session: Optional[dict], current_step: str) -> str:
    if not task_session:
        task_body = "<p class='muted'>No task generated yet. Pass the learning gate first, then generate the scoped implementation brief.</p>"
    else:
        task = task_session["task"]
        task_body = (
            f"<div class='stack'>"
            f"<div><strong>{escape(task['title'])}</strong></div>"
            f"<p class='muted'>{escape(task['objective'])}</p>"
            f"</div>"
            f"<div class='subgrid'>"
            f"<div class='subpanel'><h3>Allowed Dirs</h3><ul class='artifact-list tight'>{render_items(task['allowed_dirs'])}</ul></div>"
            f"<div class='subpanel'><h3>Required Files</h3><ul class='artifact-list tight'>{render_items(task['required_files'])}</ul></div>"
            f"</div>"
            f"<div class='subgrid'>"
            f"<div class='subpanel'><h3>Implementation Steps</h3><ul class='summary-list tight'>{render_items(task['implementation_steps'])}</ul></div>"
            f"<div class='subpanel'><h3>Acceptance Checks</h3><ul class='summary-list tight'>{render_items(task['acceptance_checks'])}</ul></div>"
            f"</div>"
            f"<div class='subpanel'><h3>Verification Expectations</h3><ul class='summary-list tight'>{render_items(task['verification_expectations'])}</ul><p class='fine-print' style='margin-top: 10px;'>{escape(task['summary'])}</p></div>"
        )
    return f"""
    <details id="step-build" class="workflow-step {'current' if current_step == 'build' else ''}" {'open' if current_step == 'build' else ''}>
      <summary class="step-summary">
        <div class="step-title-row">
          <div>
            <div class="step-kicker">Step 2</div>
            <h2>Build</h2>
          </div>
          {render_status_badge(step_status(status, 'build'))}
        </div>
        <p class="muted">{escape(workflow_reason(status, 'build'))}</p>
      </summary>
      <div class="step-body">
        <div class="step-intro">
          <p><strong>Implementation scope:</strong> build only inside the current week's allowed directories and required files.</p>
          <p class="muted">Generate the task once concept coverage passes. After working in the target repo, sync artifacts to update completion progress.</p>
        </div>
        <div class="action-grid">
          {render_button_panel('Generate Task', 'Create the structured Junior SWE task once the gate passes.', 'task_generate', 'Generate Task', disabled=not status.get('can_generate_task'))}
          {render_button_panel('Sync Artifacts', 'Scan the target repo for the required files.', 'record_sync', 'Sync Files', secondary=True)}
        </div>
        <article class="subpanel">
          <h3>Junior SWE Task</h3>
          {task_body}
        </article>
      </div>
    </details>
    """


def render_observation_status_panel(status: dict, current_step: str) -> str:
    observation = status.get("observation")
    reflection = status.get("reflection")
    verification = status.get("verification")
    observation_html = render_record_card(
        "Latest Observation",
        [
            ("Command", observation.get("command")) if observation else None,
            ("Artifact", observation.get("artifact_path")) if observation else None,
            ("Reliability", observation.get("reliability")) if observation else None,
            ("Notes", observation.get("notes")) if observation and observation.get("notes") else None,
        ],
        empty_message="No observation recorded yet.",
    )
    reflection_html = render_record_card(
        "Latest Reflection",
        [
            ("Reflection", reflection.get("text")) if reflection else None,
            ("Trustworthy", str(reflection.get("trustworthy")).lower()) if reflection and reflection.get("trustworthy") is not None else None,
            ("Buggy", "yes" if reflection and reflection.get("buggy") else "no") if reflection else None,
            ("Next Fix", reflection.get("next_fix")) if reflection and reflection.get("next_fix") else None,
        ],
        empty_message="No reflection recorded yet.",
    )
    verification_html = render_record_card(
        "Latest Verification",
        [
            ("Status", "passed" if verification and verification.get("passed") else "failed") if verification else None,
            ("Summary", verification.get("summary")) if verification else None,
        ],
        empty_message="No verification recorded yet.",
    )
    return f"""
    <details id="step-verify" class="workflow-step {'current' if current_step == 'verify' else ''}" {'open' if current_step == 'verify' else ''}>
      <summary class="step-summary">
        <div class="step-title-row">
          <div>
            <div class="step-kicker">Step 3</div>
            <h2>Verify</h2>
          </div>
          {render_status_badge(step_status(status, 'verify'))}
        </div>
        <p class="muted">{escape(workflow_reason(status, 'verify'))}</p>
      </summary>
      <div class="step-body">
        <div class="step-intro">
          <p><strong>Evidence comes before approval.</strong> Record metrics, observations, reflections, and verification results so the week is auditable.</p>
          <p class="muted">This step stays separate from implementation so it is obvious whether the work is merely built or actually trustworthy.</p>
        </div>
        <div class="subgrid">
          {observation_html}
          {reflection_html}
          {verification_html}
        </div>
        <div class="subgrid">
          {render_metric_panel()}
          {render_observation_panel()}
          {render_reflection_panel()}
          {render_verify_panel()}
        </div>
      </div>
    </details>
    """


def render_blocker_panel(status: dict) -> str:
    blockers = status["approval_blockers"]
    if blockers:
        body = "".join(f"<li>{escape(item)}</li>" for item in blockers)
        intro = f"<p class='muted'>{len(blockers)} blocker(s) still need to be cleared before approval.</p>"
    else:
        body = "<li>No blockers. You can approve this week.</li>"
        intro = "<p class='muted'>All blockers are cleared. The approval step is ready.</p>"
    return f"<article class='panel'><h2>Approval Blockers</h2>{intro}<ul class='gate-list tight'>{body}</ul></article>"


def render_approval_section(status: dict, current_step: str) -> str:
    blockers = status["approval_blockers"]
    blocker_html = "".join(f"<li>{escape(item)}</li>" for item in blockers) or "<li>No blockers. You can approve this week.</li>"
    return f"""
    <details id="step-approve" class="workflow-step {'current' if current_step == 'approve' else ''}" {'open' if current_step == 'approve' else ''}>
      <summary class="step-summary">
        <div class="step-title-row">
          <div>
            <div class="step-kicker">Step 4</div>
            <h2>Approve</h2>
          </div>
          {render_status_badge(step_status(status, 'approve'))}
        </div>
        <p class="muted">{escape(workflow_reason(status, 'approve'))}</p>
      </summary>
      <div class="step-body">
        <div class="step-intro">
          <p><strong>Approval is explicit.</strong> The week only advances after concept coverage, implementation, verification, and reliable evidence are all complete.</p>
        </div>
        <article class="subpanel">
          <h3>Approval Checklist</h3>
          <ul class="gate-list">{blocker_html}</ul>
        </article>
        <div class="action-grid">
          {render_button_panel('Approve Week', 'Mark the current week approved once all blockers are cleared.', 'approve', 'Approve', disabled=not status.get('can_approve'))}
          {render_button_panel('Advance Week', 'Move to the next week and reset week-local state.', 'advance', 'Advance', warn=True, disabled=not status['gates']['week_approved'])}
        </div>
        <div class="action-grid">
          {render_button_panel('Initialize', 'Re-run init only if you delete the current ledger first.', 'init', 'Init Again', secondary=True)}
        </div>
      </div>
    </details>
    """


def render_button_panel(
    title: str,
    description: str,
    action: str,
    button_label: str,
    secondary: bool = False,
    warn: bool = False,
    disabled: bool = False,
) -> str:
    button_class = "warn" if warn else "secondary" if secondary else ""
    disabled_attr = " disabled" if disabled else ""
    return f"""
    <article class="subpanel">
      <h3>{escape(title)}</h3>
      <p class="muted">{escape(description)}</p>
      <form method="post" action="/action" class="form-grid">
        <input type="hidden" name="action" value="{escape(action)}">
        <button type="submit" class="{button_class}"{disabled_attr}>{escape(button_label)}</button>
      </form>
    </article>
    """


def render_gate_submit_panel() -> str:
    return """
    <article class="subpanel">
      <h3>Submit Gate Answer</h3>
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
    disabled_attr = " disabled" if not options else ""
    return f"""
    <article class="subpanel">
      <h3>Answer Question</h3>
      <form method="post" action="/action" class="form-grid">
        <input type="hidden" name="action" value="learning_answer">
        <label>Question
          <select name="question_id">{options_html}</select>
        </label>
        <label>Answer
          <textarea name="learning_answer" placeholder="Answer the selected question here..."></textarea>
        </label>
        <button type="submit"{disabled_attr}>Submit Answer</button>
      </form>
    </article>
    """


def render_metric_panel() -> str:
    return """
    <article class="subpanel">
      <h3>Record Metric</h3>
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
    <article class="subpanel">
      <h3>Record Observation</h3>
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
    <article class="subpanel">
      <h3>Record Reflection</h3>
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
    <article class="subpanel">
      <h3>Record Verification</h3>
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


def render_primary_action(status: Optional[dict], initialized: bool) -> str:
    if not initialized or not status:
        return (
            "<form method='post' action='/action' class='form-grid'>"
            "<input type='hidden' name='action' value='init'>"
            "<button type='submit'>Initialize Week 1</button>"
            "</form>"
        )
    step = current_workflow_step(status)
    if step == "build" and not status.get("task_generated"):
        return (
            "<form method='post' action='/action' class='form-grid'>"
            "<input type='hidden' name='action' value='task_generate'>"
            "<button type='submit'>Generate Task</button>"
            "</form>"
        )
    if step == "approve" and status.get("can_approve"):
        return (
            "<form method='post' action='/action' class='form-grid'>"
            "<input type='hidden' name='action' value='approve'>"
            "<button type='submit'>Approve Week</button>"
            "</form>"
        )
    return f"<a class='button-link' href='#step-{escape(step)}'>Open {escape(workflow_label(step))}</a>"


def workflow_steps(status: dict) -> list[dict[str, str]]:
    return [
        {"id": "learn", "label": "Learn", "status": step_status(status, "learn")},
        {"id": "build", "label": "Build", "status": step_status(status, "build")},
        {"id": "verify", "label": "Verify", "status": step_status(status, "verify")},
        {"id": "approve", "label": "Approve", "status": step_status(status, "approve")},
    ]


def current_workflow_step(status: dict) -> str:
    for step in workflow_steps(status):
        if step["status"] != "passed":
            return step["id"]
    return "approve"


def workflow_label(step_id: str) -> str:
    labels = {"learn": "Learn", "build": "Build", "verify": "Verify", "approve": "Approve"}
    return labels.get(step_id, step_id.title())


def workflow_reason(status: dict, step_id: str) -> str:
    if step_id == "learn":
        return checkpoint_reason(status, "core_concepts", "Generate Learning Assist and pass the required questions.")
    if step_id == "build":
        completed = len(status["completed_files"])
        required = len(status["required_files"])
        if status["gates"]["implementation_complete"]:
            return f"{completed}/{required} required files are present."
        if status.get("task_generated"):
            return f"{completed}/{required} required files are present."
        return "Generate the task and start building inside the unlocked scope."
    if step_id == "verify":
        verification = status.get("verification")
        if verification and not verification.get("passed"):
            return "Verification failed. Fix the issue and record a passing result."
        if status.get("evidence_required") and not status["gates"]["evidence_reliable"]:
            return "Reliable evidence is still missing."
        if not status["gates"]["verification_passed"]:
            return "Record a passing verification result."
        return "Verification and evidence look complete."
    if step_id == "approve":
        if status["gates"]["week_approved"]:
            return "This week is approved and ready to advance."
        if status.get("can_approve"):
            return "All blockers are cleared. Approve the week to unlock the next one."
        return f"{len(status['approval_blockers'])} blocker(s) still remain."
    return ""


def checkpoint_reason(status: dict, checkpoint_id: str, fallback: str) -> str:
    for checkpoint in status.get("checkpoints", []):
        if checkpoint["id"] == checkpoint_id:
            return checkpoint["reason"]
    return fallback


def step_status(status: dict, step_id: str) -> str:
    gates = status["gates"]
    if step_id == "learn":
        return checkpoint_status(status, "core_concepts")
    if step_id == "build":
        if gates["implementation_complete"]:
            return "passed"
        if status.get("task_generated") or status["completed_files"]:
            return "in_progress"
        return "not_started"
    if step_id == "verify":
        if gates["verification_passed"] and (not status.get("evidence_required") or gates["evidence_reliable"]):
            return "passed"
        if (status.get("verification") and not gates["verification_passed"]) or (
            status.get("observation") and not gates["evidence_reliable"]
        ):
            return "failed"
        if status.get("verification") or status.get("observation") or status.get("reflection"):
            return "in_progress"
        return "not_started"
    if step_id == "approve":
        if gates["week_approved"]:
            return "passed"
        if status.get("can_approve"):
            return "in_progress"
        return "not_started"
    return "not_started"


def checkpoint_status(status: dict, checkpoint_id: str) -> str:
    for checkpoint in status.get("checkpoints", []):
        if checkpoint["id"] == checkpoint_id:
            return checkpoint["status"]
    return "not_started"


def render_status_badge(status: str) -> str:
    labels = {
        "passed": "Done",
        "in_progress": "In Progress",
        "failed": "Blocked",
        "not_started": "Not Started",
        "draft": "Draft",
    }
    return f"<span class='status-badge {escape(status)}'>{escape(labels.get(status, status.replace('_', ' ')))}</span>"


def render_question_status_badge(question_id: str, status: str) -> str:
    labels = {
        "passed": "Done",
        "in_progress": "In Progress",
        "failed": "Blocked",
        "not_started": "Not Started",
        "draft": "Draft",
    }
    return (
        f"<span class='status-badge {escape(status)}' "
        f"data-question-status-badge data-question-id='{escape(question_id)}' data-base-status='{escape(status)}'>"
        f"{escape(labels.get(status, status.replace('_', ' ')))}"
        "</span>"
    )


def latest_attempts(learning_session: Optional[dict]) -> dict[str, dict]:
    attempts: dict[str, dict] = {}
    for attempt in (learning_session or {}).get("attempts", []):
        attempts[attempt["question_id"]] = attempt
    return attempts


def question_attempt_status(attempts: dict[str, dict], question_id: str) -> str:
    result = attempts.get(question_id, {}).get("result")
    if not result:
        return "not_started"
    return "passed" if result["passed"] else "failed"


def render_items(items: list[str]) -> str:
    if not items:
        return "<li class='muted'>(none)</li>"
    return "".join(f"<li>{escape(item)}</li>" for item in items)


def render_record_card(title: str, rows: list[tuple[str, str] | None], empty_message: str) -> str:
    filtered = [row for row in rows if row]
    if not filtered:
        body = f"<p class='muted'>{escape(empty_message)}</p>"
    else:
        body = "".join(
            "<div class='key-value-item'>"
            f"<strong>{escape(label)}</strong>"
            f"<div>{escape(value)}</div>"
            "</div>"
            for label, value in filtered
        )
        body = f"<div class='key-value'>{body}</div>"
    return f"<article class='subpanel'><h3>{escape(title)}</h3>{body}</article>"


def render_markdown_block(text: str) -> str:
    lines = text.splitlines()
    chunks: list[str] = []
    list_items: list[str] = []
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        chunks.append(f"<p>{render_inline_markup(' '.join(paragraph_lines))}</p>")
        paragraph_lines.clear()

    def flush_list() -> None:
        if not list_items:
            return
        items = "".join(f"<li>{render_inline_markup(item)}</li>" for item in list_items)
        chunks.append(f"<ul>{items}</ul>")
        list_items.clear()

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            flush_list()
            continue
        if line.startswith("- "):
            flush_paragraph()
            list_items.append(line[2:])
            continue
        flush_list()
        paragraph_lines.append(line)

    flush_paragraph()
    flush_list()
    return f"<div class='rendered-markdown'>{''.join(chunks)}</div>"


def render_inline_markup(text: str) -> str:
    escaped = escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)


def humanize_section_label(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("-", "_").split("_") if part)


def asset_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".svg":
        return "image/svg+xml"
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "application/octet-stream"


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

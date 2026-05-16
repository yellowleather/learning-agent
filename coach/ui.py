from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, quote_plus, urlparse

from coach.config import load_config
from coach.orchestrator import WeekOrchestrator
from coach.errors import CoachError
from coach.models import ObservationRecord, ReflectionRecord


DEFAULT_UI_HOST = "127.0.0.1"
DEFAULT_UI_PORT = 4010
ASSET_ROOT = Path(__file__).resolve().parent / "assets"
ICON_PATH = ASSET_ROOT / "icon.png"
DEFAULT_COURSE_WEEKS = 8
MARATHON_TOTAL_MILES = 26.2
MARATHON_RUNNER_POSITION_NUDGE_PERCENT = 0.35
THEME_STORAGE_KEY = "learning-agent-theme-preference"


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
            question_message = first_param(params, "question_message")
            question_error = first_param(params, "question_error")
            selected_question_id = first_param(params, "question_id")
            view_step = first_param(params, "view_step")
            page = render_page(
                message=message,
                error=error,
                question_message=question_message,
                question_error=question_error,
                selected_question_id=selected_question_id,
                view_step=view_step,
            )
            self._send_html(page)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/topic-chat":
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length).decode("utf-8") if length else "{}"
                try:
                    payload = json.loads(raw_body or "{}")
                except json.JSONDecodeError as exc:
                    self._send_ndjson_stream(
                        [{"type": "error", "error": f"Invalid JSON body: {exc.msg}"}],
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return

                self._send_ndjson_stream(run_topic_chat_stream(payload))
                return
            if parsed.path != "/action":
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            length = int(self.headers.get("Content-Length", "0"))
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            action = first_param(form, "action")
            question_id = first_param(form, "question_id")
            try:
                if action == "learning_answer":
                    result = submit_learning_answer(form)
                    feedback_key = "question_message" if result_passed(result) else "question_error"
                    self._redirect(
                        query={
                            "question_id": question_id,
                            feedback_key: learning_answer_feedback_message(result),
                        }
                    )
                else:
                    message = run_action(action, form)
                    self._redirect(message=message, query={"question_id": question_id})
            except CoachError as exc:
                if action == "learning_answer":
                    self._redirect(
                        query={
                            "question_id": question_id,
                            "question_error": str(exc),
                        }
                    )
                else:
                    self._redirect(error=str(exc), query={"question_id": question_id})
            except Exception as exc:  # pragma: no cover
                if action == "learning_answer":
                    self._redirect(
                        query={
                            "question_id": question_id,
                            "question_error": f"Unexpected error: {exc}",
                        }
                    )
                else:
                    self._redirect(error=f"Unexpected error: {exc}", query={"question_id": question_id})

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

        def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_ndjson_stream(
            self,
            events: Iterator[dict[str, Any]] | list[dict[str, Any]],
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                for event in events:
                    encoded = (json.dumps(event) + "\n").encode("utf-8")
                    self.wfile.write(encoded)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):  # pragma: no cover
                return

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


def get_controller() -> WeekOrchestrator:
    repo_root, config = load_config()
    return WeekOrchestrator(repo_root, config)


def submit_learning_answer(form: Dict[str, list[str]]) -> Any:
    controller = get_controller()
    question_id = first_param(form, "question_id").strip()
    answer = first_param(form, "learning_answer").strip()
    if not question_id:
        raise CoachError("Question id cannot be empty.")
    if not answer:
        raise CoachError("Learning answer cannot be empty.")
    return controller.learn.answer_question(question_id, answer)


def learning_answer_feedback_message(result: Any) -> str:
    return "Question passed." if result_passed(result) else "Question failed."


def run_action(action: str, form: Dict[str, list[str]]) -> str:
    if not action:
        raise CoachError("Missing action.")

    controller = get_controller()
    if action == "init":
        ledger = controller.initialize()
        return f"Initialized Week {ledger.state.current_week}."
    if action == "learning_generate":
        session = controller.learn.generate_assist()
        return f"Generated Learning Assist for Week {session.week}."
    if action == "learning_answer":
        result = submit_learning_answer(form)
        return learning_answer_feedback_message(result)
    if action == "task_generate":
        task = controller.build.generate_task()
        return f"Generated task for Week {task.task.week}."
    if action == "record_sync":
        ledger = controller.build.sync_artifacts()
        completed = len(ledger.state.artifacts.completed_files)
        total = len(ledger.state.artifacts.required_files)
        return f"Synced artifacts: {completed}/{total} required files present."
    if action == "record_metric":
        key = first_param(form, "metric_key").strip()
        value = first_param(form, "metric_value").strip()
        if not key:
            raise CoachError("Metric key cannot be empty.")
        if not value:
            raise CoachError("Metric value cannot be empty.")
        try:
            parsed_value = float(value)
        except ValueError as exc:
            raise CoachError("Metric value must be numeric.") from exc
        controller.verify.record_metric(key, parsed_value)
        return f"Recorded metric {key}={parsed_value}."
    if action == "record_observation":
        command = first_param(form, "observation_command").strip()
        artifact_path = first_param(form, "observation_artifact_path").strip()
        reliability = first_param(form, "observation_reliability", default="uncertain").strip() or "uncertain"
        if not command:
            raise CoachError("Observation command cannot be empty.")
        if not artifact_path:
            raise CoachError("Observation artifact path cannot be empty.")
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
        controller.verify.record_observation(observation)
        return "Recorded structured observation."
    if action == "record_verify":
        summary = first_param(form, "verification_summary").strip()
        passed = first_param(form, "verification_passed", default="true") == "true"
        if not summary:
            raise CoachError("Verification summary cannot be empty.")
        controller.verify.record_verification(passed, summary)
        return "Recorded verification result."
    if action == "record_reflection":
        text = first_param(form, "reflection_text").strip()
        if not text:
            raise CoachError("Reflection text cannot be empty.")
        trustworthy = parse_optional_bool(first_param(form, "reflection_trustworthy"))
        buggy = first_param(form, "reflection_buggy", default="false") == "true"
        next_fix = first_param(form, "reflection_next_fix").strip()
        controller.verify.record_reflection(
            ReflectionRecord(text=text, trustworthy=trustworthy, buggy=buggy, next_fix=next_fix)
        )
        return "Recorded reflection."
    if action == "approve":
        ledger = controller.approve_week()
        return f"Approved Week {ledger.state.current_week}."
    if action == "advance":
        ledger = controller.advance_week()
        return f"Advanced to Week {ledger.state.current_week}."

    raise CoachError(f"Unknown action: {action}")


def run_topic_chat_stream(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    try:
        if not isinstance(payload, dict):
            raise CoachError("Topic chat request must be a JSON object.")

        history = payload.get("history") or []
        if not isinstance(history, list):
            raise CoachError("Topic chat history must be a list.")

        current_step = str(payload.get("current_step") or "").strip()
        selected_question_id = str(payload.get("selected_question_id") or "").strip() or None
        selection_context = str(payload.get("selection_context") or "").strip() or None
        message = str(payload.get("message") or "")
        yield from get_controller().stream_topic_chat(
            message=message,
            history=history,
            current_step=current_step,
            selected_question_id=selected_question_id,
            selection_context=selection_context,
        )
    except CoachError as exc:
        yield {"type": "error", "error": str(exc)}
    except Exception as exc:  # pragma: no cover
        yield {"type": "error", "error": f"Unexpected error: {exc}"}


def run_topic_chat(payload: dict[str, Any]) -> dict[str, Any]:
    done_event: dict[str, Any] | None = None
    for event in run_topic_chat_stream(payload):
        event_type = str(event.get("type") or "")
        if event_type == "error":
            raise CoachError(str(event.get("error") or "Topic chat request failed."))
        if event_type == "done":
            done_event = event

    if done_event is None:
        raise CoachError("Topic chat stream ended before a final reply was produced.")
    return {
        "reply": str(done_event.get("reply") or ""),
        "week": done_event.get("week"),
        "context_label": str(done_event.get("context_label") or ""),
    }


def render_page(
    message: Optional[str] = None,
    error: Optional[str] = None,
    question_message: Optional[str] = None,
    question_error: Optional[str] = None,
    selected_question_id: Optional[str] = None,
    view_step: Optional[str] = None,
) -> str:
    course_total_weeks = resolve_course_total_weeks()
    try:
        status = get_controller().status()
        initialized = True
    except CoachError as exc:
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
  {render_theme_script()}
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f8fb;
      --surface: rgba(255, 255, 255, 0.92);
      --surface-strong: rgba(255, 255, 255, 0.98);
      --surface-alt: #eef3f8;
      --surface-utility: rgba(255, 255, 255, 0.82);
      --border: #d9e2ec;
      --border-strong: #c7d3e0;
      --text: #1a2433;
      --muted: #667085;
      --accent: #1d66d2;
      --accent-dark: #154ea8;
      --accent-soft: #e8f0ff;
      --danger: #a61b39;
      --danger-soft: #fff0f3;
      --success: #1d7a5c;
      --success-soft: #edf9f1;
      --warning: #a76519;
      --warning-soft: #fff6e8;
      --shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
      --shadow-soft: 0 8px 24px rgba(15, 23, 42, 0.06);
      --left-rail-width: 236px;
      --left-resizer-width: 12px;
      --right-rail-width: 250px;
      --right-resizer-width: 12px;
      --assessment-side-width: 244px;
      --sidebar-width: 340px;
      --course-bar-space: 88px;
    }}
    html[data-theme="dark"] {{
      color-scheme: dark;
      --bg: #0e1520;
      --surface: rgba(17, 24, 36, 0.9);
      --surface-strong: rgba(17, 24, 36, 0.98);
      --surface-alt: #162131;
      --surface-utility: rgba(17, 24, 36, 0.82);
      --border: #2a3a52;
      --border-strong: #36506f;
      --text: #e7eef9;
      --muted: #9fb0c6;
      --accent: #74b0ff;
      --accent-dark: #c6ddff;
      --accent-soft: rgba(70, 115, 187, 0.22);
      --danger: #ff9ab0;
      --danger-soft: rgba(116, 35, 54, 0.28);
      --success: #7ed9b1;
      --success-soft: rgba(28, 92, 68, 0.28);
      --warning: #f0c27e;
      --warning-soft: rgba(120, 82, 30, 0.28);
      --shadow: 0 18px 40px rgba(0, 0, 0, 0.35);
      --shadow-soft: 0 10px 26px rgba(0, 0, 0, 0.28);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif;
      background:
        radial-gradient(circle at top center, rgba(49, 114, 216, 0.1), transparent 28%),
        linear-gradient(180deg, #fbfcfe 0%, #f4f7fb 42%, #f3f6fb 100%);
      color: var(--text);
      transition: background 180ms ease, color 180ms ease;
    }}
    html[data-theme="dark"] body {{
      background:
        radial-gradient(circle at top center, rgba(116, 176, 255, 0.16), transparent 30%),
        linear-gradient(180deg, #0d131c 0%, #101926 44%, #0f1723 100%);
    }}
    main {{
      width: min(1320px, calc(100vw - 40px));
      margin: 0 auto;
      padding: 28px 20px calc(var(--course-bar-space) + 24px);
      transition: width 180ms ease, margin-left 180ms ease, margin-right 180ms ease;
    }}
    body.left-rail-open:not(.narrow-rails) main {{
      width: min(1320px, calc(100vw - var(--sidebar-width) - 72px));
      margin-left: calc(var(--sidebar-width) + 36px);
      margin-right: 36px;
    }}
    body.right-rail-open:not(.narrow-rails) main {{
      width: min(1320px, calc(100vw - var(--sidebar-width) - 72px));
      margin-left: 36px;
      margin-right: calc(var(--sidebar-width) + 36px);
    }}
    body.left-rail-open.right-rail-open:not(.narrow-rails) main {{
      width: min(1320px, calc(100vw - (var(--sidebar-width) * 2) - 108px));
      margin-left: calc(var(--sidebar-width) + 28px);
      margin-right: calc(var(--sidebar-width) + 28px);
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
      padding: 10px 28px max(10px, env(safe-area-inset-bottom, 0px));
      border: 1px solid rgba(168, 186, 196, 0.55);
      border-bottom: 0;
      border-radius: 22px 22px 0 0;
      background: rgba(255, 252, 247, 0.96);
      box-shadow: 0 18px 40px rgba(23, 33, 43, 0.12);
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
      border: 1px solid rgba(191, 208, 220, 0.85);
      border-radius: 22px;
      box-shadow: var(--shadow-soft);
      padding: 22px;
      backdrop-filter: blur(8px);
    }}
    .topbar-main {{
      display: grid;
      gap: 18px;
    }}
    .brand {{
      display: inline-flex;
      align-items: start;
      gap: 16px;
      text-decoration: none;
    }}
    .hero-copy {{
      display: grid;
      gap: 18px;
    }}
    .hero-copy p {{
      margin: 0;
    }}
    .hero-support {{
      max-width: 42rem;
    }}
    .hero-meta {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .hero-meta-primary {{
      margin-top: 2px;
    }}
    .hero-meta-secondary {{
      gap: 8px;
    }}
    .pill {{
      border-radius: 999px;
      padding: 8px 12px;
      background: var(--surface-alt);
      color: var(--accent-dark);
      font-size: 0.92rem;
    }}
    .pill.subtle {{
      padding: 6px 10px;
      background: rgba(255, 255, 255, 0.66);
      border: 1px solid rgba(174, 190, 204, 0.7);
      font-size: 0.84rem;
    }}
    .pill strong {{
      color: var(--text);
    }}
    .status-badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 999px;
      padding: 5px 10px;
      font-size: 0.78rem;
      letter-spacing: 0;
      text-transform: none;
      font-weight: 600;
      border: 1px solid rgba(217, 226, 236, 0.95);
      background: rgba(247, 249, 252, 0.96);
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
    .rail-edge-toggle, .sidebar-edge-toggle {{
      position: fixed;
      top: 18px;
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
      transition: left 180ms ease, right 180ms ease, background 160ms ease, border-color 160ms ease;
    }}
    .rail-edge-toggle-left, .sidebar-edge-toggle {{
      left: calc(var(--sidebar-width) + 28px);
    }}
    .rail-edge-toggle-right {{
      right: calc(var(--sidebar-width) + 28px);
    }}
    .sidebar-icon {{
      position: relative;
      display: inline-block;
      width: 20px;
      height: 18px;
      transition: transform 160ms ease;
    }}
    .rail-edge-toggle-right .sidebar-icon {{
      transform: scaleX(-1);
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
    body.left-rail-collapsed .rail-edge-toggle-left,
    body.left-rail-collapsed .sidebar-edge-toggle {{
      left: 16px;
      background: rgba(220, 235, 244, 0.96);
      border-color: rgba(118, 156, 181, 0.65);
    }}
    body.right-rail-collapsed .rail-edge-toggle-right {{
      right: 16px;
      background: rgba(220, 235, 244, 0.96);
      border-color: rgba(118, 156, 181, 0.65);
    }}
    body.left-rail-collapsed .rail-edge-toggle-left .sidebar-icon::before,
    body.left-rail-collapsed .sidebar-edge-toggle .sidebar-icon::before,
    body.right-rail-collapsed .rail-edge-toggle-right .sidebar-icon::before {{
      opacity: 0.45;
    }}
    body.left-rail-collapsed .rail-edge-toggle-left .sidebar-icon::after,
    body.left-rail-collapsed .sidebar-edge-toggle .sidebar-icon::after,
    body.right-rail-collapsed .rail-edge-toggle-right .sidebar-icon::after {{
      transform: translateY(-50%) rotate(225deg);
    }}
    .rail-edge-toggle:hover,
    .sidebar-edge-toggle:hover {{
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
    .app-rail, .left-sidebar, .right-sidebar {{
      position: fixed;
      top: 24px;
      bottom: calc(var(--course-bar-space) + 20px);
      width: min(var(--sidebar-width), calc(100vw - 40px));
      overflow: hidden;
      z-index: 30;
      transition: opacity 180ms ease, transform 180ms ease;
    }}
    .rail-left, .left-sidebar {{
      left: 20px;
    }}
    .rail-right, .right-sidebar {{
      right: 20px;
    }}
    .app-rail-scroll, .left-sidebar-scroll, .right-sidebar-scroll {{
      display: grid;
      gap: 14px;
      align-content: start;
      overflow-y: auto;
      height: 100%;
      padding-right: 4px;
    }}
    .rail-right .app-rail-scroll, .right-sidebar-scroll {{
      padding-left: 4px;
      padding-right: 0;
    }}
    body.left-rail-collapsed .rail-left,
    body.left-rail-collapsed .left-sidebar {{
      transform: translateX(calc(-100% - 32px));
      opacity: 0;
      pointer-events: none;
    }}
    body.right-rail-collapsed .rail-right,
    body.right-rail-collapsed .right-sidebar {{
      transform: translateX(calc(100% + 32px));
      opacity: 0;
      pointer-events: none;
    }}
    .left-sidebar .subgrid {{
      grid-template-columns: 1fr;
    }}
    .left-sidebar .subpanel {{
      min-width: 0;
    }}
    .right-sidebar .subgrid {{
      grid-template-columns: 1fr;
    }}
    .right-sidebar .subpanel {{
      min-width: 0;
    }}
    .rail-backdrop {{
      position: fixed;
      inset: 0;
      z-index: 25;
      background: rgba(23, 33, 43, 0.28);
      backdrop-filter: blur(2px);
      opacity: 0;
      pointer-events: none;
      transition: opacity 180ms ease;
    }}
    body.narrow-rails.rail-overlay-active .rail-backdrop {{
      opacity: 1;
      pointer-events: auto;
    }}
    .summary-list li, .metric-list li, .gate-list li, .artifact-list li {{
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .step-nav {{ display: none; }}
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
      border: 1px solid rgba(199, 210, 218, 0.75);
      border-radius: 20px;
      background: rgba(255, 255, 255, 0.34);
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
      background: rgba(255, 255, 255, 0.62);
    }}
    .subpanel h3 {{
      margin-bottom: 10px;
      font-size: 1rem;
    }}
    .learn-reading-section-v3 {{
      padding: 18px;
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.74);
      border: 1px solid rgba(191, 208, 220, 0.72);
      box-shadow: var(--shadow-soft);
    }}
    .learn-reading-section-v3 + .learn-reading-section-v3 {{
      margin-top: 18px;
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
    .question-validator-feedback {{
      display: grid;
      gap: 10px;
      margin-top: 14px;
      padding: 14px 16px;
      border-radius: 14px;
      border: 1px solid rgba(191, 208, 220, 0.72);
      background: rgba(248, 251, 255, 0.94);
    }}
    .question-validator-feedback.failed {{
      border-color: rgba(196, 92, 117, 0.35);
      background: rgba(255, 243, 246, 0.96);
    }}
    .question-validator-feedback h4,
    .question-validator-feedback p {{
      margin: 0;
    }}
    .question-validator-feedback ul {{
      margin: 0;
      padding-left: 18px;
      display: grid;
      gap: 6px;
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
      border: 1px solid rgba(208, 218, 230, 0.95);
      background: rgba(255, 255, 255, 0.96);
      border-radius: 14px;
      padding: 11px 13px;
      color: var(--text);
      font-size: 0.96rem;
    }}
    textarea {{ min-height: 110px; resize: vertical; }}
    button {{
      border: 0;
      border-radius: 12px;
      background: linear-gradient(180deg, #2a74e6 0%, #1d66d2 100%);
      color: white;
      padding: 12px 18px;
      font-weight: 600;
      cursor: pointer;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.16), 0 10px 20px rgba(29, 102, 210, 0.18);
    }}
    button:disabled {{
      cursor: not-allowed;
      opacity: 0.55;
    }}
    button.secondary {{
      background: rgba(255, 255, 255, 0.98);
      color: var(--text);
      border: 1px solid rgba(217, 226, 236, 0.95);
      box-shadow: none;
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
      border-radius: 12px;
      text-decoration: none;
      background: linear-gradient(180deg, #2a74e6 0%, #1d66d2 100%);
      color: white;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-weight: 600;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.16), 0 10px 20px rgba(29, 102, 210, 0.18);
    }}
    .button-link.secondary {{
      background: rgba(255, 255, 255, 0.98);
      color: var(--text);
      border: 1px solid rgba(217, 226, 236, 0.95);
      box-shadow: none;
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
      overflow: visible;
      border: 0;
      border-radius: 0;
      background: transparent;
    }}
    .concept-card-body {{
      padding: 0;
      display: grid;
      gap: 8px;
    }}
    .concept-card-details {{
      margin-top: 2px;
      padding: 0;
      border: 0;
      background: transparent;
      box-shadow: none;
    }}
    .concept-card-details summary {{
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 10px;
      list-style: none;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-weight: 600;
      color: var(--accent-dark);
      font-size: 0.86rem;
    }}
    .concept-card-details summary::-webkit-details-marker {{
      display: none;
    }}
    .concept-card-details summary::before {{
      content: "▶";
      font-size: 0.95rem;
      line-height: 1;
      color: var(--accent-dark);
      transition: transform 140ms ease;
      opacity: 0.9;
    }}
    .concept-card-details[open] summary::before {{
      transform: rotate(90deg);
    }}
    .concept-card-details-body {{
      display: grid;
      gap: 8px;
      margin-top: 10px;
    }}
    .concept-card-title {{
      margin: 0;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.9rem;
      font-weight: 700;
      line-height: 1.3;
      color: var(--text);
    }}
    .learn-orientation-panel {{
      display: grid;
      gap: 10px;
      margin-bottom: 18px;
      padding: 16px 18px;
      border: 1px solid rgba(182, 198, 210, 0.9);
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(233, 242, 247, 0.92), rgba(248, 251, 253, 0.96));
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
    }}
    .learn-orientation-kicker {{
      margin-bottom: 0;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--accent-dark);
    }}
    .reading-document {{
      display: grid;
      gap: 18px;
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
    .reading-section-title {{
      margin: 0 0 10px;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.98rem;
      font-weight: 700;
      line-height: 1.3;
      color: var(--text);
    }}
    .rendered-markdown {{
      display: grid;
      gap: 10px;
    }}
    .rendered-markdown p, .rendered-markdown ul, .rendered-markdown ol {{
      margin: 0;
    }}
    .rendered-markdown ul, .rendered-markdown ol {{
      padding-left: 18px;
    }}
    .rendered-markdown li + li {{
      margin-top: 4px;
    }}
    .rendered-markdown pre {{
      margin: 0;
      padding: 12px 14px;
      border-radius: 16px;
      overflow-x: auto;
      background: rgba(17, 24, 39, 0.96);
      color: rgba(244, 247, 250, 0.96);
      border: 1px solid rgba(110, 127, 141, 0.55);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05);
    }}
    .rendered-markdown pre code {{
      display: block;
      font-family: "IBM Plex Mono", "SFMono-Regular", monospace;
      font-size: 0.9rem;
      line-height: 1.55;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .rendered-markdown p code,
    .rendered-markdown li code {{
      padding: 0.08rem 0.34rem;
      border-radius: 6px;
      background: rgba(19, 79, 114, 0.1);
      color: var(--accent-dark);
      font-family: "IBM Plex Mono", "SFMono-Regular", monospace;
      font-size: 0.92em;
    }}
    .question-column {{
      display: grid;
      gap: 14px;
      align-content: start;
      background: linear-gradient(180deg, rgba(239, 245, 248, 0.98), rgba(252, 253, 253, 0.94));
      border: 1px solid rgba(178, 196, 206, 0.8);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.88);
    }}
    .question-stepper {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }}
    .question-jump-form {{
      display: inline-flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      margin-left: auto;
    }}
    .question-jump-form label {{
      font-size: 0.88rem;
      color: var(--muted);
    }}
    .question-jump-form input {{
      width: 88px;
      min-height: 42px;
      padding: 0 12px;
      border-radius: 12px;
      border: 1px solid rgba(178, 196, 206, 0.9);
      background: rgba(255, 255, 255, 0.92);
      font: inherit;
    }}
    .question-jump-form button {{
      min-height: 42px;
      padding: 0 14px;
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
    .required-question-marker {{
      color: #c7332f;
      font-weight: 800;
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
    .topic-chat-panel {{
      display: grid;
      gap: 14px;
      min-height: 100%;
    }}
    .topic-chat-header {{
      display: grid;
      gap: 8px;
    }}
    .topic-chat-header p {{
      margin: 0;
    }}
    .topic-chat-sessions {{
      display: grid;
      gap: 12px;
    }}
    .topic-chat-session-bar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }}
    .topic-chat-session-list {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .topic-chat-session {{
      appearance: none;
      border: 1px solid rgba(199, 210, 218, 0.85);
      border-radius: 999px;
      padding: 8px 12px;
      background: rgba(255, 255, 255, 0.7);
      color: var(--text);
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.88rem;
      line-height: 1.2;
      cursor: pointer;
    }}
    .topic-chat-session.active {{
      background: rgba(220, 235, 244, 0.95);
      border-color: rgba(118, 156, 181, 0.75);
      color: var(--accent-dark);
    }}
    .topic-chat-thread {{
      display: grid;
      gap: 12px;
      align-content: start;
      min-height: 320px;
      max-height: min(56vh, 640px);
      overflow-y: auto;
      padding-right: 4px;
    }}
    .topic-chat-empty {{
      display: grid;
      gap: 12px;
      padding-top: 4px;
    }}
    .topic-chat-empty p {{
      margin: 0;
    }}
    .topic-chat-suggestions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .topic-chat-suggestion {{
      appearance: none;
      border: 1px solid rgba(199, 210, 218, 0.9);
      border-radius: 999px;
      padding: 8px 12px;
      background: rgba(255, 255, 255, 0.82);
      color: var(--accent-dark);
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.86rem;
      cursor: pointer;
    }}
    .topic-chat-message {{
      display: grid;
      gap: 6px;
      padding: 14px 16px;
      max-width: calc(100% - 34px);
      border-radius: 18px 18px 18px 8px;
      background: rgba(255, 255, 255, 0.9);
    }}
    .topic-chat-message[data-role="user"] {{
      justify-self: end;
      border-radius: 18px 18px 8px 18px;
      background: linear-gradient(180deg, rgba(220, 235, 244, 0.96), rgba(236, 244, 249, 0.94));
    }}
    .topic-chat-message[data-role="assistant"] {{
      justify-self: start;
      background: rgba(255, 255, 255, 0.92);
    }}
    .topic-chat-message[data-pending="true"] .topic-chat-content {{
      color: var(--muted);
      font-style: italic;
    }}
    .topic-chat-meta {{
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.78rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--accent-dark);
    }}
    .topic-chat-content {{
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      line-height: 1.5;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }}
    .topic-chat-context-strip {{
      display: grid;
      gap: 8px;
    }}
    .topic-chat-context-chip {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: start;
      padding: 10px 12px;
      border-radius: 16px;
      border: 1px solid rgba(188, 202, 214, 0.94);
      background: linear-gradient(180deg, rgba(244, 248, 251, 0.98), rgba(234, 241, 246, 0.94));
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.92);
    }}
    .topic-chat-context-copy {{
      min-width: 0;
      display: grid;
      gap: 4px;
    }}
    .topic-chat-context-kicker {{
      font-family: "IBM Plex Mono", "SFMono-Regular", monospace;
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--accent-dark);
    }}
    .topic-chat-context-preview {{
      margin: 0;
      min-width: 0;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.84rem;
      line-height: 1.4;
      color: var(--text);
      overflow-wrap: anywhere;
    }}
    .topic-chat-context-clear {{
      width: 28px;
      height: 28px;
      min-height: 28px;
      padding: 0;
      border-radius: 999px;
      box-shadow: none;
    }}
    .topic-chat-toolbar {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .topic-chat-composer textarea {{
      min-height: 92px;
    }}
    .topic-chat-status.error {{
      color: var(--danger);
    }}
    .topic-chat-status.success {{
      color: var(--success);
    }}
    .progress-shell {{
      position: relative;
      display: grid;
      gap: 14px;
      padding: 18px 18px 18px 24px;
      border: 1px solid rgba(191, 208, 220, 0.9);
      border-radius: 28px;
      background: rgba(255, 252, 247, 0.78);
      box-shadow: var(--shadow-soft);
      backdrop-filter: blur(10px);
    }}
    .progress-shell-line {{
      position: absolute;
      top: 28px;
      bottom: 28px;
      left: 32px;
      width: 2px;
      background: linear-gradient(180deg, rgba(21, 95, 134, 0.65), rgba(191, 208, 220, 0.45));
    }}
    .progress-row {{
      position: relative;
      display: grid;
      grid-template-columns: 28px minmax(0, 1fr);
      gap: 14px;
      align-items: start;
    }}
    .progress-node {{
      width: 16px;
      height: 16px;
      margin-top: 14px;
      border-radius: 999px;
      background: rgba(173, 189, 198, 0.85);
      border: 2px solid rgba(255, 255, 255, 0.82);
      box-shadow: 0 0 0 4px rgba(255, 255, 255, 0.34);
      z-index: 1;
    }}
    .progress-row.current .progress-node {{
      width: 20px;
      height: 20px;
      margin-top: 12px;
      background: linear-gradient(180deg, var(--accent), #2a7aa4);
    }}
    .progress-card {{
      display: grid;
      gap: 8px;
      padding: 14px 18px;
      border-radius: 24px;
      background: rgba(255, 255, 255, 0.68);
      border: 1px solid rgba(191, 208, 220, 0.82);
    }}
    .progress-row.current .progress-card {{
      background: rgba(255, 255, 255, 0.84);
      box-shadow: var(--shadow-soft);
    }}
    .progress-card-header {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .progress-card-title {{
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 1.12rem;
      font-weight: 600;
      color: var(--text);
    }}
    .progress-card-copy {{
      margin: 0;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      color: var(--muted);
      line-height: 1.45;
    }}
    .workflow-stage-card {{
      display: grid;
      gap: 18px;
      padding: 22px;
      border-radius: 28px;
      background: rgba(255, 252, 247, 0.92);
      border: 1px solid rgba(191, 208, 220, 0.92);
      box-shadow: var(--shadow);
    }}
    .stage-header {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: start;
      flex-wrap: wrap;
    }}
    .stage-intro {{
      display: grid;
      gap: 8px;
      padding-bottom: 4px;
      border-bottom: 1px solid rgba(191, 208, 220, 0.68);
    }}
    .stage-intro p {{
      margin: 0;
    }}
    .learning-stage-shell {{
      align-items: start;
    }}
    .stage-surface {{
      background: rgba(255, 255, 255, 0.74);
      border: 1px solid rgba(191, 208, 220, 0.72);
    }}
    .stage-advanced {{
      margin-top: 4px;
    }}
    .rail-utility-stack {{
      gap: 12px;
    }}
    .rail-utility-card {{
      background: rgba(255, 255, 255, 0.72);
      border: 1px solid rgba(191, 208, 220, 0.78);
    }}
    .topic-chat-context-tags {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .topic-chat-question-card {{
      display: grid;
      gap: 8px;
      padding: 12px 14px;
      border-radius: 18px;
      border: 1px solid rgba(191, 208, 220, 0.88);
      background: rgba(255, 255, 255, 0.78);
    }}
    .topic-chat-question-card p {{
      margin: 0;
    }}
    .topic-chat-question-label {{
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.82rem;
      font-weight: 700;
      color: var(--text);
    }}
    .topic-chat-thread-shell {{
      padding: 14px;
      border-radius: 22px;
      border: 1px dashed rgba(174, 190, 204, 0.8);
      background: rgba(255, 255, 255, 0.58);
    }}
    .topic-chat-question-button {{
      width: 100%;
      justify-content: center;
    }}
    .topic-chat-toolbar [hidden],
    .topic-chat-sessions[hidden] {{
      display: none !important;
    }}
    @media (max-width: 920px) {{
      .topbar, .workflow-shell, .subgrid, .help-grid, .action-grid, .learn-workspace, .concept-card-grid {{
        grid-template-columns: 1fr;
      }}
      main,
      body.left-rail-open main,
      body.right-rail-open main,
      body.left-rail-open.right-rail-open main {{
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
      .app-rail, .left-sidebar, .right-sidebar {{
        top: 12px;
        bottom: calc(var(--course-bar-space) + 12px);
        width: min(92vw, 420px);
        z-index: 45;
      }}
      .rail-left, .left-sidebar {{
        left: 12px;
      }}
      .rail-right, .right-sidebar {{
        right: 12px;
      }}
      .app-rail-scroll, .left-sidebar-scroll, .right-sidebar-scroll {{
        padding: 8px 2px;
      }}
      .rail-edge-toggle-left, .sidebar-edge-toggle {{
        left: 16px;
      }}
      .rail-edge-toggle-right {{
        right: 16px;
      }}
      .topic-chat-thread {{
        max-height: min(34vh, 360px);
      }}
    }}
    .app-shell-v3 {{
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }}
    .app-topbar-v3 {{
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: 18px;
      align-items: center;
      padding: 12px 18px;
      border-bottom: 1px solid rgba(217, 226, 236, 0.88);
      background: rgba(255, 255, 255, 0.86);
      backdrop-filter: blur(14px);
    }}
    .app-topbar-brand {{
      display: inline-flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }}
    .app-topbar-brand strong {{
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.98rem;
      font-weight: 700;
    }}
    .app-topbar-mark {{
      width: 36px;
      height: 36px;
      border-radius: 10px;
      border: 1px solid rgba(191, 208, 220, 0.9);
      object-fit: cover;
      background: rgba(255, 255, 255, 0.9);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7);
    }}
    .app-topbar-route {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
      min-width: 0;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.96rem;
    }}
    .app-topbar-divider {{
      width: 1px;
      height: 24px;
      background: rgba(191, 208, 220, 0.75);
    }}
    .app-topbar-week {{
      color: var(--muted);
    }}
    .app-topbar-title {{
      font-weight: 700;
      color: var(--text);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .app-topbar-status {{
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 7px 12px;
      border-radius: 999px;
      background: rgba(243, 248, 255, 0.98);
      border: 1px solid rgba(204, 220, 243, 0.95);
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      color: var(--accent-dark);
      font-size: 0.92rem;
    }}
    .app-topbar-status::before {{
      content: "";
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: var(--accent);
      box-shadow: 0 0 0 4px rgba(21, 95, 134, 0.12);
    }}
    .app-topbar-actions {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .app-topbar-search {{
      width: min(220px, 28vw);
      min-width: 164px;
    }}
    .app-topbar-search input {{
      min-height: 38px;
      padding: 9px 14px;
      font-size: 0.92rem;
    }}
    .topbar-action-icon {{
      width: 32px;
      height: 32px;
      border-radius: 999px;
      border: 1px solid rgba(217, 226, 236, 0.95);
      background: rgba(255, 255, 255, 0.98);
      color: var(--muted);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.82rem;
    }}
    .topbar-theme-toggle {{
      width: auto;
      min-width: 74px;
      padding: 0 12px 0 10px;
      gap: 8px;
      font-weight: 700;
    }}
    .topbar-theme-toggle-indicator {{
      width: 14px;
      height: 14px;
      border-radius: 999px;
      flex-shrink: 0;
      background: linear-gradient(135deg, #182537 50%, #ffd37a 50%);
      box-shadow: inset 0 0 0 1px rgba(95, 112, 138, 0.35);
    }}
    html[data-theme="dark"] .topbar-theme-toggle-indicator {{
      background: linear-gradient(135deg, #ffd37a 50%, #182537 50%);
    }}
    .topbar-theme-toggle-label {{
      font-size: 0.76rem;
      letter-spacing: 0.02em;
    }}
    .topbar-avatar {{
      width: 32px;
      height: 32px;
      border-radius: 999px;
      background: linear-gradient(180deg, rgba(21, 95, 134, 0.95), rgba(38, 120, 160, 0.9));
      color: white;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-weight: 700;
      box-shadow: 0 8px 16px rgba(21, 95, 134, 0.18);
    }}
    .app-content-v3 {{
      position: relative;
      display: grid;
      grid-template-columns:
        var(--left-rail-width)
        var(--left-resizer-width)
        minmax(0, 1fr)
        var(--right-resizer-width)
        var(--right-rail-width);
      gap: 0;
      padding: 0;
    }}
    .sidebar-edge-toggle-v3 {{
      --sidebar-edge-toggle-transform: none;
      position: absolute;
      top: 24px;
      z-index: 4;
      width: 34px;
      height: 34px;
      padding: 0;
      border-radius: 999px;
      border: 1px solid rgba(191, 208, 220, 0.94);
      background: rgba(255, 255, 255, 0.96);
      color: var(--accent-dark);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 10px 26px rgba(15, 23, 42, 0.1);
      cursor: pointer;
      transform: var(--sidebar-edge-toggle-transform);
      transition: background 120ms ease, border-color 120ms ease, transform 120ms ease, color 120ms ease;
    }}
    .sidebar-edge-toggle-v3:hover {{
      background: rgba(240, 246, 251, 0.98);
      border-color: rgba(118, 156, 181, 0.75);
      transform: var(--sidebar-edge-toggle-transform) translateY(-1px);
    }}
    .sidebar-edge-toggle-v3-left {{
      left: max(8px, calc(var(--left-rail-width) + var(--left-resizer-width) - 16px));
    }}
    .sidebar-edge-toggle-v3-right {{
      right: max(8px, calc(var(--right-rail-width) + var(--right-resizer-width) - 16px));
    }}
    .sidebar-edge-toggle-v3[aria-pressed="false"] {{
      background: rgba(225, 238, 246, 0.98);
      border-color: rgba(118, 156, 181, 0.72);
    }}
    .sidebar-edge-toggle-v3 .sidebar-icon {{
      width: 16px;
      height: 16px;
    }}
    .sidebar-edge-toggle-v3 .sidebar-icon::before {{
      top: 0;
      bottom: 0;
      left: 2px;
      width: 3px;
    }}
    .sidebar-edge-toggle-v3 .sidebar-icon::after {{
      right: 1px;
      width: 6px;
      height: 6px;
    }}
    .sidebar-edge-toggle-v3-right .sidebar-icon {{
      transform: scaleX(-1);
    }}
    body.left-rail-collapsed {{
      --left-rail-width: 0px;
      --left-resizer-width: 0px;
    }}
    body.right-rail-collapsed {{
      --right-rail-width: 0px;
      --right-resizer-width: 0px;
    }}
    body.left-rail-collapsed .sidebar-edge-toggle-v3-left {{
      left: 0;
      --sidebar-edge-toggle-transform: translateX(-35%);
    }}
    body.right-rail-collapsed .sidebar-edge-toggle-v3-right {{
      right: 0;
      --sidebar-edge-toggle-transform: translateX(35%);
    }}
    .panel-resizer-v3 {{
      position: relative;
      cursor: col-resize;
      user-select: none;
      touch-action: none;
      transition: opacity 140ms ease;
    }}
    .panel-resizer-v3::before {{
      content: "";
      position: absolute;
      top: 18px;
      bottom: 18px;
      left: 50%;
      width: 1px;
      transform: translateX(-50%);
      background: rgba(217, 226, 236, 0.95);
    }}
    .panel-resizer-v3::after {{
      content: "";
      position: absolute;
      top: 50%;
      left: 50%;
      width: 4px;
      height: 48px;
      transform: translate(-50%, -50%);
      border-radius: 999px;
      background: rgba(197, 207, 219, 0.9);
      opacity: 0;
      transition: opacity 120ms ease, background 120ms ease;
    }}
    .panel-resizer-v3:hover::after,
    .panel-resizer-v3.is-active::after {{
      opacity: 1;
      background: rgba(109, 133, 165, 0.92);
    }}
    .workspace-main-v3 {{
      min-width: 0;
      display: grid;
      gap: 16px;
      padding: 20px 24px 28px;
    }}
    .workspace-sidebar-v3 {{
      min-width: 0;
      display: grid;
      gap: 10px;
      align-content: start;
      padding: 16px 12px 22px;
      background: rgba(248, 250, 253, 0.42);
      overflow: hidden;
      transition: opacity 140ms ease, padding 140ms ease, border-color 140ms ease;
    }}
    #left-sidebar.workspace-sidebar-v3 {{
      border-right: 1px solid rgba(217, 226, 236, 0.92);
    }}
    .workspace-sidebar-right-v3 {{
      border-left: 1px solid rgba(217, 226, 236, 0.92);
    }}
    body.left-rail-collapsed #left-sidebar.workspace-sidebar-v3 {{
      padding-left: 0;
      padding-right: 0;
      border-right-color: transparent;
      opacity: 0;
      pointer-events: none;
    }}
    body.right-rail-collapsed .workspace-sidebar-right-v3 {{
      padding-left: 0;
      padding-right: 0;
      border-left-color: transparent;
      opacity: 0;
      pointer-events: none;
    }}
    body.left-rail-collapsed .panel-resizer-v3[data-panel-resizer="left"],
    body.right-rail-collapsed .panel-resizer-v3[data-panel-resizer="right"] {{
      opacity: 0;
      pointer-events: none;
    }}
    .workspace-sidebar-v3 .panel {{
      padding: 12px;
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.96);
      border: 1px solid rgba(223, 231, 240, 0.95);
      box-shadow: var(--shadow-soft);
    }}
    .workspace-sidebar-v3 h2 {{
      margin-bottom: 6px;
      font-size: 0.94rem;
    }}
    .workspace-header-v3 {{
      display: grid;
      gap: 14px;
      padding: 4px 6px 0;
    }}
    .workspace-header-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 24px;
      align-items: center;
    }}
    .workspace-header-copy {{
      display: grid;
      gap: 8px;
      max-width: 720px;
    }}
    .workspace-header-copy h1 {{
      font-size: clamp(1.7rem, 2.45vw, 2.7rem);
      margin: 0;
      letter-spacing: -0.035em;
    }}
    .workspace-header-copy p {{
      margin: 0;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.96rem;
      color: var(--muted);
    }}
    .workspace-meta-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: -4px;
    }}
    .workspace-chip {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 12px;
      border-radius: 12px;
      background: rgba(240, 244, 250, 0.96);
      border: 1px solid rgba(217, 226, 236, 0.9);
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      color: var(--text);
      font-size: 0.88rem;
    }}
    .workspace-environment-note-v3 {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 4px 9px;
      border-radius: 999px;
      border: 1px solid rgba(217, 226, 236, 0.96);
      background: rgba(255, 255, 255, 0.92);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7);
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.72rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: #7c8998;
    }}
    .workspace-primary-action {{
      min-width: 184px;
      justify-content: center;
      font-size: 0.92rem;
      border-radius: 12px;
      align-self: center;
    }}
    .marathon-strip-v3 {{
      position: relative;
      display: grid;
      gap: 18px;
      padding: 18px 22px 16px;
      border: 1px solid rgba(207, 220, 235, 0.92);
      border-radius: 20px;
      overflow: hidden;
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(245, 250, 255, 0.98));
      box-shadow: var(--shadow-soft);
    }}
    .marathon-strip-v3::before {{
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.44), transparent 62%),
        repeating-linear-gradient(90deg, rgba(220, 233, 245, 0.26) 0 1px, transparent 1px 88px);
      pointer-events: none;
    }}
    .marathon-strip-top-v3 {{
      position: relative;
      z-index: 1;
      display: grid;
      grid-template-columns: minmax(220px, 300px) minmax(0, 1fr);
      gap: 20px;
      align-items: center;
    }}
    .marathon-summary-v3 {{
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 8px;
      align-items: center;
    }}
    .marathon-copy-v3 {{
      display: grid;
      gap: 4px;
    }}
    .marathon-kicker-v3 {{
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0;
      color: var(--text);
    }}
    .marathon-progress-copy-v3 {{
      margin: 0;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.95rem;
      color: #5b6878;
    }}
    .marathon-title-wrap-v3 {{
      display: grid;
      gap: 6px;
      justify-items: center;
      text-align: center;
    }}
    .marathon-title-wrap-v3 h2 {{
      margin: 0;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: clamp(1.28rem, 2.5vw, 2rem);
      font-weight: 700;
      letter-spacing: -0.03em;
    }}
    .marathon-title-wrap-v3 p {{
      margin: 0;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.9rem;
      color: var(--muted);
      line-height: 1.35;
    }}
    .marathon-track-shell-v3 {{
      position: relative;
      z-index: 1;
      min-height: 156px;
    }}
    .marathon-track-v3 {{
      position: relative;
      min-height: 86px;
      padding-top: 8px;
    }}
    .marathon-track-line-v3 {{
      position: absolute;
      left: 12px;
      right: 0;
      top: 42px;
      height: 18px;
      border-radius: 999px;
      overflow: hidden;
      background: linear-gradient(180deg, #9bd6f8 0%, #7ec8f1 100%);
      box-shadow: inset 0 -1px 0 rgba(79, 154, 202, 0.26);
    }}
    .marathon-track-line-v3::before {{
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.3), transparent 68%);
    }}
    .marathon-track-fill-v3 {{
      position: absolute;
      left: 0;
      top: 0;
      bottom: 0;
      border-radius: 999px;
      background: linear-gradient(90deg, #4ea8df 0%, #5bb8ec 100%);
    }}
    .marathon-runner-v3 {{
      position: relative;
      width: 76px;
      height: 72px;
    }}
    .marathon-runner-progress-v3 {{
      position: absolute;
      top: -20px;
      display: grid;
      justify-items: center;
      gap: 4px;
      transform: translateX(-50%);
      pointer-events: none;
      z-index: 2;
    }}
    .marathon-runner-label-v3 {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 22px;
      padding: 0 12px;
      border-radius: 999px;
      border: 2px solid rgba(140, 187, 235, 0.9);
      background: rgba(240, 247, 255, 0.96);
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.72rem;
      font-weight: 700;
      color: #1a4f8f;
      white-space: nowrap;
      box-shadow: 0 6px 14px rgba(96, 152, 211, 0.16);
    }}
    .marathon-runner-shadow-v3 {{
      position: absolute;
      left: 18px;
      bottom: 2px;
      width: 36px;
      height: 10px;
      border-radius: 999px;
      background: rgba(58, 88, 116, 0.16);
      filter: blur(1px);
    }}
    .marathon-runner-head-v3 {{
      position: absolute;
      top: 5px;
      left: 22px;
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: #f0c39a;
      border: 2px solid #29415f;
      z-index: 3;
    }}
    .marathon-runner-head-v3::before {{
      content: "";
      position: absolute;
      top: -4px;
      left: -1px;
      width: 18px;
      height: 10px;
      border-radius: 10px 10px 6px 6px;
      background: #4c3729;
    }}
    .marathon-runner-torso-v3 {{
      position: absolute;
      top: 24px;
      left: 24px;
      width: 15px;
      height: 20px;
      border-radius: 9px;
      background: linear-gradient(180deg, #4c8acb 0%, #2d6fb5 100%);
      border: 2px solid #29415f;
      z-index: 2;
    }}
    .marathon-runner-shorts-v3 {{
      position: absolute;
      top: 39px;
      left: 25px;
      width: 15px;
      height: 10px;
      border-radius: 5px;
      background: #35597f;
      z-index: 2;
    }}
    .marathon-runner-limb-v3 {{
      position: absolute;
      width: 16px;
      height: 4px;
      border-radius: 999px;
      background: #29415f;
      transform-origin: left center;
    }}
    .marathon-runner-limb-v3.arm-back {{
      top: 28px;
      left: 18px;
      animation: marathon-runner-arm-back-v3 820ms ease-in-out infinite;
    }}
    .marathon-runner-limb-v3.arm-front {{
      top: 31px;
      left: 34px;
      animation: marathon-runner-arm-front-v3 820ms ease-in-out infinite;
    }}
    .marathon-runner-limb-v3.leg-back {{
      top: 48px;
      left: 22px;
      width: 18px;
      animation: marathon-runner-leg-back-v3 820ms ease-in-out infinite;
    }}
    .marathon-runner-limb-v3.leg-front {{
      top: 47px;
      left: 34px;
      width: 20px;
      animation: marathon-runner-leg-front-v3 820ms ease-in-out infinite;
    }}
    .marathon-runner-shoe-v3 {{
      position: absolute;
      width: 12px;
      height: 5px;
      border-radius: 999px;
      background: #4ea8df;
    }}
    .marathon-runner-shoe-v3.shoe-back {{
      left: 18px;
      top: 58px;
      animation: marathon-runner-shoe-back-v3 820ms ease-in-out infinite;
    }}
    .marathon-runner-shoe-v3.shoe-front {{
      left: 48px;
      top: 57px;
      animation: marathon-runner-shoe-front-v3 820ms ease-in-out infinite;
    }}
    .marathon-marker-row-v3 {{
      position: absolute;
      inset: 0;
      min-height: 156px;
      pointer-events: none;
    }}
    .marathon-marker-v3 {{
      position: absolute;
      top: 0;
      display: grid;
      justify-items: center;
      gap: 6px;
      padding-top: 66px;
      transform: translateX(-50%);
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.76rem;
      color: #445161;
      text-align: center;
      white-space: nowrap;
    }}
    .marathon-marker-v3::before {{
      content: "";
      position: absolute;
      top: 18px;
      width: 2px;
      height: 24px;
      border-radius: 999px;
      background: #6aa7c8;
    }}
    .marathon-marker-v3::after {{
      content: "";
      position: absolute;
      top: 18px;
      left: calc(50% + 1px);
      width: 0;
      height: 0;
      border-top: 7px solid transparent;
      border-bottom: 7px solid transparent;
      border-left: 12px solid #7db8da;
    }}
    .marathon-marker-v3.completed {{
      color: #2d6fb5;
    }}
    .marathon-marker-v3.completed::before {{
      background: #4ea8df;
    }}
    .marathon-marker-v3.completed::after {{
      border-left-color: #4ea8df;
    }}
    .marathon-marker-v3.current {{
      color: #173f77;
      font-weight: 700;
    }}
    .marathon-marker-v3.finish {{
      color: #17212b;
      font-weight: 700;
    }}
    .marathon-marker-v3.finish::before {{
      background: #2d3f55;
      height: 26px;
    }}
    .marathon-marker-v3.finish::after {{
      top: 15px;
      left: calc(50% + 1px);
      width: 17px;
      height: 15px;
      border: 0;
      border-radius: 0 2px 2px 0;
      background:
        conic-gradient(from 90deg, #2d3f55 0 25%, #ffffff 0 50%, #2d3f55 0 75%, #ffffff 0) 0 0 / 8px 8px;
      box-shadow: inset 0 0 0 1px rgba(45, 63, 85, 0.2);
      clip-path: polygon(0 0, 100% 8%, 92% 32%, 100% 56%, 91% 78%, 100% 100%, 0 100%);
      transform: skewY(-5deg);
    }}
    @keyframes marathon-runner-arm-back-v3 {{
      0%, 100% {{ transform: rotate(38deg); }}
      50% {{ transform: rotate(-22deg); }}
    }}
    @keyframes marathon-runner-arm-front-v3 {{
      0%, 100% {{ transform: rotate(-28deg); }}
      50% {{ transform: rotate(34deg); }}
    }}
    @keyframes marathon-runner-leg-back-v3 {{
      0%, 100% {{ transform: rotate(52deg); }}
      50% {{ transform: rotate(-8deg); }}
    }}
    @keyframes marathon-runner-leg-front-v3 {{
      0%, 100% {{ transform: rotate(-22deg); }}
      50% {{ transform: rotate(44deg); }}
    }}
    @keyframes marathon-runner-shoe-back-v3 {{
      0%, 100% {{ transform: translateX(-2px) translateY(2px); }}
      50% {{ transform: translateX(9px) translateY(-1px); }}
    }}
    @keyframes marathon-runner-shoe-front-v3 {{
      0%, 100% {{ transform: translateX(0) translateY(1px); }}
      50% {{ transform: translateX(-10px) translateY(0); }}
    }}
    .stepper-bar-v3 {{
      display: flex;
      align-items: stretch;
      gap: 0;
      padding: 6px 8px;
      border: 1px solid rgba(217, 226, 236, 0.92);
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.98);
      box-shadow: var(--shadow-soft);
    }}
    .stepper-item-v3 {{
      display: grid;
      grid-template-columns: auto 1fr;
      align-items: center;
      gap: 10px;
      padding: 8px 12px;
      min-width: 0;
      flex: 1 1 0;
      text-decoration: none;
      color: inherit;
    }}
    a.stepper-item-v3.clickable {{
      cursor: pointer;
      border-radius: 8px;
      transition: background 0.15s;
    }}
    a.stepper-item-v3.clickable:hover {{
      background: var(--surface-alt);
    }}
    .stepper-separator-v3 {{
      width: 28px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      color: #8b97a8;
      font-size: 1rem;
    }}
    .stepper-number-v3 {{
      width: 34px;
      height: 34px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid rgba(191, 208, 220, 0.9);
      background: rgba(255, 255, 255, 0.9);
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.9rem;
      color: var(--muted);
    }}
    .stepper-item-v3.current .stepper-number-v3 {{
      background: linear-gradient(180deg, #1b68c6, #1660b8);
      border-color: #1660b8;
      color: white;
      box-shadow: 0 12px 20px rgba(27, 104, 198, 0.18);
    }}
    .stepper-copy-v3 {{
      min-width: 0;
      display: grid;
      gap: 2px;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
    }}
    .stepper-label-v3 {{
      font-size: 0.92rem;
      font-weight: 700;
      color: var(--text);
    }}
    .stepper-subcopy-v3 {{
      color: var(--muted);
      font-size: 0.78rem;
      line-height: 1.25;
    }}
    .stepper-item-v3.current .stepper-subcopy-v3 {{
      color: var(--accent);
    }}
    .assessment-grid-v3 {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) var(--assessment-side-width);
      gap: 0;
      border: 1px solid rgba(217, 226, 236, 0.92);
      border-radius: 18px;
      overflow: hidden;
      background: rgba(255, 255, 255, 0.98);
      box-shadow: var(--shadow-soft);
    }}
    .assessment-card-v3 {{
      padding: 14px 16px 16px;
      display: grid;
      gap: 12px;
      min-width: 0;
    }}
    .assessment-side-v3 {{
      padding: 14px 14px 14px 16px;
      border-left: 1px solid rgba(228, 234, 241, 0.95);
      display: grid;
      gap: 14px;
      align-content: start;
      background: rgba(250, 251, 253, 0.98);
    }}
    .eyebrow-row-v3 {{
      display: flex;
      gap: 18px;
      flex-wrap: wrap;
      align-items: baseline;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
    }}
    .eyebrow-row-v3 strong {{
      font-size: 0.94rem;
      color: var(--text);
    }}
    .eyebrow-row-v3 span {{
      color: var(--muted);
      font-size: 0.86rem;
    }}
    .question-heading-v3 {{
      margin: 0;
      font-size: clamp(1.12rem, 1.55vw, 1.7rem);
      line-height: 1.14;
    }}
    .learn-stage-shell-v3 {{
      display: grid;
      gap: 14px;
    }}
    .learn-stage-header-v3 {{
      display: flex;
      justify-content: space-between;
      align-items: start;
      gap: 16px;
      flex-wrap: wrap;
      padding: 4px 2px 2px;
    }}
    .learn-stage-copy-v3 {{
      display: grid;
      gap: 8px;
      max-width: 44rem;
    }}
    .learn-stage-kicker-v3 {{
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.8rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--accent-dark);
    }}
    .learn-stage-copy-v3 h2 {{
      margin: 0;
      font-size: 1.18rem;
      line-height: 1.18;
    }}
    .learn-stage-copy-v3 p {{
      margin: 0;
    }}
    .learn-stage-meta-v3 {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
    }}
    .learn-empty-card-v3 {{
      min-height: 100%;
    }}
    .question-prompt-v3 {{
      margin: 0;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: clamp(1.12rem, 1.55vw, 1.42rem);
      line-height: 1.18;
      font-weight: 700;
      letter-spacing: -0.015em;
      color: var(--text);
    }}
    .guidance-block-v3 {{
      display: grid;
      gap: 10px;
      padding-bottom: 4px;
    }}
    .guidance-row-v3 {{
      display: grid;
      grid-template-columns: 76px 1fr;
      gap: 12px;
      align-items: start;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
    }}
    .guidance-row-v3 strong {{
      font-size: 0.88rem;
    }}
    .guidance-row-v3 ul {{
      margin: 0;
      padding-left: 18px;
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 0.88rem;
    }}
    .assessment-expected-v3 {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      padding-top: 2px;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      color: var(--muted);
      font-size: 0.88rem;
    }}
    .assessment-tags-v3 {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
      padding-top: 8px;
      border-top: 1px solid rgba(228, 234, 241, 0.95);
    }}
    .assessment-tag-v3 {{
      display: inline-flex;
      align-items: center;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid rgba(191, 208, 220, 0.72);
      background: rgba(233, 238, 244, 0.78);
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      color: var(--text);
      font-size: 0.84rem;
    }}
    .assessment-actions-v3 {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }}
    .assessment-actions-v3 .button-link,
    .assessment-actions-v3 button {{
      min-width: 116px;
      justify-content: center;
      border-radius: 12px;
      min-height: 36px;
      font-size: 0.84rem;
      padding: 8px 12px;
    }}
    .assessment-side-v3 .button-link {{
      min-height: 34px;
      padding: 7px 12px;
      font-size: 0.82rem;
      border-radius: 11px;
    }}
    .assessment-textarea-v3 {{
      min-height: 84px;
      font-size: 0.88rem;
    }}
    .mini-panel-v3 {{
      display: grid;
      gap: 12px;
    }}
    .mini-panel-v3 h3 {{
      margin: 0;
      font-size: 0.92rem;
    }}
    .concept-status-list-v3 {{
      display: grid;
      gap: 10px;
    }}
    .concept-status-item-v3 {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      padding: 8px 10px;
      border-radius: 12px;
      background: rgba(244, 248, 244, 0.92);
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.86rem;
    }}
    .concept-status-item-v3 .status-missing {{
      color: var(--success);
    }}
    .implementation-shell-v3 {{
      display: grid;
      gap: 14px;
    }}
    .section-header-v3 {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      flex-wrap: wrap;
    }}
    .section-header-v3 h2 {{
      margin: 0;
      font-size: 0.98rem;
    }}
    .toolbar-actions-v3 {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .toolbar-actions-v3 form {{
      margin: 0;
    }}
    .toolbar-button-v3 {{
      min-height: 36px;
      padding: 8px 12px;
      border-radius: 12px;
      background: rgba(255, 255, 255, 0.98);
      color: var(--text);
      border: 1px solid rgba(217, 226, 236, 0.92);
      box-shadow: none;
      font-size: 0.84rem;
    }}
    .implementation-grid-v3 {{
      display: grid;
      grid-template-columns: minmax(0, 1.6fr) minmax(260px, 0.9fr);
      gap: 18px;
      align-items: start;
    }}
    .table-card-v3, .activity-card-v3 {{
      border: 1px solid rgba(217, 226, 236, 0.92);
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.98);
      box-shadow: var(--shadow-soft);
      overflow: hidden;
    }}
    .table-card-body-v3 {{
      padding: 10px 0 12px;
    }}
    .file-table-v3 {{
      width: 100%;
      border-collapse: collapse;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
    }}
    .file-table-v3 th,
    .file-table-v3 td {{
      text-align: left;
      padding: 12px 14px;
      border-bottom: 1px solid rgba(191, 208, 220, 0.42);
      vertical-align: middle;
    }}
    .file-table-v3 th {{
      font-size: 0.8rem;
      color: var(--muted);
      font-weight: 600;
    }}
    .table-chip-v3 {{
      display: inline-flex;
      align-items: center;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(229, 234, 242, 0.86);
      border: 1px solid rgba(191, 208, 220, 0.8);
      color: var(--muted);
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.82rem;
    }}
    .table-chip-v3.complete {{
      color: var(--success);
      background: rgba(237, 249, 241, 0.9);
      border-color: rgba(159, 208, 177, 0.92);
    }}
    .table-action-v3 {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 72px;
      padding: 6px 10px;
      border-radius: 12px;
      border: 1px solid rgba(191, 208, 220, 0.88);
      background: rgba(255, 255, 255, 0.88);
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      text-decoration: none;
      font-size: 0.82rem;
    }}
    .table-footer-v3 {{
      display: grid;
      gap: 6px;
      padding: 0 18px 14px;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      color: var(--muted);
    }}
    .activity-card-v3 {{
      padding: 16px 18px;
      display: grid;
      gap: 14px;
    }}
    .activity-list-v3 {{
      display: grid;
      gap: 12px;
      margin: 0;
      padding: 0;
      list-style: none;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
    }}
    .activity-list-v3 li {{
      display: flex;
      gap: 10px;
      align-items: start;
      color: var(--text);
    }}
    .activity-dot-v3 {{
      width: 12px;
      height: 12px;
      border-radius: 999px;
      margin-top: 4px;
      flex-shrink: 0;
      background: #9aa9b5;
    }}
    .activity-dot-v3.good {{ background: #2bb99d; }}
    .activity-dot-v3.warn {{ background: #f0ad4e; }}
    .activity-dot-v3.bad {{ background: #d86565; }}
    .week-title-v3 {{
      font-size: 1.02rem;
      font-weight: 700;
      line-height: 1.25;
    }}
    .progress-panel-v3 {{
      display: grid;
      gap: 12px;
    }}
    .progress-overview-v3 {{
      display: grid;
      grid-template-columns: 64px 1fr;
      gap: 12px;
      align-items: center;
    }}
    .progress-ring-v3 {{
      --progress: 0;
      width: 64px;
      height: 64px;
      border-radius: 999px;
      background: conic-gradient(var(--accent) calc(var(--progress) * 1%), rgba(210, 218, 226, 0.72) 0);
      display: grid;
      place-items: center;
    }}
    .progress-ring-v3::before {{
      content: attr(data-progress-label);
      width: 48px;
      height: 48px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.94);
      display: grid;
      place-items: center;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-weight: 700;
      font-size: 0.9rem;
      color: var(--text);
    }}
    .progress-steps-v3 {{
      display: grid;
      gap: 8px;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.94rem;
    }}
    .progress-step-row-v3 {{
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: 10px;
      align-items: center;
    }}
    .progress-step-dot-v3 {{
      width: 12px;
      height: 12px;
      border-radius: 4px;
      border: 1px solid rgba(191, 208, 220, 0.9);
      background: rgba(255, 255, 255, 0.92);
    }}
    .progress-step-row-v3.current .progress-step-dot-v3 {{
      background: var(--accent);
      border-color: var(--accent);
    }}
    .progress-step-meta-v3 {{
      color: var(--muted);
    }}
    .deliverable-list-v3, .metric-list-v3, .readiness-list-v3, .resource-list-v3 {{
      display: grid;
      gap: 8px;
      margin: 0;
      padding: 0;
      list-style: none;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.92rem;
    }}
    .resource-list-v3 {{
      display: block;
      padding-left: 20px;
      list-style: disc;
    }}
    .deliverable-item-v3, .metric-item-v3, .resource-item-v3 {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      min-height: 34px;
    }}
    .resource-item-v3 {{
      display: list-item;
      min-height: 0;
      margin: 0 0 8px;
    }}
    .resource-item-v3:last-child {{
      margin-bottom: 0;
    }}
    .sidebar-status-v3 {{
      display: inline-flex;
      align-items: center;
      padding: 4px 8px;
      border-radius: 999px;
      background: rgba(246, 248, 251, 0.98);
      border: 1px solid rgba(217, 226, 236, 0.95);
      color: var(--muted);
      font-size: 0.78rem;
    }}
    .sidebar-status-v3.good {{
      color: var(--success);
      background: rgba(237, 249, 241, 0.9);
    }}
    .sidebar-status-v3.warn {{
      color: var(--warning);
      background: rgba(255, 246, 232, 0.92);
    }}
    .sidebar-button-v3 {{
      width: 100%;
      justify-content: center;
      min-height: 38px;
      border-radius: 12px;
      font-size: 0.88rem;
      box-shadow: none;
    }}
    .readiness-row-v3 {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
    }}
    .sidebar-panel-minimal-v3 {{
      background: transparent !important;
      border: 0 !important;
      box-shadow: none !important;
      padding: 0 0 12px !important;
      border-radius: 0 !important;
    }}
    .sidebar-panel-minimal-v3 + .sidebar-panel-minimal-v3 {{
      padding-top: 12px !important;
      border-top: 1px solid rgba(223, 231, 240, 0.95) !important;
    }}
    .sidebar-card-v3 {{
      display: grid;
      gap: 10px;
      background: rgba(255, 255, 255, 0.92) !important;
      box-shadow: none !important;
    }}
    .sidebar-card-v3 h2 {{
      margin-bottom: 0;
    }}
    .sidebar-card-v3 .sidebar-button-v3 {{
      margin-top: 2px;
    }}
    .assistant-panel-v3 {{
      display: grid;
      gap: 14px;
    }}
    .assistant-shell-v3 {{
      background: transparent !important;
      border: 0 !important;
      box-shadow: none !important;
      padding: 0 !important;
    }}
    .assistant-header-v3 {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }}
    .assistant-header-v3 h2 {{
      margin: 0;
      font-size: 1rem;
    }}
    .assistant-plus-v3 {{
      width: 28px;
      height: 28px;
      border-radius: 999px;
      padding: 0;
      box-shadow: none;
      min-height: 28px;
      font-size: 0.82rem;
    }}
    .assistant-tabs-v3 {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 6px;
      padding: 4px;
      border-radius: 14px;
      background: rgba(239, 242, 247, 0.8);
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.9rem;
    }}
    .assistant-tab-v3 {{
      padding: 7px 8px;
      border-radius: 10px;
      text-align: center;
      color: var(--muted);
    }}
    .assistant-tab-v3.active {{
      background: rgba(255, 255, 255, 0.92);
      color: var(--text);
      box-shadow: var(--shadow-soft);
    }}
    .assistant-card-v3 {{
      border: 1px solid rgba(223, 231, 240, 0.95);
      border-radius: 14px;
      padding: 12px;
      background: rgba(255, 255, 255, 0.98);
      display: grid;
      gap: 10px;
      box-shadow: none;
    }}
    .assistant-section-v3 {{
      display: grid;
      gap: 8px;
      padding-top: 4px;
    }}
    .assistant-section-v3 + .assistant-section-v3 {{
      padding-top: 12px;
      border-top: 1px solid rgba(223, 231, 240, 0.95);
    }}
    .assistant-section-v3 h3 {{
      margin: 0;
      font-size: 0.95rem;
    }}
    .assistant-card-v3 h3 {{
      margin: 0;
      font-size: 0.95rem;
    }}
    .assistant-panel-v3 p,
    .assistant-panel-v3 li,
    .assistant-panel-v3 label,
    .assistant-panel-v3 textarea,
    .assistant-panel-v3 button {{
      font-size: 0.9rem;
    }}
    .assistant-quick-actions-v3 {{
      display: grid;
      gap: 8px;
    }}
    .assistant-prompt-v3 {{
      width: 100%;
      justify-content: flex-start;
      text-align: left;
      background: rgba(255, 255, 255, 0.98);
      color: var(--text);
      border: 1px solid rgba(217, 226, 236, 0.92);
      box-shadow: none;
      min-height: 34px;
      padding: 7px 11px;
      font-size: 0.84rem;
    }}
    .assistant-resource-header-v3 {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      font-size: 0.86rem;
    }}
    .assistant-header-actions-v3 {{
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .topic-chat-delete-icon-v3 {{
      width: 28px;
      height: 28px;
      min-height: 28px;
      padding: 0;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      box-shadow: none;
    }}
    .topic-chat-delete-icon-v3 svg {{
      width: 14px;
      height: 14px;
      stroke: currentColor;
      fill: none;
      stroke-width: 1.6;
      stroke-linecap: round;
      stroke-linejoin: round;
    }}
    .assistant-chat-shell-v3 {{
      display: grid;
      gap: 10px;
      min-height: 500px;
    }}
    .assistant-chat-thread-v3 {{
      padding: 0;
      border-radius: 0;
      background: transparent;
      border: 0;
    }}
    .assistant-composer-v3 {{
      display: grid;
      gap: 8px;
    }}
    .assistant-composer-v3 textarea {{
      min-height: 82px;
      font-size: 0.88rem;
    }}
    .assistant-activity-card-v3 {{
      padding-top: 4px;
    }}
    .assistant-hidden {{
      display: none !important;
    }}
    html[data-theme="dark"] .course-bar,
    html[data-theme="dark"] .app-topbar-v3,
    html[data-theme="dark"] .workspace-sidebar-v3 .panel,
    html[data-theme="dark"] .marathon-strip-v3,
    html[data-theme="dark"] .stepper-bar-v3,
    html[data-theme="dark"] .assessment-grid-v3,
    html[data-theme="dark"] .table-card-v3,
    html[data-theme="dark"] .activity-card-v3,
    html[data-theme="dark"] .progress-shell,
    html[data-theme="dark"] .progress-card,
    html[data-theme="dark"] .workflow-stage-card,
    html[data-theme="dark"] .stage-surface,
    html[data-theme="dark"] .rail-utility-card,
    html[data-theme="dark"] .topic-chat-question-card,
    html[data-theme="dark"] .topic-chat-thread-shell,
    html[data-theme="dark"] .topic-chat-message,
    html[data-theme="dark"] .topic-chat-context-chip,
    html[data-theme="dark"] .question-modal,
    html[data-theme="dark"] .question-modal-link,
    html[data-theme="dark"] .question-validator-feedback,
    html[data-theme="dark"] pre {{
      background: var(--surface-strong);
      border-color: var(--border);
      box-shadow: var(--shadow-soft);
    }}
    html[data-theme="dark"] .topic-chat-message[data-role="assistant"] {{
      background: rgba(17, 24, 36, 0.96);
    }}
    html[data-theme="dark"] .topic-chat-message[data-role="user"] {{
      background: linear-gradient(180deg, rgba(42, 71, 110, 0.92), rgba(29, 49, 78, 0.96));
    }}
    html[data-theme="dark"] input,
    html[data-theme="dark"] textarea,
    html[data-theme="dark"] select,
    html[data-theme="dark"] button.secondary,
    html[data-theme="dark"] .button-link.secondary,
    html[data-theme="dark"] .topbar-action-icon,
    html[data-theme="dark"] .sidebar-edge-toggle-v3,
    html[data-theme="dark"] .topic-chat-session,
    html[data-theme="dark"] .topic-chat-suggestion,
    html[data-theme="dark"] .workspace-chip,
    html[data-theme="dark"] .workspace-environment-note-v3,
    html[data-theme="dark"] .assessment-tag-v3,
    html[data-theme="dark"] .concept-status-item-v3,
    html[data-theme="dark"] .pill.subtle,
    html[data-theme="dark"] .status-badge {{
      background: rgba(21, 29, 42, 0.96);
      border-color: var(--border);
      color: var(--text);
    }}
    html[data-theme="dark"] .app-topbar-status {{
      background: rgba(25, 37, 56, 0.98);
      border-color: rgba(84, 114, 154, 0.72);
      color: var(--accent-dark);
    }}
    html[data-theme="dark"] .status-badge.passed {{
      background: var(--success-soft);
      border-color: rgba(89, 170, 133, 0.65);
      color: var(--success);
    }}
    html[data-theme="dark"] .status-badge.in_progress {{
      background: var(--accent-soft);
      border-color: rgba(92, 138, 196, 0.62);
      color: var(--accent-dark);
    }}
    html[data-theme="dark"] .status-badge.failed {{
      background: var(--danger-soft);
      border-color: rgba(192, 95, 123, 0.58);
      color: var(--danger);
    }}
    html[data-theme="dark"] .status-badge.draft {{
      background: var(--warning-soft);
      border-color: rgba(189, 142, 74, 0.56);
      color: var(--warning);
    }}
    html[data-theme="dark"] .notice {{
      background: rgba(69, 53, 30, 0.34);
      border-color: rgba(128, 103, 63, 0.5);
    }}
    html[data-theme="dark"] .notice.success {{
      background: var(--success-soft);
    }}
    html[data-theme="dark"] .notice.error {{
      background: var(--danger-soft);
    }}
    html[data-theme="dark"] .question-modal {{
      border-color: rgba(84, 114, 154, 0.72);
      box-shadow: 0 30px 90px rgba(0, 0, 0, 0.55);
    }}
    html[data-theme="dark"] .question-modal::backdrop {{
      background: rgba(4, 8, 14, 0.7);
    }}
    html[data-theme="dark"] .question-modal-link {{
      background: rgba(21, 29, 42, 0.96);
    }}
    html[data-theme="dark"] .question-modal-link.current {{
      background: linear-gradient(180deg, rgba(34, 54, 83, 0.98), rgba(24, 39, 61, 0.98));
      border-color: rgba(98, 140, 201, 0.76);
    }}
    html[data-theme="dark"] .question-modal-close {{
      background: rgba(21, 29, 42, 0.96);
      border-color: var(--border);
      color: var(--text);
    }}
    html[data-theme="dark"] .question-modal-index {{
      color: var(--accent-dark);
    }}
    html[data-theme="dark"] .required-question-marker {{
      color: #ff8f87;
    }}
    html[data-theme="dark"] .question-validator-feedback.failed {{
      background: rgba(104, 30, 47, 0.32);
    }}
    html[data-theme="dark"] .app-topbar-divider,
    html[data-theme="dark"] .panel-resizer-v3::before {{
      background: rgba(58, 77, 103, 0.88);
    }}
    html[data-theme="dark"] .panel-resizer-v3::after {{
      background: rgba(90, 115, 150, 0.72);
    }}
    html[data-theme="dark"] .workspace-sidebar-v3 {{
      background: rgba(13, 18, 28, 0.4);
    }}
    html[data-theme="dark"] #left-sidebar.workspace-sidebar-v3 {{
      border-right-color: var(--border);
    }}
    html[data-theme="dark"] .workspace-sidebar-right-v3 {{
      border-left-color: var(--border);
    }}
    html[data-theme="dark"] .marathon-marker-v3 {{
      color: #a7b8ce;
    }}
    html[data-theme="dark"] .marathon-marker-v3::before {{
      background: #4a678a;
    }}
    html[data-theme="dark"] .marathon-marker-v3::after {{
      border-left-color: #5d7ea2;
    }}
    html[data-theme="dark"] .marathon-marker-v3.completed {{
      color: #9dcbff;
    }}
    html[data-theme="dark"] .marathon-marker-v3.completed::before {{
      background: #74b0ff;
    }}
    html[data-theme="dark"] .marathon-marker-v3.completed::after {{
      border-left-color: #74b0ff;
    }}
    html[data-theme="dark"] .marathon-marker-v3.current,
    html[data-theme="dark"] .marathon-marker-v3.finish {{
      color: #eef4fc;
    }}
    html[data-theme="dark"] .progress-shell-line {{
      background: linear-gradient(180deg, rgba(116, 176, 255, 0.54), rgba(58, 77, 103, 0.45));
    }}
    html[data-theme="dark"] .progress-node {{
      background: rgba(90, 115, 150, 0.82);
      border-color: rgba(17, 24, 36, 0.92);
      box-shadow: 0 0 0 4px rgba(17, 24, 36, 0.34);
    }}
    html[data-theme="dark"] .progress-row.current .progress-card {{
      background: rgba(20, 29, 43, 0.98);
    }}
    html[data-theme="dark"] .concept-status-item-v3 .status-missing,
    html[data-theme="dark"] .topic-chat-session.active,
    html[data-theme="dark"] .topic-chat-suggestion,
    html[data-theme="dark"] .workspace-environment-note-v3,
    html[data-theme="dark"] .workspace-chip strong {{
      color: var(--accent-dark);
    }}
    /* ── Dark mode overrides for elements not covered above ── */
    html[data-theme="dark"] .learn-orientation-panel {{
      background: linear-gradient(180deg, rgba(22, 35, 56, 0.92), rgba(17, 27, 44, 0.96));
      border-color: var(--border);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
    }}
    html[data-theme="dark"] .reading-section {{
      border-top-color: var(--border);
    }}
    html[data-theme="dark"] .reading-column {{
      background: rgba(13, 19, 30, 0.6);
      border-color: var(--border);
    }}
    html[data-theme="dark"] .subpanel {{
      background: rgba(17, 24, 36, 0.72);
    }}
    html[data-theme="dark"] .learn-reading-section-v3 {{
      background: rgba(17, 24, 36, 0.82);
      border-color: var(--border);
    }}
    html[data-theme="dark"] .step-link {{
      background: rgba(21, 29, 42, 0.82);
      border-color: var(--border);
      color: var(--text);
    }}
    html[data-theme="dark"] .step-link.current {{
      background: var(--accent-soft);
      border-color: rgba(92, 138, 196, 0.62);
    }}
    html[data-theme="dark"] .step-body {{
      border-top-color: var(--border);
    }}
    html[data-theme="dark"] .key-value-item {{
      background: rgba(21, 29, 42, 0.82);
      border-color: var(--border);
    }}
    html[data-theme="dark"] .details-block {{
      background: rgba(21, 29, 42, 0.82);
      border-color: var(--border);
    }}
    html[data-theme="dark"] .question-links a {{
      background: rgba(21, 29, 42, 0.82);
      border-color: var(--border);
      color: var(--text);
    }}
    html[data-theme="dark"] .stepper-number-v3 {{
      background: rgba(21, 29, 42, 0.82);
      border-color: var(--border);
      color: var(--muted);
    }}
    html[data-theme="dark"] .assessment-side-v3 {{
      background: rgba(14, 20, 31, 0.94);
      border-left-color: var(--border);
    }}
    html[data-theme="dark"] .toolbar-button-v3 {{
      background: rgba(21, 29, 42, 0.92);
      border-color: var(--border);
      color: var(--text);
    }}
    html[data-theme="dark"] .table-chip-v3 {{
      background: rgba(32, 44, 62, 0.86);
      border-color: var(--border);
      color: var(--muted);
    }}
    html[data-theme="dark"] .table-chip-v3.complete {{
      background: var(--success-soft);
      border-color: rgba(89, 170, 133, 0.55);
      color: var(--success);
    }}
    html[data-theme="dark"] .table-action-v3 {{
      background: rgba(21, 29, 42, 0.88);
      border-color: var(--border);
      color: var(--text);
    }}
    html[data-theme="dark"] .progress-ring-v3 {{
      background: conic-gradient(var(--accent) calc(var(--progress) * 1%), rgba(42, 58, 82, 0.9) 0);
    }}
    html[data-theme="dark"] .progress-ring-v3::before {{
      background: rgba(14, 21, 33, 0.96);
    }}
    html[data-theme="dark"] .progress-step-dot-v3 {{
      background: rgba(32, 44, 62, 0.9);
      border-color: var(--border);
    }}
    html[data-theme="dark"] .sidebar-status-v3 {{
      background: rgba(21, 29, 42, 0.94);
      border-color: var(--border);
      color: var(--muted);
    }}
    html[data-theme="dark"] .sidebar-status-v3.good {{
      background: var(--success-soft);
      color: var(--success);
    }}
    html[data-theme="dark"] .sidebar-status-v3.warn {{
      background: var(--warning-soft);
      color: var(--warning);
    }}
    html[data-theme="dark"] .sidebar-card-v3 {{
      background: rgba(21, 29, 42, 0.96) !important;
      border-color: var(--border) !important;
    }}
    html[data-theme="dark"] .sidebar-panel-minimal-v3 + .sidebar-panel-minimal-v3 {{
      border-top-color: var(--border) !important;
    }}
    html[data-theme="dark"] .assistant-tabs-v3 {{
      background: rgba(14, 20, 31, 0.88);
    }}
    html[data-theme="dark"] .assistant-tab-v3.active {{
      background: rgba(28, 38, 56, 0.96);
      color: var(--text);
    }}
    html[data-theme="dark"] .assistant-card-v3 {{
      background: rgba(17, 24, 36, 0.96);
      border-color: var(--border);
    }}
    html[data-theme="dark"] .assistant-prompt-v3 {{
      background: rgba(21, 29, 42, 0.92);
      border-color: var(--border);
      color: var(--text);
    }}
    html[data-theme="dark"] .assistant-section-v3 + .assistant-section-v3 {{
      border-top-color: var(--border);
    }}
    html[data-theme="dark"] .app-topbar-mark {{
      background: rgba(21, 29, 42, 0.92);
      border-color: var(--border);
    }}
    html[data-theme="dark"] .sidebar-edge-toggle-v3:hover {{
      background: rgba(28, 38, 56, 0.98);
      border-color: rgba(92, 138, 196, 0.72);
    }}
    html[data-theme="dark"] .sidebar-edge-toggle-v3[aria-pressed="false"] {{
      background: rgba(25, 35, 52, 0.98);
      border-color: rgba(84, 114, 154, 0.62);
    }}
    html[data-theme="dark"] .file-table-v3 th,
    html[data-theme="dark"] .file-table-v3 td {{
      border-bottom-color: var(--border);
    }}
    html[data-theme="dark"] .stepper-item-v3 + .stepper-item-v3 {{
      border-top-color: var(--border);
    }}
    html[data-theme="dark"] .workspace-environment-note-v3 {{
      background: rgba(21, 29, 42, 0.88);
      color: var(--muted);
    }}
    html[data-theme="dark"] .required-question-marker {{
      color: var(--danger);
    }}
    html[data-theme="dark"] .button-link.is-disabled {{
      background: rgba(32, 44, 62, 0.88);
      color: var(--muted);
    }}
    @media (max-width: 1220px) {{
      .app-content-v3 {{
        grid-template-columns: 260px minmax(0, 1fr);
      }}
      .sidebar-edge-toggle-v3 {{
        display: none;
      }}
      .panel-resizer-v3 {{
        display: none;
      }}
      .workspace-sidebar-right-v3 {{
        grid-column: 1 / -1;
        border-left: 0;
        border-top: 1px solid rgba(217, 226, 236, 0.92);
      }}
      body.left-rail-collapsed .app-content-v3 {{
        grid-template-columns: minmax(0, 1fr);
      }}
      body.left-rail-collapsed #left-sidebar.workspace-sidebar-v3,
      body.right-rail-collapsed .workspace-sidebar-right-v3 {{
        display: none;
      }}
    }}
    @media (max-width: 920px) {{
      .app-topbar-v3 {{
        grid-template-columns: 1fr;
      }}
      .app-topbar-actions {{
        justify-content: flex-start;
        flex-wrap: wrap;
      }}
      .app-content-v3 {{
        grid-template-columns: 1fr;
        padding: 0;
      }}
      .sidebar-edge-toggle-v3 {{
        display: none;
      }}
      .panel-resizer-v3 {{
        display: none;
      }}
      #left-sidebar.workspace-sidebar-v3,
      .workspace-sidebar-right-v3 {{
        border: 0;
      }}
      body.left-rail-collapsed #left-sidebar.workspace-sidebar-v3,
      body.right-rail-collapsed .workspace-sidebar-right-v3 {{
        display: none;
      }}
      .workspace-main-v3 {{
        padding: 20px 14px 24px;
      }}
      .workspace-header-row {{
        grid-template-columns: 1fr;
        align-items: start;
      }}
      .marathon-strip-top-v3 {{
        grid-template-columns: 1fr;
        justify-items: start;
      }}
      .marathon-title-wrap-v3 {{
        justify-items: start;
        text-align: left;
      }}
      .marathon-strip-v3 {{
        padding: 16px;
      }}
      .stepper-bar-v3,
      .assessment-grid-v3,
      .implementation-grid-v3,
      .progress-overview-v3 {{
        grid-template-columns: 1fr;
      }}
      .stepper-bar-v3 {{
        display: grid;
        gap: 0;
      }}
      .stepper-separator-v3 {{
        display: none;
      }}
      .stepper-item-v3 + .stepper-item-v3 {{
        border-top: 1px solid rgba(228, 234, 241, 0.95);
      }}
      .assessment-side-v3 {{
        border-left: 0;
        border-top: 1px solid rgba(191, 208, 220, 0.55);
      }}
    }}
  </style>
  {render_flash_cleanup_script(message, error, question_message, question_error)}
  {render_summary_selection_script()}
  {render_reading_scroll_script()}
  {render_question_navigation_script(status.get("week") if status else None, question_message)}
  {render_topic_chat_script()}
  {render_panel_resize_script()}
</head>
<body data-initialized="{str(initialized).lower()}">
  <div class="app-shell-v3">
    {render_app_topbar(status, initialized)}
    <div class="app-content-v3">
      {render_left_sidebar(status, initialized)}
      {render_sidebar_edge_toggle("left", "Show Guide", "Hide Guide", "sidebar-edge-toggle-v3-left")}
      <div class="panel-resizer-v3" data-panel-resizer="left" aria-hidden="true"></div>
      <div class="workspace-main-v3">
        {render_notice(message, error)}
      {render_header(status, initialized, course_total_weeks)}
        {render_info_sections(initialized)}
        {render_body(
            status,
            initialized,
            selected_question_id=selected_question_id,
            question_message=question_message,
            question_error=question_error,
            view_step=view_step,
        )}
      </div>
      <div class="panel-resizer-v3" data-panel-resizer="right" aria-hidden="true"></div>
      {render_right_sidebar(status, initialized, selected_question_id=selected_question_id)}
      {render_sidebar_edge_toggle("right", "Show Assistant", "Hide Assistant", "sidebar-edge-toggle-v3-right")}
    </div>
  </div>
</body>
</html>"""


def maybe_autoload_learning_assist(status: Optional[dict]) -> tuple[Optional[dict], Optional[str]]:
    if not status or status.get("learning_generated"):
        return status, None

    controller = get_controller()
    try:
        controller.learn.ensure_assist()
        return controller.status(), None
    except Exception as exc:  # pragma: no cover - defensive UI fallback
        if suppress_autoload_error(exc):
            return status, None
        return status, f"Learning Assist could not auto-load: {exc}"


def suppress_autoload_error(exc: Exception) -> bool:
    message = str(exc)
    suppressed_prefixes = (
        "OPENAI_API_KEY must be set",
        "ANTHROPIC_API_KEY must be set",
        "Config field `model` must be set",
        "The `openai` package is not installed.",
        "Anthropic authentication failed.",
        "Anthropic connection failed.",
        "Anthropic request timed out.",
    )
    suppressed_types = {"APIConnectionError", "APITimeoutError", "ConnectError", "TimeoutException"}
    return any(message.startswith(prefix) for prefix in suppressed_prefixes) or exc.__class__.__name__ in suppressed_types


def render_app_topbar(status: Optional[dict], initialized: bool) -> str:
    week_label = f"Week {status['week']}" if initialized and status else "Week 1"
    title = compact_week_title(status["title"]) if initialized and status else "Baseline Inference Server"
    status_label = topbar_status_label(status, initialized)
    return f"""
    <header class="app-topbar-v3">
      <div class="app-topbar-brand">
        <img class="app-topbar-mark" src="/assets/icon.png" alt="Learning Agent icon">
        <strong>Capstone Project</strong>
      </div>
      <div class="app-topbar-route" aria-label="Current route">
        <span class="app-topbar-divider" aria-hidden="true"></span>
        <span class="app-topbar-week">{escape(week_label)}</span>
        <span aria-hidden="true">•</span>
        <span class="app-topbar-title">{escape(title)}</span>
        <span class="app-topbar-status">{escape(status_label)}</span>
      </div>
      <div class="app-topbar-actions">
        <label class="app-topbar-search" aria-label="Search">
          <input type="search" placeholder="Search">
        </label>
        <button
          type="button"
          class="topbar-action-icon topbar-theme-toggle"
          data-theme-toggle
          aria-label="Switch to dark mode"
          aria-pressed="false"
          title="Switch to dark mode"
        >
          <span class="topbar-theme-toggle-indicator" aria-hidden="true"></span>
          <span class="topbar-theme-toggle-label" data-theme-toggle-label>Dark</span>
        </button>
        <span class="topbar-action-icon" aria-hidden="true">?</span>
        <span class="topbar-action-icon" aria-hidden="true">!</span>
        <span class="topbar-avatar" aria-label="User avatar">PE</span>
      </div>
    </header>
    """


def render_sidebar_edge_toggle(side: str, show_label: str, hide_label: str, side_class: str) -> str:
    return f"""
    <button
      type="button"
      class="sidebar-edge-toggle-v3 {side_class}"
      data-sidebar-toggle="{escape(side)}"
      data-sidebar-toggle-show="{escape(show_label)}"
      data-sidebar-toggle-hide="{escape(hide_label)}"
      aria-label="{escape(hide_label)}"
      aria-pressed="true"
      title="{escape(hide_label)}"
    >
      <span class="sidebar-icon" aria-hidden="true"></span>
    </button>
    """


def topbar_status_label(status: Optional[dict], initialized: bool) -> str:
    if not initialized or not status:
        return "Not Started"
    if status["gates"]["week_approved"]:
        return "Approved"
    if current_workflow_step(status) == "approve" and status.get("can_approve"):
        return "Ready"
    return "In Progress"


def compact_week_title(title: str) -> str:
    if title.startswith("Build a "):
        return title[len("Build a ") :]
    return title


def render_header(status: Optional[dict], initialized: bool, course_total_weeks: int) -> str:
    current_step = current_workflow_step(status) if initialized and status else None
    current_label = workflow_label(current_step) if current_step else "Set Up"
    return f"""
    <section class="workspace-header-v3">
      <div class="workspace-header-row">
        <div class="workspace-header-copy">
          <h1>Learn by Building Real Systems</h1>
          <p>Master concepts, build artifacts, and unlock the next stage.</p>
        </div>
        {render_primary_action(status, initialized)}
      </div>
      {render_marathon_strip(status, initialized, current_step, current_label, course_total_weeks)}
      <div class="workspace-meta-row">
        <span class="workspace-environment-note-v3">localhost:{DEFAULT_UI_PORT}</span>
      </div>
    </section>
    """


def render_marathon_strip(
    status: Optional[dict],
    initialized: bool,
    current_step: Optional[str],
    current_label: str,
    course_total_weeks: int,
) -> str:
    total_weeks = marathon_total_weeks(status, course_total_weeks)
    runner_percent = marathon_runner_percent(status, initialized, total_weeks)
    base_margin_percent = 100 / (total_weeks + 3)
    outer_margin_percent = base_margin_percent / 2
    runner_start_percent = outer_margin_percent
    runner_gap_percent = base_margin_percent / 4
    track_start_percent = runner_start_percent + runner_gap_percent
    track_end_percent = 100 - outer_margin_percent
    checkpoint_step_percent = (track_end_percent - track_start_percent) / total_weeks
    progress_step = (runner_percent / 100) * total_weeks
    completed_steps = min(total_weeks - 1, int(progress_step))
    step_fraction = progress_step - completed_steps
    checkpoint_positions = [runner_start_percent] + [
        track_start_percent + checkpoint_step_percent * index for index in range(1, total_weeks)
    ] + [track_end_percent]
    runner_visual_percent = checkpoint_positions[completed_steps] + (
        checkpoint_positions[completed_steps + 1] - checkpoint_positions[completed_steps]
    ) * step_fraction
    runner_visual_percent += MARATHON_RUNNER_POSITION_NUDGE_PERCENT
    runner_visual_percent = max(runner_start_percent, min(track_end_percent, runner_visual_percent))
    track_fill_percent = 0.0
    if track_end_percent > track_start_percent:
        track_fill_percent = max(
            0.0,
            min(100.0, ((runner_visual_percent - track_start_percent) / (track_end_percent - track_start_percent)) * 100),
        )
    title = f"The {total_weeks}-Week AI Engineering Marathon"
    summary_label = marathon_question_summary(status, initialized)
    subtitle = marathon_summary_copy(status, initialized, current_step, current_label)
    progress_copy = marathon_progress_copy(status, initialized, current_step)
    marker_html = render_marathon_markers(status, initialized, total_weeks)
    return f"""
    <article class="marathon-strip-v3" data-marathon-strip>
      <div class="marathon-strip-top-v3">
        <div class="marathon-summary-v3">
          <div class="marathon-copy-v3">
            <span class="marathon-kicker-v3">Marathon Progress</span>
            <p class="marathon-progress-copy-v3">{escape(summary_label)}</p>
          </div>
        </div>
        <div class="marathon-title-wrap-v3">
          <h2>{escape(title)}</h2>
          <p>{escape(subtitle)}</p>
        </div>
      </div>
      <div class="marathon-track-shell-v3">
        <div
          class="marathon-track-v3"
          data-marathon-progress
          role="progressbar"
          aria-valuemin="0"
          aria-valuemax="100"
          aria-valuenow="{int(round(runner_percent))}"
          aria-valuetext="{escape(progress_copy)}"
        >
          <div class="marathon-track-line-v3" style="left: {track_start_percent:.2f}%; right: {100 - track_end_percent:.2f}%;">
            <div class="marathon-track-fill-v3" style="width: {track_fill_percent:.2f}%;"></div>
          </div>
          <div class="marathon-runner-progress-v3" data-marathon-runner style="left: {runner_visual_percent:.2f}%;">
            <span class="marathon-runner-label-v3">You</span>
            <div class="marathon-runner-v3" aria-hidden="true">
              <span class="marathon-runner-shadow-v3"></span>
              <span class="marathon-runner-head-v3"></span>
              <span class="marathon-runner-torso-v3"></span>
              <span class="marathon-runner-shorts-v3"></span>
              <span class="marathon-runner-limb-v3 arm-back"></span>
              <span class="marathon-runner-limb-v3 arm-front"></span>
              <span class="marathon-runner-limb-v3 leg-back"></span>
              <span class="marathon-runner-limb-v3 leg-front"></span>
              <span class="marathon-runner-shoe-v3 shoe-back"></span>
              <span class="marathon-runner-shoe-v3 shoe-front"></span>
            </div>
          </div>
        </div>
        <div class="marathon-marker-row-v3">
          {marker_html}
        </div>
      </div>
    </article>
    """


def marathon_total_weeks(status: Optional[dict], course_total_weeks: Optional[int] = None) -> int:
    total_weeks = int((status or {}).get("total_weeks") or course_total_weeks or DEFAULT_COURSE_WEEKS)
    return max(1, total_weeks)


def resolve_course_total_weeks() -> int:
    try:
        return max(1, int(get_controller().curriculum_metadata().total_weeks))
    except CoachError:
        return DEFAULT_COURSE_WEEKS


def marathon_runner_percent(status: Optional[dict], initialized: bool, total_weeks: int) -> float:
    if not initialized or not status:
        return 0.0
    current_week = min(max(int(status["week"]), 1), total_weeks)
    week_completion = marathon_week_completion(status)
    return round(((current_week - 1) + week_completion) / total_weeks * 100, 2)


def marathon_week_completion(status: dict) -> float:
    if status["gates"]["week_approved"]:
        return 1.0

    progress = status.get("question_progress", {})
    required_total = int(progress.get("required_total", 0) or 0)
    required_passed = int(progress.get("required_passed", 0) or 0)
    learning_session = status.get("learning_session") or {}
    total_questions = len(learning_session.get("questions", []))
    answered_questions = len(latest_attempts(learning_session))
    answered_fraction = 0.0 if total_questions == 0 else min(1.0, answered_questions / total_questions)
    required_fraction = 0.0 if required_total == 0 else min(1.0, required_passed / required_total)
    learn_fraction = max(answered_fraction, required_fraction)

    required_files = len(status.get("required_files", []))
    completed_files = len(status.get("completed_files", []))
    build_fraction = 0.0 if required_files == 0 else min(1.0, completed_files / required_files)

    verify_fraction = marathon_verify_fraction(status)
    approve_fraction = 1.0 if status.get("can_approve") else 0.0

    return min(1.0, learn_fraction * 0.58 + build_fraction * 0.24 + verify_fraction * 0.12 + approve_fraction * 0.06)


def marathon_verify_fraction(status: dict) -> float:
    verification_fraction = 1.0 if status["gates"]["verification_passed"] else 0.5 if status.get("verification") else 0.0
    if not status.get("evidence_required"):
        return verification_fraction
    evidence_fraction = 1.0 if status["gates"]["evidence_reliable"] else 0.5 if status.get("observation") else 0.0
    return (verification_fraction + evidence_fraction) / 2


def marathon_question_summary(status: Optional[dict], initialized: bool) -> str:
    if not initialized or not status:
        return "Week 1 / Question 0 of 0"

    learning_session = status.get("learning_session") or {}
    total_questions = len(learning_session.get("questions", []))
    answered_questions = len(latest_attempts(learning_session))
    return f"Week {status['week']} / Question {answered_questions} of {total_questions}"


def marathon_summary_copy(
    status: Optional[dict],
    initialized: bool,
    current_step: Optional[str],
    current_label: Optional[str] = None,
) -> str:
    if not initialized or not status:
        return "Initialize Week 1 to start the race."

    progress = status.get("question_progress", {})
    if current_step == "learn":
        return f"{progress.get('required_passed', 0)} of {progress.get('required_total', 0)} required checkpoints passed. Current stop: {current_label or 'Learn'}."
    if current_step == "build":
        return f"{len(status['completed_files'])} of {len(status['required_files'])} deliverables shipped. Current stop: {current_label or 'Build'}."
    if current_step == "verify":
        return f"{workflow_reason(status, 'verify')} Current stop: {current_label or 'Verify'}."
    if current_step == "approve":
        return f"{workflow_reason(status, 'approve')} Current stop: {current_label or 'Approve'}."
    return "The next checkpoint unlocks as soon as the first week is initialized."


def marathon_progress_copy(status: Optional[dict], initialized: bool, current_step: Optional[str]) -> str:
    if not initialized or not status:
        return "0% through the marathon"
    return marathon_summary_copy(status, initialized, current_step)


def render_marathon_markers(status: Optional[dict], initialized: bool, total_weeks: int) -> str:
    current_week = int(status["week"]) if initialized and status else 1
    current_week = min(max(current_week, 1), total_weeks)
    current_week_completed = bool(initialized and status and status["gates"]["week_approved"])
    base_margin_percent = 100 / (total_weeks + 3)
    outer_margin_percent = base_margin_percent / 2
    runner_gap_percent = base_margin_percent / 4
    track_start_percent = outer_margin_percent + runner_gap_percent
    track_end_percent = 100 - outer_margin_percent
    checkpoint_step_percent = (track_end_percent - track_start_percent) / total_weeks
    markers = []
    for index in range(1, total_weeks):
        classes = ["marathon-marker-v3"]
        if initialized and index < current_week:
            classes.append("completed")
        elif initialized and index == current_week:
            classes.append("completed" if current_week_completed else "current")
        markers.append(
            f"<div class='{' '.join(classes)}' style='left: {track_start_percent + checkpoint_step_percent * index:.2f}%'>"
            f"<span>Week {index}</span>"
            "</div>"
        )
    finish_classes = ["marathon-marker-v3", "finish"]
    if initialized and current_week == total_weeks:
        finish_classes.append("completed" if current_week_completed else "current")
    markers.append(
        f"<div class='{' '.join(finish_classes)}' style='left: {track_end_percent:.2f}%'>"
        f"<span>Week {total_weeks}</span>"
        "<span>Finish</span>"
        "</div>"
    )
    return "".join(markers)


def next_step_copy(status: Optional[dict], current_step: Optional[str]) -> str:
    if not status or not current_step:
        return "Initialize Week 1 to begin."
    if current_step == "learn":
        progress = status.get("question_progress", {})
        return f"{progress.get('required_passed', 0)}/{progress.get('required_total', 0)} required questions passed."
    if current_step == "build":
        return workflow_reason(status, current_step)
    if current_step == "verify":
        return workflow_reason(status, current_step)
    if current_step == "approve":
        return workflow_reason(status, current_step)
    return ""


def render_state_summary(status: Optional[dict], initialized: bool) -> str:
    if not initialized or not status:
        return """
        <div class="stack">
          <span class="brand-label">This Week's Outcome</span>
          <h2>Current Week</h2>
          <p class="muted">No ledger loaded yet. Initialize Week 1 to begin.</p>
        </div>
        """

    gates = status["gates"]
    complete_count = sum(1 for value in gates.values() if value)
    return (
        f"<div class='stack'>"
        f"<span class='brand-label'>This Week's Outcome</span>"
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


def render_flash_cleanup_script(
    message: Optional[str],
    error: Optional[str],
    question_message: Optional[str],
    question_error: Optional[str],
) -> str:
    if not message and not error and not question_message and not question_error:
        return ""
    return """
  <script>
    window.addEventListener("DOMContentLoaded", function () {
      const url = new URL(window.location.href);
      url.searchParams.delete("message");
      url.searchParams.delete("error");
      url.searchParams.delete("question_message");
      url.searchParams.delete("question_error");
      const nextUrl = url.pathname + (url.search ? url.search : "") + url.hash;
      window.history.replaceState({}, document.title, nextUrl || "/");
    });
</script>
"""


def render_theme_script() -> str:
    return f"""
  <script>
    (function () {{
      const storageKey = "{THEME_STORAGE_KEY}";
      const root = document.documentElement;
      const mediaQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

      function storedTheme() {{
        try {{
          const value = window.localStorage.getItem(storageKey);
          return value === "dark" || value === "light" ? value : "";
        }} catch (_error) {{
          return "";
        }}
      }}

      function resolvedTheme() {{
        const stored = storedTheme();
        if (stored) {{
          return stored;
        }}
        return mediaQuery && mediaQuery.matches ? "dark" : "light";
      }}

      function applyTheme(theme) {{
        const nextTheme = theme === "dark" ? "dark" : "light";
        root.dataset.theme = nextTheme;
        root.style.colorScheme = nextTheme;
        const toggle = document.querySelector("[data-theme-toggle]");
        if (!toggle) {{
          return;
        }}
        const nextTitle = nextTheme === "dark" ? "Switch to light mode" : "Switch to dark mode";
        const nextLabel = nextTheme === "dark" ? "Light" : "Dark";
        toggle.setAttribute("aria-pressed", nextTheme === "dark" ? "true" : "false");
        toggle.setAttribute("aria-label", nextTitle);
        toggle.setAttribute("title", nextTitle);
        toggle.dataset.themeCurrent = nextTheme;
        const label = toggle.querySelector("[data-theme-toggle-label]");
        if (label) {{
          label.textContent = nextLabel;
        }}
      }}

      function persistTheme(theme) {{
        try {{
          window.localStorage.setItem(storageKey, theme);
        }} catch (_error) {{
          return;
        }}
      }}

      applyTheme(resolvedTheme());

      document.addEventListener("DOMContentLoaded", function () {{
        applyTheme(resolvedTheme());
        const toggle = document.querySelector("[data-theme-toggle]");
        if (toggle) {{
          toggle.addEventListener("click", function () {{
            const nextTheme = root.dataset.theme === "dark" ? "light" : "dark";
            persistTheme(nextTheme);
            applyTheme(nextTheme);
          }});
        }}
      }});

      if (mediaQuery) {{
        const syncWithSystem = function () {{
          if (!storedTheme()) {{
            applyTheme(resolvedTheme());
          }}
        }};
        if (typeof mediaQuery.addEventListener === "function") {{
          mediaQuery.addEventListener("change", syncWithSystem);
        }} else if (typeof mediaQuery.addListener === "function") {{
          mediaQuery.addListener(syncWithSystem);
        }}
      }}
    }})();
  </script>
"""


def render_sidebar_script() -> str:
    return """
  <script>
    (function () {
      const legacyLeftKey = "learning-agent-sidebar-collapsed";
      const railConfig = {
        left: { storageKey: "learning-agent-left-rail-collapsed", fallbackKey: legacyLeftKey },
        right: { storageKey: "learning-agent-right-rail-collapsed" },
      };
      const narrowQuery = window.matchMedia("(max-width: 920px)");

      function railButtons(side) {
        return document.querySelectorAll("[data-rail-toggle][data-rail-side='" + side + "']");
      }

      function railLabel(side, collapsed) {
        return (collapsed ? "Show " : "Hide ") + side + " sidebar";
      }

      function isCollapsed(side) {
        return document.body.classList.contains(side + "-rail-collapsed");
      }

      function anyRailOpen() {
        return document.body.classList.contains("left-rail-open") || document.body.classList.contains("right-rail-open");
      }

      function updateBackdrop() {
        const isNarrow = narrowQuery.matches;
        const active = isNarrow && anyRailOpen();
        const backdrop = document.querySelector("[data-rail-backdrop]");
        document.body.classList.toggle("narrow-rails", isNarrow);
        document.body.classList.toggle("rail-overlay-active", active);
        if (backdrop) {
          backdrop.hidden = !active;
        }
      }

      function setRailState(side, collapsed, persist) {
        document.body.classList.toggle(side + "-rail-collapsed", collapsed);
        document.body.classList.toggle(side + "-rail-open", !collapsed);
        railButtons(side).forEach(function (button) {
          const label = railLabel(side, collapsed);
          button.setAttribute("aria-pressed", (!collapsed).toString());
          button.setAttribute("aria-expanded", (!collapsed).toString());
          button.setAttribute("aria-label", label);
          button.setAttribute("title", label);
        });
        if (persist) {
          window.localStorage.setItem(railConfig[side].storageKey, String(collapsed));
        }
        updateBackdrop();
      }

      function closeOverlayRails() {
        if (!narrowQuery.matches) {
          return;
        }
        ["left", "right"].forEach(function (side) {
          if (!isCollapsed(side)) {
            setRailState(side, true, true);
          }
        });
      }

      function readStoredState(side) {
        const config = railConfig[side];
        const stored = window.localStorage.getItem(config.storageKey);
        if (stored !== null) {
          return stored === "true";
        }
        if (config.fallbackKey) {
          const legacy = window.localStorage.getItem(config.fallbackKey);
          if (legacy !== null) {
            return legacy === "true";
          }
        }
        return false;
      }

      window.addEventListener("DOMContentLoaded", function () {
        ["left", "right"].forEach(function (side) {
          setRailState(side, readStoredState(side), false);
        });

        document.querySelectorAll("[data-rail-toggle]").forEach(function (button) {
          button.addEventListener("click", function () {
            const side = button.getAttribute("data-rail-side");
            if (!side || !railConfig[side]) {
              return;
            }
            setRailState(side, !isCollapsed(side), true);
          });
        });

        const backdrop = document.querySelector("[data-rail-backdrop]");
        if (backdrop) {
          backdrop.addEventListener("click", closeOverlayRails);
        }

        document.addEventListener("keydown", function (event) {
          if (event.key === "Escape") {
            closeOverlayRails();
          }
        });

        if (typeof narrowQuery.addEventListener === "function") {
          narrowQuery.addEventListener("change", updateBackdrop);
        } else if (typeof narrowQuery.addListener === "function") {
          narrowQuery.addListener(updateBackdrop);
        }

        updateBackdrop();
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


def render_reading_scroll_script() -> str:
    return """
  <script>
    (function () {
      function atTop(element) {
        return element.scrollTop <= 0;
      }

      function atBottom(element) {
        return element.scrollTop + element.clientHeight >= element.scrollHeight - 1;
      }

      window.addEventListener("DOMContentLoaded", function () {
        const readingScroll = document.querySelector("[data-reading-scroll]");
        if (!readingScroll) {
          return;
        }

        readingScroll.addEventListener(
          "wheel",
          function (event) {
            if (event.deltaY < 0 && atTop(readingScroll)) {
              event.preventDefault();
              window.scrollBy({ top: event.deltaY, left: 0, behavior: "auto" });
              return;
            }
            if (event.deltaY > 0 && atBottom(readingScroll)) {
              event.preventDefault();
              window.scrollBy({ top: event.deltaY, left: 0, behavior: "auto" });
            }
          },
          { passive: false }
        );
      });
    })();
  </script>
"""


def render_topic_chat_script() -> str:
    return """
  <script>
    (function () {
      function chatRoot() {
        return document.querySelector("[data-topic-chat-root]");
      }

      function storageKey(root, suffix) {
        const week = root.getAttribute("data-week") || "unknown";
        return "learning-agent-topic-chat-" + suffix + "-week-" + week;
      }

      function sessionsKey(root) {
        return storageKey(root, "sessions");
      }

      function draftKey(root) {
        return storageKey(root, "draft");
      }

      function safeParse(raw, fallback) {
        if (!raw) {
          return fallback;
        }
        try {
          return JSON.parse(raw);
        } catch (_error) {
          return fallback;
        }
      }

      function escapeHtml(text) {
        const node = document.createElement("div");
        node.textContent = text == null ? "" : String(text);
        return node.innerHTML;
      }

      function renderInlineMarkup(text) {
        let escaped = escapeHtml(text);
        escaped = escaped.replace(/`([^`]+)`/g, "<code>$1</code>");
        return escaped.replace(/\\*\\*(.+?)\\*\\*/g, "<strong>$1</strong>");
      }

      function renderMarkdownBlock(text) {
        const lines = String(text || "").split(/\\r?\\n/);
        const chunks = [];
        const unorderedListItems = [];
        const orderedListItems = [];
        const paragraphLines = [];
        const codeLines = [];
        let inCodeBlock = false;

        function flushParagraph() {
          if (!paragraphLines.length) {
            return;
          }
          chunks.push("<p>" + renderInlineMarkup(paragraphLines.join(" ")) + "</p>");
          paragraphLines.length = 0;
        }

        function flushUnorderedList() {
          if (!unorderedListItems.length) {
            return;
          }
          const items = unorderedListItems
            .map(function (item) {
              return "<li>" + renderInlineMarkup(item) + "</li>";
            })
            .join("");
          chunks.push("<ul>" + items + "</ul>");
          unorderedListItems.length = 0;
        }

        function flushOrderedList() {
          if (!orderedListItems.length) {
            return;
          }
          const items = orderedListItems
            .map(function (item) {
              return "<li>" + renderInlineMarkup(item) + "</li>";
            })
            .join("");
          chunks.push("<ol>" + items + "</ol>");
          orderedListItems.length = 0;
        }

        function flushCodeBlock() {
          if (!codeLines.length) {
            inCodeBlock = false;
            return;
          }
          chunks.push("<pre><code>" + escapeHtml(codeLines.join("\\n")) + "</code></pre>");
          codeLines.length = 0;
          inCodeBlock = false;
        }

        lines.forEach(function (rawLine) {
          const line = rawLine.trim();
          if (inCodeBlock) {
            if (line.startsWith("```")) {
              flushCodeBlock();
            } else {
              codeLines.push(rawLine.replace(/\\s+$/, ""));
            }
            return;
          }
          if (line.startsWith("```") && line.endsWith("```") && line.length > 6) {
            flushParagraph();
            flushUnorderedList();
            flushOrderedList();
            chunks.push("<pre><code>" + escapeHtml(line.slice(3, -3).trim()) + "</code></pre>");
            return;
          }
          if (line.startsWith("```")) {
            flushParagraph();
            flushUnorderedList();
            flushOrderedList();
            inCodeBlock = true;
            codeLines.length = 0;
            return;
          }
          if (!line) {
            flushParagraph();
            flushUnorderedList();
            flushOrderedList();
            return;
          }
          if (line.startsWith("### ")) {
            flushParagraph();
            flushUnorderedList();
            flushOrderedList();
            chunks.push("<h5>" + renderInlineMarkup(line.slice(4)) + "</h5>");
            return;
          }
          if (line.startsWith("## ")) {
            flushParagraph();
            flushUnorderedList();
            flushOrderedList();
            chunks.push("<h4>" + renderInlineMarkup(line.slice(3)) + "</h4>");
            return;
          }
          if (line.startsWith("# ")) {
            flushParagraph();
            flushUnorderedList();
            flushOrderedList();
            chunks.push("<h3>" + renderInlineMarkup(line.slice(2)) + "</h3>");
            return;
          }
          if (line.startsWith("- ")) {
            flushParagraph();
            flushOrderedList();
            unorderedListItems.push(line.slice(2));
            return;
          }
          const orderedMatch = line.match(/^\\d+\\.\\s+(.*)$/);
          if (orderedMatch) {
            flushParagraph();
            flushUnorderedList();
            orderedListItems.push(orderedMatch[1]);
            return;
          }
          flushUnorderedList();
          flushOrderedList();
          paragraphLines.push(line);
        });

        flushParagraph();
        flushUnorderedList();
        flushOrderedList();
        flushCodeBlock();
        return "<div class='rendered-markdown'>" + chunks.join("") + "</div>";
      }

      function renderPlainTextBlock(text) {
        const paragraphs = String(text || "")
          .split(/\\r?\\n\\s*\\r?\\n/)
          .map(function (paragraph) {
            return paragraph.trim();
          })
          .filter(Boolean);
        if (!paragraphs.length) {
          return "<div class='rendered-markdown'><p></p></div>";
        }
        const chunks = paragraphs.map(function (paragraph) {
          return "<p>" + escapeHtml(paragraph).replace(/\\r?\\n/g, "<br>") + "</p>";
        });
        return "<div class='rendered-markdown'>" + chunks.join("") + "</div>";
      }

      function normalizeSelectionText(text) {
        return String(text || "")
          .replace(/\\u00a0/g, " ")
          .replace(/\\r\\n?/g, "\\n")
          .trim();
      }

      function selectionPreview(text) {
        const compact = normalizeSelectionText(text).replace(/\\s+/g, " ");
        if (!compact) {
          return "";
        }
        return compact.length > 160 ? compact.slice(0, 157) + "..." : compact;
      }

      function selectedTextFromDocument() {
        const selection = window.getSelection();
        if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
          return "";
        }
        const range = selection.getRangeAt(0);
        const container = range.commonAncestorContainer;
        const element = container && container.nodeType === Node.ELEMENT_NODE
          ? container
          : (container ? container.parentElement : null);
        if (!element || !document.body.contains(element)) {
          return "";
        }
        if (element.closest("textarea, input, button")) {
          return "";
        }
        return normalizeSelectionText(selection.toString());
      }

      function normalizeMessage(item) {
        if (!item || (item.role !== "user" && item.role !== "assistant") || typeof item.content !== "string") {
          return null;
        }
        return { role: item.role, content: item.content, pending: false };
      }

      function normalizeSession(item, index) {
        if (!item || typeof item !== "object") {
          return null;
        }
        const messages = Array.isArray(item.messages)
          ? item.messages.map(normalizeMessage).filter(Boolean)
          : [];
        const createdAt = typeof item.created_at === "number" ? item.created_at : Date.now() + index;
        const updatedAt = typeof item.updated_at === "number" ? item.updated_at : createdAt;
        return {
          id: typeof item.id === "string" && item.id ? item.id : "session_" + String(createdAt) + "_" + String(index),
          title: typeof item.title === "string" && item.title ? item.title : "New chat",
          created_at: createdAt,
          updated_at: updatedAt,
          messages: messages,
        };
      }

      function normalizeState(raw) {
        const payload = raw && typeof raw === "object" ? raw : {};
        const sessions = Array.isArray(payload.sessions)
          ? payload.sessions.map(normalizeSession).filter(Boolean)
          : [];
        const activeSessionId =
          typeof payload.active_session_id === "string" && payload.active_session_id
            ? payload.active_session_id
            : sessions[0]
              ? sessions[0].id
              : "";
        return {
          active_session_id: sessions.some(function (session) { return session.id === activeSessionId; })
            ? activeSessionId
            : (sessions[0] ? sessions[0].id : ""),
          sessions: sessions,
        };
      }

      function loadState(root) {
        return normalizeState(safeParse(window.localStorage.getItem(sessionsKey(root)), null));
      }

      function saveState(root, state) {
        window.localStorage.setItem(sessionsKey(root), JSON.stringify(state));
      }

      function loadDrafts(root) {
        const payload = safeParse(window.localStorage.getItem(draftKey(root)), {});
        return payload && typeof payload === "object" ? payload : {};
      }

      function saveDrafts(root, drafts) {
        window.localStorage.setItem(draftKey(root), JSON.stringify(drafts));
      }

      function activeSession(state) {
        return state.sessions.find(function (session) {
          return session.id === state.active_session_id;
        });
      }

      function isUntitledSession(session) {
        return Boolean(
          session &&
          session.title === "New chat" &&
          Array.isArray(session.messages) &&
          session.messages.length === 0
        );
      }

      function coalesceUntitledSessions(root, state) {
        const untitled = state.sessions.filter(isUntitledSession);
        if (untitled.length <= 1) {
          return state;
        }

        const keepId = untitled.some(function (session) { return session.id === state.active_session_id; })
          ? state.active_session_id
          : untitled[0].id;

        untitled.forEach(function (session) {
          if (session.id !== keepId) {
            clearDraft(root, session.id);
          }
        });

        state.sessions = state.sessions.filter(function (session) {
          return !isUntitledSession(session) || session.id === keepId;
        });

        if (!state.sessions.some(function (session) { return session.id === state.active_session_id; })) {
          state.active_session_id = keepId;
        }
        return state;
      }

      function makeSessionId() {
        return "session_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 8);
      }

      function createSession() {
        const now = Date.now();
        return {
          id: makeSessionId(),
          title: "New chat",
          created_at: now,
          updated_at: now,
          messages: [],
        };
      }

      function autoTitle(message) {
        const compact = message.replace(/\\s+/g, " ").trim();
        if (!compact) {
          return "New chat";
        }
        return compact.length > 42 ? compact.slice(0, 39) + "..." : compact;
      }

      function setStatus(root, text, tone) {
        const node = root.querySelector("[data-topic-chat-status]");
        if (!node) {
          return;
        }
        node.textContent = text || "";
        node.className = "fine-print topic-chat-status" + (tone ? " " + tone : "");
      }

      function renderSessions(root, state, pending) {
        const list = root.querySelector("[data-topic-chat-session-list]");
        if (!list) {
          return;
        }
        list.innerHTML = "";
        state.sessions
          .slice()
          .sort(function (left, right) {
            return right.updated_at - left.updated_at;
          })
          .forEach(function (session) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "topic-chat-session" + (session.id === state.active_session_id ? " active" : "");
            button.setAttribute("data-topic-chat-session", session.id);
            button.disabled = Boolean(pending);
            button.textContent = session.title;
            list.appendChild(button);
          });
      }

      function renderHistory(root, session) {
        const thread = root.querySelector("[data-topic-chat-thread]");
        const empty = root.querySelector("[data-topic-chat-empty]");
        if (!thread) {
          return;
        }
        thread.querySelectorAll("[data-topic-chat-message]").forEach(function (node) {
          node.remove();
        });
        const messages = session ? session.messages : [];
        if (empty) {
          empty.hidden = messages.length > 0;
        }
        messages.forEach(function (item, index) {
          const article = document.createElement("article");
          article.className = "topic-chat-message";
          article.setAttribute("data-role", item.role);
          article.setAttribute("data-pending", item.pending ? "true" : "false");
          article.setAttribute("data-topic-chat-message", String(index));

          const meta = document.createElement("div");
          meta.className = "topic-chat-meta";
          const role = document.createElement("span");
          role.textContent = item.role === "assistant" ? "Tutor" : "You";
          meta.appendChild(role);

          const content = document.createElement("div");
          content.className = "topic-chat-content";
          if (item.role === "assistant") {
            content.innerHTML = renderMarkdownBlock(item.content);
          } else {
            content.innerHTML = renderPlainTextBlock(item.content);
          }

          article.appendChild(meta);
          article.appendChild(content);
          thread.appendChild(article);
        });
        thread.scrollTop = thread.scrollHeight;
      }

      function setComposerDisabled(root, disabled) {
        const textarea = root.querySelector("[data-topic-chat-textarea]");
        const sendButton = root.querySelector("[data-topic-chat-submit]");
        const deleteButton = root.querySelector("[data-topic-chat-delete]");
        const newButton = root.querySelector("[data-topic-chat-new]");
        const clearSelectionButton = root.querySelector("[data-topic-chat-selection-clear]");
        if (textarea) {
          textarea.disabled = disabled;
        }
        if (sendButton) {
          sendButton.disabled = disabled;
        }
        if (deleteButton) {
          deleteButton.disabled = disabled;
        }
        if (newButton) {
          newButton.disabled = disabled;
        }
        if (clearSelectionButton) {
          clearSelectionButton.disabled = disabled;
        }
      }

      function updateDeleteButton(root, state, initialized, pending) {
        const button = root.querySelector("[data-topic-chat-delete]");
        if (!button) {
          return;
        }
        const hasActiveSession = Boolean(activeSession(state));
        button.hidden = !hasActiveSession;
        button.disabled = !initialized || pending || !hasActiveSession;
      }

      function persistDraft(root, state) {
        const textarea = root.querySelector("[data-topic-chat-textarea]");
        const session = activeSession(state);
        if (!textarea || !session) {
          return;
        }
        const drafts = loadDrafts(root);
        const value = textarea.value || "";
        if (!value.trim()) {
          delete drafts[session.id];
        } else {
          drafts[session.id] = value;
        }
        saveDrafts(root, drafts);
      }

      function clearDraft(root, sessionId) {
        const drafts = loadDrafts(root);
        delete drafts[sessionId];
        saveDrafts(root, drafts);
      }

      function restoreDraft(root, state) {
        const textarea = root.querySelector("[data-topic-chat-textarea]");
        const session = activeSession(state);
        if (!textarea) {
          return;
        }
        if (!session) {
          textarea.value = "";
          return;
        }
        const drafts = loadDrafts(root);
        textarea.value = typeof drafts[session.id] === "string" ? drafts[session.id] : "";
      }

      function renderSelectionContext(root, selectedContext) {
        const strip = root.querySelector("[data-topic-chat-selection-strip]");
        const preview = root.querySelector("[data-topic-chat-selection-preview]");
        if (!strip || !preview) {
          return;
        }
        const hasSelection = Boolean(normalizeSelectionText(selectedContext));
        strip.hidden = !hasSelection;
        preview.textContent = hasSelection ? selectionPreview(selectedContext) : "";
      }

      function renderState(root, state, initialized, pending, selectedContext) {
        renderSessions(root, state, pending);
        renderHistory(root, activeSession(state));
        restoreDraft(root, state);
        renderSelectionContext(root, selectedContext);
        updateDeleteButton(root, state, initialized, pending);
      }

      function submitTopicChatForm(form) {
        if (typeof form.requestSubmit === "function") {
          form.requestSubmit();
          return;
        }
        form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      }

      async function readTopicChatStream(response, onEvent) {
        if (!response.body) {
          throw new Error("Topic chat response did not include a readable stream.");
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        
        function flushLines() {
          const lines = buffer.split(/\\r?\\n/);
          buffer = lines.pop() || "";
          lines.forEach(function (line) {
            if (!line.trim()) {
              return;
            }
            onEvent(JSON.parse(line));
          });
        }

        while (true) {
          const result = await reader.read();
          if (result.done) {
            buffer += decoder.decode(result.value, { stream: false });
            flushLines();
            break;
          }
          buffer += decoder.decode(result.value, { stream: true });
          flushLines();
        }

        if (buffer.trim()) {
          onEvent(JSON.parse(buffer));
        }
      }

      window.addEventListener("DOMContentLoaded", function () {
        const root = chatRoot();
        if (!root) {
          return;
        }

        const initialized = root.getAttribute("data-initialized") === "true";
        const form = root.querySelector("[data-topic-chat-form]");
        const textarea = root.querySelector("[data-topic-chat-textarea]");
        const newButton = root.querySelector("[data-topic-chat-new]");
        const deleteButton = root.querySelector("[data-topic-chat-delete]");
        let pending = false;
        let selectedContext = "";
        let state = loadState(root);
        state = coalesceUntitledSessions(root, state);
        saveState(root, state);

        renderState(root, state, initialized, pending, selectedContext);

        if (textarea) {
          textarea.addEventListener("input", function () {
            persistDraft(root, state);
            setStatus(root, "", "");
          });
          textarea.addEventListener("keydown", function (event) {
            if (event.key !== "Enter" || event.shiftKey || event.isComposing) {
              return;
            }
            event.preventDefault();
            if (!initialized || pending || !form) {
              return;
            }
            submitTopicChatForm(form);
          });
        }

        document.addEventListener("selectionchange", function () {
          if (!initialized) {
            return;
          }
          const nextSelection = selectedTextFromDocument();
          if (!nextSelection) {
            return;
          }
          selectedContext = nextSelection;
          renderSelectionContext(root, selectedContext);
        });

        if (newButton) {
          newButton.addEventListener("click", function () {
            if (!initialized || pending) {
              return;
            }
            persistDraft(root, state);
            const existingUntitled = state.sessions.find(isUntitledSession);
            if (existingUntitled) {
              state.active_session_id = existingUntitled.id;
            } else {
              const session = createSession();
              state.sessions.unshift(session);
              state.active_session_id = session.id;
            }
            saveState(root, state);
            renderState(root, state, initialized, pending, selectedContext);
            setStatus(root, "", "");
            if (textarea) {
              textarea.focus();
            }
          });
        }

        if (!initialized || !form || !textarea) {
          setComposerDisabled(root, !initialized);
          return;
        }

        if (deleteButton) {
          deleteButton.addEventListener("click", function () {
            if (pending) {
              return;
            }
            const session = activeSession(state);
            if (!session) {
              return;
            }
            clearDraft(root, session.id);
            state.sessions = state.sessions.filter(function (item) {
              return item.id !== session.id;
            });
            state.active_session_id = state.sessions[0] ? state.sessions[0].id : "";
            saveState(root, state);
            renderState(root, state, initialized, pending, selectedContext);
            setStatus(root, "Chat deleted.", "success");
          });
        }

        root.addEventListener("click", function (event) {
          const sessionButton = event.target.closest("[data-topic-chat-session]");
          if (sessionButton) {
            if (pending) {
              return;
            }
            persistDraft(root, state);
            state.active_session_id = sessionButton.getAttribute("data-topic-chat-session") || "";
            saveState(root, state);
            renderState(root, state, initialized, pending, selectedContext);
            setStatus(root, "", "");
            return;
          }

          const clearSelectionButton = event.target.closest("[data-topic-chat-selection-clear]");
          if (clearSelectionButton) {
            selectedContext = "";
            renderSelectionContext(root, selectedContext);
            setStatus(root, "", "");
            return;
          }

          const suggestion = event.target.closest("[data-topic-chat-suggestion]");
          if (suggestion && textarea) {
            textarea.value = suggestion.getAttribute("data-topic-chat-prompt") || "";
            persistDraft(root, state);
            submitTopicChatForm(form);
          }
        });

        form.addEventListener("submit", async function (event) {
          event.preventDefault();
          if (pending) {
            return;
          }
          const message = textarea.value.trim();
          if (!message) {
            setStatus(root, "Enter a message before sending.", "error");
            return;
          }

          if (!activeSession(state)) {
            const session = createSession();
            state.sessions.unshift(session);
            state.active_session_id = session.id;
          }

          const session = activeSession(state);
          const targetSessionId = session.id;
          const priorHistory = session.messages.slice();
          const selectionContextForRequest = selectedContext;
          if (session.title === "New chat" && session.messages.length === 0) {
            session.title = autoTitle(message);
          }
          session.messages.push({ role: "user", content: message });
          const assistantPlaceholder = { role: "assistant", content: "Thinking...", pending: true };
          session.messages.push(assistantPlaceholder);
          session.updated_at = Date.now();
          saveState(root, state);
          pending = true;
          renderState(root, state, initialized, pending, selectedContext);
          textarea.value = "";
          clearDraft(root, targetSessionId);
          setStatus(root, "Asking the model...", "");
          setComposerDisabled(root, true);

          try {
            let streamCompleted = false;
            const response = await fetch("/api/topic-chat", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                message: message,
                history: priorHistory.map(function (item) {
                  return { role: item.role, content: item.content };
                }),
                current_step: root.getAttribute("data-current-step") || "",
                selection_context: selectionContextForRequest,
              }),
            });
            await readTopicChatStream(response, function (payload) {
              const replySession = state.sessions.find(function (item) {
                return item.id === targetSessionId;
              });
              if (!replySession) {
                return;
              }
              const assistantMessage = replySession.messages[replySession.messages.length - 1];
              if (!assistantMessage || assistantMessage.role !== "assistant") {
                return;
              }
              if (payload.type === "delta") {
                if (assistantMessage.pending) {
                  assistantMessage.content = payload.delta || "";
                  assistantMessage.pending = false;
                } else {
                  assistantMessage.content += payload.delta || "";
                }
                replySession.updated_at = Date.now();
                saveState(root, state);
                renderHistory(root, replySession);
                return;
              }
              if (payload.type === "done") {
                streamCompleted = true;
                assistantMessage.pending = false;
                assistantMessage.content = payload.reply || assistantMessage.content;
                replySession.updated_at = Date.now();
                saveState(root, state);
                renderHistory(root, replySession);
                return;
              }
              if (payload.type === "error") {
                throw new Error(payload.error || "Topic chat request failed.");
              }
            });
            if (!streamCompleted) {
              throw new Error("Topic chat stream ended before the assistant finished replying.");
            }
            if (selectionContextForRequest && selectedContext === selectionContextForRequest) {
              selectedContext = "";
              renderSelectionContext(root, selectedContext);
            }
            setStatus(root, "Reply ready.", "success");
          } catch (error) {
            const replySession = state.sessions.find(function (item) {
              return item.id === targetSessionId;
            });
            if (replySession) {
              const assistantMessage = replySession.messages[replySession.messages.length - 1];
              if (
                assistantMessage &&
                assistantMessage.role === "assistant" &&
                assistantMessage.pending
              ) {
                replySession.messages.pop();
                saveState(root, state);
              }
            }
            setStatus(root, error && error.message ? error.message : "Topic chat request failed.", "error");
          } finally {
            pending = false;
            renderState(root, state, initialized, pending, selectedContext);
            setComposerDisabled(root, false);
            textarea.focus();
          }
        });

        window.addEventListener("beforeunload", function () {
          persistDraft(root, state);
        });
      });
    })();
  </script>
"""


def render_panel_resize_script() -> str:
    return """
  <script>
    (function () {
      const leftKey = "learning-agent-left-rail-width";
      const rightKey = "learning-agent-right-rail-width";
      const leftCollapsedKey = "learning-agent-left-rail-collapsed";
      const rightCollapsedKey = "learning-agent-right-rail-collapsed";
      const minWidth = 208;
      const maxWidth = 340;
      const disabledQuery = window.matchMedia("(max-width: 1220px)");

      function clamp(value) {
        return Math.min(maxWidth, Math.max(minWidth, value));
      }

      function setWidth(side, value, persist) {
        const width = clamp(value);
        document.documentElement.style.setProperty("--" + side + "-rail-width", width + "px");
        if (persist) {
          window.localStorage.setItem(side === "left" ? leftKey : rightKey, String(width));
        }
      }

      function readStored(side, fallback) {
        const raw = window.localStorage.getItem(side === "left" ? leftKey : rightKey);
        const parsed = raw ? Number(raw) : NaN;
        return Number.isFinite(parsed) ? clamp(parsed) : fallback;
      }

      function collapsedKey(side) {
        return side === "left" ? leftCollapsedKey : rightCollapsedKey;
      }

      function readCollapsed(side) {
        return window.localStorage.getItem(collapsedKey(side)) === "true";
      }

      function writeCollapsed(side, collapsed) {
        window.localStorage.setItem(collapsedKey(side), collapsed ? "true" : "false");
      }

      function applyCollapsedState(side, collapsed) {
        document.body.classList.toggle(side + "-rail-collapsed", collapsed);
      }

      function syncToggleButton(button, collapsed) {
        if (!button) {
          return;
        }
        const showLabel = button.getAttribute("data-sidebar-toggle-show") || "Show";
        const hideLabel = button.getAttribute("data-sidebar-toggle-hide") || "Hide";
        const label = collapsed ? showLabel : hideLabel;
        button.setAttribute("aria-pressed", collapsed ? "false" : "true");
        button.setAttribute("aria-label", label);
        button.setAttribute("title", label);
      }

      function resetForNarrow() {
        document.documentElement.style.removeProperty("--left-rail-width");
        document.documentElement.style.removeProperty("--right-rail-width");
      }

      window.addEventListener("DOMContentLoaded", function () {
        const shell = document.querySelector(".app-content-v3");
        const leftHandle = document.querySelector("[data-panel-resizer='left']");
        const rightHandle = document.querySelector("[data-panel-resizer='right']");
        const leftToggle = document.querySelector("[data-sidebar-toggle='left']");
        const rightToggle = document.querySelector("[data-sidebar-toggle='right']");
        if (!shell || !leftHandle || !rightHandle) {
          return;
        }

        function applyStoredWidths() {
          applyCollapsedState("left", readCollapsed("left"));
          applyCollapsedState("right", readCollapsed("right"));
          syncToggleButton(leftToggle, readCollapsed("left"));
          syncToggleButton(rightToggle, readCollapsed("right"));
          if (disabledQuery.matches) {
            resetForNarrow();
            return;
          }
          setWidth("left", readStored("left", 236), false);
          setWidth("right", readStored("right", 250), false);
        }

        function startResize(side, handle, startEvent) {
          if (disabledQuery.matches || readCollapsed(side)) {
            return;
          }
          startEvent.preventDefault();
          handle.classList.add("is-active");

          function onMove(event) {
            const rect = shell.getBoundingClientRect();
            if (side === "left") {
              setWidth("left", event.clientX - rect.left, false);
            } else {
              setWidth("right", rect.right - event.clientX, false);
            }
          }

          function onUp(event) {
            const rect = shell.getBoundingClientRect();
            if (side === "left") {
              setWidth("left", event.clientX - rect.left, true);
            } else {
              setWidth("right", rect.right - event.clientX, true);
            }
            handle.classList.remove("is-active");
            window.removeEventListener("pointermove", onMove);
            window.removeEventListener("pointerup", onUp);
          }

          window.addEventListener("pointermove", onMove);
          window.addEventListener("pointerup", onUp);
        }

        leftHandle.addEventListener("pointerdown", function (event) {
          startResize("left", leftHandle, event);
        });
        rightHandle.addEventListener("pointerdown", function (event) {
          startResize("right", rightHandle, event);
        });

        [leftToggle, rightToggle].forEach(function (button) {
          if (!button) {
            return;
          }
          button.addEventListener("click", function () {
            const side = button.getAttribute("data-sidebar-toggle");
            if (!side) {
              return;
            }
            const nextCollapsed = !readCollapsed(side);
            writeCollapsed(side, nextCollapsed);
            applyCollapsedState(side, nextCollapsed);
            syncToggleButton(button, nextCollapsed);
          });
        });

        if (typeof disabledQuery.addEventListener === "function") {
          disabledQuery.addEventListener("change", applyStoredWidths);
        } else if (typeof disabledQuery.addListener === "function") {
          disabledQuery.addListener(applyStoredWidths);
        }

        applyStoredWidths();
      });
    })();
  </script>
"""


def render_question_navigation_script(current_week: Optional[int], question_message: Optional[str]) -> str:
    week_literal = "null" if current_week is None else str(current_week)
    message_literal = json.dumps(question_message or "")
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

        document.querySelectorAll("[data-question-jump-form]").forEach(function (form) {
          form.addEventListener("submit", function (event) {
            event.preventDefault();
            const input = form.querySelector("[data-question-jump-input]");
            const rawValue = input ? input.value.trim() : "";
            const targetNumber = Number(rawValue);
            const targetLink = document.querySelector(
              "[data-question-modal-link][data-question-order='" + String(targetNumber) + "']"
            );

            if (!Number.isInteger(targetNumber) || !targetLink) {
              if (input) {
                input.focus();
                input.select();
              }
              return;
            }

            saveDraftNow();
            const href = targetLink.getAttribute("href") || "";
            const questionId = new URL(href, window.location.origin).searchParams.get("question_id") || "";
            persistQuestionNavigationState(questionId);
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


def render_info_sections(initialized: bool) -> str:
    if initialized:
        return ""
    return """
    <article class="panel" style="padding: 18px 20px;">
      <h2>Quick Start</h2>
      <p class="muted">Initialize Week 1 to load the current week, unlock the guided workflow, and turn the workspace into a live engineering project.</p>
    </article>
    """


def render_body(
    status: Optional[dict],
    initialized: bool,
    selected_question_id: Optional[str] = None,
    question_message: Optional[str] = None,
    question_error: Optional[str] = None,
    view_step: Optional[str] = None,
) -> str:
    if not initialized or not status:
        return f"""
        <section class="implementation-shell-v3">
          {render_stepper_bar_v3(None, "learn", initialized=False)}
          <div class="assessment-grid-v3" id="current-assessment">
            <article class="assessment-card-v3">
              <div class="eyebrow-row-v3">
                <strong>Current Assessment</strong>
                <span>Initialize Week 1</span>
              </div>
              <h2 class="question-heading-v3">Set up the week ledger to begin the guided workflow.</h2>
              <div class="guidance-block-v3">
                <div class="guidance-row-v3">
                  <strong>Guidance</strong>
                  <ul>
                    <li>Create the local ledger and load Week 1 from the roadmap.</li>
                    <li>Unlock the week, progress, deliverables, and assistant rails.</li>
                    <li>Start with concept practice before implementation work appears.</li>
                  </ul>
                </div>
              </div>
              <div class="assessment-expected-v3">
                <strong>Expected:</strong>
                <span>No ledger loaded yet. Initialize Week 1 to start the course.</span>
              </div>
              <div class="assessment-actions-v3">
                <form method="post" action="/action" class="form-grid">
                  <input type="hidden" name="action" value="init">
                  <button type="submit">Initialize Week 1</button>
                </form>
              </div>
            </article>
            <aside class="assessment-side-v3">
              <div class="mini-panel-v3">
                <h3>Your Progress</h3>
                <div class="progress-block" aria-label="Question progress">
                  <div class="progress-meta">
                    <strong>0 / 0 Questions</strong>
                    <span>Not started</span>
                  </div>
                  <div class="progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="0" aria-valuenow="0" aria-valuetext="0% complete">
                    <div class="progress-fill" style="width: 0%;"></div>
                  </div>
                </div>
              </div>
              <div class="mini-panel-v3">
                <h3>Concepts</h3>
                <div class="concept-status-list-v3">
                  <div class="concept-status-item-v3"><span>Token Generation</span><span class="status-missing">Locked</span></div>
                  <div class="concept-status-item-v3"><span>Prefill vs Decode</span><span class="status-missing">Locked</span></div>
                  <div class="concept-status-item-v3"><span>Inference Pipeline</span><span class="status-missing">Locked</span></div>
                </div>
              </div>
            </aside>
          </div>
        </section>
        """

    learning_session = status.get("learning_session") or {}
    actual_step = current_workflow_step(status)
    valid_step_ids = {s["id"] for s in workflow_steps(status)}
    current_step = (
        view_step
        if view_step and view_step in valid_step_ids and view_step != actual_step
        else actual_step
    )
    orientation_html = render_week_orientation_banner(learning_session.get("reading_material"))
    assessment = (
        render_learning_assessment_v3(
            status,
            learning_session,
            selected_question_id,
            question_message=question_message,
            question_error=question_error,
        )
        if current_step == "learn"
        else render_generic_assessment_v3(status, current_step)
    )
    supporting_section = "" if current_step == "learn" else render_implementation_section_v3(status)
    return f"""
    <section class="implementation-shell-v3">
      {orientation_html}
      {render_stepper_bar_v3(status, current_step, initialized=True, actual_step=actual_step)}
      {assessment}
      {supporting_section}
    </section>
    """


def render_stepper_bar_v3(status: Optional[dict], current_step: str, initialized: bool, actual_step: Optional[str] = None) -> str:
    step_descriptions = {
        "learn": "Concept Mastery",
        "build": "Create Deliverables",
        "verify": "Metrics & Evidence",
        "approve": "Unlock Next Stage",
    }
    if initialized and status:
        steps = workflow_steps(status)
    else:
        steps = [
            {"id": "learn", "label": "Learn", "status": "not_started"},
            {"id": "build", "label": "Build", "status": "not_started"},
            {"id": "verify", "label": "Verify", "status": "not_started"},
            {"id": "approve", "label": "Approve", "status": "not_started"},
        ]

    items = []
    for index, step in enumerate(steps, start=1):
        step_id = step["id"]
        is_current = step_id == current_step
        is_passed = step["status"] == "passed"
        is_actual = step_id == actual_step
        # Clickable if: passed (review) OR is the real active step when viewing an override
        can_click = (is_passed or (is_actual and not is_current)) and not is_current
        current_class = " current" if is_current else ""
        clickable_class = " clickable" if can_click else ""
        inner = (
            f"<span class='stepper-number-v3'>{index}</span>"
            "<div class='stepper-copy-v3'>"
            f"<span class='stepper-label-v3'>{escape(step['label'])}</span>"
            f"<span class='stepper-subcopy-v3'>{escape(step_descriptions.get(step_id, ''))}</span>"
            "</div>"
        )
        if can_click:
            items.append(
                f"<a href='{'/' if is_actual else f'/?view_step={step_id}'}' class='stepper-item-v3{current_class}{clickable_class}'>"
                f"{inner}"
                "</a>"
            )
        else:
            items.append(
                f"<div class='stepper-item-v3{current_class}'>"
                f"{inner}"
                "</div>"
            )
        if index < len(steps):
            items.append("<span class='stepper-separator-v3' aria-hidden='true'>→</span>")
    return f"<section class='stepper-bar-v3'>{''.join(items)}</section>"


def render_learning_assessment_v3(
    status: dict,
    learning_session: dict,
    selected_question_id: Optional[str],
    question_message: Optional[str] = None,
    question_error: Optional[str] = None,
) -> str:
    progress = status.get("question_progress", {})
    questions = learning_session.get("questions", [])
    attempts = latest_attempts(learning_session)
    reading_material = learning_session.get("reading_material")
    selected_question = select_learning_question(questions, selected_question_id)
    cards_html = "".join(render_concept_card(card) for card in learning_session.get("concept_cards", []))
    if not cards_html:
        cards_html = "<p class='muted'>No concept cards generated yet.</p>"
    reading_html = render_reading_material(reading_material)
    workspace_html = (
        render_learning_workspace(
            selected_question,
            questions,
            attempts,
            progress,
            question_message=question_message,
            question_error=question_error,
        )
        if selected_question
        else render_learning_workspace_empty_v3(progress)
    )
    question_modal = render_question_list_modal(questions, attempts, selected_question["id"] if selected_question else None)
    return f"""
    <section class="learn-stage-shell-v3" id="current-assessment">
      <div class="learn-stage-header-v3">
        <div class="learn-stage-copy-v3">
          <span class="learn-stage-kicker-v3">Learn Workspace</span>
          <h2>Study on the left and answer on the right.</h2>
          <p class="muted">This surface is specific to the active Learn step. Build and Verify content stay out of the center workspace until those steps become active.</p>
        </div>
        <div class="learn-stage-meta-v3">
          <span class="assessment-tag-v3">Open-book mode</span>
          <span class="assessment-tag-v3">Concept anchors</span>
        </div>
      </div>
      <section class="learn-workspace learning-stage-shell">
        <div class="reading-column">
          <div class="reading-column-scroll" data-reading-scroll>
            <article class="subpanel stage-surface learn-reading-section-v3">
              <h3>Concept Cards</h3>
              <div class="concept-card-grid">{cards_html}</div>
            </article>
            <article class="subpanel stage-surface learn-reading-section-v3">
              <h3>Reading Material</h3>
              <div class="reading-stack">{reading_html}</div>
            </article>
            {render_additional_resources_panel(status, "subpanel stage-surface learn-reading-section-v3")}
          </div>
        </div>
        <div class="questions-column">
          {workspace_html}
        </div>
      </section>
      {question_modal}
    </section>
    """


def render_generic_assessment_v3(status: dict, current_step: str) -> str:
    guidance = "".join(f"<li>{escape(item)}</li>" for item in step_focus_guidance(status, current_step))
    return f"""
    <div class="assessment-grid-v3" id="current-assessment">
      <article class="assessment-card-v3">
        <div class="eyebrow-row-v3">
          <strong>Current Focus</strong>
          <span>{escape(workflow_label(current_step))}</span>
        </div>
        <h2 class="question-heading-v3">{escape(workflow_reason(status, current_step))}</h2>
        <div class="guidance-block-v3">
          <div class="guidance-row-v3">
            <strong>Guidance</strong>
            <ul>{guidance}</ul>
          </div>
        </div>
        <div class="assessment-actions-v3">
          {render_current_step_actions_v3(status, current_step)}
        </div>
      </article>
      {render_assessment_side_v3(status, {}, None, status.get('question_progress', {}))}
    </div>
    """


def render_assessment_side_v3(
    status: dict,
    learning_session: dict,
    selected_question: Optional[dict],
    progress: dict,
) -> str:
    required_passed = int(progress.get("required_passed", 0))
    required_total = int(progress.get("required_total", 0))
    progress_percent = 0 if required_total == 0 else round((required_passed / required_total) * 100)
    attempts = latest_attempts(learning_session)
    concept_items = []
    for tag in question_concept_tags(selected_question, learning_session):
        label = "Ready" if selected_question and question_attempt_status(attempts, selected_question["id"]) == "passed" else "Missing"
        concept_items.append(
            f"<div class='concept-status-item-v3'><span>{escape(tag)}</span><span class='status-missing'>{escape(label)}</span></div>"
        )
    if not concept_items:
        concept_items.append(
            "<div class='concept-status-item-v3'><span>Week concepts</span><span class='status-missing'>Pending</span></div>"
        )
    return f"""
    <aside class="assessment-side-v3">
      <div class="mini-panel-v3">
        <h3>Your Progress</h3>
        <div class="progress-block" aria-label="Question progress">
          <div class="progress-meta">
            <strong>{required_passed} / {required_total} Questions</strong>
            <span>{progress_percent}% complete</span>
          </div>
          <div class="progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="{required_total}" aria-valuenow="{required_passed}" aria-valuetext="{progress_percent}% complete">
            <div class="progress-fill" style="width: {progress_percent}%;"></div>
          </div>
        </div>
      </div>
      <div class="mini-panel-v3">
        <h3>Concepts</h3>
        <div class="concept-status-list-v3">
          {''.join(concept_items)}
        </div>
        <a class="button-link secondary" href="/?question_id={quote_plus(selected_question['id']) if selected_question else ''}#question-list-modal">View All</a>
      </div>
    </aside>
    """


def render_assessment_guidance_items(selected_question: dict, learning_session: dict) -> str:
    rubric = selected_question.get("scoring_rubric", [])
    items = [escape(item) for item in rubric[:3]]
    if len(items) < 3:
        prompt_lower = selected_question.get("prompt_text", "").lower()
        if "prefill" in prompt_lower or "decode" in prompt_lower:
            defaults = [
                "Define both phases clearly.",
                "Explain where each phase happens in inference.",
                "Call out why decode is iterative and latency-sensitive.",
            ]
        else:
            defaults = [
                "Explain the concept in system terms.",
                "Tie the answer back to the deliverables for this week.",
                "Show what would matter in a real implementation.",
            ]
        for item in defaults:
            if len(items) >= 3:
                break
            items.append(escape(item))
    return "".join(f"<li>{item}</li>" for item in items)


def question_concept_tags(selected_question: Optional[dict], learning_session: dict) -> list[str]:
    if not selected_question:
        return ["Token Generation", "Inference Pipeline"]
    prompt_lower = selected_question.get("prompt_text", "").lower()
    if "prefill" in prompt_lower or "decode" in prompt_lower:
        return ["Token Generation", "Prefill vs Decode", "Inference Pipeline"]
    concept_cards = learning_session.get("concept_cards", [])
    tags = [card.get("title") or humanize_section_label(card.get("concept", "Concept")) for card in concept_cards[:3]]
    return [tag for tag in tags if tag] or ["Current Week", "Implementation", "Verification"]


def step_focus_guidance(status: dict, current_step: str) -> list[str]:
    if current_step == "build":
        return [
            "Generate the scoped implementation brief if it is missing.",
            "Create the required files inside the allowed directories.",
            "Scan the repository to refresh deliverable completion.",
        ]
    if current_step == "verify":
        return [
            "Record the required benchmark metrics.",
            "Capture at least one structured observation with reliability notes.",
            "Record a passing verification result before approval.",
        ]
    if current_step == "approve":
        return [
            "Clear every approval blocker for the week.",
            "Approve the week only after the evidence is trustworthy.",
            "Advance only after approval is explicitly recorded.",
        ]
    return [
        "Pass the required concept questions.",
        "Use the current resources to tighten your answer.",
        "Unlock the build step with solid conceptual coverage.",
    ]


def render_current_step_actions_v3(status: dict, current_step: str) -> str:
    if current_step == "build":
        return (
            render_toolbar_action_form(
                "task_generate",
                "Create Build Brief",
                disabled=not status.get("can_generate_task"),
            )
            + render_toolbar_action_form("record_sync", "Scan Repository", secondary=True)
        )
    if current_step == "verify":
        return (
            render_toolbar_action_form("record_sync", "Scan Repository", secondary=True)
            + "<a class='button-link secondary' href='#implementation'>Review Evidence</a>"
        )
    if current_step == "approve":
        return (
            render_toolbar_action_form("approve", "Approve Week", disabled=not status.get("can_approve"))
            + render_toolbar_action_form(
                "advance",
                "Advance Week",
                secondary=True,
                disabled=not status["gates"]["week_approved"],
            )
        )
    return "<button type='button' class='button-link secondary' data-question-modal-open>See Full Question List</button>"


def render_toolbar_action_form(action: str, label: str, secondary: bool = False, disabled: bool = False) -> str:
    button_class = "toolbar-button-v3" + (" secondary" if secondary else "")
    disabled_attr = " disabled" if disabled else ""
    return (
        "<form method='post' action='/action'>"
        f"<input type='hidden' name='action' value='{escape(action)}'>"
        f"<button type='submit' class='{button_class}'{disabled_attr}>{escape(label)}</button>"
        "</form>"
    )


def render_learning_workspace_empty_v3(progress: dict) -> str:
    required_passed = int(progress.get("required_passed", 0))
    required_total = int(progress.get("required_total", 0))
    progress_percent = 0 if required_total == 0 else round((required_passed / required_total) * 100)
    return f"""
    <article class="subpanel question-column learn-empty-card-v3" id="question-workspace">
      <div class="step-title-row">
        <div>
          <h3>Generate Learning Brief</h3>
          <p class="fine-print">Load question-linked concept cards, reading material, and the first assessment set for this week.</p>
        </div>
      </div>
      <div class="progress-block" aria-label="Question progress">
        <div class="progress-meta">
          <strong>{required_passed}/{required_total} required questions passed</strong>
          <span>{progress_percent}% complete</span>
        </div>
        <div class="progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="{required_total}" aria-valuenow="{required_passed}" aria-valuetext="{progress_percent}% complete">
          <div class="progress-fill" style="width: {progress_percent}%;"></div>
        </div>
      </div>
      <p class="muted">Only the Learn workspace is active here. The Build implementation surface and the Verify evidence surface stay hidden until those steps become current.</p>
      <form method="post" action="/action" class="form-grid">
        <input type="hidden" name="action" value="learning_generate">
        <button type="submit">Generate Learning Brief</button>
      </form>
    </article>
    """


def render_implementation_section_v3(status: dict) -> str:
    task_label = "Refresh Build Brief" if status.get("task_generated") else "Create Build Brief"
    return f"""
    <section class="implementation-shell-v3" id="implementation">
      <div class="section-header-v3">
        <h2>Implementation</h2>
        <div class="toolbar-actions-v3">
          {render_toolbar_action_form('task_generate', task_label, disabled=not status.get('can_generate_task'))}
          {render_toolbar_action_form('record_sync', 'Scan Repository', secondary=True)}
        </div>
      </div>
      <div class="implementation-grid-v3">
        <article class="table-card-v3">
          <div class="table-card-body-v3">
            <table class="file-table-v3">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Status</th>
                  <th>Path</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {render_file_status_rows_v3(status)}
              </tbody>
            </table>
          </div>
          <div class="table-footer-v3">
            <div><strong>Last scan:</strong> {len(status['completed_files'])} files detected</div>
            <div><strong>Missing:</strong> {escape(', '.join(missing_required_files(status)) or '(none)')}</div>
          </div>
        </article>
        <aside class="activity-card-v3">
          <h3>Recent Activity</h3>
          <ul class="activity-list-v3">
            {render_recent_activity_v3(status)}
          </ul>
          <a class="button-link secondary" href="#current-assessment">View Timeline</a>
        </aside>
      </div>
    </section>
    """


def render_file_status_rows_v3(status: dict) -> str:
    rows = []
    completed = set(status["completed_files"])
    for path in status["required_files"]:
        file_name = path.split("/")[-1]
        directory = path.rsplit("/", 1)[0] + "/" if "/" in path else "./"
        is_complete = path in completed
        status_chip = (
            "<span class='table-chip-v3 complete'>Complete</span>"
            if is_complete
            else "<span class='table-chip-v3'>Not Started</span>"
        )
        action_label = "Done" if is_complete else "Start"
        rows.append(
            "<tr>"
            f"<td>{escape(file_name)}</td>"
            f"<td>{status_chip}</td>"
            f"<td><span class='table-chip-v3'>{escape(directory)}</span></td>"
            f"<td><a class='table-action-v3' href='#implementation'>{escape(action_label)}</a></td>"
            "</tr>"
        )
    return "".join(rows) or (
        "<tr><td colspan='4' class='muted'>No deliverables for this week.</td></tr>"
    )


def missing_required_files(status: dict) -> list[str]:
    completed = set(status["completed_files"])
    return [path for path in status["required_files"] if path not in completed]


def render_recent_activity_v3(status: dict) -> str:
    items: list[tuple[str, str]] = []
    progress = status.get("question_progress", {})
    if progress.get("required_passed", 0):
        items.append(("good", f"Answered Question {progress['required_passed']}"))
    elif status.get("learning_generated"):
        items.append(("warn", "Assessment practice started"))
    for path in status["completed_files"][:2]:
        items.append(("good", f"{path.split('/')[-1]} detected"))
    missing_metrics = [metric for metric in status["required_metrics"] if metric not in status["recorded_metrics"]]
    if missing_metrics:
        items.append(("warn", f"{missing_metrics[0]} missing"))
    verification = status.get("verification")
    if verification and verification.get("passed"):
        items.append(("good", "Verification passed"))
    elif status.get("gates", {}).get("week_approved"):
        items.append(("good", "Week approved"))
    else:
        items.append(("warn", "Verification pending"))
    if not items:
        items.append(("warn", "No activity yet"))
    return "".join(
        f"<li><span class='activity-dot-v3 {escape(tone)}'></span><span>{escape(text)}</span></li>"
        for tone, text in items[:5]
    )


def render_progression_shell(status: dict, current_step: str) -> str:
    rows = []
    for index, step in enumerate(workflow_steps(status), start=1):
        step_id = step["id"]
        row_class = "progress-row current" if step_id == current_step else "progress-row"
        rows.append(
            f"<article class='{row_class}' id='progress-{escape(step_id)}'>"
            "<div class='progress-node' aria-hidden='true'></div>"
            "<div class='progress-card'>"
            "<div class='progress-card-header'>"
            f"<div class='progress-card-title'>{escape(progression_title(status, step_id, index))}</div>"
            f"{render_status_badge(step['status'])}"
            "</div>"
            f"<p class='progress-card-copy'>{escape(progression_summary(status, step_id))}</p>"
            "</div>"
            "</article>"
        )
    return (
        "<section class='progress-shell'>"
        "<div class='progress-shell-line' aria-hidden='true'></div>"
        f"{''.join(rows)}"
        "</section>"
    )


def render_active_stage(
    status: dict,
    learning_session: Optional[dict],
    task_session: Optional[dict],
    current_step: str,
    selected_question_id: Optional[str],
) -> str:
    if current_step == "learn":
        return render_learning_stage(status, learning_session, selected_question_id)
    if current_step == "build":
        return render_build_stage(status, task_session)
    if current_step == "verify":
        return render_verify_stage(status)
    return render_approval_stage(status)


def render_learning_stage(
    status: dict,
    learning_session: Optional[dict],
    selected_question_id: Optional[str],
) -> str:
    progress = status.get("question_progress", {})
    questions = (learning_session or {}).get("questions", [])
    attempts = latest_attempts(learning_session)
    reading_material = (learning_session or {}).get("reading_material")
    selected_question = select_learning_question(questions, selected_question_id)

    cards_html = "".join(render_concept_card(card) for card in (learning_session or {}).get("concept_cards", []))
    if not cards_html:
        cards_html = "<p class='muted'>No concept cards generated yet.</p>"

    reading_html = render_reading_material(reading_material)

    workspace_html = render_learning_workspace(selected_question, questions, attempts, progress) if selected_question else """
      <article class="subpanel question-column" id="question-workspace">
        <h3>Answer Question</h3>
        <p class="muted">Learning content will load automatically for the current week. Once it is ready, this answer workspace will show the current question here.</p>
      </article>
    """
    question_modal_html = render_question_list_modal(questions, attempts, selected_question["id"] if selected_question else None)
    return f"""
    <section id="stage-learn" class="stage-card workflow-stage-card">
      <div class="stage-header">
        <div class="stack">
          <span class="brand-label">Step 1</span>
          <h2>Learn</h2>
          <p class="muted">{escape(workflow_reason(status, 'learn'))}</p>
        </div>
        {render_status_badge(step_status(status, 'learn'))}
      </div>
      <div class="stage-intro">
        <p><strong>Required coverage:</strong> {progress.get('required_passed', 0)}/{progress.get('required_total', 0)} required questions passed.</p>
        <p class="muted">Use the learning material like an open-book engineering studio: keep the concepts and reading on one side while you answer on the other.</p>
      </div>
      <section class="learn-workspace learning-stage-shell">
        <div class="reading-column">
          <div class="reading-column-scroll" data-reading-scroll>
            <article class="subpanel stage-surface">
              <h3>Concept Cards</h3>
              <div class="concept-card-grid">{cards_html}</div>
            </article>
            <article class="subpanel stage-surface">
              <h3>Reading Material</h3>
              <div class="reading-stack">{reading_html}</div>
            </article>
            {render_additional_resources_panel(status, "subpanel stage-surface")}
          </div>
        </div>
        <div class="questions-column">
          {workspace_html}
        </div>
      </section>
      {question_modal_html}
    </section>
    """


def render_build_stage(status: dict, task_session: Optional[dict]) -> str:
    if not task_session:
        task_body = "<p class='muted'>No task generated yet. Pass the learning check first, then generate the scoped implementation brief.</p>"
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
    <section id="stage-build" class="stage-card workflow-stage-card">
      <div class="stage-header">
        <div class="stack">
          <span class="brand-label">Step 2</span>
          <h2>Generate Task</h2>
          <p class="muted">{escape(workflow_reason(status, 'build'))}</p>
        </div>
        {render_status_badge(step_status(status, 'build'))}
      </div>
      <div class="stage-intro">
        <p><strong>Implementation boundaries:</strong> build only inside the current week's allowed directories and required files.</p>
        <p class="muted">Generate the task once concept coverage passes. After working in the target repo, sync artifacts to update completion progress.</p>
      </div>
      <div class="action-grid">
        {render_button_panel('Generate Task', 'Create the structured Junior SWE task once the learning check passes.', 'task_generate', 'Generate Task', disabled=not status.get('can_generate_task'))}
        {render_button_panel('Sync Artifacts', 'Scan the target repo for the required files.', 'record_sync', 'Sync Files', secondary=True)}
      </div>
      <article class="subpanel stage-surface">
        <h3>Junior SWE Task</h3>
        {task_body}
      </article>
    </section>
    """


def render_verify_stage(status: dict) -> str:
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
    <section id="stage-verify" class="stage-card workflow-stage-card">
      <div class="stage-header">
        <div class="stack">
          <span class="brand-label">Step 3</span>
          <h2>Verification</h2>
          <p class="muted">{escape(workflow_reason(status, 'verify'))}</p>
        </div>
        {render_status_badge(step_status(status, 'verify'))}
      </div>
      <div class="stage-intro">
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
    </section>
    """


def render_approval_stage(status: dict) -> str:
    blockers = status["approval_blockers"]
    blocker_html = "".join(f"<li>{escape(item)}</li>" for item in blockers) or "<li>No blockers. You can approve this week.</li>"
    return f"""
    <section id="stage-approve" class="stage-card workflow-stage-card">
      <div class="stage-header">
        <div class="stack">
          <span class="brand-label">Step 4</span>
          <h2>Approval</h2>
          <p class="muted">{escape(workflow_reason(status, 'approve'))}</p>
        </div>
        {render_status_badge(step_status(status, 'approve'))}
      </div>
      <div class="stage-intro">
        <p><strong>Approval is explicit.</strong> The week only advances after concept coverage, implementation, verification, and reliable evidence are all complete.</p>
      </div>
      <article class="subpanel stage-surface">
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
    </section>
    """


def render_left_sidebar(status: Optional[dict], initialized: bool) -> str:
    if not initialized or not status:
        return """
        <aside id="left-sidebar" class="workspace-sidebar-v3">
          <article class="panel sidebar-panel-minimal-v3">
            <h2>Current Week</h2>
            <p class="week-title-v3">Baseline Inference Server</p>
            <p class="muted">Run a model locally and expose it as an API.</p>
          </article>
          <article class="panel progress-panel-v3 sidebar-panel-minimal-v3">
            <h2>Progress</h2>
            <div class="progress-overview-v3">
              <div class="progress-ring-v3" style="--progress: 0;" data-progress-label="0%"></div>
              <div class="progress-steps-v3">
                <div class="progress-step-row-v3 current"><span class="progress-step-dot-v3"></span><span>Learn</span><span class="progress-step-meta-v3">0/0</span></div>
                <div class="progress-step-row-v3"><span class="progress-step-dot-v3"></span><span>Build</span><span class="progress-step-meta-v3">Locked</span></div>
                <div class="progress-step-row-v3"><span class="progress-step-dot-v3"></span><span>Verify</span><span class="progress-step-meta-v3">Locked</span></div>
                <div class="progress-step-row-v3"><span class="progress-step-dot-v3"></span><span>Approve</span><span class="progress-step-meta-v3">Locked</span></div>
              </div>
            </div>
          </article>
        </aside>
        """
    current_step = current_workflow_step(status)
    deliverables_action = (
        "<span class='button-link secondary is-disabled sidebar-button-v3'>Available In Build</span>"
        if current_step == "learn"
        else "<a class='button-link secondary sidebar-button-v3' href='#implementation'>View all</a>"
    )
    metrics_action = (
        "<span class='button-link secondary is-disabled sidebar-button-v3'>Available In Verify</span>"
        if current_step == "learn"
        else "<a class='button-link secondary sidebar-button-v3' href='#implementation'>Record</a>"
    )
    return f"""
    <aside id="left-sidebar" class="workspace-sidebar-v3">
      <article class="panel sidebar-panel-minimal-v3">
        <h2>Current Week</h2>
        <p class="week-title-v3">{escape(status['title'])}</p>
        <p class="muted">{escape(status['goal'])}</p>
      </article>
      <article class="panel progress-panel-v3 sidebar-panel-minimal-v3">
        <h2>Progress</h2>
        <div class="progress-overview-v3">
          <div class="progress-ring-v3" style="--progress: {workflow_progress_percent_v3(status)};" data-progress-label="{workflow_progress_percent_v3(status)}%"></div>
          <div class="progress-steps-v3">
            {render_progress_rows_v3(status)}
          </div>
        </div>
      </article>
      <article class="panel sidebar-card-v3">
        <h2>Deliverables</h2>
        <ul class="deliverable-list-v3">
          {render_deliverable_rows_v3(status)}
        </ul>
        {deliverables_action}
      </article>
      <article class="panel sidebar-card-v3">
        <h2>Benchmark Metrics</h2>
        <ul class="metric-list-v3">
          {render_metric_rows_v3(status)}
        </ul>
        {metrics_action}
      </article>
      <article class="panel sidebar-card-v3">
        <h2>Approval Readiness</h2>
        <div class="readiness-list-v3">
          {render_readiness_rows_v3(status)}
        </div>
      </article>
    </aside>
    """


def render_right_sidebar(status: Optional[dict], initialized: bool, selected_question_id: Optional[str] = None) -> str:
    if not initialized or not status:
        body = render_topic_chat_panel(
            initialized=False,
            week=None,
            week_title="Initialize Week 1 to begin",
            current_step="setup",
            selected_question=None,
            resources=[],
            starter_prompts=[],
        )
    else:
        current_step = current_workflow_step(status)
        learning_session = status.get("learning_session") or {}
        selected_question = select_learning_question(learning_session.get("questions", []), selected_question_id)
        body = render_topic_chat_panel(
            initialized=True,
            week=status["week"],
            week_title=status["title"],
            current_step=current_step,
            selected_question=selected_question,
            resources=assistant_resources_v3(status, learning_session, selected_question),
            starter_prompts=build_topic_chat_starter_prompts(learning_session, selected_question),
        )
    return f"""
    <aside id="right-sidebar" class="workspace-sidebar-v3 workspace-sidebar-right-v3">
      {body}
    </aside>
    """


def render_topic_chat_panel(
    initialized: bool,
    week: Optional[int],
    week_title: str,
    current_step: str,
    selected_question: Optional[dict],
    resources: list[str],
    starter_prompts: list[str],
) -> str:
    week_value = str(week) if week is not None else "uninitialized"
    disabled_attr = " disabled" if not initialized else ""
    step_label = workflow_label(current_step) if current_step in {"learn", "build", "verify", "approve"} else "Set Up"
    starter_prompts_html = render_topic_chat_starters(starter_prompts)
    disabled_copy = (
        "<p class='fine-print'>This assistant unlocks after initialization because the tutor needs a live week context.</p>"
        if not initialized
        else "<p class='fine-print'>Chats stay local to this browser for this week and use the app's current model configuration.</p>"
    )
    return f"""
    <article class="panel assistant-panel-v3 assistant-shell-v3" data-topic-chat-root data-initialized="{str(initialized).lower()}" data-week="{escape(week_value)}" data-current-step="{escape(current_step)}">
      <div class="assistant-header-v3">
        <h2>Assistant</h2>
        <button type="button" class="secondary assistant-plus-v3" data-topic-chat-new{disabled_attr}>+</button>
      </div>
      <div class="assistant-tabs-v3">
        <span class="assistant-tab-v3 active">Ask</span>
        <span class="assistant-tab-v3">Hints</span>
        <span class="assistant-tab-v3">Context</span>
      </div>
      <article class="assistant-card-v3">
        <h3>How can I help?</h3>
        <div class="assistant-quick-actions-v3">
          {starter_prompts_html}
        </div>
      </article>
      <section class="assistant-section-v3">
        <div class="assistant-resource-header-v3">
          <h3>Threads</h3>
        </div>
        <div class="topic-chat-session-list" data-topic-chat-session-list></div>
      </section>
      <section class="assistant-section-v3 assistant-chat-shell-v3">
        <div class="assistant-resource-header-v3">
          <h3>Chat</h3>
          <div class="assistant-header-actions-v3">
            <button
              type="button"
              class="secondary topic-chat-delete-icon-v3"
              data-topic-chat-delete
              aria-label="Delete chat"
              title="Delete chat"
              hidden{disabled_attr}
            >
              <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                <path d="M3.5 4.5h9"></path>
                <path d="M6.5 2.75h3"></path>
                <path d="M5.25 4.5v7.25"></path>
                <path d="M8 4.5v7.25"></path>
                <path d="M10.75 4.5v7.25"></path>
                <path d="M4.25 4.5l.45 8.25h6.6l.45-8.25"></path>
              </svg>
            </button>
          </div>
        </div>
        <div class="assistant-chat-thread-v3">
          <div class="topic-chat-thread" data-topic-chat-thread>
          <div class="topic-chat-empty" data-topic-chat-empty>
            <p><strong>No chat yet.</strong></p>
            <p class="muted">Ask for clarification, implementation tradeoffs, or how the current week ties back to the required files and metrics.</p>
          </div>
        </div>
        </div>
      </section>
      <form class="assistant-section-v3 assistant-composer-v3" data-topic-chat-form>
        <div class="topic-chat-context-strip" data-topic-chat-selection-strip hidden>
          <div class="topic-chat-context-chip">
            <div class="topic-chat-context-copy">
              <span class="topic-chat-context-kicker">Selection Context</span>
              <p class="topic-chat-context-preview" data-topic-chat-selection-preview></p>
            </div>
            <button
              type="button"
              class="secondary topic-chat-context-clear"
              data-topic-chat-selection-clear
              aria-label="Remove selected text context"
              title="Remove selected text context"
            >
              ×
            </button>
          </div>
        </div>
        <label>Message
          <textarea name="topic_chat_message" placeholder="Ask about the current week, files, metrics, or the active question." data-topic-chat-textarea{disabled_attr}></textarea>
        </label>
        <div class="topic-chat-toolbar">
          <button type="submit" data-topic-chat-submit{disabled_attr}>Send</button>
        </div>
      </form>
      {disabled_copy}
      <p class="fine-print topic-chat-status" data-topic-chat-status></p>
    </article>
    """


def build_topic_chat_starter_prompts(learning_session: dict, selected_question: Optional[dict]) -> list[str]:
    prompts: list[str] = []
    questions = learning_session.get("questions", [])
    concept_cards = learning_session.get("concept_cards", [])
    reading_material = learning_session.get("reading_material") or {}
    markdown_sections = markdown_heading_sections(reading_material.get("body_markdown", ""))

    focus_question = selected_question or (questions[0] if questions else None)
    if focus_question and focus_question.get("prompt_text"):
        starter_topic = beginner_topic_from_question(focus_question["prompt_text"])
        prompts.append(f"I'm new to this. Can you explain {starter_topic} in simple terms?")

    first_content_section = next((section for section in markdown_sections if section.get("title") != "How This Week Works"), None)
    if first_content_section:
        prompts.append(
            f'Can you walk me through "{first_content_section["title"]}" like I\'m just getting started?'
        )

    first_card = next((card for card in concept_cards if card.get("title") or card.get("concept")), None)
    if first_card:
        card_title = first_card.get("title") or humanize_section_label(first_card.get("concept", "concept"))
        prompts.append(f'What does "{card_title}" mean, and why does it matter this week?')

    measurement_section = find_markdown_section_for_theme(
        markdown_sections,
        ("latency", "throughput", "benchmark", "metric", "measure", "verify", "tokens per second", "tps"),
    )
    if measurement_section:
        prompts.append(
            f'What should I pay attention to when reading "{measurement_section.get("title", "measurement")}"?'
        )

    if len(prompts) < 4:
        build_section = find_markdown_section_for_theme(
            markdown_sections,
            ("file", "build", "implement", "artifact", "deliverable", "code"),
        )
        if build_section:
            prompts.append(
                f'How does "{build_section.get("title", "the build work")}" connect to the files I will touch?'
            )

    deduped_prompts: list[str] = []
    for prompt in prompts:
        if prompt not in deduped_prompts:
            deduped_prompts.append(prompt)
        if len(deduped_prompts) == 4:
            break
    return deduped_prompts


def find_markdown_section_for_theme(markdown_sections: list[dict], keywords: tuple[str, ...]) -> Optional[dict]:
    best_section = None
    best_score = 0
    for section in markdown_sections:
        if section.get("title") == "How This Week Works":
            continue
        text = f"{section.get('title', '')} {section.get('body_markdown', '')}".lower()
        score = sum(1 for keyword in keywords if keyword in text)
        if score > best_score:
            best_score = score
            best_section = section
    return best_section if best_score > 0 else None


def markdown_heading_sections(body_markdown: str) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    current_title: Optional[str] = None
    current_lines: list[str] = []

    for raw_line in body_markdown.splitlines():
        line = raw_line.strip()
        heading_match = re.match(r"^##\s+(.+?)\s*$", line)
        if heading_match:
            if current_title is not None:
                sections.append(
                    {
                        "title": current_title,
                        "body_markdown": "\n".join(current_lines).strip(),
                    }
                )
            current_title = heading_match.group(1).strip()
            current_lines = []
            continue
        if current_title is not None:
            current_lines.append(raw_line)

    if current_title is not None:
        sections.append(
            {
                "title": current_title,
                "body_markdown": "\n".join(current_lines).strip(),
            }
        )
    return sections


def beginner_topic_from_question(prompt_text: str) -> str:
    text = prompt_text.strip().rstrip(".?!")
    lower = text.lower()
    imperative_prefixes = (
        ("explain ", ""),
        ("define ", ""),
        ("describe ", ""),
        ("compare ", ""),
    )
    for prefix, replacement in imperative_prefixes:
        if lower.startswith(prefix):
            return text[len(prefix) :].strip() or "this topic"
    if lower.startswith("what is the difference between "):
        return "the difference between " + text[len("What is the difference between ") :].strip()
    if lower.startswith("what is "):
        return text[len("What is ") :].strip() or "this topic"
    if lower.startswith("how would you "):
        return text[len("How would you ") :].strip() or "this"
    if lower.startswith("how do you "):
        return text[len("How do you ") :].strip() or "this"
    return text or "this topic"


def render_topic_chat_starters(prompts: list[str]) -> str:
    if not prompts:
        return "<p class='muted'>Starter questions will appear once learning content is loaded.</p>"
    return "".join(
        f"<button type='button' class='assistant-prompt-v3 topic-chat-suggestion' data-topic-chat-suggestion data-topic-chat-prompt='{escape(prompt)}'>{escape(prompt)}</button>"
        for prompt in prompts
    )


def workflow_progress_percent_v3(status: dict) -> int:
    passed_steps = sum(1 for step in workflow_steps(status) if step["status"] == "passed")
    return min(100, max(25, passed_steps * 25 + 25))


def render_progress_rows_v3(status: dict) -> str:
    progress = status.get("question_progress", {})
    rows = []
    for step in workflow_steps(status):
        step_id = step["id"]
        current_class = " current" if step_id == current_workflow_step(status) else ""
        if step_id == "learn":
            meta = f"{progress.get('required_passed', 0)}/{progress.get('required_total', 0)}"
        elif step_id == "build":
            meta = f"{len(status['completed_files'])}/{len(status['required_files'])}"
        elif step_id == "verify":
            meta = f"{len(status['recorded_metrics'])}/{len(status['required_metrics'])}"
        else:
            meta = "Ready" if status.get("can_approve") else "Locked"
        rows.append(
            f"<div class='progress-step-row-v3{current_class}'>"
            "<span class='progress-step-dot-v3'></span>"
            f"<span>{escape(step['label'])}</span>"
            f"<span class='progress-step-meta-v3'>{escape(meta)}</span>"
            "</div>"
        )
    return "".join(rows)


def render_deliverable_rows_v3(status: dict) -> str:
    completed = set(status["completed_files"])
    rows = []
    for path in status["required_files"]:
        tone = "good" if path in completed else "warn"
        label = "Ready" if path in completed else "Not started"
        rows.append(
            f"<li class='deliverable-item-v3'><span>{escape(path.split('/')[-1])}</span><span class='sidebar-status-v3 {tone}'>{escape(label)}</span></li>"
        )
    return "".join(rows) or "<li class='deliverable-item-v3'><span>No deliverables</span><span class='sidebar-status-v3'>Empty</span></li>"


def render_metric_rows_v3(status: dict) -> str:
    rows = []
    for metric in status["required_metrics"]:
        recorded = metric in status["recorded_metrics"]
        tone = "good" if recorded else "warn"
        label = "Recorded" if recorded else "Missing"
        rows.append(
            f"<li class='metric-item-v3'><span>{escape(metric)}</span><span class='sidebar-status-v3 {tone}'>{escape(label)}</span></li>"
        )
    return "".join(rows) or "<li class='metric-item-v3'><span>No metrics</span><span class='sidebar-status-v3'>Empty</span></li>"


def render_resource_rows_v3(status: dict) -> str:
    rows = []
    for resource in status.get("key_resources", []):
        rows.append(f"<li class='resource-item-v3'><span>{format_resource_text_html(resource)}</span></li>")
    return "".join(rows) or "<li class='resource-item-v3'><span>No additional resources for this week.</span></li>"


def render_additional_resources_panel(status: dict, classes: str) -> str:
    return (
        f"<article class='{escape(classes)}'>"
        "<h3>Additional Resources</h3>"
        f"<ul class='resource-list-v3'>{render_resource_rows_v3(status)}</ul>"
        "</article>"
    )


def format_resource_text_html(text: str) -> str:
    normalized = text.strip()
    if normalized.startswith("- "):
        normalized = normalized[2:].strip()
    formatted = escape(normalized)
    formatted = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", formatted)
    formatted = re.sub(r"`([^`]+)`", r"<code>\1</code>", formatted)
    return formatted


def render_readiness_rows_v3(status: dict) -> str:
    concepts_ready = step_status(status, "learn") == "passed"
    files_ready = step_status(status, "build") == "passed"
    metrics_ready = all(metric in status["recorded_metrics"] for metric in status["required_metrics"]) if status["required_metrics"] else True
    rows = [
        ("Concept Questions", concepts_ready),
        ("Required Files", files_ready),
        ("Required Metrics", metrics_ready),
        ("Verification", status["gates"]["verification_passed"]),
    ]
    rendered = []
    for label, ready in rows:
        tone = "good" if ready else "warn"
        text = "Ready" if ready else "Pending"
        rendered.append(
            f"<div class='readiness-row-v3'><span>{escape(label)}</span><span class='sidebar-status-v3 {tone}'>{escape(text)}</span></div>"
        )
    return "".join(rendered)


def assistant_resources_v3(status: dict, learning_session: dict, selected_question: Optional[dict]) -> list[str]:
    resources: list[str] = []
    reading_material = learning_session.get("reading_material") or {}
    if reading_material.get("title"):
        resources.append(reading_material.get("title", "Week notes"))
    for section in markdown_heading_sections(reading_material.get("body_markdown", ""))[:1]:
        resources.append(section.get("title", "Week notes"))
    for path in status["required_files"]:
        if len(resources) >= 3:
            break
        resources.append(path)
    if selected_question:
        resources.insert(0, selected_question["id"])
    return resources[:3]


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
    required_metrics = "".join(f"<li>{escape(item)}</li>" for item in status["required_metrics"]) or "<li>(none)</li>"
    required = "".join(f"<li>{escape(item)}</li>" for item in status["required_files"]) or "<li>(none)</li>"
    completed = "".join(f"<li>{escape(item)}</li>" for item in status["completed_files"]) or "<li class='muted'>(none)</li>"
    return f"""
    <article class="panel">
      <h2>Week Scope</h2>
      <p class="muted">Active dirs: {escape(', '.join(status['active_dirs']) or '(none)')}</p>
      <div class="stack rail-utility-stack">
        <div class="subpanel rail-utility-card">
          <h3>Required Files</h3>
          <ul class="artifact-list tight">{required}</ul>
        </div>
        <div class="subpanel rail-utility-card">
          <h3>Completed Files</h3>
          <ul class="artifact-list tight">{completed}</ul>
        </div>
        <div class="subpanel rail-utility-card">
          <h3>Required Metrics</h3>
          <ul class="metric-list tight">{required_metrics}</ul>
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
    current_step: str,
    selected_question_id: Optional[str],
) -> str:
    progress = status.get("question_progress", {})
    questions = (learning_session or {}).get("questions", [])
    attempts = latest_attempts(learning_session)
    reading_material = (learning_session or {}).get("reading_material")
    selected_question = select_learning_question(questions, selected_question_id)

    cards_html = "".join(render_concept_card(card) for card in (learning_session or {}).get("concept_cards", []))
    if not cards_html:
        cards_html = "<p class='muted'>No concept cards generated yet.</p>"

    reading_html = render_reading_material(reading_material)

    workspace_html = render_learning_workspace(selected_question, questions, attempts, progress) if selected_question else """
      <article class="subpanel question-column">
        <h3>Answer Question</h3>
        <p class="muted">Learning content will load automatically for the current week. Once it is ready, this answer workspace will show the current question here.</p>
      </article>
    """
    question_modal_html = render_question_list_modal(questions, attempts, selected_question["id"] if selected_question else None)
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
          <p><strong>Required coverage:</strong> {progress.get('required_passed', 0)}/{progress.get('required_total', 0)} baseline questions passed.</p>
          <p class="muted">Keep the reading material and concept cards open on the left while you answer questions on the right.</p>
        </div>
        <section class="learn-workspace">
          <div class="reading-column">
            <div class="reading-column-scroll" data-reading-scroll>
              <article class="subpanel learn-reading-section-v3">
                <h3>Concept Cards</h3>
                <div class="concept-card-grid">{cards_html}</div>
              </article>
              <article class="subpanel learn-reading-section-v3">
                <h3>Reading Material</h3>
                <div class="reading-stack">{reading_html}</div>
              </article>
              {render_additional_resources_panel(status, "subpanel learn-reading-section-v3")}
            </div>
          </div>
          <div class="questions-column">
            {workspace_html}
          </div>
        </section>
        {question_modal_html}
      </div>
    </details>
    """


def render_concept_card(card: dict) -> str:
    detail_items = [
        f"<div class='fine-print'><strong>Why it matters:</strong> {escape(card['why_it_matters'])}</div>",
        f"<div class='fine-print'><strong>Common mistake:</strong> {escape(card['common_mistake'])}</div>",
    ]
    if card.get("quick_check_question"):
        detail_items.append(f"<div class='fine-print'><strong>Quick check:</strong> {escape(card['quick_check_question'])}</div>")
    details_html = (
        "<details class='concept-card-details'>"
        "<summary>Details</summary>"
        f"<div class='concept-card-details-body'>{''.join(detail_items)}</div>"
        "</details>"
    )
    return (
        "<article class='concept-card' id='card-"
        f"{escape(card.get('id') or card.get('concept', 'concept'))}'>"
        "<div class='concept-card-body'>"
        f"<div class='concept-card-title'>{escape(card.get('title') or card.get('concept', 'Concept'))}</div>"
        f"<div>{escape(card['explanation'])}</div>"
        f"{details_html}"
        "</div>"
        "</article>"
    )


def render_reading_material(reading_material: Optional[dict]) -> str:
    if not reading_material:
        return "<p class='muted'>No reading material generated yet.</p>"
    title = reading_material.get("title", "Reading")
    body_markdown = reading_material.get("body_markdown", "")
    markdown_sections = markdown_heading_sections(body_markdown)
    content_sections = [section for section in markdown_sections if section.get("title") != "How This Week Works"]

    if not markdown_sections:
        return (
            f"<article class='reading-section' id='reading-material'>"
            f"<h4>{escape(title)}</h4>"
            f"{render_markdown_block(body_markdown)}"
            "</article>"
        )

    sections_html = "".join(
        "<section class='reading-section'>"
        f"<h5 class='reading-section-title'>{escape(section.get('title', 'Reading'))}</h5>"
        f"{render_markdown_block(section.get('body_markdown', ''))}"
        "</section>"
        for section in content_sections
    )

    return (
        f"<article class='reading-document' id='reading-material'>"
        f"<h4>{escape(title)}</h4>"
        f"{sections_html}"
        "</article>"
    )


def render_week_orientation_banner(reading_material: Optional[dict]) -> str:
    if not reading_material:
        return ""
    body_markdown = reading_material.get("body_markdown", "")
    orientation_section = next(
        (
            section
            for section in markdown_heading_sections(body_markdown)
            if section.get("title") == "How This Week Works"
        ),
        None,
    )
    if not orientation_section or not orientation_section.get("body_markdown"):
        return ""
    return (
        "<section class='learn-orientation-panel'>"
        "<div class='learn-orientation-kicker'>How This Week Works</div>"
        f"{render_markdown_block(orientation_section.get('body_markdown', ''))}"
        "</section>"
    )


def render_learning_workspace(
    selected_question: dict,
    questions: list[dict],
    attempts: dict[str, dict],
    progress: dict,
    question_message: Optional[str] = None,
    question_error: Optional[str] = None,
) -> str:
    question_index = next((index for index, question in enumerate(questions) if question["id"] == selected_question["id"]), 0)
    previous_question = questions[question_index - 1] if question_index > 0 else None
    next_question = questions[question_index + 1] if question_index < len(questions) - 1 else None
    required_passed = int(progress.get("required_passed", 0))
    required_total = int(progress.get("required_total", 0))
    progress_percent = 0 if required_total == 0 else round((required_passed / required_total) * 100)
    rubric = render_items(selected_question.get("scoring_rubric", []))
    status = question_attempt_status(attempts, selected_question["id"])
    latest_attempt = attempts.get(selected_question["id"], {})
    previous_answer = latest_attempt.get("answer", "")
    feedback_html = render_question_feedback_notice(question_message, question_error)
    validator_feedback_html = render_question_validator_feedback(latest_attempt.get("result"), status)
    jump_control_html = render_question_jump_control(question_index + 1, len(questions))
    return f"""
    <article class="subpanel question-column" id="question-workspace">
      <div class="step-title-row">
        <div>
          <h3>Answer Question</h3>
          <p class="fine-print">Question {question_index + 1} of {len(questions)}</p>
          <p class="question-prompt-v3">{format_question_prompt_html(selected_question)}</p>
          <p class="fine-print"><span class="required-question-marker">*</span> Required to unlock Build</p>
        </div>
        {render_question_status_badge(selected_question['id'], status)}
      </div>
      <div class="question-stepper">
        {render_question_step_link(previous_question, "Previous Question", "previous")}
        {render_question_step_link(next_question, "Next Question", "next")}
        <button type="button" class="button-link secondary" data-question-modal-open>See Full Question List</button>
        {jump_control_html}
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
      <details class="rubric-inline">
        <summary>What A Good Answer Should Cover</summary>
        <ul class="summary-list tight" style="margin-top: 14px;">{rubric}</ul>
      </details>
      {feedback_html}
      {validator_feedback_html}
      <form method="post" action="/action" class="form-grid" data-learning-answer-form>
        <input type="hidden" name="action" value="learning_answer">
        <input type="hidden" name="question_id" value="{escape(selected_question['id'])}">
        <label>Answer
          <textarea name="learning_answer" placeholder="Answer this question while using the material on the left as reference." data-learning-answer-textarea>{escape(previous_answer)}</textarea>
        </label>
        <p class="fine-print" data-draft-status></p>
        <button type="submit">Submit Answer</button>
      </form>
    </article>
    """


def render_question_feedback_notice(message: Optional[str], error: Optional[str]) -> str:
    if message:
        return f"<div class='notice success'>{escape(message)}</div>"
    if error:
        return f"<div class='notice error'>{escape(error)}</div>"
    return ""


def render_question_jump_control(current_number: int, total_questions: int) -> str:
    return (
        "<form class='question-jump-form' data-question-jump-form>"
        "<label for='question-jump-input'>Jump to question</label>"
        f"<input id='question-jump-input' type='number' min='1' max='{total_questions}' value='{current_number}' "
        "inputmode='numeric' data-question-jump-input aria-label='Jump to question number'>"
        "<button type='submit' class='button-link secondary'>Go</button>"
        "</form>"
    )


def render_question_validator_feedback(result: Any, status: str) -> str:
    if status != "failed" or not result:
        return ""

    if isinstance(result, dict):
        rationale = str(result.get("score_rationale") or "").strip()
        missing_concepts = [str(item).strip() for item in result.get("missing_concepts", []) if str(item).strip()]
    else:
        rationale = str(getattr(result, "score_rationale", "") or "").strip()
        missing_concepts = [str(item).strip() for item in getattr(result, "missing_concepts", []) if str(item).strip()]

    parts = ["<div class='question-validator-feedback failed'>", "<h4>What was missing</h4>"]
    if rationale:
        parts.append(f"<p>{escape(rationale)}</p>")
    if missing_concepts:
        parts.append("<p><strong>Missing concepts:</strong></p>")
        parts.append("<ul>")
        parts.extend(f"<li>{escape(item)}</li>" for item in missing_concepts)
        parts.append("</ul>")
    parts.append("</div>")
    return "".join(parts)


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
            f"<a class='question-modal-link{current_class}' href='/?question_id={quote_plus(question['id'])}' data-question-step-link data-question-modal-link data-question-order='{index}'>"
            "<div class='question-modal-meta'>"
            f"<span class='question-modal-index'>Question {index}</span>"
            f"{render_question_status_badge(question['id'], question_attempt_status(attempts, question['id']))}"
            "</div>"
            f"<div class='question-modal-prompt'>{format_question_prompt_html(question)}</div>"
            "</a>"
            "</li>"
        )

    return f"""
    <dialog id="question-list-modal" class="question-modal" aria-label="Full question list">
      <div class="question-modal-body">
        <div class="question-modal-header">
          <div class="stack">
            <h3>Full Question List</h3>
            <p class="muted">Browse every question and see which ones are passed, failed, or not started. `*` marks a required question.</p>
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


def is_required_learning_question(question: dict) -> bool:
    return question.get("depth") == "baseline"


def format_question_prompt(question: dict) -> str:
    prompt = str(question.get("prompt_text") or "").strip()
    return f"{prompt} *" if is_required_learning_question(question) and prompt else prompt


def format_question_prompt_html(question: dict) -> str:
    prompt = escape(str(question.get("prompt_text") or "").strip())
    if is_required_learning_question(question) and prompt:
        return f"{prompt} <span class=\"required-question-marker\">*</span>"
    return prompt


def render_task_panel(status: dict, task_session: Optional[dict], current_step: str) -> str:
    if not task_session:
        task_body = "<p class='muted'>No task generated yet. Pass the learning check first, then generate the scoped implementation brief.</p>"
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
          <p><strong>Implementation boundaries:</strong> build only inside the current week's allowed directories and required files.</p>
          <p class="muted">Generate the task once concept coverage passes. After working in the target repo, sync artifacts to update completion progress.</p>
        </div>
        <div class="action-grid">
          {render_button_panel('Generate Task', 'Create the structured Junior SWE task once the learning check passes.', 'task_generate', 'Generate Task', disabled=not status.get('can_generate_task'))}
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


def render_learning_answer_panel(learning_session: Optional[dict]) -> str:
    options = []
    for question in (learning_session or {}).get("questions", []):
        options.append(
            f"<option value=\"{escape(question['id'])}\">{escape(question['id'])} - {escape(format_question_prompt(question))}</option>"
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
            "<button type='submit' class='workspace-primary-action'>Initialize Week 1</button>"
            "</form>"
        )
    step = current_workflow_step(status)
    if step == "build" and not status.get("task_generated"):
        return (
            "<form method='post' action='/action' class='form-grid'>"
            "<input type='hidden' name='action' value='task_generate'>"
            "<button type='submit' class='workspace-primary-action'>Create Build Brief</button>"
            "</form>"
        )
    if step == "approve" and status.get("can_approve"):
        return (
            "<form method='post' action='/action' class='form-grid'>"
            "<input type='hidden' name='action' value='approve'>"
            "<button type='submit' class='workspace-primary-action'>Approve Week</button>"
            "</form>"
        )
    return (
        f"<a class='button-link workspace-primary-action' href='#current-assessment'>"
        f"Continue Step <span aria-hidden='true'>→</span>"
        "</a>"
    )


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


def progression_title(status: dict, step_id: str, index: int) -> str:
    labels = {
        "learn": "Learn",
        "build": "Generate Task",
        "verify": "Verification",
        "approve": "Approval",
    }
    return f"Step {index}: {labels.get(step_id, workflow_label(step_id))}"


def progression_summary(status: dict, step_id: str) -> str:
    if step_id == "learn":
        progress = status.get("question_progress", {})
        return f"{progress.get('required_passed', 0)}/{progress.get('required_total', 0)} required questions passed."
    if step_id == "approve" and status.get("approval_blockers"):
        return "Based on task and evidence completion progress."
    return workflow_reason(status, step_id)


def workflow_reason(status: dict, step_id: str) -> str:
    if step_id == "learn":
        return checkpoint_reason(status, "learning_questions", "Pass the required questions to unlock Build.")
    if step_id == "build":
        completed = len(status["completed_files"])
        required = len(status["required_files"])
        if status["gates"]["implementation_complete"]:
            return f"{completed}/{required} required files are present."
        if status.get("task_generated"):
            return f"{completed}/{required} required files are present. Create the remaining files for this week."
        return "Generate the task and create the required files for this week."
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
            return "Approve this week to unlock the next one."
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
        return checkpoint_status(status, "learning_questions")
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
    unordered_list_items: list[str] = []
    ordered_list_items: list[str] = []
    paragraph_lines: list[str] = []
    code_lines: list[str] = []
    in_code_block = False

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        chunks.append(f"<p>{render_inline_markup(' '.join(paragraph_lines))}</p>")
        paragraph_lines.clear()

    def flush_unordered_list() -> None:
        if not unordered_list_items:
            return
        items = "".join(f"<li>{render_inline_markup(item)}</li>" for item in unordered_list_items)
        chunks.append(f"<ul>{items}</ul>")
        unordered_list_items.clear()

    def flush_ordered_list() -> None:
        if not ordered_list_items:
            return
        items = "".join(f"<li>{render_inline_markup(item)}</li>" for item in ordered_list_items)
        chunks.append(f"<ol>{items}</ol>")
        ordered_list_items.clear()

    def flush_code_block() -> None:
        nonlocal in_code_block
        if not code_lines:
            in_code_block = False
            return
        chunks.append(f"<pre><code>{escape(chr(10).join(code_lines))}</code></pre>")
        code_lines.clear()
        in_code_block = False

    for raw_line in lines:
        line = raw_line.strip()
        if in_code_block:
            if line.startswith("```"):
                flush_code_block()
            else:
                code_lines.append(raw_line.rstrip())
            continue
        if line.startswith("```") and line.endswith("```") and len(line) > 6:
            flush_paragraph()
            flush_unordered_list()
            flush_ordered_list()
            chunks.append(f"<pre><code>{escape(line[3:-3].strip())}</code></pre>")
            continue
        if line.startswith("```"):
            flush_paragraph()
            flush_unordered_list()
            flush_ordered_list()
            in_code_block = True
            code_lines.clear()
            continue
        if not line:
            flush_paragraph()
            flush_unordered_list()
            flush_ordered_list()
            continue
        if line.startswith("### "):
            flush_paragraph()
            flush_unordered_list()
            flush_ordered_list()
            chunks.append(f"<h5>{render_inline_markup(line[4:])}</h5>")
            continue
        if line.startswith("## "):
            flush_paragraph()
            flush_unordered_list()
            flush_ordered_list()
            chunks.append(f"<h4>{render_inline_markup(line[3:])}</h4>")
            continue
        if line.startswith("# "):
            flush_paragraph()
            flush_unordered_list()
            flush_ordered_list()
            chunks.append(f"<h3>{render_inline_markup(line[2:])}</h3>")
            continue
        if line.startswith("- "):
            flush_paragraph()
            flush_ordered_list()
            unordered_list_items.append(line[2:])
            continue
        ordered_match = re.match(r"^\d+\.\s+(.*)$", line)
        if ordered_match:
            flush_paragraph()
            flush_unordered_list()
            ordered_list_items.append(ordered_match.group(1))
            continue
        flush_unordered_list()
        flush_ordered_list()
        paragraph_lines.append(line)

    flush_paragraph()
    flush_unordered_list()
    flush_ordered_list()
    flush_code_block()
    return f"<div class='rendered-markdown'>{''.join(chunks)}</div>"


def render_inline_markup(text: str) -> str:
    escaped = escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
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


def result_passed(result: Any) -> bool:
    if isinstance(result, dict):
        return bool(result.get("passed"))
    return bool(getattr(result, "passed", False))


def parse_optional_float(value: str) -> float | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError as exc:
        raise CoachError("Expected a numeric value.") from exc


def parse_optional_int(value: str) -> int | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError as exc:
        raise CoachError("Expected an integer value.") from exc


def parse_optional_bool(value: str) -> bool | None:
    stripped = value.strip().lower()
    if not stripped:
        return None
    if stripped == "true":
        return True
    if stripped == "false":
        return False
    raise CoachError("Expected a boolean value.")


def escape(value: str) -> str:
    return html.escape(value, quote=True)


def pluralize(count: int, singular: str, plural: Optional[str] = None) -> str:
    if count == 1:
        return singular
    return plural or f"{singular}s"

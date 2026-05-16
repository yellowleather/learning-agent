from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from coach.errors import CoachError

DEFAULT_CURRICULUM_PROMPT_PATH = "curriculum/prompts/ai_inference_engineering_8_week_plan.md"
DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-1-20250805"
DEFAULT_PLAN_PATH = "docs/8_week_plan.md"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
ANTHROPIC_REQUEST_TIMEOUT_SECONDS = 600
DEFAULT_CURRICULUM_MAX_TOKENS = 16000
DEFAULT_CURRICULUM_TEMPERATURE = 0.8


class BootstrappedWorkspace:
    def __init__(self, workspace_root: str, plan_path: str, prompt_path: str, model: str, directories: list[str]):
        self.workspace_root = workspace_root
        self.plan_path = plan_path
        self.prompt_path = prompt_path
        self.model = model
        self.directories = directories


class AnthropicMessageClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = (api_key or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
        if not self.api_key:
            raise CoachError(
                "ANTHROPIC_API_KEY is not set. Export it or add it to the repo-local .env before running curriculum bootstrap."
            )

    def generate_text(
        self,
        *,
        prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        request = urllib.request.Request(
            ANTHROPIC_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": ANTHROPIC_API_VERSION,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=ANTHROPIC_REQUEST_TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise CoachError(f"Anthropic API request failed with HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise CoachError(f"Anthropic API request failed: {exc.reason}") from exc

        data = json.loads(body)
        content_blocks = data.get("content", [])
        text_parts: list[str] = []
        for block in content_blocks:
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                text_parts.append(block["text"])
        text = "".join(text_parts).strip()
        if not text:
            raise CoachError("Anthropic API returned an empty response.")
        return text


def bootstrap_curriculum_workspace(
    *,
    repo_root: Path,
    prompt_path: Path,
    output_repo_path: Path,
    model: str = DEFAULT_ANTHROPIC_MODEL,
    client: AnthropicMessageClient | None = None,
) -> BootstrappedWorkspace:
    resolved_prompt_path = prompt_path.resolve()
    if not resolved_prompt_path.exists():
        raise CoachError(f"Prompt asset not found: {resolved_prompt_path}")

    workspace_root = output_repo_path.resolve() if output_repo_path.is_absolute() else (repo_root / output_repo_path).resolve()
    _validate_output_repo_path(workspace_root)

    prompt_text = resolved_prompt_path.read_text().strip()
    anthropic = client or AnthropicMessageClient()

    plan_markdown = anthropic.generate_text(
        prompt=prompt_text,
        model=model,
        max_tokens=DEFAULT_CURRICULUM_MAX_TOKENS,
        temperature=DEFAULT_CURRICULUM_TEMPERATURE,
    )
    directories: list[str] = []
    _write_workspace(
        workspace_root=workspace_root,
        prompt_path=resolved_prompt_path,
        repo_root=repo_root,
        plan_markdown=plan_markdown,
        directories=directories,
        model=model,
    )
    return BootstrappedWorkspace(
        workspace_root=str(workspace_root),
        plan_path=str(workspace_root / DEFAULT_PLAN_PATH),
        prompt_path=str(resolved_prompt_path),
        model=model,
        directories=directories,
    )


def _validate_output_repo_path(workspace_root: Path) -> None:
    if not workspace_root.exists():
        return
    existing_entries = [entry.name for entry in workspace_root.iterdir()]
    non_git_entries = [name for name in existing_entries if name != ".git"]
    if non_git_entries:
        raise CoachError(f"Output repo path already exists and is not empty: {workspace_root}")


def _write_workspace(
    *,
    workspace_root: Path,
    prompt_path: Path,
    repo_root: Path,
    plan_markdown: str,
    directories: list[str],
    model: str,
) -> None:
    workspace_root.mkdir(parents=True, exist_ok=True)

    plan_path = workspace_root / DEFAULT_PLAN_PATH
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(plan_markdown.rstrip() + "\n")

    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "prompt_path": str(prompt_path.relative_to(repo_root)),
        "plan_path": DEFAULT_PLAN_PATH,
        "directories": directories,
    }
    (workspace_root / "workspace_manifest.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    (workspace_root / ".gitignore").write_text(".venv/\n__pycache__/\n.pytest_cache/\n.env\n")
    (workspace_root / "README.md").write_text(
        (
            f"# {workspace_root.name}\n\n"
            "This workspace was bootstrapped from a curriculum-generation prompt.\n\n"
            f"- Plan: `{DEFAULT_PLAN_PATH}`\n"
            f"- Prompt asset: `{prompt_path.relative_to(repo_root)}`\n"
            f"- Model: `{model}`\n"
        )
    )

    if not (workspace_root / ".git").exists():
        _initialize_git_repo(workspace_root)


def _initialize_git_repo(workspace_root: Path) -> None:
    try:
        subprocess.run(
            ["git", "init"],
            cwd=workspace_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise CoachError(f"Failed to initialize nested git repository at {workspace_root}: {exc.stderr}") from exc

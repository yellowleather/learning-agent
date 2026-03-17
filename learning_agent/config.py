from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from learning_agent.errors import LearningAgentError
from learning_agent.models import AppConfig


CONFIG_FILENAME = "learning_agent.config.json"
DOTENV_FILENAME = ".env"


def locate_repo_root(start: Optional[Path] = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for path in [current, *current.parents]:
        if (path / CONFIG_FILENAME).exists():
            return path
    raise LearningAgentError(
        f"Could not find {CONFIG_FILENAME}. Run commands from the repo or create the config file first."
    )


def load_config(start: Optional[Path] = None) -> tuple[Path, AppConfig]:
    repo_root = locate_repo_root(start)
    load_dotenv(repo_root / DOTENV_FILENAME)
    config_path = repo_root / CONFIG_FILENAME
    try:
        data = json.loads(config_path.read_text())
    except FileNotFoundError as exc:
        raise LearningAgentError(f"Missing config file at {config_path}.") from exc
    except json.JSONDecodeError as exc:
        raise LearningAgentError(f"Config file {config_path} is not valid JSON: {exc}") from exc
    return repo_root, AppConfig.model_validate(data)


def resolve_repo_path(repo_root: Path, configured_path: str) -> Path:
    return (repo_root / configured_path).resolve()


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)

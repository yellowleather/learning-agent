from pathlib import Path
import re
from typing import Dict, Optional

from engine.errors import EngineError


def load_prompt(name: str) -> str:
    prompt_path = Path(__file__).resolve().parent / "prompts" / name
    try:
        return prompt_path.read_text().strip()
    except FileNotFoundError as exc:
        raise EngineError(f"Prompt asset not found: {prompt_path}") from exc


def render_prompt(name: str, replacements: Optional[Dict[str, str]] = None) -> str:
    prompt = load_prompt(name)
    for key, value in (replacements or {}).items():
        prompt = prompt.replace(f"{{{{{key}}}}}", value)

    unresolved = sorted(set(re.findall(r"\{\{[A-Z0-9_]+\}\}", prompt)))
    if unresolved:
        raise EngineError(f"Prompt asset {name} has unresolved placeholders: {', '.join(unresolved)}")
    return prompt

"""Prompt loading for the topic_chat service.

Mirrors coach.prompts but reads from topic_chat/prompts/. Providers that
implement answer_topic_chat / stream_topic_chat should load the chat
system prompt through this module so the prompt and the call stay in
one package.
"""

from __future__ import annotations

import re
from pathlib import Path
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
        raise EngineError(
            f"Prompt asset {name} has unresolved placeholders: {', '.join(unresolved)}"
        )
    return prompt

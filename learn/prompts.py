"""Prompt loading for the learn domain.

Mirrors coach.prompts but reads from learn/prompts/. Providers that
implement learn-specific calls (generate_question_bank, generate_reading,
generate_concept_cards, generate_prior_knowledge_summary,
score_learning_question) should load prompts through this module so the
prompts and the calls that consume them stay in one package.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional

from coach.errors import CoachError


def load_prompt(name: str) -> str:
    prompt_path = Path(__file__).resolve().parent / "prompts" / name
    try:
        return prompt_path.read_text().strip()
    except FileNotFoundError as exc:
        raise CoachError(f"Prompt asset not found: {prompt_path}") from exc


def render_prompt(name: str, replacements: Optional[Dict[str, str]] = None) -> str:
    prompt = load_prompt(name)
    for key, value in (replacements or {}).items():
        prompt = prompt.replace(f"{{{{{key}}}}}", value)

    unresolved = sorted(set(re.findall(r"\{\{[A-Z0-9_]+\}\}", prompt)))
    if unresolved:
        raise CoachError(
            f"Prompt asset {name} has unresolved placeholders: {', '.join(unresolved)}"
        )
    return prompt

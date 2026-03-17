from pathlib import Path

from learning_agent.errors import LearningAgentError


def load_prompt(name: str) -> str:
    prompt_path = Path(__file__).resolve().parent / "prompts" / name
    try:
        return prompt_path.read_text().strip()
    except FileNotFoundError as exc:
        raise LearningAgentError(f"Prompt asset not found: {prompt_path}") from exc

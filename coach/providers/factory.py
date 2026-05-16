from coach.errors import CoachError
from coach.models import AppConfig
from coach.providers.anthropic_provider import AnthropicProvider
from coach.providers.base import LLMProvider
from coach.providers.openai_provider import OpenAIProvider


def get_provider(config: AppConfig) -> LLMProvider:
    if config.provider == "openai":
        return OpenAIProvider(model=config.model)
    if config.provider == "anthropic":
        return AnthropicProvider(model=config.model)
    raise CoachError(f"Unsupported provider: {config.provider}")

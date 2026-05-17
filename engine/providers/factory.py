from engine.errors import EngineError
from engine.models import AppConfig
from engine.providers.anthropic_provider import AnthropicProvider
from engine.providers.base import LLMProvider
from engine.providers.openai_provider import OpenAIProvider


def get_provider(config: AppConfig) -> LLMProvider:
    if config.provider == "openai":
        return OpenAIProvider(model=config.model)
    if config.provider == "anthropic":
        return AnthropicProvider(model=config.model)
    raise EngineError(f"Unsupported provider: {config.provider}")

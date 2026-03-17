from learning_agent.errors import LearningAgentError
from learning_agent.models import AppConfig
from learning_agent.providers.base import LLMProvider
from learning_agent.providers.openai_provider import OpenAIProvider


def get_provider(config: AppConfig) -> LLMProvider:
    if config.provider == "openai":
        return OpenAIProvider(model=config.model)
    raise LearningAgentError(f"Unsupported provider: {config.provider}")

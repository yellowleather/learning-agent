from learning_agent.models import AppConfig
from learning_agent.providers.anthropic_provider import AnthropicProvider
from learning_agent.providers.factory import get_provider
from learning_agent.providers.openai_provider import OpenAIProvider


def test_get_provider_returns_openai_provider():
    provider = get_provider(
        AppConfig(
            provider="openai",
            model="gpt-test",
            roadmap_path="docs/plan.md",
            target_repo_path="ai_inference_engineering",
        )
    )

    assert isinstance(provider, OpenAIProvider)


def test_get_provider_returns_anthropic_provider():
    provider = get_provider(
        AppConfig(
            provider="anthropic",
            model="claude-test",
            roadmap_path="docs/plan.md",
            target_repo_path="ai_inference_engineering",
        )
    )

    assert isinstance(provider, AnthropicProvider)

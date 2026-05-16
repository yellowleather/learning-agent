from coach.models import AppConfig
from coach.providers.anthropic_provider import AnthropicProvider
from coach.providers.factory import get_provider
from coach.providers.openai_provider import OpenAIProvider


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

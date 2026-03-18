from learning_agent.models import ClassifiedQuestionBankPayload, RawQuestionBankPayload
from learning_agent.providers.openai_provider import OpenAIProvider


def test_normalize_raw_payload_maps_common_tier_variants():
    provider = OpenAIProvider(model="test-model")
    payload = {
        "week": 1,
        "questions": [
            {
                "prompt_text": "Explain the result.",
                "tier": "Tier 2",
                "topic_area": "benchmarking",
            }
        ],
    }

    normalized = provider._normalize_payload(payload, RawQuestionBankPayload)

    assert normalized["questions"][0]["tier"] == "implementation_knowledge"


def test_normalize_classified_payload_maps_common_question_variants():
    provider = OpenAIProvider(model="test-model")
    payload = {
        "week": 1,
        "questions": [
            {
                "id": "q1",
                "type": "implementation_oriented",
                "scope": "required",
                "depth": "intermediate",
                "prompt_text": "Show evidence.",
                "scoring_rubric": ["Provide evidence."],
                "roadmap_anchor": {"week": 1},
                "observation_required": False,
            }
        ],
    }

    normalized = provider._normalize_payload(payload, ClassifiedQuestionBankPayload)

    assert normalized["questions"][0]["type"] == "implementation"
    assert normalized["questions"][0]["scope"] == "core"
    assert normalized["questions"][0]["depth"] == "deep"


def test_validate_raw_question_bank_rejects_small_bank():
    provider = OpenAIProvider(model="test-model")
    payload = RawQuestionBankPayload.model_validate(
        {
            "week": 1,
            "questions": [
                {
                    "prompt_text": "Show evidence.",
                    "tier": "foundational_concepts",
                    "topic_area": "prefill_vs_decode",
                }
            ],
        }
    )

    errors = provider._validate_raw_question_bank(payload)

    assert any("at least 60 raw questions" in error for error in errors)

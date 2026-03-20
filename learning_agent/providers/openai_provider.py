from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any, Type, TypeVar

from pydantic import BaseModel

from learning_agent.errors import LearningAgentError
from learning_agent.models import (
    ClassifiedQuestionBankPayload,
    ConceptCardPayload,
    EvidenceQuestionPayload,
    GateQuestion,
    GateResult,
    GeneratedTask,
    LearningQuestion,
    LearningSession,
    ObservationRecord,
    ProgressState,
    QuestionScore,
    RawLearningQuestion,
    RawQuestionBankPayload,
    TopicChatTurn,
    WeekSpec,
)
from learning_agent.prompts import load_prompt
from learning_agent.providers.base import LLMProvider


ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str):
        self.model = model.strip()

    def generate_raw_question_bank(self, week_spec: WeekSpec, ledger_state: ProgressState) -> RawQuestionBankPayload:
        system_prompt = load_prompt("mentor.md")
        base_user_prompt = (
            "You are a senior hiring manager at a top AI infrastructure company assessing whether a candidate has "
            "deeply mastered the material from the current unlocked week of an inference engineering training plan.\n"
            "Generate a comprehensive raw assessment bank for the current week. Output JSON only.\n\n"
            "Do not generate concept cards in this step.\n"
            "Do not classify questions into the final application schema in this step.\n"
            "Do not generate evidence-based questions in this step.\n"
            "Your goal here is only to produce the largest high-quality raw list of current-week assessment questions possible.\n\n"
            "Generate at least 60 raw questions total across these tiers:\n"
            "Tier 1 - Foundational Concepts (Must Know): at least 22 questions.\n"
            "Tier 2 - Implementation Knowledge (Should Know): at least 24 questions.\n"
            "Tier 3 - Optimization and Production Insights (Nice to Have): at least 14 questions.\n\n"
            "Rules:\n"
            "- Generate at least 60 questions total.\n"
            "- Every question must be specific and technical. Avoid vague or generic questions.\n"
            "- Stay fully scoped to this week only. Do not pull in concepts that belong to later weeks.\n"
            "- Where relevant, include questions about the specific tools, libraries, and technologies named or implied by this week's plan.\n"
            "- Include tradeoff questions, not just definitions.\n"
            "- Include implementation-readiness questions tied to the required files, metrics, deliverables, and verification needs.\n"
            "- Include at least one debugging-process question per tier.\n"
            "- Return each question with only three fields: prompt_text, tier, topic_area.\n"
            "- tier must be one of: foundational_concepts, implementation_knowledge, optimization_and_production_insights.\n"
            "- topic_area should be a short technical label such as prefill_vs_decode, latency_metrics, hf_model_loading, benchmarking, or api_serving.\n\n"
            f"Current week context:\n{week_spec.model_dump_json(indent=2)}\n"
            f"Current ledger state:\n{ledger_state.model_dump_json(indent=2)}\n"
            'Required JSON shape: {"week": 1, "questions": [{"prompt_text": "...", "tier": "foundational_concepts", "topic_area": "..."}]}'
        )
        payload = self._completion_as_model(system_prompt, base_user_prompt, RawQuestionBankPayload)
        errors = self._validate_raw_question_bank(payload)
        if not errors:
            return payload

        merged_payload = payload
        for _attempt in range(2):
            gap_prompt = self._build_raw_question_gap_prompt(
                week_spec=week_spec,
                ledger_state=ledger_state,
                existing_payload=merged_payload,
                errors=errors,
            )
            supplemental = self._completion_as_model(system_prompt, gap_prompt, RawQuestionBankPayload)
            merged_payload = self._merge_raw_question_banks(merged_payload, supplemental)
            errors = self._validate_raw_question_bank(merged_payload)
            if not errors:
                return merged_payload

        raise LearningAgentError("Raw question bank generation failed validation: " + "; ".join(errors))

    def generate_concept_cards(
        self,
        week_spec: WeekSpec,
        ledger_state: ProgressState,
        questions: list[RawLearningQuestion],
    ) -> ConceptCardPayload:
        system_prompt = load_prompt("mentor.md")
        user_prompt = (
            "Derive the teaching cards needed to help a learner answer the provided current-week assessment bank.\n"
            "Use only the current-week context, ledger state, and the provided raw questions. Output JSON only.\n"
            "Generate 5-10 concept cards that cover the smallest meaningful teaching surface needed to answer the bank well.\n"
            "Each card must teach a real current-week concept, explain why it matters for the week's deliverables, "
            "state a common mistake, and optionally include a quick check.\n"
            "Do not generate future-week concepts.\n\n"
            f"Current week context:\n{week_spec.model_dump_json(indent=2)}\n"
            f"Current ledger state:\n{ledger_state.model_dump_json(indent=2)}\n"
            f"Raw question bank:\n{json.dumps([question.model_dump(mode='json') for question in questions], indent=2)}\n"
            'Required JSON shape: {"week": 1, "concept_cards": [{"concept": "...", "explanation": "...", '
            '"why_it_matters": "...", "common_mistake": "...", "quick_check_question": "..."}]}'
        )
        return self._completion_as_model(system_prompt, user_prompt, ConceptCardPayload)

    def classify_question_bank(
        self,
        week_spec: WeekSpec,
        ledger_state: ProgressState,
        questions: list[RawLearningQuestion],
    ) -> ClassifiedQuestionBankPayload:
        system_prompt = load_prompt("mentor.md")
        batches = self._chunk_raw_questions(questions, batch_size=20)
        classified_questions: list[LearningQuestion] = []
        for index, batch in enumerate(batches, start=1):
            payload = self._classify_question_batch(
                system_prompt=system_prompt,
                week_spec=week_spec,
                ledger_state=ledger_state,
                batch=batch,
                batch_index=index,
                batch_count=len(batches),
            )
            classified_questions.extend(payload.questions)
        classified_questions = self._ensure_unique_question_ids(classified_questions)
        return ClassifiedQuestionBankPayload(week=week_spec.number, questions=classified_questions)

    def generate_gate_question(self, week_spec: WeekSpec) -> GateQuestion:
        system_prompt = load_prompt("mentor.md")
        user_prompt = (
            "Create one Socratic concept gate question for the current week.\n"
            "Use only the provided current-week context. Output JSON only.\n"
            f"Current week context:\n{week_spec.model_dump_json(indent=2)}\n"
            'Required JSON shape: {"week": 1, "question": "...", "rubric": ["..."], "context_summary": "..."}'
        )
        return self._completion_as_model(system_prompt, user_prompt, GateQuestion)

    def score_gate_answer(self, week_spec: WeekSpec, question: GateQuestion, answer: str) -> GateResult:
        system_prompt = load_prompt("mentor.md")
        user_prompt = (
            "Evaluate whether the answer passes the concept gate.\n"
            "Use only the current-week context and rubric. Output JSON only.\n"
            f"Current week context:\n{week_spec.model_dump_json(indent=2)}\n"
            f"Question:\n{question.model_dump_json(indent=2)}\n"
            f"Answer:\n{answer}\n"
            'Required JSON shape: {"passed": true, "score_rationale": "...", "missing_concepts": ["..."]}'
        )
        return self._completion_as_model(system_prompt, user_prompt, GateResult)

    def generate_task(self, week_spec: WeekSpec, ledger_state: ProgressState) -> GeneratedTask:
        system_prompt = load_prompt("junior.md")
        user_prompt = (
            "Generate the current-week implementation task for the Junior SWE.\n"
            "Use only the provided current-week context and ledger state. Output JSON only.\n"
            f"Current week context:\n{week_spec.model_dump_json(indent=2)}\n"
            f"Current ledger state:\n{ledger_state.model_dump_json(indent=2)}\n"
            'Required JSON shape: {"week": 1, "title": "...", "objective": "...", "allowed_dirs": ["..."], '
            '"required_files": ["..."], "implementation_steps": ["..."], "acceptance_checks": ["..."], '
            '"verification_expectations": ["..."], "summary": "..."}'
        )
        return self._completion_as_model(system_prompt, user_prompt, GeneratedTask)

    def score_learning_question(
        self,
        week_spec: WeekSpec,
        question: LearningQuestion,
        answer: str,
        observation: ObservationRecord | None,
    ) -> QuestionScore:
        system_prompt = load_prompt("mentor.md")
        observation_json = observation.model_dump_json(indent=2) if observation is not None else "null"
        user_prompt = (
            "Evaluate whether the answer passes the current learning question.\n"
            "Use only the current-week context, the question rubric, and the observation if one is provided. Output JSON only.\n"
            f"Current week context:\n{week_spec.model_dump_json(indent=2)}\n"
            f"Question:\n{question.model_dump_json(indent=2)}\n"
            f"Observation:\n{observation_json}\n"
            f"Answer:\n{answer}\n"
            'Required JSON shape: {"passed": true, "score_rationale": "...", "missing_concepts": ["..."]}'
        )
        return self._completion_as_model(system_prompt, user_prompt, QuestionScore)

    def generate_evidence_questions(
        self,
        week_spec: WeekSpec,
        observation: ObservationRecord,
        learning_session: LearningSession,
    ) -> EvidenceQuestionPayload:
        system_prompt = load_prompt("mentor.md")
        user_prompt = (
            "Create 2-4 evidence-based follow-up questions grounded in the provided observation.\n"
            "Use only the current-week context and the observed result. Output JSON only.\n"
            "All generated questions must have type='evidence_based', scope='core' or 'adjacent', and observation_required=true.\n"
            f"Current week context:\n{week_spec.model_dump_json(indent=2)}\n"
            f"Observation:\n{observation.model_dump_json(indent=2)}\n"
            f"Existing learning session:\n{learning_session.model_dump_json(indent=2)}\n"
            'Required JSON shape: {"week": 1, "questions": [{"id": "evidence_prefill_1", "type": "evidence_based", '
            '"scope": "core", "depth": "baseline", "prompt_text": "...", "scoring_rubric": ["..."], '
            '"roadmap_anchor": {"week": 1}, "observation_required": true}]}'
        )
        return self._completion_as_model(system_prompt, user_prompt, EvidenceQuestionPayload)

    def answer_topic_chat(
        self,
        week_spec: WeekSpec,
        context: str,
        history: list[TopicChatTurn],
        message: str,
    ) -> str:
        messages = self._topic_chat_messages(week_spec, context, history, message)
        response = self._chat_completions_create(
            model=self.model,
            temperature=0.3,
            messages=messages,
        )
        content = response.choices[0].message.content
        if not content or not content.strip():
            raise LearningAgentError("OpenAI provider returned an empty topic chat response.")
        return content.strip()

    def stream_topic_chat(
        self,
        week_spec: WeekSpec,
        context: str,
        history: list[TopicChatTurn],
        message: str,
    ) -> Iterator[str]:
        messages = self._topic_chat_messages(week_spec, context, history, message)
        response = self._chat_completions_create(
            model=self.model,
            temperature=0.3,
            messages=messages,
            stream=True,
        )
        emitted = False
        for chunk in response:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            text = self._coerce_stream_text(getattr(delta, "content", None))
            if not text:
                continue
            emitted = True
            yield text
        if not emitted:
            raise LearningAgentError("OpenAI provider returned an empty topic chat response.")

    def _topic_chat_messages(
        self,
        week_spec: WeekSpec,
        context: str,
        history: list[TopicChatTurn],
        message: str,
    ) -> list[dict[str, str]]:
        system_prompt = load_prompt("mentor.md")
        history_lines = []
        for turn in history[-10:]:
            history_lines.append(f"{turn.role.title()}: {turn.content}")
        history_text = "\n".join(history_lines) if history_lines else "(no prior chat)"
        user_prompt = (
            "You are the topic tutor for the current unlocked week of this learning agent.\n"
            "Answer the user's question using the provided week context.\n"
            "Stay grounded in the current week, current artifacts, current metrics, and current progress.\n"
            "Be concise but technically useful.\n"
            "Do not invent repository state that is not present in the context.\n"
            "Avoid drifting into future-week material unless the user explicitly asks for a comparison.\n\n"
            f"Current week context:\n{week_spec.model_dump_json(indent=2)}\n\n"
            f"Current app context:\n{context}\n\n"
            f"Recent chat history:\n{history_text}\n\n"
            f"User question:\n{message}\n"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _coerce_stream_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            pieces: list[str] = []
            for item in content:
                if isinstance(item, str):
                    pieces.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        pieces.append(text)
                    continue
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    pieces.append(text)
            return "".join(pieces)
        return ""

    def _classify_question_batch(
        self,
        system_prompt: str,
        week_spec: WeekSpec,
        ledger_state: ProgressState,
        batch: list[RawLearningQuestion],
        batch_index: int,
        batch_count: int,
    ) -> ClassifiedQuestionBankPayload:
        user_prompt = (
            "Classify the provided raw current-week assessment questions into the application's structured question schema.\n"
            "Use only the current-week context, ledger state, and the raw questions in this batch. Output JSON only.\n"
            "Preserve the substance of each raw question. You may tighten wording, but do not omit or merge any question.\n"
            f"This is batch {batch_index} of {batch_count}. You must return exactly {len(batch)} classified questions.\n"
            "Every classified question must include id, type, scope, depth, prompt_text, scoring_rubric, roadmap_anchor, and observation_required.\n"
            "For this initial bank:\n"
            "- type must be concept or implementation only.\n"
            "- observation_required must be false for every question.\n"
            "- foundational_concepts should mostly map to concept/core/baseline or concept/core/deep.\n"
            "- implementation_knowledge should mostly map to implementation/core/baseline or implementation/core/deep.\n"
            "- optimization_and_production_insights should mostly map to concept/adjacent/deep, implementation/adjacent/deep, or stretch variants.\n"
            "- Use ids that include the batch number so they remain globally unique.\n"
            "- Each scoring rubric must be concrete enough to score a free-text answer.\n"
            "- Stay strictly within the current week.\n\n"
            f"Current week context:\n{week_spec.model_dump_json(indent=2)}\n"
            f"Current ledger state:\n{ledger_state.model_dump_json(indent=2)}\n"
            f"Raw question batch:\n{json.dumps([question.model_dump(mode='json') for question in batch], indent=2)}\n"
            'Required JSON shape: {"week": 1, "questions": [{"id": "b1_tier1_latency_01", "type": "concept", '
            '"scope": "core", "depth": "baseline", "prompt_text": "...", "scoring_rubric": ["..."], '
            '"roadmap_anchor": {"week": 1, "topic": "..."}, "observation_required": false}]}'
        )
        payload = self._completion_as_model(system_prompt, user_prompt, ClassifiedQuestionBankPayload)
        if len(payload.questions) != len(batch):
            retry_prompt = (
                f"{user_prompt}\n\nThe previous attempt returned {len(payload.questions)} classified questions "
                f"for a batch of {len(batch)} raw questions. Regenerate this batch and return exactly {len(batch)} "
                "classified questions, one for each raw question, with no omissions."
            )
            payload = self._completion_as_model(system_prompt, retry_prompt, ClassifiedQuestionBankPayload)
        return payload

    def _completion_as_model(
        self, system_prompt: str, user_prompt: str, response_model: Type[ResponseModelT]
    ) -> ResponseModelT:
        response = self._chat_completions_create(
            model=self.model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise LearningAgentError("OpenAI provider returned an empty response.")
        payload = self._extract_json(content)
        payload = self._normalize_payload(payload, response_model)
        return response_model.model_validate(payload)

    def _chat_completions_create(self, **kwargs: Any):
        client = self._client()
        try:
            return client.chat.completions.create(**kwargs)
        except LearningAgentError:
            raise
        except Exception as exc:
            raise self._translate_chat_error(exc) from exc

    def _translate_chat_error(self, exc: Exception) -> LearningAgentError:
        try:
            import openai
        except ImportError:
            return LearningAgentError(str(exc) or "OpenAI request failed.")

        if isinstance(exc, openai.AuthenticationError):
            return LearningAgentError("OpenAI authentication failed. Check OPENAI_API_KEY.")
        if isinstance(exc, openai.APIConnectionError):
            return LearningAgentError("OpenAI connection failed. Check network access and API configuration.")
        if isinstance(exc, openai.APITimeoutError):
            return LearningAgentError("OpenAI request timed out. Try again.")
        if isinstance(exc, openai.RateLimitError):
            return LearningAgentError("OpenAI rate limit hit. Try again shortly.")
        if isinstance(exc, openai.APIStatusError):
            status_code = getattr(exc, "status_code", None)
            if status_code:
                return LearningAgentError(f"OpenAI request failed with status {status_code}.")
            return LearningAgentError("OpenAI request failed.")
        if isinstance(exc, openai.OpenAIError):
            return LearningAgentError(str(exc) or "OpenAI request failed.")
        return LearningAgentError(str(exc) or "OpenAI request failed.")

    def _client(self):
        if not self.model:
            raise LearningAgentError("Config field `model` must be set before using the OpenAI provider.")
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise LearningAgentError("OPENAI_API_KEY must be set before using the OpenAI provider.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LearningAgentError("The `openai` package is not installed.") from exc
        return OpenAI(api_key=api_key)

    def _extract_json(self, content: str):
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LearningAgentError(f"Model response was not valid JSON: {exc}") from exc

    def _normalize_payload(self, payload: Any, response_model: Type[ResponseModelT]) -> Any:
        if not isinstance(payload, dict):
            return payload

        if response_model is RawQuestionBankPayload:
            questions = payload.get("questions")
            if isinstance(questions, list):
                payload = dict(payload)
                payload["questions"] = [self._normalize_raw_question(question) for question in questions]
            return payload

        if response_model in {ClassifiedQuestionBankPayload, EvidenceQuestionPayload}:
            questions = payload.get("questions")
            if isinstance(questions, list):
                payload = dict(payload)
                payload["questions"] = [self._normalize_question(question) for question in questions]
        return payload

    def _validate_raw_question_bank(self, payload: RawQuestionBankPayload) -> list[str]:
        errors: list[str] = []
        questions = payload.questions
        if len(questions) < 60:
            errors.append(f"expected at least 60 raw questions but received {len(questions)}")

        tier1 = [question for question in questions if question.tier == "foundational_concepts"]
        tier2 = [question for question in questions if question.tier == "implementation_knowledge"]
        tier3 = [question for question in questions if question.tier == "optimization_and_production_insights"]

        if len(tier1) < 22:
            errors.append(f"expected at least 22 foundational questions but received {len(tier1)}")
        if len(tier2) < 24:
            errors.append(f"expected at least 24 implementation questions but received {len(tier2)}")
        if len(tier3) < 14:
            errors.append(f"expected at least 14 optimization questions but received {len(tier3)}")

        return errors

    def _merge_raw_question_banks(
        self, current: RawQuestionBankPayload, supplemental: RawQuestionBankPayload
    ) -> RawQuestionBankPayload:
        return RawQuestionBankPayload(
            week=current.week,
            questions=[*current.questions, *supplemental.questions],
        )

    def _build_raw_question_gap_prompt(
        self,
        week_spec: WeekSpec,
        ledger_state: ProgressState,
        existing_payload: RawQuestionBankPayload,
        errors: list[str],
    ) -> str:
        counts = self._raw_question_bank_counts(existing_payload)
        additional_total = max(60 - counts["total"], 0) + 8
        additional_foundational = max(22 - counts["foundational_concepts"], 0) + 2
        additional_implementation = max(24 - counts["implementation_knowledge"], 0) + 4
        additional_optimization = max(14 - counts["optimization_and_production_insights"], 0) + 2
        return (
            "The existing raw question bank is close, but it does not yet satisfy the required minimum counts.\n"
            "Generate only additional raw questions that fill the gaps. Output JSON only.\n"
            "Do not repeat or paraphrase any existing question.\n"
            "Stay strictly within the current week.\n"
            f"Current week context:\n{week_spec.model_dump_json(indent=2)}\n"
            f"Current ledger state:\n{ledger_state.model_dump_json(indent=2)}\n"
            f"Existing raw question bank:\n{existing_payload.model_dump_json(indent=2)}\n"
            "Validation failures:\n"
            + "\n".join(f"- {error}" for error in errors)
            + "\n"
            + "Generate at least "
            + str(additional_total)
            + " additional questions, including at least "
            + str(additional_foundational)
            + " foundational_concepts questions, at least "
            + str(additional_implementation)
            + " implementation_knowledge questions, and at least "
            + str(additional_optimization)
            + " optimization_and_production_insights questions.\n"
            + 'Required JSON shape: {"week": 1, "questions": [{"prompt_text": "...", "tier": "foundational_concepts", "topic_area": "..."}]}'
        )

    def _raw_question_bank_counts(self, payload: RawQuestionBankPayload) -> dict[str, int]:
        counts = {
            "total": len(payload.questions),
            "foundational_concepts": 0,
            "implementation_knowledge": 0,
            "optimization_and_production_insights": 0,
        }
        for question in payload.questions:
            counts[question.tier] = counts.get(question.tier, 0) + 1
        return counts

    def _chunk_raw_questions(
        self, questions: list[RawLearningQuestion], batch_size: int
    ) -> list[list[RawLearningQuestion]]:
        return [questions[index : index + batch_size] for index in range(0, len(questions), batch_size)]

    def _ensure_unique_question_ids(self, questions: list[LearningQuestion]) -> list[LearningQuestion]:
        seen: dict[str, int] = {}
        normalized_questions: list[LearningQuestion] = []
        for question in questions:
            count = seen.get(question.id, 0)
            if count == 0:
                normalized_questions.append(question)
            else:
                normalized_questions.append(
                    question.model_copy(update={"id": f"{question.id}_{count + 1}"})
                )
            seen[question.id] = count + 1
        return normalized_questions

    def _normalize_raw_question(self, question: Any) -> Any:
        if not isinstance(question, dict):
            return question

        normalized = dict(question)
        tier = normalized.get("tier")
        if isinstance(tier, str):
            normalized["tier"] = self._normalize_raw_tier(tier)
        return normalized

    def _normalize_question(self, question: Any) -> Any:
        if not isinstance(question, dict):
            return question

        normalized = dict(question)

        question_type = normalized.get("type")
        if isinstance(question_type, str):
            normalized["type"] = self._normalize_question_type(question_type)

        depth = normalized.get("depth")
        if isinstance(depth, str):
            normalized["depth"] = self._normalize_question_depth(depth)

        scope = normalized.get("scope")
        if isinstance(scope, str):
            normalized["scope"] = self._normalize_question_scope(scope)

        return normalized

    def _normalize_question_type(self, value: str) -> str:
        normalized = value.strip().lower()
        if normalized in {"concept", "implementation", "evidence_based"}:
            return normalized
        if "evidence" in normalized:
            return "evidence_based"
        if "impl" in normalized:
            return "implementation"
        return {
            "conceptual": "concept",
            "implementation_oriented": "implementation",
        }.get(normalized, "concept")

    def _normalize_question_depth(self, value: str) -> str:
        normalized = value.strip().lower()
        if normalized in {"baseline", "deep", "stretch"}:
            return normalized
        if any(token in normalized for token in {"base", "basic", "foundation", "intro"}):
            return "baseline"
        if any(token in normalized for token in {"deep", "deeper", "intermediate"}):
            return "deep"
        if any(token in normalized for token in {"stretch", "advanced", "expert"}):
            return "stretch"
        return "deep"

    def _normalize_question_scope(self, value: str) -> str:
        normalized = value.strip().lower()
        if normalized in {"core", "adjacent", "later_week"}:
            return normalized
        if any(token in normalized for token in {"later", "future"}):
            return "later_week"
        if any(token in normalized for token in {"adjacent", "enrich"}):
            return "adjacent"
        return {
            "required": "core",
            "current_week": "core",
        }.get(normalized, "core")

    def _normalize_raw_tier(self, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
        if normalized in {
            "foundational_concepts",
            "implementation_knowledge",
            "optimization_and_production_insights",
        }:
            return normalized
        if any(token in normalized for token in {"foundational", "must_know", "tier1", "tier_1"}):
            return "foundational_concepts"
        if any(token in normalized for token in {"implementation", "should_know", "tier2", "tier_2"}):
            return "implementation_knowledge"
        if any(token in normalized for token in {"optimization", "production", "nice_to_have", "tier3", "tier_3"}):
            return "optimization_and_production_insights"
        return "foundational_concepts"

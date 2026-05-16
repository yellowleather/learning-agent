"""Learn stage.

Owns the learning pipeline: question-bank generation, reading material,
concept cards, scoring user answers, and the learning_check_passed gate.
Also owns the cross-week reset (`reset_pipeline`) that the UI uses when the
user wants to regenerate this week's learning content from scratch.

`reset_pipeline` clears more than just learning state — it clears all
downstream gates and ephemeral state so the week can be re-run cleanly.
That is intentional behaviour preserved from the original controller.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Optional

from curriculum.access import CurriculumAccess
from coach.errors import CoachError
from coach.models import (
    CheckpointState,
    Ledger,
)
from learn.models import (
    ConceptCard,
    ConceptCardPayload,
    LearningBundle,
    LearningQuestion,
    LearningQuestionBankPayload,
    LearningSession,
    QuestionAttempt,
    ReadingMaterialPayload,
)
from coach.providers.base import LLMProvider
from coach.state import StateStore


class LearnStage:
    """Stage controller for the learning pipeline."""

    def __init__(
        self,
        state: StateStore,
        curriculum: CurriculumAccess,
        provider_factory: Callable[[], LLMProvider],
    ):
        self.state = state
        self.curriculum = curriculum
        self.provider_factory = provider_factory

    # -- Public actions ----------------------------------------------------

    def generate_assist(self) -> LearningSession:
        """Generate the current week's question bank + reading + concept cards
        from the provider, persist as a LearningSession, and flip the learning
        gate if (somehow) the required attempts were already in place."""
        ledger = self.state.load_ledger()
        week_spec = self.curriculum.current_week(ledger.state.current_week)
        provider = self.provider_factory()
        _prior, session = self._build_session(provider, ledger, week_spec)
        self.state.save_learning(session)
        self._sync_progress(ledger, session)
        self.state.save_ledger(ledger)
        return session

    def reset_pipeline(self) -> Ledger:
        """Reset the whole week to a clean state. Clears every gate and every
        recorded artefact / metric / observation / reflection, then drops the
        learning + task ephemeral files. Used when the user wants to regenerate
        learning material for the current week from scratch."""
        ledger = self.state.load_ledger()
        ledger.state.gates.learning_check_passed = False
        ledger.state.gates.implementation_complete = False
        ledger.state.gates.verification_passed = False
        ledger.state.gates.evidence_reliable = False
        ledger.state.gates.week_approved = False
        ledger.state.artifacts.completed_files = []
        ledger.state.metrics.recorded = {}
        ledger.state.verification = None
        ledger.state.observation = None
        ledger.state.reflection = None
        self.state.save_ledger(ledger)
        self.state.clear_ephemeral_state()
        return ledger

    def compare_providers(
        self,
        providers: list[tuple[str, str, LLMProvider]],
        output_dir: Path,
    ) -> dict[str, Any]:
        """Run the same learning pipeline against each provider and write the
        outputs (and validation errors) to per-provider subdirectories. Used
        as an offline eval tool from the CLI."""
        ledger = self.reset_pipeline()
        week_spec = self.curriculum.current_week(ledger.state.current_week)
        output_dir.mkdir(parents=True, exist_ok=True)

        results: list[dict[str, str]] = []
        for label, model, provider in providers:
            provider_dir = output_dir / label
            provider_dir.mkdir(parents=True, exist_ok=True)
            try:
                provider_result = self._compare_single_provider(
                    provider=provider,
                    ledger=ledger,
                    week_spec=week_spec,
                    provider_label=label,
                    model=model,
                    output_dir=provider_dir,
                )
            except Exception as exc:
                self._write_json(
                    provider_dir / "metadata.json",
                    {
                        "provider_label": label,
                        "model": model,
                        "week": int(week_spec["number"]),
                        "status": "error",
                        "error": str(exc),
                    },
                )
                results.append(
                    {
                        "provider_label": label,
                        "model": model,
                        "output_dir": str(provider_dir),
                        "status": "error",
                        "error": str(exc),
                    }
                )
                continue
            results.append(provider_result)

        return {
            "week": int(week_spec["number"]),
            "output_dir": str(output_dir),
            "providers": results,
        }

    def answer_question(self, question_id: str, answer: str):
        """Score a single answer through the provider, append the attempt to
        the persisted session, and flip the learning gate if the user has
        now satisfied the required baseline questions."""
        ledger = self.state.load_ledger()
        session = self.state.load_learning()
        question = self._question_by_id(session, question_id)
        week_spec = self.curriculum.current_week(ledger.state.current_week)
        provider = self.provider_factory()
        result = provider.score_learning_question(week_spec, question, answer, ledger.state.observation)
        session.attempts.append(QuestionAttempt(question_id=question_id, answer=answer, result=result))
        self.state.save_learning(session)
        self._sync_progress(ledger, session)
        self.state.save_ledger(ledger)
        return result

    def get_session(self) -> Optional[LearningSession]:
        """Return the persisted learning session, or None if none exists."""
        if not self.state.learning_path.exists():
            return None
        return self.state.load_learning()

    def ensure_assist(self) -> LearningSession:
        """Return the persisted session iff it matches the current week, else
        regenerate. Used by callers that don't care whether the session is new
        or cached, just that it exists for *this* week."""
        session = self.get_session()
        if session is None:
            return self.generate_assist()

        ledger = self.state.load_ledger()
        if session.week != ledger.state.current_week:
            return self.generate_assist()

        return session

    def get_bundle(self) -> Optional[LearningBundle]:
        """Return the user-facing view of the learning session (concept cards,
        reading, questions, attempts) — without the internal scoring rubric or
        prior-knowledge summary."""
        session = self.get_session()
        if session is None:
            return None
        return LearningBundle(
            week=session.week,
            concept_cards=session.concept_cards,
            reading_material=session.reading_material,
            questions=session.questions,
            attempts=session.attempts,
        )

    # -- Cross-stage introspection (read-only, called by orchestrator) -----

    def question_progress(self, session: Optional[LearningSession]) -> dict[str, Any]:
        """How many required baseline questions have been passed so far."""
        if session is None:
            return {
                "required_total": 0,
                "required_passed": 0,
                "required_pending": 0,
            }
        latest_attempts = self._latest_attempts(session)
        required_ids = self._required_question_ids(session)
        required_passed = sum(
            1
            for question_id in required_ids
            if latest_attempts.get(question_id, None) and latest_attempts[question_id].result.passed
        )
        return {
            "required_total": len(required_ids),
            "required_passed": required_passed,
            "required_pending": max(len(required_ids) - required_passed, 0),
        }

    def required_questions_passed(self, session: LearningSession) -> bool:
        """True iff every required baseline question has a latest passing attempt."""
        required_ids = self._required_question_ids(session)
        if not required_ids:
            return False
        latest_attempts = self._latest_attempts(session)
        return all(
            question_id in latest_attempts and latest_attempts[question_id].result.passed
            for question_id in required_ids
        )

    def build_checkpoint(
        self, ledger: Ledger, learning_session: Optional[LearningSession]
    ) -> CheckpointState:
        """Render the Learning Questions checkpoint card for the status payload."""
        if learning_session is None:
            return CheckpointState(
                id="learning_questions",
                title="Learning Questions",
                description="Generate Learning Assist content and pass the required baseline questions.",
                status="not_started" if not ledger.state.gates.learning_check_passed else "passed",
                reason="Generate Learning Assist to load concept cards and questions."
                if not ledger.state.gates.learning_check_passed
                else "Concept coverage satisfied through the required baseline questions.",
            )

        progress = self.question_progress(learning_session)
        latest_attempts = self._latest_attempts(learning_session)
        required_ids = set(self._required_question_ids(learning_session))
        attempted_required = [question_id for question_id in required_ids if question_id in latest_attempts]
        status = "not_started"
        if self.required_questions_passed(learning_session):
            status = "passed"
        elif attempted_required and any(
            not latest_attempts[question_id].result.passed for question_id in attempted_required
        ):
            status = "failed"
        elif attempted_required:
            status = "in_progress"
        reason = f"{progress['required_passed']}/{progress['required_total']} required questions passed."
        return CheckpointState(
            id="learning_questions",
            title="Learning Questions",
            description="Cover the current week's required baseline questions.",
            status=status,
            reason=reason,
        )

    # -- Internal pipeline -------------------------------------------------

    def _build_session(
        self,
        provider: LLMProvider,
        ledger: Ledger,
        week_spec: dict[str, Any],
    ) -> tuple[str, LearningSession]:
        prior_knowledge_summary = provider.generate_prior_knowledge_summary(
            full_plan=self.curriculum.markdown(),
            target_week_number=int(week_spec["number"]),
        )
        question_payload = provider.generate_question_bank(week_spec, prior_knowledge_summary, ledger.state)
        if not isinstance(question_payload, LearningQuestionBankPayload):
            question_payload = LearningQuestionBankPayload.model_validate(question_payload)
        questions = question_payload.questions
        question_errors = self._validate_questions(questions)
        if question_errors:
            raise CoachError(
                "Learning Assist question bank failed validation: " + "; ".join(question_errors)
            )

        reading_payload = provider.generate_reading_material(
            week_spec, prior_knowledge_summary, ledger.state, questions
        )
        if not isinstance(reading_payload, ReadingMaterialPayload):
            reading_payload = ReadingMaterialPayload.model_validate(reading_payload)
        reading_material = self._normalize_reading_material(reading_payload)
        reading_errors = self._validate_reading_material(reading_material)
        if reading_errors:
            raise CoachError(
                "Learning Assist reading generation failed validation: " + "; ".join(reading_errors)
            )

        concept_payload = provider.generate_concept_cards_from_reading(week_spec, ledger.state, reading_material)
        if not isinstance(concept_payload, ConceptCardPayload):
            concept_payload = ConceptCardPayload.model_validate(concept_payload)
        concept_cards = self._normalize_concept_cards(concept_payload.concept_cards)
        concept_errors = self._validate_concept_cards(concept_cards)
        if concept_errors:
            raise CoachError(
                "Learning Assist concept-card generation failed validation: " + "; ".join(concept_errors)
            )

        session = LearningSession(
            week=int(week_spec["number"]),
            concept_cards=concept_cards,
            reading_material=reading_material,
            questions=questions,
        )
        return prior_knowledge_summary, session

    def _compare_single_provider(
        self,
        *,
        provider: LLMProvider,
        ledger: Ledger,
        week_spec: dict[str, Any],
        provider_label: str,
        model: str,
        output_dir: Path,
    ) -> dict[str, Any]:
        week_number = int(week_spec["number"])
        prior_knowledge_summary = provider.generate_prior_knowledge_summary(
            full_plan=self.curriculum.markdown(),
            target_week_number=week_number,
        )
        self._write_text(output_dir / "prior_knowledge_summary.txt", prior_knowledge_summary)

        question_payload = provider.generate_question_bank(week_spec, prior_knowledge_summary, ledger.state)
        if not isinstance(question_payload, LearningQuestionBankPayload):
            question_payload = LearningQuestionBankPayload.model_validate(question_payload)
        questions = question_payload.questions
        question_bank_payload = LearningQuestionBankPayload(week=week_number, questions=questions)
        self._write_json(output_dir / "question_bank.json", question_bank_payload.model_dump(mode="json"))

        question_errors = self._validate_questions(questions)

        reading_payload = provider.generate_reading_material(
            week_spec, prior_knowledge_summary, ledger.state, questions
        )
        if not isinstance(reading_payload, ReadingMaterialPayload):
            reading_payload = ReadingMaterialPayload.model_validate(reading_payload)
        reading_material = self._normalize_reading_material(reading_payload)
        self._write_json(output_dir / "reading_material.json", reading_material.model_dump(mode="json"))

        reading_errors = self._validate_reading_material(reading_material)

        concept_payload = provider.generate_concept_cards_from_reading(week_spec, ledger.state, reading_material)
        if not isinstance(concept_payload, ConceptCardPayload):
            concept_payload = ConceptCardPayload.model_validate(concept_payload)
        concept_cards = self._normalize_concept_cards(concept_payload.concept_cards)
        concept_card_payload = ConceptCardPayload(week=week_number, concept_cards=concept_cards)
        self._write_json(output_dir / "concept_cards.json", concept_card_payload.model_dump(mode="json"))

        concept_errors = self._validate_concept_cards(concept_cards)

        validation_errors = {
            "question_bank": question_errors,
            "reading_material": reading_errors,
            "concept_cards": concept_errors,
        }
        self._write_json(output_dir / "validation_errors.json", validation_errors)

        is_valid = not any(validation_errors.values())
        if is_valid:
            session = LearningSession(
                week=week_number,
                concept_cards=concept_cards,
                reading_material=reading_material,
                questions=questions,
            )
            self._write_json(output_dir / "learning_session.json", session.model_dump(mode="json"))

        metadata = {
            "provider_label": provider_label,
            "model": model,
            "week": week_number,
            "status": "valid" if is_valid else "invalid",
        }
        self._write_json(output_dir / "metadata.json", metadata)
        return {
            "provider_label": provider_label,
            "model": model,
            "output_dir": str(output_dir),
            "status": metadata["status"],
        }

    def _sync_progress(self, ledger: Ledger, session: LearningSession) -> None:
        """Flip the learning gate iff this week has any required questions and
        all of them have a passing latest attempt."""
        if self._required_question_ids(session) and self.required_questions_passed(session):
            ledger.state.gates.learning_check_passed = True

    # -- Validators (moved verbatim) ---------------------------------------

    def _validate_questions(self, questions: list[LearningQuestion]) -> list[str]:
        errors: list[str] = []
        if len(questions) < 50:
            errors.append(f"expected at least 50 questions but received {len(questions)}")

        ids = [question.id for question in questions]
        if len(set(ids)) != len(ids):
            errors.append("question ids must be unique")

        depth_counts = {"baseline": 0, "deep": 0, "stretch": 0}
        for question in questions:
            if not question.prompt_text.strip():
                errors.append("question bank contains an empty question prompt")
            if not question.scoring_rubric:
                errors.append(f"question {question.id!r} is missing a scoring rubric")
            depth_counts[question.depth] = depth_counts.get(question.depth, 0) + 1
            prompt_lower = question.prompt_text.lower()
            if "week 2" in prompt_lower or "week 3" in prompt_lower or "next week" in prompt_lower:
                errors.append(f"question appears to leak future-week material: {question.prompt_text}")

        if depth_counts["baseline"] < 18:
            errors.append("question bank does not contain enough baseline questions")
        if depth_counts["deep"] < 20:
            errors.append("question bank does not contain enough deep questions")
        if depth_counts["stretch"] < 12:
            errors.append("question bank does not contain enough stretch questions")

        return errors

    def _validate_reading_material(self, reading_material: ReadingMaterialPayload) -> list[str]:
        errors: list[str] = []
        banned_patterns = [
            r"\bchapter\b",
            r"\bsection\b",
            r"\bconcept cards?\b",
            r"\bquestion bank\b",
            r"\brubric\b",
            r"\bui\b",
        ]

        if not reading_material.title.strip():
            errors.append("reading material title cannot be empty")
        if not reading_material.body_markdown.strip():
            errors.append("reading material body cannot be empty")
            return errors
        if not re.search(r"(?im)^##\s+How This Week Works\s*$", reading_material.body_markdown):
            errors.append("reading material must include a 'How This Week Works' heading")

        total_word_count = len(reading_material.body_markdown.split())
        if total_word_count < 220:
            errors.append("reading material is too short to support the current week's question set")
        if len(re.findall(r"(?im)^##\s+", reading_material.body_markdown)) < 3:
            errors.append("reading material should contain at least 3 markdown sections")

        text = " ".join(part for part in (reading_material.title, reading_material.body_markdown) if part).strip()
        for pattern in banned_patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                errors.append(f"reading material uses internal product language: {pattern}")
                break

        return errors

    def _validate_concept_cards(self, concept_cards: list[ConceptCard]) -> list[str]:
        errors: list[str] = []
        if len(concept_cards) < 3:
            errors.append(f"expected at least 3 concept cards but received {len(concept_cards)}")
        if not concept_cards:
            return errors

        ids = [card.id for card in concept_cards]
        if len(set(ids)) != len(ids):
            errors.append("concept card ids must be unique")

        banned_patterns = [
            r"\bchapter\b",
            r"\bsection\b",
            r"\bquestion bank\b",
            r"\brubric\b",
            r"\bui\b",
        ]

        for card in concept_cards:
            if not card.title.strip():
                errors.append(f"concept card {card.id!r} has an empty title")
            if not card.explanation.strip():
                errors.append(f"concept card {card.id!r} has an empty explanation")
            if not card.why_it_matters.strip():
                errors.append(f"concept card {card.id!r} has an empty why_it_matters")
            if not card.common_mistake.strip():
                errors.append(f"concept card {card.id!r} has an empty common_mistake")
            text = " ".join(
                part
                for part in (
                    card.title,
                    card.explanation,
                    card.why_it_matters,
                    card.common_mistake,
                    card.quick_check_question or "",
                )
                if part
            )
            for pattern in banned_patterns:
                if re.search(pattern, text, flags=re.IGNORECASE):
                    errors.append(f"concept card {card.id!r} uses internal product language: {pattern}")
                    break

        return errors

    # -- Normalizers -------------------------------------------------------

    def _normalize_reading_material(self, reading_material: ReadingMaterialPayload) -> ReadingMaterialPayload:
        title = (reading_material.title or "").strip() or "Week Reading"
        body_markdown = (reading_material.body_markdown or "").strip()
        if body_markdown and not re.search(r"(?im)^##\s+How This Week Works\s*$", body_markdown):
            body_markdown = "## How This Week Works\n\n" + body_markdown
        return reading_material.model_copy(update={"title": title, "body_markdown": body_markdown})

    def _normalize_concept_cards(self, concept_cards: list[ConceptCard]) -> list[ConceptCard]:
        normalized_cards: list[ConceptCard] = []
        used_ids: set[str] = set()
        for index, card in enumerate(concept_cards, start=1):
            title = card.title.strip() or _humanize_label(card.concept)
            concept = card.concept.strip() or _slugify(title).replace("-", "_")
            card_id = card.id.strip() or _slugify(concept or title or f"concept-{index}")
            if card_id in used_ids:
                suffix = 2
                while f"{card_id}-{suffix}" in used_ids:
                    suffix += 1
                card_id = f"{card_id}-{suffix}"
            used_ids.add(card_id)
            normalized_cards.append(
                card.model_copy(
                    update={
                        "id": card_id,
                        "concept": concept,
                        "title": title,
                        "explanation": card.explanation.strip(),
                        "why_it_matters": card.why_it_matters.strip(),
                        "common_mistake": card.common_mistake.strip(),
                        "quick_check_question": (card.quick_check_question or "").strip() or None,
                    }
                )
            )
        return normalized_cards

    # -- Question / attempt helpers ----------------------------------------

    def _required_question_ids(self, session: LearningSession) -> list[str]:
        return [question.id for question in session.questions if question.depth == "baseline"]

    def _latest_attempts(self, session: LearningSession) -> dict[str, QuestionAttempt]:
        attempts: dict[str, QuestionAttempt] = {}
        for attempt in session.attempts:
            attempts[attempt.question_id] = attempt
        return attempts

    def _question_by_id(self, session: LearningSession, question_id: str) -> LearningQuestion:
        for question in session.questions:
            if question.id == question_id:
                return question
        raise CoachError(
            f"Question `{question_id}` does not exist in the current learning session."
        )

    # -- IO helpers --------------------------------------------------------

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def _write_text(self, path: Path, text: str) -> None:
        path.write_text(text.rstrip() + "\n")


def _humanize_label(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("-", "_").split("_") if part)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "content"

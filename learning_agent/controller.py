from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Dict

from learning_agent.config import resolve_repo_path
from learning_agent.errors import LearningAgentError
from learning_agent.models import (
    AppConfig,
    CheckpointState,
    ConceptCard,
    ConceptCardPayload,
    CurriculumMetadata,
    Ledger,
    LearningBundle,
    LearningQuestion,
    LearningQuestionBankPayload,
    LearningSession,
    ObservationRecord,
    QuestionAttempt,
    ReadingMaterialPayload,
    ReflectionRecord,
    TaskSession,
    TopicChatTurn,
    VerificationRecord,
)
from learning_agent.providers.factory import get_provider
from learning_agent.roadmap_parser import load_roadmap_dict
from learning_agent.state import StateStore


class LearningController:
    def __init__(self, repo_root: Path, config: AppConfig):
        self.repo_root = repo_root
        self.config = config
        self.state = StateStore(repo_root, config)
        self.roadmap_path = resolve_repo_path(repo_root, config.roadmap_path)
        self.target_repo_path = resolve_repo_path(repo_root, config.target_repo_path)

    def initialize(self) -> Ledger:
        roadmap = self._load_roadmap()
        metadata = self._curriculum_metadata(roadmap)
        week_one = self._week_by_number(roadmap, 1)
        return self.state.initialize_ledger(metadata, week_one)

    def status(self) -> Dict[str, Any]:
        ledger = self.state.load_ledger()
        week_spec = self._load_current_week(ledger)
        blockers = self._approval_blockers(ledger)
        task_exists = self.state.task_path.exists()
        learning_exists = self.state.learning_path.exists()
        task_session = self.get_task_session()
        learning_session = self.get_learning_session()
        checkpoints = self._build_checkpoints(ledger, learning_session)
        return {
            "week": int(week_spec["number"]),
            "total_weeks": ledger.curriculum_metadata.total_weeks,
            "title": str(week_spec["short_title"]),
            "goal": str(week_spec["goal"]),
            "key_resources": list(week_spec.get("key_resources", [])),
            "active_dirs": ledger.state.active_dirs,
            "required_files": ledger.state.artifacts.required_files,
            "completed_files": ledger.state.artifacts.completed_files,
            "required_metrics": ledger.state.metrics.required,
            "recorded_metrics": ledger.state.metrics.recorded,
            "gates": ledger.state.gates.model_dump(mode="json"),
            "task_generated": task_exists,
            "learning_generated": learning_exists,
            "verification": ledger.state.verification.model_dump(mode="json") if ledger.state.verification else None,
            "observation": ledger.state.observation.model_dump(mode="json") if ledger.state.observation else None,
            "reflection": ledger.state.reflection.model_dump(mode="json") if ledger.state.reflection else None,
            "evidence_required": self._requires_evidence(ledger),
            "checkpoints": [checkpoint.model_dump(mode="json") for checkpoint in checkpoints],
            "question_progress": self._question_progress(learning_session),
            "can_generate_task": ledger.state.gates.learning_check_passed,
            "can_approve": not blockers,
            "approval_blockers": blockers,
            "task_session": task_session.model_dump(mode="json") if task_session else None,
            "learning_session": learning_session.model_dump(mode="json") if learning_session else None,
        }

    def generate_learning_assist(self) -> LearningSession:
        ledger = self.state.load_ledger()
        week_spec = self._load_current_week(ledger)
        provider = self._provider()
        question_payload = provider.generate_question_bank(week_spec, ledger.state)
        if not isinstance(question_payload, LearningQuestionBankPayload):
            question_payload = LearningQuestionBankPayload.model_validate(question_payload)
        questions = question_payload.questions
        question_errors = self._validate_questions(questions)
        if question_errors:
            raise LearningAgentError("Learning Assist question bank failed validation: " + "; ".join(question_errors))
        reading_payload = provider.generate_reading_material(week_spec, ledger.state, questions)
        if not isinstance(reading_payload, ReadingMaterialPayload):
            reading_payload = ReadingMaterialPayload.model_validate(reading_payload)
        reading_material = self._normalize_reading_material(reading_payload)
        reading_errors = self._validate_reading_material(reading_material)
        if reading_errors:
            raise LearningAgentError("Learning Assist reading generation failed validation: " + "; ".join(reading_errors))
        concept_payload = provider.generate_concept_cards_from_reading(week_spec, ledger.state, reading_material)
        if not isinstance(concept_payload, ConceptCardPayload):
            concept_payload = ConceptCardPayload.model_validate(concept_payload)
        concept_cards = self._normalize_concept_cards(concept_payload.concept_cards)
        concept_errors = self._validate_concept_cards(concept_cards)
        if concept_errors:
            raise LearningAgentError("Learning Assist concept-card generation failed validation: " + "; ".join(concept_errors))
        session = LearningSession(
            week=int(week_spec["number"]),
            concept_cards=concept_cards,
            reading_material=reading_material,
            questions=questions,
        )
        self.state.save_learning(session)
        self._sync_learning_progress(ledger, session)
        self.state.save_ledger(ledger)
        return session

    def answer_learning_question(self, question_id: str, answer: str):
        ledger = self.state.load_ledger()
        session = self.state.load_learning()
        question = self._question_by_id(session, question_id)
        week_spec = self._load_current_week(ledger)
        provider = self._provider()
        result = provider.score_learning_question(week_spec, question, answer, ledger.state.observation)
        session.attempts.append(QuestionAttempt(question_id=question_id, answer=answer, result=result))
        self.state.save_learning(session)
        self._sync_learning_progress(ledger, session)
        self.state.save_ledger(ledger)
        return result

    def generate_task(self):
        ledger = self.state.load_ledger()
        if not ledger.state.gates.learning_check_passed:
            raise LearningAgentError("Cannot generate a task before the learning check passes.")
        week_spec = self._load_current_week(ledger)
        provider = self._provider()
        task = provider.generate_task(week_spec, ledger.state)
        session = TaskSession(task=task)
        self.state.save_task(session)
        return session

    def sync_artifacts(self) -> Ledger:
        ledger = self.state.load_ledger()
        completed = []
        for relative_path in ledger.state.artifacts.required_files:
            if (self.target_repo_path / relative_path).exists():
                completed.append(relative_path)
        ledger.state.artifacts.completed_files = completed
        required = ledger.state.artifacts.required_files
        ledger.state.gates.implementation_complete = bool(required) and len(completed) == len(required)
        self.state.save_ledger(ledger)
        return ledger

    def record_metric(self, key: str, value: Any) -> Ledger:
        ledger = self.state.load_ledger()
        ledger.state.metrics.recorded[key] = value
        self.state.save_ledger(ledger)
        return ledger

    def record_observation(self, observation: ObservationRecord) -> Ledger:
        ledger = self.state.load_ledger()
        ledger.state.observation = observation
        if observation.latency_p95_ms is not None:
            ledger.state.metrics.recorded["latency_p95"] = observation.latency_p95_ms
        if observation.tokens_per_sec is not None:
            ledger.state.metrics.recorded["tokens_per_sec"] = observation.tokens_per_sec
        ledger.state.gates.evidence_reliable = observation.reliability == "valid"
        self.state.save_ledger(ledger)
        return ledger

    def record_reflection(self, reflection: ReflectionRecord) -> Ledger:
        ledger = self.state.load_ledger()
        ledger.state.reflection = reflection
        if reflection.buggy or reflection.trustworthy is False:
            ledger.state.gates.evidence_reliable = False
        self.state.save_ledger(ledger)
        return ledger

    def record_verification(self, passed: bool, summary: str) -> Ledger:
        ledger = self.state.load_ledger()
        if not self.state.task_path.exists():
            raise LearningAgentError("Generate a task before recording verification.")
        record = VerificationRecord(passed=passed, summary=summary)
        self.state.update_task_verification(record)
        ledger.state.verification = record
        ledger.state.gates.verification_passed = passed
        self.state.save_ledger(ledger)
        return ledger

    def approve_week(self) -> Ledger:
        ledger = self.state.load_ledger()
        blockers = self._approval_blockers(ledger)
        if blockers:
            joined = "; ".join(blockers)
            raise LearningAgentError(f"Week cannot be approved yet: {joined}.")
        ledger.state.gates.week_approved = True
        self.state.save_ledger(ledger)
        return ledger

    def advance_week(self) -> Ledger:
        ledger = self.state.load_ledger()
        if not ledger.state.gates.week_approved:
            raise LearningAgentError("Approve the current week before advancing.")
        roadmap = self._load_roadmap()
        metadata = self._curriculum_metadata(roadmap)
        next_week = self._week_by_number(roadmap, ledger.state.current_week + 1)
        ledger = Ledger(
            curriculum_metadata=metadata,
            state={
                "current_week": int(next_week["number"]),
                "active_dirs": list(next_week["active_dirs"]),
                "artifacts": {
                    "required_files": list(next_week["required_files"]),
                    "completed_files": [],
                },
                "metrics": {
                    "required": list(next_week["required_metrics"]),
                    "recorded": {},
                },
            },
        )
        self.state.save_ledger(ledger)
        self.state.clear_ephemeral_state()
        return ledger

    def get_task_session(self):
        if not self.state.task_path.exists():
            return None
        return self.state.load_task()

    def get_learning_session(self):
        if not self.state.learning_path.exists():
            return None
        return self.state.load_learning()

    def ensure_learning_assist(self):
        session = self.get_learning_session()
        if session is None:
            return self.generate_learning_assist()

        ledger = self.state.load_ledger()
        if session.week != ledger.state.current_week:
            return self.generate_learning_assist()

        return session

    def get_learning_bundle(self):
        session = self.get_learning_session()
        if session is None:
            return None
        return LearningBundle(
            week=session.week,
            concept_cards=session.concept_cards,
            reading_material=session.reading_material,
            questions=session.questions,
            attempts=session.attempts,
        )

    def answer_topic_chat(
        self,
        message: str,
        history: list[dict[str, str]] | list[TopicChatTurn],
        current_step: str,
        selected_question_id: str | None = None,
    ) -> dict[str, Any]:
        done_event: dict[str, Any] | None = None
        error_message: str | None = None
        for event in self.stream_topic_chat(
            message=message,
            history=history,
            current_step=current_step,
            selected_question_id=selected_question_id,
        ):
            event_type = str(event.get("type") or "")
            if event_type == "done":
                done_event = event
            if event_type == "error":
                error_message = str(event.get("error") or "Topic chat request failed.")

        if error_message:
            raise LearningAgentError(error_message)
        if done_event is None:
            raise LearningAgentError("Topic chat stream ended before a final reply was produced.")
        return {
            "reply": str(done_event.get("reply") or ""),
            "week": done_event.get("week"),
            "context_label": str(done_event.get("context_label") or ""),
        }

    def stream_topic_chat(
        self,
        message: str,
        history: list[dict[str, str]] | list[TopicChatTurn],
        current_step: str,
        selected_question_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        if not message.strip():
            raise LearningAgentError("Topic chat message cannot be empty.")

        ledger = self.state.load_ledger()
        week_spec = self._load_current_week(ledger)
        session = self.get_learning_session()
        step_id = current_step.strip().lower() or self._default_step_for_topic_chat(ledger, session)
        valid_steps = {"learn", "build", "verify", "approve"}
        if step_id not in valid_steps:
            raise LearningAgentError(f"Unknown workflow step: {current_step}")

        history_turns = [turn if isinstance(turn, TopicChatTurn) else TopicChatTurn.model_validate(turn) for turn in history]
        context_label, context = self._build_topic_chat_context(
            ledger=ledger,
            week_spec=week_spec,
            learning_session=session,
            current_step=step_id,
            selected_question_id=selected_question_id,
        )
        yield {
            "type": "start",
            "week": int(week_spec["number"]),
            "context_label": context_label,
        }

        raw_chunks: list[str] = []
        provider = self._provider()
        stream_method = getattr(provider, "stream_topic_chat", None)
        if callable(stream_method):
            stream = stream_method(week_spec, context, history_turns, message.strip())
        else:
            stream = iter([provider.answer_topic_chat(week_spec, context, history_turns, message.strip())])

        for chunk in stream:
            text = str(chunk or "")
            if not text:
                continue
            raw_chunks.append(text)
            yield {"type": "delta", "delta": text}

        reply = self._normalize_topic_chat_reply("".join(raw_chunks))
        yield {
            "type": "done",
            "reply": reply,
            "week": int(week_spec["number"]),
            "context_label": context_label,
        }

    def _load_roadmap(self) -> dict[str, Any]:
        return load_roadmap_dict(self.roadmap_path)

    def _curriculum_metadata(self, roadmap: dict[str, Any]) -> CurriculumMetadata:
        return CurriculumMetadata(
            title=str(roadmap["title"]),
            total_weeks=len(roadmap["weeks"]),
            target_repo=self.config.target_repo_path,
        )

    def _week_by_number(self, roadmap: dict[str, Any], week_number: int) -> dict[str, Any]:
        for week in roadmap["weeks"]:
            if int(week["number"]) == week_number:
                return week
        raise LearningAgentError(f"Week {week_number} does not exist in the roadmap.")

    def _load_current_week(self, ledger: Ledger) -> dict[str, Any]:
        roadmap = self._load_roadmap()
        return self._week_by_number(roadmap, ledger.state.current_week)

    def _provider(self):
        return get_provider(self.config)

    def _normalize_topic_chat_reply(self, reply: str) -> str:
        text = str(reply or "").strip()
        if not text:
            raise LearningAgentError("Topic chat returned an empty reply.")

        parsed = self._parse_topic_chat_json(text)
        if parsed is None:
            return text

        extracted = self._extract_topic_chat_message(parsed)
        return extracted or text

    def _parse_topic_chat_json(self, text: str) -> dict[str, Any] | list[Any] | None:
        candidates = [text]
        fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL)
        if fenced:
            candidates.insert(0, fenced.group(1).strip())

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, (dict, list)):
                return parsed
        return None

    def _extract_topic_chat_message(self, payload: dict[str, Any] | list[Any]) -> str | None:
        if isinstance(payload, dict):
            for key in ("response", "reply", "message", "content", "text", "answer"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, dict):
                    nested = self._extract_topic_chat_message(value)
                    if nested:
                        return nested
            return None
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, str) and item.strip():
                    return item.strip()
                if isinstance(item, (dict, list)):
                    nested = self._extract_topic_chat_message(item)
                    if nested:
                        return nested
        return None

    def _normalize_reading_material(self, reading_material: ReadingMaterialPayload) -> ReadingMaterialPayload:
        title = (reading_material.title or "").strip() or "Week Reading"
        body_markdown = (reading_material.body_markdown or "").strip()
        if body_markdown and not re.search(r"(?im)^##\s+How This Week Works\s*$", body_markdown):
            body_markdown = "## How This Week Works\n\n" + body_markdown
        return reading_material.model_copy(update={"title": title, "body_markdown": body_markdown})

    def _normalize_concept_cards(
        self,
        concept_cards: list[ConceptCard],
    ) -> list[ConceptCard]:
        normalized_cards: list[ConceptCard] = []
        used_ids: set[str] = set()
        for index, card in enumerate(concept_cards, start=1):
            title = card.title.strip() or self._humanize_label(card.concept)
            concept = card.concept.strip() or self._slugify(title).replace("-", "_")
            card_id = card.id.strip() or self._slugify(concept or title or f"concept-{index}")
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

    def _humanize_label(self, value: str) -> str:
        return " ".join(part.capitalize() for part in value.replace("-", "_").split("_") if part)

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "content"

    def _default_step_for_topic_chat(self, ledger: Ledger, learning_session: LearningSession | None) -> str:
        if learning_session is None or not self._required_questions_passed(learning_session):
            return "learn"
        if not ledger.state.gates.implementation_complete:
            return "build"
        if not ledger.state.gates.verification_passed or (
            self._requires_evidence(ledger) and not ledger.state.gates.evidence_reliable
        ):
            return "verify"
        return "approve"

    def _build_topic_chat_context(
        self,
        ledger: Ledger,
        week_spec: dict[str, Any],
        learning_session: LearningSession | None,
        current_step: str,
        selected_question_id: str | None,
    ) -> tuple[str, str]:
        blockers = self._approval_blockers(ledger)
        progress = self._question_progress(learning_session)
        lines = [
            f"Step: {current_step}",
            f"Week title: {week_spec['short_title']}",
            f"Week goal: {week_spec['goal']}",
            "Active directories: " + (", ".join(week_spec["active_dirs"]) or "(none)"),
            "Required files: " + (", ".join(week_spec["required_files"]) or "(none)"),
            "Required metrics: " + (", ".join(week_spec["required_metrics"]) or "(none)"),
            "Completed files: " + (", ".join(ledger.state.artifacts.completed_files) or "(none)"),
            "Recorded metrics: "
            + (json.dumps(ledger.state.metrics.recorded, sort_keys=True) if ledger.state.metrics.recorded else "(none)"),
            "Approval blockers: " + (", ".join(blockers) or "(none)"),
            (
                "Learning progress: "
                f"{progress['required_passed']}/{progress['required_total']} baseline questions passed"
            ),
        ]

        context_label = f"Week {week_spec['number']} · {self._humanize_label(current_step)}"
        if selected_question_id and current_step == "learn":
            lines.append(
                "Selected question context is available in the UI but is intentionally not injected into chat grounding by default."
            )

        if learning_session is not None:
            lines.append(
                "Available concept cards: "
                + (", ".join(card.title or card.concept for card in learning_session.concept_cards[:8]) or "(none)")
            )
            if learning_session.reading_material is not None:
                lines.append(f"Reading title: {learning_session.reading_material.title}")

        if ledger.state.observation is not None:
            observation = ledger.state.observation
            lines.append(f"Latest observation command: {observation.command}")
            lines.append(f"Latest observation artifact: {observation.artifact_path}")
            lines.append(f"Latest observation reliability: {observation.reliability}")

        if ledger.state.verification is not None:
            verification = ledger.state.verification
            lines.append(f"Latest verification status: {'passed' if verification.passed else 'failed'}")
            lines.append(f"Latest verification summary: {verification.summary}")

        if ledger.state.reflection is not None:
            lines.append(f"Latest reflection: {ledger.state.reflection.text}")

        return context_label, "\n".join(lines)

    def _approval_blockers(self, ledger: Ledger) -> list[str]:
        blockers = []
        if not ledger.state.gates.learning_check_passed:
            blockers.append("learning check not passed")
        if not ledger.state.gates.implementation_complete:
            blockers.append("required files are incomplete")
        if not ledger.state.gates.verification_passed:
            blockers.append("verification has not passed")
        missing_metrics = [
            metric for metric in ledger.state.metrics.required if metric not in ledger.state.metrics.recorded
        ]
        if missing_metrics:
            blockers.append(f"missing metrics: {', '.join(missing_metrics)}")
        if self._requires_evidence(ledger):
            if ledger.state.observation is None:
                blockers.append("structured observation has not been recorded")
            if not ledger.state.gates.evidence_reliable:
                blockers.append("evidence is not reliable yet")
            if ledger.state.reflection is None:
                blockers.append("reflection has not been recorded")
        return blockers

    def _sync_learning_progress(self, ledger: Ledger, session: LearningSession) -> None:
        if self._required_question_ids(session) and self._required_questions_passed(session):
            ledger.state.gates.learning_check_passed = True

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

    def _validate_concept_cards(
        self,
        concept_cards: list[ConceptCard],
    ) -> list[str]:
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

    def _required_question_ids(self, session: LearningSession) -> list[str]:
        return [
            question.id
            for question in session.questions
            if question.depth == "baseline"
        ]

    def _question_progress(self, session: LearningSession | None) -> dict[str, Any]:
        if session is None:
            return {
                "required_total": 0,
                "required_passed": 0,
                "required_pending": 0,
            }
        latest_attempts = self._latest_attempts(session)
        required_ids = self._required_question_ids(session)
        required_passed = sum(1 for question_id in required_ids if latest_attempts.get(question_id, None) and latest_attempts[question_id].result.passed)
        return {
            "required_total": len(required_ids),
            "required_passed": required_passed,
            "required_pending": max(len(required_ids) - required_passed, 0),
        }

    def _required_questions_passed(self, session: LearningSession) -> bool:
        required_ids = self._required_question_ids(session)
        if not required_ids:
            return False
        latest_attempts = self._latest_attempts(session)
        return all(
            question_id in latest_attempts and latest_attempts[question_id].result.passed for question_id in required_ids
        )

    def _latest_attempts(self, session: LearningSession) -> dict[str, QuestionAttempt]:
        attempts: dict[str, QuestionAttempt] = {}
        for attempt in session.attempts:
            attempts[attempt.question_id] = attempt
        return attempts

    def _question_by_id(self, session: LearningSession, question_id: str) -> LearningQuestion:
        for question in session.questions:
            if question.id == question_id:
                return question
        raise LearningAgentError(f"Question `{question_id}` does not exist in the current learning session.")

    def _requires_evidence(self, ledger: Ledger) -> bool:
        return bool(ledger.state.metrics.required)

    def _build_checkpoints(self, ledger: Ledger, learning_session: LearningSession | None) -> list[CheckpointState]:
        checkpoints = [self._build_learning_checkpoint(ledger, learning_session), self._build_implementation_checkpoint(ledger)]
        if self._requires_evidence(ledger):
            checkpoints.append(self._build_evidence_checkpoint(ledger, learning_session))
        return checkpoints

    def _build_learning_checkpoint(self, ledger: Ledger, learning_session: LearningSession | None) -> CheckpointState:
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

        progress = self._question_progress(learning_session)
        latest_attempts = self._latest_attempts(learning_session)
        required_ids = set(self._required_question_ids(learning_session))
        attempted_required = [question_id for question_id in required_ids if question_id in latest_attempts]
        status = "not_started"
        if self._required_questions_passed(learning_session):
            status = "passed"
        elif attempted_required and any(not latest_attempts[question_id].result.passed for question_id in attempted_required):
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

    def _build_implementation_checkpoint(self, ledger: Ledger) -> CheckpointState:
        if ledger.state.gates.implementation_complete and ledger.state.gates.verification_passed:
            return CheckpointState(
                id="implementation",
                title="Implementation",
                description="Complete the required files and verification checks for the active week.",
                status="passed",
                reason="Required files are present and verification passed.",
            )
        if ledger.state.verification is not None and not ledger.state.gates.verification_passed:
            return CheckpointState(
                id="implementation",
                title="Implementation",
                description="Complete the required files and verification checks for the active week.",
                status="failed",
                reason="Verification was recorded as failed.",
            )
        if self.state.task_path.exists() or ledger.state.artifacts.completed_files:
            return CheckpointState(
                id="implementation",
                title="Implementation",
                description="Complete the required files and verification checks for the active week.",
                status="in_progress",
                reason=f"{len(ledger.state.artifacts.completed_files)}/{len(ledger.state.artifacts.required_files)} required files present.",
            )
        return CheckpointState(
            id="implementation",
            title="Implementation",
            description="Complete the required files and verification checks for the active week.",
            status="not_started",
            reason="Generate the task and start building the required artifacts.",
        )

    def _build_evidence_checkpoint(
        self, ledger: Ledger, learning_session: LearningSession | None
    ) -> CheckpointState:
        if ledger.state.observation is None and ledger.state.reflection is None:
            return CheckpointState(
                id="evidence_reliability",
                title="Evidence Reliability",
                description="Record a structured observation and capture a reflection.",
                status="not_started",
                reason="Observation and reflection are still missing.",
            )
        if ledger.state.observation is not None and ledger.state.observation.reliability != "valid":
            return CheckpointState(
                id="evidence_reliability",
                title="Evidence Reliability",
                description="Record a structured observation and capture a reflection.",
                status="failed",
                reason=f"Observation marked as {ledger.state.observation.reliability}.",
            )
        if ledger.state.reflection is not None and (
            ledger.state.reflection.buggy or ledger.state.reflection.trustworthy is False
        ):
            return CheckpointState(
                id="evidence_reliability",
                title="Evidence Reliability",
                description="Record a structured observation and capture a reflection.",
                status="failed",
                reason="Reflection reports unreliable or buggy evidence.",
            )
        if ledger.state.gates.evidence_reliable and ledger.state.reflection is not None:
            reason = "Reliable observation recorded and reflection captured."
            return CheckpointState(
                id="evidence_reliability",
                title="Evidence Reliability",
                description="Record a structured observation and capture a reflection.",
                status="passed",
                reason=reason,
            )
        return CheckpointState(
            id="evidence_reliability",
            title="Evidence Reliability",
            description="Record a structured observation and capture a reflection.",
            status="in_progress",
            reason="Evidence is partially recorded but not fully trusted yet.",
        )

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Dict

from learning_agent.config import resolve_repo_path
from learning_agent.curriculum import get_week_spec, load_curriculum
from learning_agent.errors import LearningAgentError
from learning_agent.models import (
    AppConfig,
    ClassifiedQuestionBankPayload,
    CheckpointState,
    ConceptCardPayload,
    ConceptCard,
    EvidenceQuestionPayload,
    FigureAsset,
    GateSession,
    Ledger,
    LearningBundle,
    LearningQuestion,
    LearningSession,
    ObservationRecord,
    QuestionAttempt,
    RawQuestionBankPayload,
    RawLearningQuestion,
    ReadingMaterialPayload,
    ReadingSection,
    ReflectionRecord,
    TaskSession,
    TopicChatTurn,
    VerificationRecord,
    WeekSpec,
)
from learning_agent.providers.factory import get_provider
from learning_agent.state import StateStore


class LearningController:
    def __init__(self, repo_root: Path, config: AppConfig):
        self.repo_root = repo_root
        self.config = config
        self.state = StateStore(repo_root, config)
        self.roadmap_path = resolve_repo_path(repo_root, config.roadmap_path)
        self.target_repo_path = resolve_repo_path(repo_root, config.target_repo_path)

    def initialize(self) -> Ledger:
        metadata, weeks = load_curriculum(self.roadmap_path, self.config.target_repo_path)
        week_one = get_week_spec(weeks, 1)
        return self.state.initialize_ledger(metadata, week_one)

    def status(self) -> Dict[str, Any]:
        ledger = self.state.load_ledger()
        week_spec = self._load_current_week_spec(ledger)
        blockers = self._approval_blockers(ledger)
        gate_exists = self.state.gate_path.exists()
        task_exists = self.state.task_path.exists()
        learning_exists = self.state.learning_path.exists()
        gate_session = self.get_gate_session()
        task_session = self.get_task_session()
        learning_session = self.get_learning_session()
        checkpoints = self._build_checkpoints(ledger, learning_session)
        return {
            "week": week_spec.number,
            "total_weeks": ledger.curriculum_metadata.total_weeks,
            "title": week_spec.title,
            "goal": week_spec.goal,
            "active_dirs": ledger.state.active_functional_dirs,
            "learning_assist_enabled": ledger.state.learning_assist_enabled,
            "required_files": ledger.state.artifacts.required_files,
            "completed_files": ledger.state.artifacts.completed_files,
            "required_metrics": ledger.state.metrics.required,
            "recorded_metrics": ledger.state.metrics.recorded,
            "gates": ledger.state.gates.model_dump(mode="json"),
            "gate_asked": gate_exists,
            "task_generated": task_exists,
            "learning_generated": learning_exists,
            "verification": ledger.state.verification.model_dump(mode="json") if ledger.state.verification else None,
            "observation": ledger.state.observation.model_dump(mode="json") if ledger.state.observation else None,
            "reflection": ledger.state.reflection.model_dump(mode="json") if ledger.state.reflection else None,
            "evidence_required": self._requires_evidence(ledger),
            "checkpoints": [checkpoint.model_dump(mode="json") for checkpoint in checkpoints],
            "question_progress": self._question_progress(learning_session),
            "can_generate_task": ledger.state.gates.socratic_check_passed,
            "can_approve": not blockers,
            "approval_blockers": blockers,
            "gate_session": gate_session.model_dump(mode="json") if gate_session else None,
            "task_session": task_session.model_dump(mode="json") if task_session else None,
            "learning_session": learning_session.model_dump(mode="json") if learning_session else None,
        }

    def ask_gate(self):
        ledger = self.state.load_ledger()
        week_spec = self._load_current_week_spec(ledger)
        provider = self._provider()
        question = provider.generate_gate_question(week_spec)
        session = GateSession(prompt=question)
        self.state.save_gate(session)
        return session

    def submit_gate(self, answer: str):
        ledger = self.state.load_ledger()
        week_spec = self._load_current_week_spec(ledger)
        gate_session = self.state.load_gate()
        provider = self._provider()
        result = provider.score_gate_answer(week_spec, gate_session.prompt, answer)
        gate_session.last_answer = answer
        gate_session.result = result
        self.state.save_gate(gate_session)
        ledger.state.gates.socratic_check_passed = result.passed
        self.state.save_ledger(ledger)
        return result

    def set_learning_assist_enabled(self, enabled: bool) -> Ledger:
        ledger = self.state.load_ledger()
        ledger.state.learning_assist_enabled = enabled
        self.state.save_ledger(ledger)
        return ledger

    def generate_learning_assist(self) -> LearningSession:
        ledger = self.state.load_ledger()
        week_spec = self._load_current_week_spec(ledger)
        provider = self._provider()
        raw_payload = provider.generate_raw_question_bank(week_spec, ledger.state)
        if not isinstance(raw_payload, RawQuestionBankPayload):
            raw_payload = RawQuestionBankPayload.model_validate(raw_payload)
        raw_questions = self._dedupe_raw_questions(raw_payload.questions)
        raw_errors = self._validate_raw_questions(raw_questions)
        if raw_errors:
            raise LearningAgentError("Learning Assist raw question bank failed validation: " + "; ".join(raw_errors))
        classified_payload = provider.classify_question_bank(week_spec, ledger.state, raw_questions)
        if not isinstance(classified_payload, ClassifiedQuestionBankPayload):
            classified_payload = ClassifiedQuestionBankPayload.model_validate(classified_payload)
        question_errors = self._validate_classified_questions(classified_payload.questions, expected_count=len(raw_questions))
        if question_errors:
            raise LearningAgentError(
                "Learning Assist classified question bank failed validation: " + "; ".join(question_errors)
            )
        reading_payload = provider.generate_reading_material(week_spec, ledger.state, classified_payload.questions)
        if not isinstance(reading_payload, ReadingMaterialPayload):
            reading_payload = ReadingMaterialPayload.model_validate(reading_payload)
        reading_sections = self._normalize_reading_sections(classified_payload.questions, reading_payload.reading_sections)
        reading_errors = self._validate_reading_sections(week_spec, classified_payload.questions, reading_sections)
        if reading_errors:
            raise LearningAgentError("Learning Assist reading generation failed validation: " + "; ".join(reading_errors))
        concept_payload = provider.generate_concept_cards_from_reading(week_spec, ledger.state, reading_sections)
        if not isinstance(concept_payload, ConceptCardPayload):
            concept_payload = ConceptCardPayload.model_validate(concept_payload)
        concept_cards = self._normalize_concept_cards(reading_sections, concept_payload.concept_cards)
        concept_errors = self._validate_concept_cards(reading_sections, concept_cards)
        if concept_errors:
            raise LearningAgentError("Learning Assist concept-card generation failed validation: " + "; ".join(concept_errors))
        reading_sections = self._link_reading_sections_to_concepts(reading_sections, concept_cards)
        figures = self._build_figure_assets(week_spec, concept_cards, classified_payload.questions)
        concept_cards = self._decorate_concept_cards(concept_cards)
        questions = self._link_questions_to_content(classified_payload.questions, concept_cards, reading_sections)
        session = LearningSession(
            week=week_spec.number,
            concept_cards=concept_cards,
            figures=figures,
            reading_sections=reading_sections,
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
        if question.observation_required and not self._observation_ready_for_questions(ledger):
            raise LearningAgentError("This question requires a valid observation before it can be answered.")
        week_spec = self._load_current_week_spec(ledger)
        provider = self._provider()
        result = provider.score_learning_question(week_spec, question, answer, ledger.state.observation)
        session.attempts.append(QuestionAttempt(question_id=question_id, answer=answer, result=result))
        self.state.save_learning(session)
        self._sync_learning_progress(ledger, session)
        self.state.save_ledger(ledger)
        return result

    def generate_task(self):
        ledger = self.state.load_ledger()
        if not ledger.state.gates.socratic_check_passed:
            raise LearningAgentError("Cannot generate a task before the concept gate passes.")
        week_spec = self._load_current_week_spec(ledger)
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
        if self.state.learning_path.exists() and observation.reliability == "valid":
            session = self.state.load_learning()
            if not any(question.type == "evidence_based" for question in session.questions):
                week_spec = self._load_current_week_spec(ledger)
                provider = self._provider()
                payload = provider.generate_evidence_questions(week_spec, observation, session)
                if not isinstance(payload, EvidenceQuestionPayload):
                    payload = EvidenceQuestionPayload.model_validate(payload)
                session.questions.extend(
                    self._link_questions_to_content(payload.questions, session.concept_cards, session.reading_sections)
                )
                self.state.save_learning(session)
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
        metadata, weeks = load_curriculum(self.roadmap_path, self.config.target_repo_path)
        next_week = get_week_spec(weeks, ledger.state.current_week + 1)
        ledger = Ledger(
            curriculum_metadata=metadata,
            state={
                "current_week": next_week.number,
                "active_functional_dirs": next_week.active_dirs,
                "learning_assist_enabled": ledger.state.learning_assist_enabled,
                "artifacts": {
                    "required_files": next_week.required_files,
                    "completed_files": [],
                },
                "metrics": {
                    "required": next_week.required_metrics,
                    "recorded": {},
                },
            },
        )
        self.state.save_ledger(ledger)
        self.state.clear_ephemeral_state()
        return ledger

    def get_gate_session(self):
        if not self.state.gate_path.exists():
            return None
        return self.state.load_gate()

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
            figures=session.figures,
            reading_sections=session.reading_sections,
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
        week_spec = self._load_current_week_spec(ledger)
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
            "week": week_spec.number,
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
            "week": week_spec.number,
            "context_label": context_label,
        }

    def _load_current_week_spec(self, ledger: Ledger) -> WeekSpec:
        _, weeks = load_curriculum(self.roadmap_path, self.config.target_repo_path)
        return get_week_spec(weeks, ledger.state.current_week)

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

    def _decorate_concept_cards(self, cards: list) -> list:
        decorated = []
        for index, card in enumerate(cards, start=1):
            title = card.title.strip() or self._humanize_label(card.concept)
            card_id = card.id.strip() or self._slugify(card.concept or title or f"concept-{index}")
            image_key = self._image_key_for_text(f"{card.concept} {card.explanation} {card.why_it_matters}")
            decorated.append(
                card.model_copy(
                    update={
                        "id": card_id,
                        "title": title,
                        "image_path": self._image_path_for_key(image_key),
                        "image_alt": self._figure_asset_for_key(image_key).alt_text,
                    }
                )
            )
        return decorated

    def _build_figure_assets(
        self,
        week_spec: WeekSpec,
        concept_cards: list,
        questions: list[LearningQuestion],
    ) -> list[FigureAsset]:
        figure_keys: list[str] = []
        for card in concept_cards:
            key = self._key_from_image_path(card.image_path)
            if key:
                self._append_if_missing(figure_keys, key)

        combined_text = " ".join(question.prompt_text for question in questions).lower()
        if "server.py" in " ".join(week_spec.required_files) or "api" in combined_text:
            self._append_if_missing(figure_keys, "server_architecture")
        if any(keyword in combined_text for keyword in ("benchmark", "latency", "throughput", "tokens per second", "tps")):
            self._append_if_missing(figure_keys, "benchmark_flow")
            self._append_if_missing(figure_keys, "latency_throughput")

        return [self._figure_asset_for_key(key) for key in figure_keys]

    def _normalize_reading_sections(
        self,
        questions: list[LearningQuestion],
        reading_sections: list[ReadingSection],
    ) -> list[ReadingSection]:
        if not reading_sections:
            return []

        known_question_ids = {question.id for question in questions}
        normalized_sections: list[ReadingSection] = []
        used_ids: set[str] = set()
        for index, section in enumerate(reading_sections, start=1):
            raw_id = (section.id or "").strip() or (section.title or "").strip() or f"reading-{index}"
            section_id = re.sub(r"[^a-z0-9_]+", "-", raw_id.lower()).strip("-") or f"reading_{index}"
            if section_id in used_ids:
                suffix = 2
                while f"{section_id}-{suffix}" in used_ids:
                    suffix += 1
                section_id = f"{section_id}-{suffix}"
            used_ids.add(section_id)
            title = (section.title or "").strip() or self._humanize_label(section_id)
            normalized_sections.append(
                section.model_copy(
                    update={
                        "id": section_id,
                        "title": title,
                        "body_markdown": section.body_markdown.strip(),
                        "figure_ids": [],
                        "related_concept_ids": [],
                    }
                )
            )

        week_map_index = next(
            (
                index
                for index, section in enumerate(normalized_sections)
                if section.id == "week_map" or section.title.strip().lower() == "how this week works"
            ),
            None,
        )
        if week_map_index is not None and week_map_index != 0:
            week_map = normalized_sections.pop(week_map_index)
            week_map = week_map.model_copy(update={"id": "week_map", "title": "How This Week Works"})
            normalized_sections.insert(0, week_map)
        elif week_map_index == 0:
            normalized_sections[0] = normalized_sections[0].model_copy(update={"id": "week_map", "title": "How This Week Works"})

        return normalized_sections

    def _normalize_concept_cards(
        self,
        reading_sections: list[ReadingSection],
        concept_cards: list[ConceptCard],
    ) -> list[ConceptCard]:
        known_section_ids = {section.id for section in reading_sections}
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
            related_section_ids = [section_id for section_id in card.related_section_ids if section_id in known_section_ids]
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
                        "related_section_ids": related_section_ids,
                    }
                )
            )
        return normalized_cards

    def _link_reading_sections_to_concepts(
        self,
        sections: list[ReadingSection],
        concept_cards: list,
    ) -> list[ReadingSection]:
        linked_sections: list[ReadingSection] = []
        for section in sections:
            related_concept_ids = [
                card.id
                for card in concept_cards
                if section.id in getattr(card, "related_section_ids", [])
            ]
            linked_sections.append(section.model_copy(update={"related_concept_ids": related_concept_ids}))
        return linked_sections

    def _link_questions_to_content(
        self,
        questions: list[LearningQuestion],
        concept_cards: list,
        reading_sections: list[ReadingSection],
    ) -> list[LearningQuestion]:
        linked_questions: list[LearningQuestion] = []
        for question in questions:
            related_concept_ids = self._best_concept_ids_for_question(question, concept_cards)

            linked_questions.append(
                question.model_copy(
                    update={
                        "related_concept_ids": related_concept_ids,
                    }
                )
            )
        return linked_questions

    def _figure_asset_for_key(self, key: str) -> FigureAsset:
        library = {
            "prefill_decode": FigureAsset(
                id="prefill_decode",
                title="Prefill vs Decode",
                image_path="/assets/illustrations/prefill-decode.svg",
                alt_text="Diagram comparing prompt prefill with stepwise decode generation.",
                caption="Prefill processes the whole prompt together; decode emits one token at a time.",
            ),
            "latency_throughput": FigureAsset(
                id="latency_throughput",
                title="Latency vs Throughput",
                image_path="/assets/illustrations/latency-throughput.svg",
                alt_text="Curve showing latency rising as throughput approaches saturation.",
                caption="The knee of the curve is where throughput gains begin to cost too much latency.",
            ),
            "server_architecture": FigureAsset(
                id="server_architecture",
                title="Inference Server Architecture",
                image_path="/assets/illustrations/server-architecture.svg",
                alt_text="Request flow from API entry through queue, model runtime, and metrics.",
                caption="Week 1 is about understanding the path from HTTP request to generated output and measurement.",
            ),
            "benchmark_flow": FigureAsset(
                id="benchmark_flow",
                title="Benchmark Flow",
                image_path="/assets/illustrations/benchmark-flow.svg",
                alt_text="Loop showing prompts, timed requests, metrics calculation, and result logging.",
                caption="A clean benchmark loop separates generation, timing, and evidence capture.",
            ),
        }
        return library[key]

    def _image_key_for_text(self, text: str) -> str:
        lower = text.lower()
        if "prefill" in lower or "decode" in lower:
            return "prefill_decode"
        if "latency" in lower or "throughput" in lower or "tokens per second" in lower or "tps" in lower:
            return "latency_throughput"
        if "benchmark" in lower or "metric" in lower:
            return "benchmark_flow"
        return "server_architecture"

    def _image_path_for_key(self, key: str) -> str:
        return self._figure_asset_for_key(key).image_path

    def _key_from_image_path(self, image_path: str | None) -> str | None:
        if not image_path:
            return None
        return Path(image_path).stem.replace("-", "_")

    def _humanize_label(self, value: str) -> str:
        return " ".join(part.capitalize() for part in value.replace("-", "_").split("_") if part)

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "content"

    def _append_if_missing(self, items: list[str], value: str) -> None:
        if value not in items:
            items.append(value)

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
        week_spec: WeekSpec,
        learning_session: LearningSession | None,
        current_step: str,
        selected_question_id: str | None,
    ) -> tuple[str, str]:
        blockers = self._approval_blockers(ledger)
        progress = self._question_progress(learning_session)
        lines = [
            f"Step: {current_step}",
            f"Week title: {week_spec.title}",
            f"Week goal: {week_spec.goal}",
            "Active directories: " + (", ".join(week_spec.active_dirs) or "(none)"),
            "Required files: " + (", ".join(week_spec.required_files) or "(none)"),
            "Required metrics: " + (", ".join(week_spec.required_metrics) or "(none)"),
            "Completed files: " + (", ".join(ledger.state.artifacts.completed_files) or "(none)"),
            "Recorded metrics: "
            + (json.dumps(ledger.state.metrics.recorded, sort_keys=True) if ledger.state.metrics.recorded else "(none)"),
            "Approval blockers: " + (", ".join(blockers) or "(none)"),
            (
                "Learning progress: "
                f"{progress['required_passed']}/{progress['required_total']} baseline questions passed; "
                f"{progress['evidence_answered']}/{progress['evidence_total']} evidence questions answered"
            ),
        ]

        context_label = f"Week {week_spec.number} · {self._humanize_label(current_step)}"
        if selected_question_id and current_step == "learn":
            lines.append(
                "Selected question context is available in the UI but is intentionally not injected into chat grounding by default."
            )

        if learning_session is not None:
            lines.append(
                "Available concept cards: "
                + (", ".join(card.title or card.concept for card in learning_session.concept_cards[:8]) or "(none)")
            )
            lines.append(
                "Reading sections: "
                + (", ".join(section.title for section in learning_session.reading_sections[:8]) or "(none)")
            )

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

    def _match_tokens(self, text: str) -> set[str]:
        tokens = {token for token in re.split(r"[^a-z0-9]+", text.lower()) if len(token) >= 4}
        if "tps" in text.lower():
            tokens.add("tokens")
        return tokens

    def _approval_blockers(self, ledger: Ledger) -> list[str]:
        blockers = []
        if not ledger.state.gates.socratic_check_passed:
            blockers.append("concept gate not passed")
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
            ledger.state.gates.socratic_check_passed = True

    def _dedupe_raw_questions(self, questions: list[RawLearningQuestion]) -> list[RawLearningQuestion]:
        deduped: list[RawLearningQuestion] = []
        seen: set[str] = set()
        for question in questions:
            normalized = " ".join(question.prompt_text.lower().split())
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(question)
        return deduped

    def _validate_raw_questions(self, questions: list[RawLearningQuestion]) -> list[str]:
        errors: list[str] = []
        if len(questions) < 50:
            errors.append(f"expected at least 50 deduped raw questions but received {len(questions)}")

        tier_counts = {
            "foundational_concepts": 0,
            "implementation_knowledge": 0,
            "optimization_and_production_insights": 0,
        }
        for question in questions:
            if not question.prompt_text.strip():
                errors.append("raw question bank contains an empty question prompt")
            tier_counts[question.tier] = tier_counts.get(question.tier, 0) + 1
            prompt_lower = question.prompt_text.lower()
            if "week 2" in prompt_lower or "week 3" in prompt_lower or "next week" in prompt_lower:
                errors.append(f"raw question appears to leak future scope: {question.prompt_text}")

        if tier_counts["foundational_concepts"] < 18:
            errors.append(
                "raw question bank does not contain enough foundational questions after dedupe"
            )
        if tier_counts["implementation_knowledge"] < 20:
            errors.append(
                "raw question bank does not contain enough implementation questions after dedupe"
            )
        if tier_counts["optimization_and_production_insights"] < 12:
            errors.append(
                "raw question bank does not contain enough optimization questions after dedupe"
            )
        return errors

    def _validate_classified_questions(
        self, questions: list[LearningQuestion], expected_count: int
    ) -> list[str]:
        errors: list[str] = []
        if len(questions) != expected_count:
            errors.append(
                f"classified question count {len(questions)} does not match deduped raw question count {expected_count}"
            )
        if len(questions) < 50:
            errors.append(f"expected at least 50 classified questions but received {len(questions)}")

        ids = [question.id for question in questions]
        if len(set(ids)) != len(ids):
            errors.append("classified question ids must be unique")

        evidence_questions = [question.id for question in questions if question.type == "evidence_based"]
        if evidence_questions:
            errors.append("initial classified question bank must not include evidence-based questions")

        observation_required = [question.id for question in questions if question.observation_required]
        if observation_required:
            errors.append("initial classified question bank must set observation_required=false for all questions")

        tier1 = [
            question
            for question in questions
            if question.type == "concept" and question.scope == "core" and question.depth in {"baseline", "deep"}
        ]
        tier2 = [
            question
            for question in questions
            if question.type == "implementation"
            and question.scope == "core"
            and question.depth in {"baseline", "deep"}
        ]
        tier3 = [
            question
            for question in questions
            if question.scope == "adjacent" and question.depth in {"deep", "stretch"}
        ]
        if len(tier1) < 18:
            errors.append(f"expected at least 18 classified Tier 1 questions but received {len(tier1)}")
        if len(tier2) < 20:
            errors.append(f"expected at least 20 classified Tier 2 questions but received {len(tier2)}")
        if len(tier3) < 12:
            errors.append(f"expected at least 12 classified Tier 3 questions but received {len(tier3)}")

        return errors

    def _validate_reading_sections(
        self,
        week_spec: WeekSpec,
        questions: list[LearningQuestion],
        reading_sections: list[ReadingSection],
    ) -> list[str]:
        errors: list[str] = []
        if len(reading_sections) < 3:
            errors.append(f"expected at least 3 reading blocks but received {len(reading_sections)}")
        if not reading_sections:
            return errors

        if reading_sections[0].id != "week_map":
            errors.append("the first reading block must be week_map")
        if reading_sections[0].title.strip() != "How This Week Works":
            errors.append("the first reading block title must be 'How This Week Works'")

        banned_patterns = [
            r"\bchapter\b",
            r"\bsection\b",
            r"\bconcept cards?\b",
            r"\bquestion bank\b",
            r"\brubric\b",
            r"\bui\b",
        ]

        total_word_count = 0
        for reading_section in reading_sections:
            text = " ".join(part for part in (reading_section.title, reading_section.body_markdown) if part).strip()
            total_word_count += len(reading_section.body_markdown.split())
            if not reading_section.title.strip():
                errors.append(f"reading block {reading_section.id!r} has an empty title")
            if len(reading_section.body_markdown.split()) < 35:
                errors.append(f"reading block {reading_section.id!r} is too thin to teach from")
            for pattern in banned_patterns:
                if re.search(pattern, text, flags=re.IGNORECASE):
                    errors.append(f"reading block {reading_section.id!r} uses internal product language: {pattern}")
                    break

        if total_word_count < 220:
            errors.append("reading material is too short to support the current week's question set")

        return errors

    def _validate_concept_cards(
        self,
        reading_sections: list[ReadingSection],
        concept_cards: list[ConceptCard],
    ) -> list[str]:
        errors: list[str] = []
        if len(concept_cards) < 3:
            errors.append(f"expected at least 3 concept cards but received {len(concept_cards)}")
        if not concept_cards:
            return errors

        known_section_ids = {section.id for section in reading_sections}
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

        linked_section_ids: set[str] = set()
        for card in concept_cards:
            if not card.title.strip():
                errors.append(f"concept card {card.id!r} has an empty title")
            if not card.explanation.strip():
                errors.append(f"concept card {card.id!r} has an empty explanation")
            if not card.why_it_matters.strip():
                errors.append(f"concept card {card.id!r} has an empty why_it_matters")
            if not card.common_mistake.strip():
                errors.append(f"concept card {card.id!r} has an empty common_mistake")
            if not card.related_section_ids:
                errors.append(f"concept card {card.id!r} is not linked to any reading blocks")
            invalid_section_ids = [section_id for section_id in card.related_section_ids if section_id not in known_section_ids]
            if invalid_section_ids:
                errors.append(
                    f"concept card {card.id!r} references unknown reading blocks: {', '.join(sorted(invalid_section_ids))}"
                )
            linked_section_ids.update(section_id for section_id in card.related_section_ids if section_id in known_section_ids)
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

        if linked_section_ids != known_section_ids:
            missing_links = sorted(known_section_ids - linked_section_ids)
            if missing_links:
                errors.append("concept cards do not cover all reading blocks: " + ", ".join(missing_links))

        return errors

    def _best_reading_section_id_for_question(
        self,
        question: LearningQuestion,
        reading_sections: list[ReadingSection],
    ) -> str:
        best_section_id = reading_sections[0].id
        best_score = -1
        for reading_section in reading_sections:
            score = self._reading_section_match_score(question, reading_section)
            if score > best_score:
                best_score = score
                best_section_id = reading_section.id
        return best_section_id

    def _reading_section_match_score(self, question: LearningQuestion, reading_section: ReadingSection) -> int:
        question_tokens = self._match_tokens(question.prompt_text)
        section_text = f"{reading_section.title} {reading_section.body_markdown}".lower()
        section_tokens = self._match_tokens(section_text)
        score = len(question_tokens & section_tokens)
        if question.type == "implementation" and any(
            token in section_text for token in ("file", "build", "implement", "artifact", "deliverable", "code")
        ):
            score += 3
        if any(token in question.prompt_text.lower() for token in ("latency", "throughput", "benchmark", "tokens per second", "tps", "measure", "verify")):
            if any(token in section_text for token in ("latency", "throughput", "benchmark", "metric", "measure", "verify", "tokens per second", "tps")):
                score += 3
        if any(token in question.prompt_text.lower() for token in ("prefill", "decode", "token", "generation", "cache")):
            if any(token in section_text for token in ("prefill", "decode", "token", "generation", "cache")):
                score += 3
        if any(token in question.prompt_text.lower() for token in ("request", "response", "api", "server", "pipeline", "inference", "serving")):
            if any(token in section_text for token in ("request", "response", "api", "server", "pipeline", "inference", "serving")):
                score += 3
        return score

    def _best_concept_ids_for_question(self, question: LearningQuestion, concept_cards: list[ConceptCard]) -> list[str]:
        ranked_cards: list[tuple[int, str]] = []
        question_tokens = self._match_tokens(question.prompt_text)
        anchor_tokens = self._match_tokens(json.dumps(question.roadmap_anchor, sort_keys=True))
        for card in concept_cards:
            card_text = " ".join(
                part
                for part in (
                    card.id,
                    card.concept,
                    card.title,
                    card.explanation,
                    card.why_it_matters,
                    card.common_mistake,
                    card.quick_check_question or "",
                )
                if part
            )
            card_tokens = self._match_tokens(card_text)
            score = len(question_tokens & card_tokens) + len(anchor_tokens & card_tokens)
            if score > 0:
                ranked_cards.append((score, card.id))
        ranked_cards.sort(key=lambda item: (-item[0], item[1]))
        if ranked_cards:
            return [card_id for _score, card_id in ranked_cards[:3]]
        return [card.id for card in concept_cards[:2]]

    def _required_question_ids(self, session: LearningSession) -> list[str]:
        return [
            question.id
            for question in session.questions
            if question.scope == "core" and question.depth == "baseline" and not question.observation_required
        ]

    def _question_progress(self, session: LearningSession | None) -> dict[str, Any]:
        if session is None:
            return {
                "required_total": 0,
                "required_passed": 0,
                "required_pending": 0,
                "evidence_total": 0,
                "evidence_answered": 0,
            }
        latest_attempts = self._latest_attempts(session)
        required_ids = self._required_question_ids(session)
        required_passed = sum(1 for question_id in required_ids if latest_attempts.get(question_id, None) and latest_attempts[question_id].result.passed)
        evidence_ids = [question.id for question in session.questions if question.type == "evidence_based"]
        evidence_answered = sum(1 for question_id in evidence_ids if question_id in latest_attempts)
        return {
            "required_total": len(required_ids),
            "required_passed": required_passed,
            "required_pending": max(len(required_ids) - required_passed, 0),
            "evidence_total": len(evidence_ids),
            "evidence_answered": evidence_answered,
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

    def _observation_ready_for_questions(self, ledger: Ledger) -> bool:
        return ledger.state.observation is not None and ledger.state.gates.evidence_reliable

    def _build_checkpoints(self, ledger: Ledger, learning_session: LearningSession | None) -> list[CheckpointState]:
        checkpoints = [self._build_core_checkpoint(ledger, learning_session), self._build_implementation_checkpoint(ledger)]
        if self._requires_evidence(ledger):
            checkpoints.append(self._build_evidence_checkpoint(ledger, learning_session))
        return checkpoints

    def _build_core_checkpoint(self, ledger: Ledger, learning_session: LearningSession | None) -> CheckpointState:
        if learning_session is None:
            return CheckpointState(
                id="core_concepts",
                title="Core Concepts",
                description="Generate Learning Assist content and pass the required baseline core questions.",
                status="not_started" if not ledger.state.gates.socratic_check_passed else "passed",
                reason="Generate Learning Assist to load concept cards and questions."
                if not ledger.state.gates.socratic_check_passed
                else "Concept coverage satisfied through the concept gate.",
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
            id="core_concepts",
            title="Core Concepts",
            description="Cover the current week's core concept and implementation questions.",
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
                description="Record a structured observation, generate evidence questions, and capture a reflection.",
                status="not_started",
                reason="Observation and reflection are still missing.",
            )
        if ledger.state.observation is not None and ledger.state.observation.reliability != "valid":
            return CheckpointState(
                id="evidence_reliability",
                title="Evidence Reliability",
                description="Record a structured observation, generate evidence questions, and capture a reflection.",
                status="failed",
                reason=f"Observation marked as {ledger.state.observation.reliability}.",
            )
        if ledger.state.reflection is not None and (
            ledger.state.reflection.buggy or ledger.state.reflection.trustworthy is False
        ):
            return CheckpointState(
                id="evidence_reliability",
                title="Evidence Reliability",
                description="Record a structured observation, generate evidence questions, and capture a reflection.",
                status="failed",
                reason="Reflection reports unreliable or buggy evidence.",
            )
        if ledger.state.gates.evidence_reliable and ledger.state.reflection is not None:
            reason = "Reliable observation recorded and reflection captured."
            if learning_session is not None:
                progress = self._question_progress(learning_session)
                if progress["evidence_total"]:
                    reason = f"{reason} {progress['evidence_answered']}/{progress['evidence_total']} evidence questions answered."
            return CheckpointState(
                id="evidence_reliability",
                title="Evidence Reliability",
                description="Record a structured observation, generate evidence questions, and capture a reflection.",
                status="passed",
                reason=reason,
            )
        return CheckpointState(
            id="evidence_reliability",
            title="Evidence Reliability",
            description="Record a structured observation, generate evidence questions, and capture a reflection.",
            status="in_progress",
            reason="Evidence is partially recorded but not fully trusted yet.",
        )

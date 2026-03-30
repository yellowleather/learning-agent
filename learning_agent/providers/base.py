from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

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
    RawQuestionBankPayload,
    RawLearningQuestion,
    ReadingMaterialPayload,
    TopicChatTurn,
)


class LLMProvider(ABC):
    @abstractmethod
    def generate_raw_question_bank(self, week_spec: dict[str, Any], ledger_state: ProgressState) -> RawQuestionBankPayload:
        raise NotImplementedError

    @abstractmethod
    def classify_question_bank(
        self,
        week_spec: dict[str, Any],
        ledger_state: ProgressState,
        questions: list[RawLearningQuestion],
    ) -> ClassifiedQuestionBankPayload:
        raise NotImplementedError

    @abstractmethod
    def generate_reading_material(
        self,
        week_spec: dict[str, Any],
        ledger_state: ProgressState,
        questions: list[LearningQuestion],
    ) -> ReadingMaterialPayload:
        raise NotImplementedError

    @abstractmethod
    def generate_concept_cards_from_reading(
        self,
        week_spec: dict[str, Any],
        ledger_state: ProgressState,
        reading_sections: list,
    ) -> ConceptCardPayload:
        raise NotImplementedError

    @abstractmethod
    def generate_gate_question(self, week_spec: dict[str, Any]) -> GateQuestion:
        raise NotImplementedError

    @abstractmethod
    def score_gate_answer(self, week_spec: dict[str, Any], question: GateQuestion, answer: str) -> GateResult:
        raise NotImplementedError

    @abstractmethod
    def generate_task(self, week_spec: dict[str, Any], ledger_state: ProgressState) -> GeneratedTask:
        raise NotImplementedError

    @abstractmethod
    def score_learning_question(
        self,
        week_spec: dict[str, Any],
        question: LearningQuestion,
        answer: str,
        observation: ObservationRecord | None,
    ) -> QuestionScore:
        raise NotImplementedError

    @abstractmethod
    def generate_evidence_questions(
        self,
        week_spec: dict[str, Any],
        observation: ObservationRecord,
        learning_session: LearningSession,
    ) -> EvidenceQuestionPayload:
        raise NotImplementedError

    @abstractmethod
    def answer_topic_chat(
        self,
        week_spec: dict[str, Any],
        context: str,
        history: list[TopicChatTurn],
        message: str,
    ) -> str:
        raise NotImplementedError

    def stream_topic_chat(
        self,
        week_spec: dict[str, Any],
        context: str,
        history: list[TopicChatTurn],
        message: str,
    ) -> Iterator[str]:
        yield self.answer_topic_chat(week_spec, context, history, message)

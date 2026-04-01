from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from learning_agent.models import (
    ConceptCardPayload,
    GeneratedTask,
    LearningQuestion,
    LearningQuestionBankPayload,
    ObservationRecord,
    ProgressState,
    QuestionScore,
    ReadingMaterialPayload,
    TopicChatTurn,
)


class LLMProvider(ABC):
    @abstractmethod
    def generate_question_bank(
        self, week_spec: dict[str, Any], ledger_state: ProgressState
    ) -> LearningQuestionBankPayload:
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

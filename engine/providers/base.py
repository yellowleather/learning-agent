from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from engine.models import (
    GeneratedTask,
    ProgressState,
)
from topic_chat.models import TopicChatTurn
from verify.models import (
    ObservationRecord,
)
from learn.models import (
    ConceptCardPayload,
    LearningQuestion,
    LearningQuestionBankPayload,
    QuestionScore,
    ReadingMaterialPayload,
)


class LLMProvider(ABC):
    @abstractmethod
    def generate_prior_knowledge_summary(self, full_plan: str, target_week_number: int) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate_question_bank(
        self,
        week_spec: dict[str, Any],
        prior_knowledge_summary: str,
        ledger_state: ProgressState,
    ) -> LearningQuestionBankPayload:
        raise NotImplementedError

    @abstractmethod
    def generate_reading_material(
        self,
        week_spec: dict[str, Any],
        prior_knowledge_summary: str,
        ledger_state: ProgressState,
        questions: list[LearningQuestion],
    ) -> ReadingMaterialPayload:
        raise NotImplementedError

    @abstractmethod
    def generate_concept_cards_from_reading(
        self,
        week_spec: dict[str, Any],
        ledger_state: ProgressState,
        reading_material: ReadingMaterialPayload,
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

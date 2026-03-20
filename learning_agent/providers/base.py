from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

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
    TopicChatTurn,
    WeekSpec,
)


class LLMProvider(ABC):
    @abstractmethod
    def generate_raw_question_bank(self, week_spec: WeekSpec, ledger_state: ProgressState) -> RawQuestionBankPayload:
        raise NotImplementedError

    @abstractmethod
    def generate_concept_cards(
        self,
        week_spec: WeekSpec,
        ledger_state: ProgressState,
        questions: list[RawLearningQuestion],
    ) -> ConceptCardPayload:
        raise NotImplementedError

    @abstractmethod
    def classify_question_bank(
        self,
        week_spec: WeekSpec,
        ledger_state: ProgressState,
        questions: list[RawLearningQuestion],
    ) -> ClassifiedQuestionBankPayload:
        raise NotImplementedError

    @abstractmethod
    def generate_gate_question(self, week_spec: WeekSpec) -> GateQuestion:
        raise NotImplementedError

    @abstractmethod
    def score_gate_answer(self, week_spec: WeekSpec, question: GateQuestion, answer: str) -> GateResult:
        raise NotImplementedError

    @abstractmethod
    def generate_task(self, week_spec: WeekSpec, ledger_state: ProgressState) -> GeneratedTask:
        raise NotImplementedError

    @abstractmethod
    def score_learning_question(
        self,
        week_spec: WeekSpec,
        question: LearningQuestion,
        answer: str,
        observation: ObservationRecord | None,
    ) -> QuestionScore:
        raise NotImplementedError

    @abstractmethod
    def generate_evidence_questions(
        self,
        week_spec: WeekSpec,
        observation: ObservationRecord,
        learning_session: LearningSession,
    ) -> EvidenceQuestionPayload:
        raise NotImplementedError

    @abstractmethod
    def answer_topic_chat(
        self,
        week_spec: WeekSpec,
        context: str,
        history: list[TopicChatTurn],
        message: str,
    ) -> str:
        raise NotImplementedError

    def stream_topic_chat(
        self,
        week_spec: WeekSpec,
        context: str,
        history: list[TopicChatTurn],
        message: str,
    ) -> Iterator[str]:
        yield self.answer_topic_chat(week_spec, context, history, message)

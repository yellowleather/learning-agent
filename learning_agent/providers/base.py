from __future__ import annotations

from abc import ABC, abstractmethod

from learning_agent.models import (
    EvidenceQuestionPayload,
    GateQuestion,
    GateResult,
    GeneratedTask,
    LearningAssistPayload,
    LearningQuestion,
    LearningSession,
    ObservationRecord,
    ProgressState,
    QuestionScore,
    WeekSpec,
)


class LLMProvider(ABC):
    @abstractmethod
    def generate_learning_assist(self, week_spec: WeekSpec, ledger_state: ProgressState) -> LearningAssistPayload:
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

from __future__ import annotations

from abc import ABC, abstractmethod

from learning_agent.models import GateQuestion, GateResult, GeneratedTask, ProgressState, WeekSpec


class LLMProvider(ABC):
    @abstractmethod
    def generate_gate_question(self, week_spec: WeekSpec) -> GateQuestion:
        raise NotImplementedError

    @abstractmethod
    def score_gate_answer(self, week_spec: WeekSpec, question: GateQuestion, answer: str) -> GateResult:
        raise NotImplementedError

    @abstractmethod
    def generate_task(self, week_spec: WeekSpec, ledger_state: ProgressState) -> GeneratedTask:
        raise NotImplementedError

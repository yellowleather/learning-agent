"""Pydantic models owned by the learn domain.

These describe the learning content produced by the provider pipeline
(reading, concept cards, question bank) and the user-facing session that
records progress through them. Cross-stage models (Ledger, Gates,
ProgressState, etc.) stay in coach.models.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import Field

from engine._base import StrictModel


class ConceptCard(StrictModel):
    id: str = ""
    concept: str
    title: str = ""
    explanation: str
    why_it_matters: str
    common_mistake: str
    quick_check_question: Optional[str] = None


class LearningQuestion(StrictModel):
    id: str
    depth: Literal["baseline", "deep", "stretch"]
    prompt_text: str
    scoring_rubric: List[str] = Field(default_factory=list)


class QuestionScore(StrictModel):
    passed: bool
    score_rationale: str
    missing_concepts: List[str] = Field(default_factory=list)


class QuestionAttempt(StrictModel):
    question_id: str
    answer: str
    result: QuestionScore


class LearningAssistPayload(StrictModel):
    week: int
    concept_cards: List[ConceptCard] = Field(default_factory=list)
    questions: List[LearningQuestion] = Field(default_factory=list)


class LearningQuestionBankPayload(StrictModel):
    week: int
    questions: List[LearningQuestion] = Field(default_factory=list)


class ReadingMaterialPayload(StrictModel):
    week: int
    title: str
    body_markdown: str


class ConceptCardPayload(StrictModel):
    week: int
    concept_cards: List[ConceptCard] = Field(default_factory=list)


class LearningSession(StrictModel):
    week: int
    concept_cards: List[ConceptCard] = Field(default_factory=list)
    reading_material: Optional[ReadingMaterialPayload] = None
    questions: List[LearningQuestion] = Field(default_factory=list)
    attempts: List[QuestionAttempt] = Field(default_factory=list)


class LearningBundle(StrictModel):
    """User-facing view of a LearningSession — same shape but explicit so
    callers can change one surface without touching the other."""
    week: int
    concept_cards: List[ConceptCard] = Field(default_factory=list)
    reading_material: Optional[ReadingMaterialPayload] = None
    questions: List[LearningQuestion] = Field(default_factory=list)
    attempts: List[QuestionAttempt] = Field(default_factory=list)

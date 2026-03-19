from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppConfig(StrictModel):
    provider: Literal["openai"] = "openai"
    model: str = ""
    roadmap_path: str
    target_repo_path: str
    state_dir: str = "state"


class CurriculumMetadata(StrictModel):
    title: str
    total_weeks: int
    target_repo: str


class Gates(StrictModel):
    socratic_check_passed: bool = False
    implementation_complete: bool = False
    verification_passed: bool = False
    evidence_reliable: bool = False
    week_approved: bool = False


class ArtifactState(StrictModel):
    required_files: List[str] = Field(default_factory=list)
    completed_files: List[str] = Field(default_factory=list)


class MetricsState(StrictModel):
    required: List[str] = Field(default_factory=list)
    recorded: Dict[str, Any] = Field(default_factory=dict)


class VerificationRecord(StrictModel):
    passed: bool
    summary: str


class ObservationRecord(StrictModel):
    command: str
    artifact_path: str
    prompt_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_p95_ms: Optional[float] = None
    tokens_per_sec: Optional[float] = None
    notes: str = ""
    reliability: Literal["valid", "invalid_due_to_bug", "invalid_due_to_bad_measurement", "uncertain"] = "uncertain"


class ReflectionRecord(StrictModel):
    text: str
    trustworthy: Optional[bool] = None
    buggy: bool = False
    next_fix: str = ""


class ConceptCard(StrictModel):
    id: str = ""
    concept: str
    title: str = ""
    explanation: str
    why_it_matters: str
    common_mistake: str
    quick_check_question: Optional[str] = None
    image_path: Optional[str] = None
    image_alt: str = ""
    related_section_ids: List[str] = Field(default_factory=list)


class RawLearningQuestion(StrictModel):
    prompt_text: str
    tier: Literal["foundational_concepts", "implementation_knowledge", "optimization_and_production_insights"]
    topic_area: str


class LearningQuestion(StrictModel):
    id: str
    type: Literal["concept", "implementation", "evidence_based"]
    scope: Literal["core", "adjacent", "later_week"]
    depth: Literal["baseline", "deep", "stretch"]
    prompt_text: str
    scoring_rubric: List[str] = Field(default_factory=list)
    roadmap_anchor: Dict[str, Any] = Field(default_factory=dict)
    observation_required: bool = False
    related_concept_ids: List[str] = Field(default_factory=list)
    related_section_ids: List[str] = Field(default_factory=list)


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


class RawQuestionBankPayload(StrictModel):
    week: int
    questions: List[RawLearningQuestion] = Field(default_factory=list)


class ConceptCardPayload(StrictModel):
    week: int
    concept_cards: List[ConceptCard] = Field(default_factory=list)


class ClassifiedQuestionBankPayload(StrictModel):
    week: int
    questions: List[LearningQuestion] = Field(default_factory=list)


class EvidenceQuestionPayload(StrictModel):
    week: int
    questions: List[LearningQuestion] = Field(default_factory=list)


class FigureAsset(StrictModel):
    id: str
    title: str
    image_path: str
    alt_text: str
    caption: str


class ReadingSection(StrictModel):
    id: str
    title: str
    body_markdown: str
    figure_ids: List[str] = Field(default_factory=list)
    related_question_ids: List[str] = Field(default_factory=list)
    related_concept_ids: List[str] = Field(default_factory=list)


class LearningSession(StrictModel):
    week: int
    concept_cards: List[ConceptCard] = Field(default_factory=list)
    figures: List[FigureAsset] = Field(default_factory=list)
    reading_sections: List[ReadingSection] = Field(default_factory=list)
    questions: List[LearningQuestion] = Field(default_factory=list)
    attempts: List[QuestionAttempt] = Field(default_factory=list)


class LearningBundle(StrictModel):
    week: int
    concept_cards: List[ConceptCard] = Field(default_factory=list)
    figures: List[FigureAsset] = Field(default_factory=list)
    reading_sections: List[ReadingSection] = Field(default_factory=list)
    questions: List[LearningQuestion] = Field(default_factory=list)
    attempts: List[QuestionAttempt] = Field(default_factory=list)


class TopicChatTurn(StrictModel):
    role: Literal["user", "assistant"]
    content: str


class CheckpointState(StrictModel):
    id: str
    title: str
    description: str
    status: Literal["not_started", "in_progress", "passed", "failed"]
    reason: str = ""


class ProgressState(StrictModel):
    current_week: int
    active_functional_dirs: List[str] = Field(default_factory=list)
    learning_assist_enabled: bool = True
    gates: Gates = Field(default_factory=Gates)
    artifacts: ArtifactState = Field(default_factory=ArtifactState)
    metrics: MetricsState = Field(default_factory=MetricsState)
    verification: Optional[VerificationRecord] = None
    observation: Optional[ObservationRecord] = None
    reflection: Optional[ReflectionRecord] = None


class Ledger(StrictModel):
    curriculum_metadata: CurriculumMetadata
    state: ProgressState


class WeekSpec(StrictModel):
    number: int
    title: str
    goal: str
    concepts: List[str] = Field(default_factory=list)
    tasks: List[str] = Field(default_factory=list)
    deliverable_paths: List[str] = Field(default_factory=list)
    required_files: List[str] = Field(default_factory=list)
    active_dirs: List[str] = Field(default_factory=list)
    required_metrics: List[str] = Field(default_factory=list)


class GateQuestion(StrictModel):
    week: int
    question: str
    rubric: List[str] = Field(default_factory=list)
    context_summary: str


class GateResult(StrictModel):
    passed: bool
    score_rationale: str
    missing_concepts: List[str] = Field(default_factory=list)


class GateSession(StrictModel):
    prompt: GateQuestion
    last_answer: Optional[str] = None
    result: Optional[GateResult] = None


class GeneratedTask(StrictModel):
    week: int
    title: str
    objective: str
    allowed_dirs: List[str] = Field(default_factory=list)
    required_files: List[str] = Field(default_factory=list)
    implementation_steps: List[str] = Field(default_factory=list)
    acceptance_checks: List[str] = Field(default_factory=list)
    verification_expectations: List[str] = Field(default_factory=list)
    summary: str


class TaskSession(StrictModel):
    task: GeneratedTask
    verification: Optional[VerificationRecord] = None

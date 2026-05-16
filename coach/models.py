from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppConfig(StrictModel):
    provider: Literal["openai", "anthropic"] = "openai"
    model: str = ""
    roadmap_path: str
    target_repo_path: str
    state_dir: str = "state"


class CurriculumMetadata(StrictModel):
    title: str
    total_weeks: int
    target_repo: str


class Gates(StrictModel):
    learning_check_passed: bool = False
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
    week: int
    concept_cards: List[ConceptCard] = Field(default_factory=list)
    reading_material: Optional[ReadingMaterialPayload] = None
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
    active_dirs: List[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("active_dirs", "active_functional_dirs"),
    )
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


class CommandRun(StrictModel):
    """One subprocess invocation by the BuildAgent through the run_command tool.

    Carries the captured *facts* of the run only — exit code and tails of
    stdout/stderr. No judgement about whether the command succeeded relative
    to the brief (that is review_build's job)."""
    cmd: str
    exit_code: int
    stdout_tail: str
    stderr_tail: str
    duration_ms: int
    truncated: bool


class FileTouched(StrictModel):
    """Net effect of the BuildAgent on a single file in the target repo.

    `diff` is a unified diff against the file's contents at agent start,
    truncated to a reasonable cap; `diff_truncated` signals when content
    was clipped."""
    path: str
    action: Literal["create", "modify", "delete"]
    diff: str
    diff_truncated: bool


class BuildReport(StrictModel):
    """Terminal report from a BuildAgent run.

    Pure facts. The agent declares `status`, `summary`, and `notes`; the
    platform fills `commands_run`, `files_touched`, and `metrics_recorded`
    from observed tool calls. No verification verdict — that belongs to
    review_build."""
    status: Literal[
        "completed",
        "gave_up",
        "timed_out",
        "stopped_by_user",
        "errored",
    ]
    summary: str
    commands_run: List[CommandRun] = Field(default_factory=list)
    files_touched: List[FileTouched] = Field(default_factory=list)
    metrics_recorded: Dict[str, float] = Field(default_factory=dict)
    notes: str = ""


class BuildSession(StrictModel):
    """Persisted lifecycle record for a single BuildAgent run.

    Lives in state/current_build.json. The streaming transcript is *not*
    embedded here — it lives in state/current_build.transcript.jsonl so a
    long run doesn't bloat the loaded session payload."""
    week: int
    started_at_utc: str
    ended_at_utc: Optional[str] = None
    duration_seconds: int = 0
    turn_count: int = 0
    report: Optional[BuildReport] = None


class TranscriptEvent(StrictModel):
    """One event line in state/current_build.transcript.jsonl.

    `kind` is strictly enumerated; an agent that emits a new kind will
    fail validation loudly so the enum can be extended deliberately."""
    seq: int
    timestamp_utc: str
    kind: Literal["thought", "tool_call", "tool_result", "tool_error", "system"]
    payload: Dict[str, Any] = Field(default_factory=dict)

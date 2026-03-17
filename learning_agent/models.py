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


class ProgressState(StrictModel):
    current_week: int
    active_functional_dirs: List[str] = Field(default_factory=list)
    gates: Gates = Field(default_factory=Gates)
    artifacts: ArtifactState = Field(default_factory=ArtifactState)
    metrics: MetricsState = Field(default_factory=MetricsState)
    verification: Optional[VerificationRecord] = None


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

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import AliasChoices, Field

from coach._base import StrictModel
from verify.models import (
    ObservationRecord,
    ReflectionRecord,
    VerificationRecord,
)


# StrictModel is re-exported here for any caller that still imports it from
# coach.models; new code should import directly from coach._base.
__all__ = [
    "StrictModel",
    "ObservationRecord",
    "ReflectionRecord",
    "VerificationRecord",
]


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

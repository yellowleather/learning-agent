from __future__ import annotations

from pathlib import Path
from typing import List

from learning_agent.errors import LearningAgentError
from learning_agent.models import CurriculumMetadata, WeekSpec
from learning_agent.roadmap_parser import load_roadmap_dict


def load_curriculum(roadmap_path: Path, target_repo_path: str) -> tuple[CurriculumMetadata, List[WeekSpec]]:
    roadmap = load_roadmap_dict(roadmap_path)
    weeks = [
        WeekSpec(
            number=week["number"],
            title=week["short_title"],
            goal=week["goal"],
            concepts=week["topics_covered"],
            tasks=week["tasks"],
            deliverable_paths=week["deliverable_paths"],
            required_files=week["required_files"],
            active_dirs=week["active_dirs"],
            required_metrics=week["required_metrics"],
        )
        for week in roadmap["weeks"]
    ]

    metadata = CurriculumMetadata(
        title=roadmap["title"],
        total_weeks=len(weeks),
        target_repo=target_repo_path,
    )
    return metadata, weeks


def get_week_spec(weeks: List[WeekSpec], week_number: int) -> WeekSpec:
    for week in weeks:
        if week.number == week_number:
            return week
    raise LearningAgentError(f"Week {week_number} does not exist in the roadmap.")

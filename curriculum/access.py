"""Curriculum reads, centralised behind a single object with a cached roadmap.

The roadmap markdown is parsed once on first access and reused for the lifetime
of the instance. This matches PRD §3 ("curriculum markdown is immutable for the
duration of a run") and avoids re-parsing on every status / stage call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from coach.errors import CoachError
from coach.models import CurriculumMetadata
from curriculum.parser import load_roadmap_dict


class CurriculumAccess:
    """Read-only view over the parsed curriculum roadmap.

    Stages depend on this rather than reaching into the roadmap parser
    themselves, so the source-of-truth path stays singular and the parse
    cost is paid at most once per process.
    """

    def __init__(self, roadmap_path: Path, target_repo_path: str):
        self._roadmap_path = roadmap_path
        self._target_repo_path = target_repo_path
        self._roadmap: dict[str, Any] | None = None

    @property
    def roadmap_path(self) -> Path:
        return self._roadmap_path

    @property
    def roadmap(self) -> dict[str, Any]:
        """Parsed roadmap dict. Lazily loaded, cached for the instance lifetime."""
        if self._roadmap is None:
            self._roadmap = load_roadmap_dict(self._roadmap_path)
        return self._roadmap

    def markdown(self) -> str:
        """Raw roadmap markdown source. Used for prior-knowledge context windows."""
        try:
            return self._roadmap_path.read_text()
        except FileNotFoundError as exc:
            raise CoachError(f"Roadmap file not found: {self._roadmap_path}") from exc

    def metadata(self) -> CurriculumMetadata:
        """Curriculum-level metadata (title, total weeks, target repo path)."""
        return CurriculumMetadata(
            title=str(self.roadmap["title"]),
            total_weeks=len(self.roadmap["weeks"]),
            target_repo=self._target_repo_path,
        )

    def week_by_number(self, week_number: int) -> dict[str, Any]:
        """Lookup a specific week's spec by number. Raises if the week is absent."""
        for week in self.roadmap["weeks"]:
            if int(week["number"]) == week_number:
                return week
        raise CoachError(f"Week {week_number} does not exist in the roadmap.")

    def current_week(self, current_week_number: int) -> dict[str, Any]:
        """Return the spec for the week the ledger says is currently active."""
        return self.week_by_number(current_week_number)

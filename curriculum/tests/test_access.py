"""Unit tests for CurriculumAccess.

Covers the read paths used by the orchestrator and stages: lazy parse + cache,
markdown source access, metadata derivation, and week lookup (including the
not-found error case).
"""

from pathlib import Path

import pytest

from curriculum.access import CurriculumAccess
from coach.errors import CoachError


def _week_block(number: int, short_title: str, file_path: str) -> str:
    return f"""## Week {number}: {short_title}

### Goal

Goal for week {number}.

### Narrative

Narrative for week {number}.

### Topics Covered

- topic-{number}

### By the End of This Week You Will Be Able To

- Explain topic-{number}
- Build artifact-{number}

### Assessment Targets

1. Explain topic-{number}.
2. Describe artifact-{number}.

### Implementation

**Files created this week:**

- `{file_path}` — File {number}.

**Deliverables:** A thing in `{file_path}`.

**Cloud deployment:** Not required.

### Key Resources

- Resource {number}.

"""


def _write_roadmap(tmp_path: Path) -> Path:
    """Minimal two-week roadmap in the shape roadmap_parser expects."""
    path = tmp_path / "roadmap.md"
    path.write_text(
        f"""# Test Curriculum

## Overview

Overview text.

## Repository Structure

```
target/
├── dir_one/
└── dir_two/
```

Repository description.

{_week_block(1, "First Week", "dir_one/file_one.py")}
{_week_block(2, "Second Week", "dir_two/file_two.py")}
## Capstone Summary

### Artifacts Built

| Artifact | Location | Description |
|---|---|---|
| Thing | `dir_one/file_one.py` | Example |

### What You Can Now Do

You can do things.
"""
    )
    return path


def test_roadmap_is_lazily_loaded_and_cached(tmp_path: Path) -> None:
    # First .roadmap access parses from disk; subsequent accesses return the
    # same dict object without re-reading the file.
    path = _write_roadmap(tmp_path)
    access = CurriculumAccess(path, target_repo_path="target/repo")
    first = access.roadmap
    path.unlink()  # delete the file to prove the second read is from cache
    second = access.roadmap
    assert first is second


def test_markdown_returns_raw_file_contents(tmp_path: Path) -> None:
    # markdown() yields the unparsed source text used by prior-knowledge prompts.
    path = _write_roadmap(tmp_path)
    access = CurriculumAccess(path, target_repo_path="target/repo")
    text = access.markdown()
    assert text.startswith("# Test Curriculum")
    assert "Week 2: Second Week" in text


def test_markdown_raises_coach_error_when_file_missing(tmp_path: Path) -> None:
    # A missing roadmap file surfaces as a CoachError, not a raw OSError,
    # so callers can present it without leaking the exception type.
    access = CurriculumAccess(tmp_path / "does_not_exist.md", target_repo_path="target/repo")
    with pytest.raises(CoachError):
        access.markdown()


def test_metadata_reports_title_total_weeks_and_target_repo(tmp_path: Path) -> None:
    # Metadata aggregates curriculum title, total week count, and the configured
    # target repo string used when initialising the ledger.
    path = _write_roadmap(tmp_path)
    access = CurriculumAccess(path, target_repo_path="ai_inference_engineering")
    metadata = access.metadata()
    assert metadata.title == "Test Curriculum"
    assert metadata.total_weeks == 2
    assert metadata.target_repo == "ai_inference_engineering"


def test_week_by_number_returns_matching_week_spec(tmp_path: Path) -> None:
    # week_by_number finds the entry whose 'number' field matches.
    path = _write_roadmap(tmp_path)
    access = CurriculumAccess(path, target_repo_path="target/repo")
    week_two = access.week_by_number(2)
    assert int(week_two["number"]) == 2
    assert week_two["short_title"] == "Second Week"


def test_week_by_number_raises_when_week_is_absent(tmp_path: Path) -> None:
    # Unknown week numbers raise a CoachError with a useful message
    # so the orchestrator can surface the boundary instead of indexing into None.
    path = _write_roadmap(tmp_path)
    access = CurriculumAccess(path, target_repo_path="target/repo")
    with pytest.raises(CoachError) as excinfo:
        access.week_by_number(99)
    assert "Week 99" in str(excinfo.value)


def test_current_week_delegates_to_week_by_number(tmp_path: Path) -> None:
    # current_week is a thin alias that takes the integer the ledger holds and
    # returns the same dict week_by_number would for that integer.
    path = _write_roadmap(tmp_path)
    access = CurriculumAccess(path, target_repo_path="target/repo")
    assert access.current_week(1) == access.week_by_number(1)

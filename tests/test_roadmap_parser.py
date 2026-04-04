from pathlib import Path

from learning_agent.roadmap_parser import load_roadmap_dict


def build_week(number: int) -> str:
    return f"""## Week {number}: Week Title {number}

### Goal

Goal {number}.

### Narrative

Narrative {number}.

### Topics Covered

- concept {number}

### By the End of This Week You Will Be Able To

- explain concept {number}
- build artifact {number}

### Assessment Targets

1. Explain concept {number}.
2. Describe artifact {number}.

### Implementation

**Files created this week:**

- `server/week_{number}.py` — Implementation file {number}.

**Deliverables:** A report in `docs/week_{number}.md`.

**Cloud deployment:** Not required.

### Key Resources

- Resource {number}.
"""


def write_full_roadmap(path: Path, total_weeks: int = 8) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# 8-Week Inference Engineering Roadmap\n\n"
        "## Overview\n\n"
        "Overview text.\n\n"
        "## Repository Structure\n\n"
        "```\n"
        "inference/\n"
        "├── server/\n"
        "└── docs/\n"
        "```\n\n"
        "Repository description.\n\n"
        + "\n\n".join(build_week(week_number) for week_number in range(1, total_weeks + 1))
        + "\n\n## Capstone Summary\n\n"
        "### Artifacts Built\n\n"
        "| Artifact | Location | Description |\n"
        "|---|---|---|\n"
        "| Final artifact | `server/week_1.py` | Example |\n\n"
        "### What You Can Now Do\n\n"
        "You can ship the system.\n"
    )


def test_load_roadmap_dict_parses_full_plan(tmp_path):
    roadmap = tmp_path / "docs" / "plan.md"
    write_full_roadmap(roadmap)

    parsed = load_roadmap_dict(roadmap)

    assert parsed["title"] == "8-Week Inference Engineering Roadmap"
    assert parsed["repository_structure"]["directories"] == ["server", "docs"]
    assert len(parsed["weeks"]) == 8
    assert parsed["weeks"][0]["title"] == "Week 1: Week Title 1"
    assert parsed["weeks"][0]["topics_covered"] == ["concept 1"]
    assert parsed["weeks"][0]["implementation"]["files"][0]["path"] == "server/week_1.py"
    assert parsed["weeks"][0]["required_files"] == ["server/week_1.py", "docs/week_1.md"]
    assert parsed["capstone_summary"]["artifacts_built"][0]["artifact"] == "Final artifact"


def test_load_roadmap_dict_accepts_non_eight_week_curriculum(tmp_path):
    roadmap = tmp_path / "docs" / "plan.md"
    write_full_roadmap(roadmap, total_weeks=3)

    parsed = load_roadmap_dict(roadmap)

    assert len(parsed["weeks"]) == 3
    assert parsed["weeks"][-1]["title"] == "Week 3: Week Title 3"


def test_load_roadmap_dict_ignores_thematic_break_after_key_resources(tmp_path):
    roadmap = tmp_path / "docs" / "plan.md"
    write_full_roadmap(roadmap)
    roadmap.write_text(roadmap.read_text().replace("### Key Resources\n\n- Resource 1.\n", "### Key Resources\n\n- Resource 1.\n\n---\n"))

    parsed = load_roadmap_dict(roadmap)

    assert parsed["weeks"][0]["key_resources"] == ["Resource 1."]


def test_load_roadmap_dict_rejects_missing_required_week_subsection(tmp_path):
    roadmap = tmp_path / "docs" / "plan.md"
    roadmap.parent.mkdir(parents=True, exist_ok=True)
    roadmap.write_text(
        "# 8-Week Inference Engineering Roadmap\n\n"
        "## Overview\n\n"
        "Overview text.\n\n"
        "## Repository Structure\n\n"
        "```\n"
        "inference/\n"
        "└── server/\n"
        "```\n\n"
        "Repository description.\n\n"
        "## Week 1: Broken Week\n\n"
        "### Goal\n\n"
        "Broken goal.\n\n"
        "### Topics Covered\n\n"
        "- concept 1\n\n"
        "### Implementation\n\n"
        "**Files created this week:**\n\n"
        "- `server/week_1.py` — Implementation file 1.\n\n"
        "**Deliverables:** A report in `docs/week_1.md`.\n\n"
        "**Cloud deployment:** Not required.\n\n"
        + "\n\n".join(build_week(week_number) for week_number in range(2, 9))
        + "\n\n## Capstone Summary\n\n"
        "### Artifacts Built\n\n"
        "| Artifact | Location | Description |\n"
        "|---|---|---|\n"
        "| Final artifact | `server/week_1.py` | Example |\n\n"
        "### What You Can Now Do\n\n"
        "You can ship the system.\n"
    )

    try:
        load_roadmap_dict(roadmap)
    except Exception as exc:  # pragma: no cover - assertion below narrows the behavior.
        assert "Week 1 is missing required subsection `### Narrative`" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected roadmap parsing to fail for a missing required subsection.")

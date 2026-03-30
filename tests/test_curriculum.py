from pathlib import Path

from learning_agent.curriculum import get_week_spec, load_curriculum
from learning_agent.roadmap_parser import load_roadmap_dict


def build_week(
    number: int,
    title: str,
    goal: str,
    topics: list[str],
    files: list[tuple[str, str]],
    deliverables: str,
) -> str:
    topics_block = "\n".join(f"- {item}" for item in topics)
    files_block = "\n".join(f"- `{path}` — {description}" for path, description in files)
    return f"""## Week {number}: {title}

### Goal

{goal}

### Narrative

This week builds one concrete part of the system and explains why it matters.

### Topics Covered

{topics_block}

### By the End of This Week You Will Be Able To

- Explain the main system tradeoff for this week
- Implement the required component and reason about its behavior

### Assessment Targets

1. Explain the main concept for this week.
2. Describe the implementation tradeoff for this week.

### Implementation

**Files created this week:**

{files_block}

**Deliverables:** {deliverables}

**Cloud deployment:** Not required.

### Key Resources

- Example resource for this week.
"""


def test_week_one_is_parsed_from_a_realistic_roadmap(tmp_path):
    roadmap = tmp_path / "docs" / "plan.md"
    roadmap.parent.mkdir(parents=True, exist_ok=True)
    roadmap.write_text(
        "# 8-Week Inference Engineering Roadmap\n\n"
        "## Overview\n\n"
        "This is a full roadmap overview.\n\n"
        "## Repository Structure\n\n"
        "```\n"
        "inference/\n"
        "├── simple_server/\n"
        "├── deploy/\n"
        "├── runtime/\n"
        "├── server/\n"
        "├── benchmarks/\n"
        "└── docs/\n"
        "```\n\n"
        "The repository structure is described here.\n\n"
        + "\n\n".join(
            [
                build_week(
                    1,
                    "Build a Baseline Inference Server",
                    "Run a model locally and expose it as an API.",
                    ["prefill vs decode", "latency vs throughput"],
                    [
                        ("simple_server/server.py", "Small API server entrypoint."),
                        ("simple_server/benchmark.py", "Benchmark runner for the baseline server."),
                    ],
                    "A benchmark report in `docs/baseline_results.md` measuring tokens/sec and latency for the baseline server.",
                ),
                build_week(
                    2,
                    "Containerize and Measure",
                    "Containerize the service.",
                    ["docker packaging"],
                    [("deploy/Dockerfile", "Container image for the service.")],
                    "A runnable container build using `deploy/Dockerfile`.",
                ),
                build_week(
                    3,
                    "Scheduler Basics",
                    "Add request scheduling.",
                    ["batching"],
                    [("runtime/scheduler.py", "Basic request scheduler.")],
                    "A scheduler implementation in `runtime/scheduler.py`.",
                ),
                build_week(
                    4,
                    "KV Cache",
                    "Implement cache-aware serving.",
                    ["kv cache"],
                    [("runtime/cache.py", "Cache-aware serving logic.")],
                    "A cache implementation in `runtime/cache.py`.",
                ),
                build_week(
                    5,
                    "Streaming",
                    "Add token streaming.",
                    ["response streaming"],
                    [("server/streaming.py", "Streaming response support.")],
                    "Token streaming implemented in `server/streaming.py`.",
                ),
                build_week(
                    6,
                    "Quantization",
                    "Measure precision tradeoffs.",
                    ["quantization"],
                    [("benchmarks/quantization.md", "Quantization benchmark notes.")],
                    "A throughput benchmark write-up in `benchmarks/quantization.md`.",
                ),
                build_week(
                    7,
                    "Scaling",
                    "Study scaling behavior.",
                    ["concurrency limits"],
                    [("benchmarks/scaling.md", "Scaling benchmark results.")],
                    "A load-test report in `benchmarks/scaling.md`.",
                ),
                build_week(
                    8,
                    "Production Review",
                    "Summarize the system.",
                    ["operational tradeoffs"],
                    [("docs/capstone.md", "Final capstone summary.")],
                    "A final written summary in `docs/capstone.md`.",
                ),
            ]
        )
        + "\n\n## Capstone Summary\n\n### Artifacts Built\n\n| Artifact | Location | Description |\n|---|---|---|\n| Baseline server | `simple_server/server.py` | Simple server |\n\n### What You Can Now Do\n\nYou can explain the system end to end.\n"
    )
    metadata, weeks = load_curriculum(roadmap, "ai_inference_engineering")

    assert metadata.total_weeks == 8

    week_one = get_week_spec(weeks, 1)
    assert week_one.title == "Build a Baseline Inference Server"
    assert week_one.concepts == ["prefill vs decode", "latency vs throughput"]
    assert "simple_server/server.py" in week_one.tasks[0]
    assert "simple_server/server.py" in week_one.required_files
    assert "simple_server/benchmark.py" in week_one.required_files
    assert "docs/baseline_results.md" in week_one.required_files
    assert week_one.active_dirs == ["simple_server", "docs"]
    assert "tokens_per_sec" in week_one.required_metrics


def test_load_roadmap_dict_returns_full_plan_shape(tmp_path):
    roadmap = tmp_path / "docs" / "plan.md"
    roadmap.parent.mkdir(parents=True, exist_ok=True)
    roadmap.write_text(
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
        + "\n\n".join(
            build_week(
                week_number,
                f"Week Title {week_number}",
                f"Goal {week_number}.",
                [f"concept {week_number}"],
                [(f"server/week_{week_number}.py", f"Implementation file {week_number}.")],
                f"A report in `docs/week_{week_number}.md`.",
            )
            for week_number in range(1, 9)
        )
        + "\n\n## Capstone Summary\n\n### Artifacts Built\n\n| Artifact | Location | Description |\n|---|---|---|\n| Final artifact | `server/week_1.py` | Example |\n\n### What You Can Now Do\n\nYou can ship the system.\n"
    )

    roadmap_dict = load_roadmap_dict(roadmap)

    assert roadmap_dict["title"] == "8-Week Inference Engineering Roadmap"
    assert roadmap_dict["overview"] == "Overview text."
    assert roadmap_dict["repository_structure"]["directories"] == ["server", "docs"]
    assert len(roadmap_dict["weeks"]) == 8
    assert roadmap_dict["weeks"][0]["title"] == "Week 1: Week Title 1"
    assert roadmap_dict["weeks"][0]["goal"] == "Goal 1."
    assert roadmap_dict["weeks"][0]["topics_covered"] == ["concept 1"]
    assert roadmap_dict["weeks"][0]["implementation"]["files"][0]["path"] == "server/week_1.py"
    assert roadmap_dict["weeks"][0]["required_files"] == ["server/week_1.py", "docs/week_1.md"]
    assert roadmap_dict["capstone_summary"]["artifacts_built"][0]["artifact"] == "Final artifact"


def test_load_roadmap_dict_validates_required_subsections(tmp_path):
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
        "- concept\n\n"
        "### Implementation\n\n"
        "**Files created this week:**\n\n"
        "- `server/main.py` — Main file.\n\n"
        "**Deliverables:** A report in `docs/week_1.md`.\n\n"
        "**Cloud deployment:** Not required.\n\n"
        + "\n\n".join(
            build_week(
                week_number,
                f"Week Title {week_number}",
                f"Goal {week_number}.",
                [f"concept {week_number}"],
                [(f"server/week_{week_number}.py", f"Implementation file {week_number}.")],
                f"A report in `docs/week_{week_number}.md`.",
            )
            for week_number in range(2, 9)
        )
        + "\n\n## Capstone Summary\n\n### Artifacts Built\n\n| Artifact | Location | Description |\n|---|---|---|\n| Final artifact | `server/main.py` | Example |\n\n### What You Can Now Do\n\nYou can ship the system.\n"
    )

    try:
        load_roadmap_dict(roadmap)
    except Exception as exc:  # pragma: no cover - assertion below narrows the behavior.
        assert "Week 1 is missing required subsection `### Narrative`" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected roadmap validation to fail for a missing week subsection.")

import json

from typer.testing import CliRunner

from learning_agent.cli import app
from learning_agent.models import (
    ConceptCardPayload,
    LearningQuestionBankPayload,
    QuestionScore,
    ReadingMaterialPayload,
)


runner = CliRunner()


def _extra_weeks(start: int = 2) -> str:
    blocks = []
    for week_number in range(start, 9):
        blocks.append(
            f"""## Week {week_number}: Extra Week {week_number}

### Goal

Goal for week {week_number}.

### Narrative

Narrative for week {week_number}.

### Topics Covered

- concept {week_number}

### By the End of This Week You Will Be Able To

- Explain concept {week_number}
- Build artifact {week_number}

### Assessment Targets

1. Explain concept {week_number}.
2. Describe artifact {week_number}.

### Implementation

**Files created this week:**

- `docs/week_{week_number}.md` — Artifact for week {week_number}.

**Deliverables:** A written artifact in `docs/week_{week_number}.md`.

**Cloud deployment:** Not required.

### Key Resources

- Example resource.
"""
        )
    return "\n\n".join(blocks)


def _reading_sections_for(questions):
    question_ids = [question["id"] if isinstance(question, dict) else question.id for question in questions]
    return ReadingMaterialPayload(
        week=1,
        reading_sections=[
            {
                "id": "week_map",
                "title": "How This Week Works",
                "body_markdown": (
                    "Week 1 teaches the shape of a basic inference system before implementation begins. "
                    "The learner should understand what the server is responsible for, how the model runtime participates in generation, "
                    "and why the deliverables are organized around serving, measurement, and written evidence. "
                    "That context makes the later coding tasks feel like concrete expressions of the same system instead of a separate activity."
                ),
            },
            {
                "id": "request_to_response",
                "title": "From Request To Generated Tokens",
                "body_markdown": (
                    "The cleanest way to understand this week is to trace one request all the way through the service. "
                    "An API request arrives, the server validates and prepares it, the runtime performs model work, and generated output comes back through the service boundary. "
                    "That path explains both system design and debugging because every claim about behavior eventually maps to some part of this flow."
                ),
            },
            {
                "id": "generation_mechanics",
                "title": "Prefill, Decode, And Why The Split Matters",
                "body_markdown": (
                    "Prefill and decode are not the same kind of work. "
                    "During prefill the prompt is consumed and turned into model state, then the runtime enters decode and emits output over time. "
                    "Once you keep that split in view, latency and throughput questions become much easier to reason about. "
                    "It also becomes easier to explain why long prompts and long generations can stress the system in different ways."
                ),
            },
            {
                "id": "build_artifacts",
                "title": "How Week 1 Maps Onto Code",
                "body_markdown": (
                    "The implementation artifacts should feel like direct representations of the ideas in the reading. "
                    "One file defines the serving boundary, another captures measurement logic, and the results document turns observations into evidence. "
                    "That mapping helps you explain why each file exists and what system responsibility it carries. "
                    "Questions about implementation should therefore connect code structure back to runtime behavior and measurement."
                ),
            },
            {
                "id": "measure_and_verify",
                "title": "How To Measure And Verify",
                "body_markdown": (
                    "You should not treat performance numbers as isolated facts. "
                    "A useful benchmark makes clear what was timed, how outputs were counted, what prompt shape was used, and why repeated runs deserve trust. "
                    "Latency and throughput illuminate different properties of the same system, so both need to be tied back to the inference path that produced them. "
                    "That is what turns a number into technical evidence."
                ),
            },
        ],
    )


def _concept_cards_for(_reading_sections):
    return ConceptCardPayload(
        week=1,
        concept_cards=[
            {
                "id": "prefill-vs-decode",
                "concept": "prefill_vs_decode",
                "title": "Prefill vs Decode",
                "explanation": "Prefill processes the prompt and decode emits output token by token.",
                "why_it_matters": "It explains why prompt length and output length stress the system differently.",
                "common_mistake": "Treating inference as one undifferentiated block.",
                "quick_check_question": "What changes once prefill ends and decode begins?",
            },
            {
                "id": "request-flow",
                "concept": "request_flow",
                "title": "Request Flow",
                "explanation": "Request flow is the path from API request through runtime work to returned output.",
                "why_it_matters": "It anchors system explanations in the serving path.",
                "common_mistake": "Skipping the server when explaining inference.",
                "quick_check_question": "What happens between request arrival and response delivery?",
            },
            {
                "id": "implementation-boundaries",
                "concept": "implementation_boundaries",
                "title": "Implementation Boundaries",
                "explanation": "Implementation boundaries connect the reading to the files that express it in code.",
                "why_it_matters": "This keeps implementation grounded in system responsibilities.",
                "common_mistake": "Treating files as disconnected tasks.",
                "quick_check_question": "Which file owns which responsibility?",
            },
            {
                "id": "latency-metrics",
                "concept": "latency_metrics",
                "title": "Latency Metrics",
                "explanation": "Latency metrics describe how long the system takes to respond.",
                "why_it_matters": "They make performance reasoning concrete.",
                "common_mistake": "Quoting latency without context.",
                "quick_check_question": "What part of the path could increase latency?",
            },
            {
                "id": "benchmark-evidence",
                "concept": "benchmark_evidence",
                "title": "Benchmark Evidence",
                "explanation": "Benchmark evidence turns performance claims into inspectable results.",
                "why_it_matters": "It connects measurement to trust.",
                "common_mistake": "Reporting numbers without benchmark context.",
                "quick_check_question": "What makes a benchmark trustworthy?",
            },
        ],
    )


class FakeProvider:
    def generate_question_bank(self, week_spec, ledger_state):
        questions = [
            {
                "id": "prefill_decode_baseline",
                "depth": "baseline",
                "prompt_text": "Explain prefill vs decode.",
                "scoring_rubric": ["Mention prompt processing.", "Mention iterative decoding."],
            }
        ]
        questions.append(
            {
                "id": "baseline_metrics_reasoning",
                "depth": "baseline",
                "prompt_text": "How should you reason about tokens per second in relation to decode work?",
                "scoring_rubric": ["Connect the metric to decode throughput.", "Explain what the metric hides."],
            }
        )
        questions.extend(
            {
                "id": f"baseline_concept_{index}",
                "depth": "baseline",
                "prompt_text": f"Baseline concept question {index}",
                "scoring_rubric": ["Explain the concept clearly."],
            }
            for index in range(3, 19)
        )
        questions.extend(
            {
                "id": f"concept_deep_{index}",
                "depth": "deep",
                "prompt_text": f"Concept deep question {index}",
                "scoring_rubric": ["Explain the concept clearly.", "Include the key tradeoff."],
            }
            for index in range(1, 21)
        )
        questions.extend(
            {
                "id": f"stretch_tradeoff_{index}",
                "depth": "stretch",
                "prompt_text": f"Stretch tradeoff question {index}",
                "scoring_rubric": ["Discuss the ceiling-level tradeoff."],
            }
            for index in range(1, 13)
        )
        return LearningQuestionBankPayload(week=week_spec["number"], questions=questions)

    def generate_reading_material(self, week_spec, ledger_state, questions):
        return _reading_sections_for(questions)

    def generate_concept_cards_from_reading(self, week_spec, ledger_state, reading_sections):
        return _concept_cards_for(reading_sections)

    def generate_task(self, week_spec, ledger_state):
        raise AssertionError("Task generation is not exercised in this CLI test.")

    def score_learning_question(self, week_spec, question, answer, observation):
        return QuestionScore(passed=True, score_rationale="Sufficient answer.", missing_concepts=[])

    def answer_topic_chat(self, week_spec, context, history, message):
        return f"Topic tutor: {message}"


def test_init_and_status(monkeypatch, tmp_path):
    roadmap = tmp_path / "docs" / "plan.md"
    roadmap.parent.mkdir(parents=True, exist_ok=True)
    roadmap.write_text(
        f"""# 8-Week Inference Engineering Roadmap

## Overview

Overview text.

## Repository Structure

```
inference/
├── simple_server/
└── docs/
```

Repository description.

## Week 1: Build a Baseline Inference Server

### Goal

Run a model locally and expose it as an API.

### Narrative

This week establishes the baseline serving path and the first performance measurements.

### Topics Covered

- prefill vs decode

### By the End of This Week You Will Be Able To

- Explain how the baseline server works
- Measure the initial performance characteristics

### Assessment Targets

1. Explain prefill vs decode.
2. Describe how to measure the baseline server.

### Implementation

**Files created this week:**

- `simple_server/server.py` — API server entrypoint.

**Deliverables:** A baseline server in `simple_server/server.py`.

**Cloud deployment:** Not required.

### Key Resources

- Example resource.

{_extra_weeks()}

## Capstone Summary

### Artifacts Built

| Artifact | Location | Description |
|---|---|---|
| Baseline server | `simple_server/server.py` | Example |

### What You Can Now Do

You can ship the system.
"""
    )

    config = {
        "provider": "openai",
        "model": "test-model",
        "roadmap_path": "docs/plan.md",
        "target_repo_path": "ai_inference_engineering",
        "state_dir": "state",
    }
    (tmp_path / "learning_agent.config.json").write_text(json.dumps(config))
    (tmp_path / "ai_inference_engineering" / "simple_server").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("learning_agent.controller.get_provider", lambda _config: FakeProvider())

    init_result = runner.invoke(app, ["init"])
    assert init_result.exit_code == 0

    status_result = runner.invoke(app, ["status"])
    assert status_result.exit_code == 0
    assert "Week 1: Build a Baseline Inference Server" in status_result.stdout
    assert "simple_server/server.py" in status_result.stdout


def test_learn_generate_and_answer(monkeypatch, tmp_path):
    roadmap = tmp_path / "docs" / "plan.md"
    roadmap.parent.mkdir(parents=True, exist_ok=True)
    roadmap.write_text(
        f"""# 8-Week Inference Engineering Roadmap

## Overview

Overview text.

## Repository Structure

```
inference/
├── simple_server/
└── docs/
```

Repository description.

## Week 1: Build a Baseline Inference Server

### Goal

Run a model locally and expose it as an API.

### Narrative

This week establishes the baseline serving path and the first performance measurements.

### Topics Covered

- prefill vs decode

### By the End of This Week You Will Be Able To

- Explain how the baseline server works
- Measure the initial performance characteristics

### Assessment Targets

1. Explain prefill vs decode.
2. Describe how to measure the baseline server.

### Implementation

**Files created this week:**

- `simple_server/server.py` — API server entrypoint.

**Deliverables:** A benchmark note in `docs/baseline_results.md` measuring tokens/sec for the baseline server.

**Cloud deployment:** Not required.

### Key Resources

- Example resource.

{_extra_weeks()}

## Capstone Summary

### Artifacts Built

| Artifact | Location | Description |
|---|---|---|
| Baseline server | `simple_server/server.py` | Example |

### What You Can Now Do

You can ship the system.
"""
    )

    config = {
        "provider": "openai",
        "model": "test-model",
        "roadmap_path": "docs/plan.md",
        "target_repo_path": "ai_inference_engineering",
        "state_dir": "state",
    }
    (tmp_path / "learning_agent.config.json").write_text(json.dumps(config))
    (tmp_path / "ai_inference_engineering" / "simple_server").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ai_inference_engineering" / "docs").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("learning_agent.controller.get_provider", lambda _config: FakeProvider())

    assert runner.invoke(app, ["init"]).exit_code == 0

    generate_result = runner.invoke(app, ["learn", "generate"])
    assert generate_result.exit_code == 0
    assert "Generated Learning Assist for Week 1." in generate_result.stdout
    assert "prefill_decode_baseline" in generate_result.stdout

    answer_result = runner.invoke(
        app,
        ["learn", "answer", "--question-id", "prefill_decode_baseline", "--answer", "Prefill processes the prompt first."],
    )
    assert answer_result.exit_code == 0
    assert "Pass" in answer_result.stdout

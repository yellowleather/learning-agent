from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a deterministic demo Learning Agent UI server.")
    parser.add_argument("--code-root", default=None, help="Path to the Learning Agent codebase to import.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4010)
    return parser


class FakeProvider:
    def generate_raw_question_bank(self, week_spec, ledger_state):
        questions = [
            {
                "prompt_text": "Explain prefill vs decode.",
                "tier": "foundational_concepts",
                "topic_area": "prefill_vs_decode",
            }
        ]
        questions.extend(
            {
                "prompt_text": f"Concept deep question {index}",
                "tier": "foundational_concepts",
                "topic_area": "latency_metrics",
            }
            for index in range(2, 19)
        )
        questions.append(
            {
                "prompt_text": "How would you measure tokens per second?",
                "tier": "implementation_knowledge",
                "topic_area": "benchmarking",
            }
        )
        questions.extend(
            {
                "prompt_text": f"Implementation deep question {index}",
                "tier": "implementation_knowledge",
                "topic_area": "api_serving",
            }
            for index in range(2, 21)
        )
        questions.extend(
            {
                "prompt_text": f"Optimization question {index}",
                "tier": "optimization_and_production_insights",
                "topic_area": "throughput_tradeoffs",
            }
            for index in range(1, 13)
        )
        return {"week": week_spec.number, "questions": questions}

    def generate_concept_cards(self, week_spec, ledger_state, questions):
        return {
            "week": week_spec.number,
            "concept_cards": [
                {
                    "concept": "prefill_vs_decode",
                    "explanation": "Prefill handles the prompt while decode emits tokens.",
                    "why_it_matters": "Benchmark interpretation depends on this split.",
                    "common_mistake": "Treating all latency as one number.",
                    "quick_check_question": "Which phase grows first with prompt length?",
                }
            ],
        }

    def classify_question_bank(self, week_spec, ledger_state, questions):
        classified_questions = [
            {
                "id": "core_prefill",
                "type": "concept",
                "scope": "core",
                "depth": "baseline",
                "prompt_text": "Explain prefill vs decode.",
                "scoring_rubric": ["Mention prompt processing.", "Mention iterative decoding."],
                "roadmap_anchor": {"week": week_spec.number},
                "observation_required": False,
            }
        ]
        classified_questions.extend(
            {
                "id": f"core_concept_deep_{index}",
                "type": "concept",
                "scope": "core",
                "depth": "deep",
                "prompt_text": f"Concept deep question {index}",
                "scoring_rubric": ["Explain the concept clearly."],
                "roadmap_anchor": {"week": week_spec.number},
                "observation_required": False,
            }
            for index in range(2, 19)
        )
        classified_questions.append(
            {
                "id": "impl_measure_tokens",
                "type": "implementation",
                "scope": "core",
                "depth": "baseline",
                "prompt_text": "How would you measure tokens per second?",
                "scoring_rubric": ["Count generated tokens.", "Divide by decode time."],
                "roadmap_anchor": {"week": week_spec.number},
                "observation_required": False,
            }
        )
        classified_questions.extend(
            {
                "id": f"impl_deep_{index}",
                "type": "implementation",
                "scope": "core",
                "depth": "deep",
                "prompt_text": f"Implementation deep question {index}",
                "scoring_rubric": ["Describe the implementation tradeoff."],
                "roadmap_anchor": {"week": week_spec.number},
                "observation_required": False,
            }
            for index in range(2, 21)
        )
        classified_questions.extend(
            {
                "id": f"adjacent_opt_{index}",
                "type": "concept",
                "scope": "adjacent",
                "depth": "deep",
                "prompt_text": f"Optimization question {index}",
                "scoring_rubric": ["Discuss the tradeoff."],
                "roadmap_anchor": {"week": week_spec.number},
                "observation_required": False,
            }
            for index in range(1, 13)
        )
        return {"week": week_spec.number, "questions": classified_questions}

    def generate_gate_question(self, week_spec):
        raise AssertionError("Legacy gate is not exercised in the demo server.")

    def score_gate_answer(self, week_spec, question, answer):
        raise AssertionError("Legacy gate is not exercised in the demo server.")

    def generate_task(self, week_spec, ledger_state):
        raise AssertionError("Task generation is not exercised in the demo server.")

    def score_learning_question(self, week_spec, question, answer, observation):
        return {"passed": True, "score_rationale": "Good answer.", "missing_concepts": []}

    def generate_evidence_questions(self, week_spec, observation, learning_session):
        return {"week": week_spec.number, "questions": []}

    def answer_topic_chat(self, week_spec, context, history, message):
        return f"Tutor reply about: {message}"


def write_demo_config(workspace: Path) -> None:
    config = {
        "provider": "openai",
        "model": "test-model",
        "roadmap_path": "docs/plan.md",
        "target_repo_path": "ai_inference_engineering",
        "state_dir": "state",
    }
    (workspace / "learning_agent.config.json").write_text(json.dumps(config))


def write_demo_roadmap(workspace: Path) -> None:
    roadmap = workspace / "docs" / "plan.md"
    roadmap.parent.mkdir(parents=True, exist_ok=True)
    roadmap.write_text(
        """# 8-Week Inference Engineering Roadmap

# Week 1 --- Build a Baseline Inference Server

## Goal

Run a model locally and expose it as an API.

## Learn

Concepts:

- prefill vs decode

## Tasks

- Load a small LLM
- measure tokens/sec

## Deliverables

    simple_server/
        server.py

Document:

    docs/baseline_results.md
"""
    )


def prepare_workspace() -> Path:
    workspace = Path(tempfile.mkdtemp(prefix="learning_agent_demo_"))
    write_demo_config(workspace)
    write_demo_roadmap(workspace)
    (workspace / "ai_inference_engineering" / "simple_server").mkdir(parents=True, exist_ok=True)
    (workspace / "ai_inference_engineering" / "docs").mkdir(parents=True, exist_ok=True)
    return workspace


def main() -> None:
    args = build_parser().parse_args()
    code_root = Path(args.code_root).resolve() if args.code_root else Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(code_root))

    import learning_agent.controller as controller
    from learning_agent.ui import run_action, serve_ui

    workspace = prepare_workspace()
    old_cwd = Path.cwd()
    try:
        os.chdir(workspace)
        controller.get_provider = lambda _config: FakeProvider()
        run_action("init", {"action": ["init"]})
        run_action("learning_generate", {"action": ["learning_generate"]})
        print(f"Demo workspace: {workspace}", flush=True)
        serve_ui(host=args.host, port=args.port)
    finally:
        os.chdir(old_cwd)
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    main()

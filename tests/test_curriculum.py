from pathlib import Path

from learning_agent.curriculum import get_week_spec, load_curriculum


def test_week_one_is_parsed_from_the_real_roadmap():
    roadmap = Path("ai_inference_engineering/docs/inference_engineering_8_week_plan.md")
    metadata, weeks = load_curriculum(roadmap, "ai_inference_engineering")

    assert metadata.total_weeks == 8

    week_one = get_week_spec(weeks, 1)
    assert week_one.title == "Build a Baseline Inference Server"
    assert "simple_server/server.py" in week_one.required_files
    assert "simple_server/benchmark.py" in week_one.required_files
    assert "docs/baseline_results.md" in week_one.required_files
    assert week_one.active_dirs == ["simple_server", "docs"]
    assert "tokens_per_sec" in week_one.required_metrics

# Curriculum Generation

This directory holds prompt assets for generating standalone learning-plan workspaces.

`learning_agent curriculum bootstrap` reads a prompt from `curriculum_generation/prompts/`, sends that prompt text to Anthropic as-is, writes the returned markdown into the output repo path you provide, and initializes the target repo locally without precreating scaffold directories from the plan.

Typical usage:

```bash
export ANTHROPIC_API_KEY=your_key_here
.venv/bin/python -m learning_agent curriculum bootstrap \
  --prompt-path curriculum_generation/prompts/ai_inference_engineering_8_week_plan.md \
  --output-repo-path ai_inference_engineering
```

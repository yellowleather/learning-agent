# curriculum/

Curriculum reads, parsing, and bootstrapping. This package is the single source of truth for **what** is being taught; `coach/` is the runtime that paces the user through it.

## Layout

```
curriculum/
├── access.py        # CurriculumAccess — cached read API over the parsed roadmap
├── parser.py        # Parses the roadmap markdown into a dict
├── bootstrap.py     # `coach curriculum bootstrap` — generates a fresh roadmap from a prompt
├── prompts/         # Prompt assets used by bootstrap
└── tests/
```

## CurriculumAccess (`access.py`)

The read API used by the orchestrator and every stage. One instance per process; lazy-parses the roadmap on first access and caches it (PRD §3 declares the roadmap immutable for a run).

```python
from curriculum.access import CurriculumAccess

curriculum = CurriculumAccess(roadmap_path, target_repo_path="my_repo")

metadata   = curriculum.metadata()          # CurriculumMetadata
week_spec  = curriculum.current_week(1)     # dict
week_three = curriculum.week_by_number(3)   # dict
markdown   = curriculum.markdown()          # raw source, used by prior-knowledge prompts
```

## Parser (`parser.py`)

`load_roadmap_dict(path) -> dict[str, Any]` — parses the roadmap markdown into the dict shape downstream code consumes. Stages do not call the parser directly; they go through `CurriculumAccess`.

## Bootstrap (`bootstrap.py`)

Powers the `coach curriculum bootstrap` CLI command. Reads a prompt from `curriculum/prompts/`, sends it verbatim to Anthropic, writes the returned markdown into the output repo path, and initialises a git repo there. Used once when starting a brand-new curriculum.

```bash
export ANTHROPIC_API_KEY=your_key_here
.venv/bin/python -m coach curriculum bootstrap \
  --prompt-path curriculum/prompts/ai_inference_engineering_8_week_plan.md \
  --output-repo-path ai_inference_engineering
```

## Prompts (`prompts/`)

Curriculum-generation prompt templates. Each prompt produces one complete roadmap. Today: `ai_inference_engineering_8_week_plan.md`.

## Why this is its own package

`coach/` and `curriculum/` are deliberately separated:

- `curriculum/` is **content + generation** — the material and the tool that creates it.
- `coach/` is **runtime + pacing** — the workflow that walks a user through that material week by week.

This split keeps the runtime stable when the curriculum surface changes (new prompts, new generation strategies) and makes it easy to swap in different curricula without touching `coach/`.

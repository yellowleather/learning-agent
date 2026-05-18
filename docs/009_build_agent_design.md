# BuildAgent Design

> **Status (May 2026).** This is now partially implemented. The data
> foundation (models, persistence, archive flow), `verification_command`,
> provider agent-turn abstraction, BuildAgent prompts, local executor,
> seven-tool surface, and first agent runner are in place. `review_build`,
> post-failure UX, and the Verify-stage UI redesign remain open.

## 1. Why this agent exists

The Build step of the weekly workflow today is: the platform generates a
structured implementation brief via the provider, and the human writes
the code. The BuildAgent replaces the human-writes-the-code step with an
autonomous loop that produces the implementation, captures the work as a
structured report, and hands back to the user for review.

The unusual constraint relative to a typical coding agent: **the code
the agent writes is teaching material.** The user — a senior engineer
learning a new domain — reads the result to understand the system being
built. Optimisations that obscure the algorithm, speculative
abstractions, and clever-but-opaque code all hurt this product even if
the tests pass. The agent's pedagogy bias is what makes it different
from "just run Claude Code in the target directory."

## 2. Locked decisions

### 2.1 The agent is custom, not Claude Code / Codex

We considered shelling out to Claude Code with MCP + hooks instead of
building our own loop. Decided against:

- Claude Code is Anthropic-only, and we want to evaluate on both
  Anthropic and OpenAI.
- Path enforcement (writes confined to `active_dirs`), week scoping (no
  visibility into other weeks), custom tools (`record_metric`, `done`),
  and the structured `BuildReport` are all easier to land cleanly in our
  own loop than to retrofit into Claude Code via hooks and MCP.
- The pedagogy bias is a system-prompt-level concern; Claude Code's
  defaults are tuned for shipping code, not teaching code.

### 2.2 Provider abstraction from day one

The agent supports both Anthropic and OpenAI. The system prompt is
plain text — provider-agnostic. The agent loop has a thin provider
abstraction so the same prompt + tools + protocol works on either
vendor.

Mapping the provider-specific knobs:

| Concept                | Anthropic                                  | OpenAI                                              |
|------------------------|--------------------------------------------|-----------------------------------------------------|
| Tool use               | `messages.create` with `tools=...`         | Responses API or Chat Completions with `tools=...`  |
| Tool-use response      | `tool_use` content blocks                  | `tool_calls` field on the message                   |
| Tool result reply      | `tool_result` content block                | `tool` role message with `tool_call_id`             |
| Deep reasoning         | `thinking={type:"enabled", budget_tokens}` | Reasoning model (`o3`, `o4-mini`) + `reasoning_effort` |
| Streaming              | `messages.stream`                          | Responses streaming or Chat Completions streaming    |

### 2.3 The seven tools

The agent has exactly seven tools. Discovery and writes are restricted
to `target_repo_path / allowed_dirs`. Subprocess execution goes through
an allowlist and a per-call timeout.

1. **`read_file(path)`** — read a file under `target_repo_path`. Allowed
   to read outside `allowed_dirs` (reading neighbouring code is normal),
   but rejected if path resolves outside the target repo or matches the
   roadmap path.
2. **`list_dir(path)`** — list a directory under `target_repo_path`.
3. **`write_file(path, content)`** — create or overwrite a file. Path
   must resolve under `target_repo_path / allowed_dirs`. Rejected with
   a structured error otherwise; the agent can read the error and try
   the right path.
4. **`edit_file(path, old, new)`** — find-and-replace within an existing
   file. Same path constraints. Useful for incremental edits without
   re-emitting the whole file.
5. **`run_command(cmd)`** — subprocess execution. Allowlist:
   `pytest`, `python`, `uv`, plus the brief's `verification_command`.
   Output captured with a tail cap. Per-call wall-clock timeout. No
   shell parsing — args are a list.
6. **`record_metric(key, value)`** — write a numeric metric value into
   the ledger. Restricted to keys present in `required_metrics`.
7. **`done(status, summary, notes="")`** — terminal. Status is one of
   `completed` / `gave_up`. Called exactly once.

The platform fills in the rest of `BuildReport.commands_run`,
`files_touched`, `metrics_recorded` from observed tool calls. The agent
declares only `status`, `summary`, and `notes`.

### 2.4 Sandbox: subprocess + allowlist + 30-min wall clock

`LocalExecutor` is the v1 implementation behind a pluggable
`Executor` interface. It runs commands as the host user, with `cwd =
target_repo_path`, an argv-list (no shell), a per-call timeout, and tail
caps on stdout/stderr.

The 30-minute wall clock is enforced at the loop level, not per call.
If the agent is mid-tool-call when the budget hits, the executor cancels
the subprocess and the loop records `status="timed_out"`.

`DockerExecutor` and `RemoteGPUExecutor` are siblings the abstraction
admits without rewrites. Not built yet.

### 2.5 Three-strikes rule on the same failing fix

If the agent tries the same fix three times and it still fails, it
should either find a different approach or call `done(status="gave_up",
notes=...)` rather than spinning. The rule is in the system prompt; the
platform does not enforce it mechanically.

### 2.6 `gave_up` vs `timed_out`

Two distinct terminal failure modes:

- `gave_up` — agent itself recognised it was stuck and called `done` early.
- `timed_out` — platform killed the run at the 30-min mark; agent never
  got to call `done`.

Both are useful signals. The user reading the report can tell whether
the agent was self-aware about its limits.

### 2.7 No retry against Mentor verdicts

When `review_build` (the Mentor) judges the report and the verdict
fails on some facet, the platform halts and surfaces the verdict to the
user. The agent does **not** get a second pass to fix the build based on
the verdict. The user fixes things manually and can re-trigger
`review_build` without re-running the agent.

Within its own loop, the agent can iterate freely on tool errors or
failing tests — that's not a Mentor retry, that's the agent's normal
work.

### 2.8 `evidence_reliable` stays human

`review_build` will flip `verification_passed` (or not). The human
still flips `evidence_reliable` after looking at the diffs and the
output. That last human checkpoint survives the agent landing — it's
the pedagogical point of the platform.

### 2.9 `BuildReport` schema is locked and shipped

See `build/models.py`. Five Pydantic models:

- `CommandRun` — cmd, exit_code, stdout_tail, stderr_tail, duration_ms,
  truncated.
- `FileTouched` — path, action (`create | modify | delete`), diff,
  diff_truncated.
- `BuildReport` — status enum, summary, commands_run, files_touched,
  metrics_recorded, notes.
- `BuildSession` — week, started_at_utc, ended_at_utc, duration_seconds,
  turn_count, optional report.
- `TranscriptEvent` — seq, timestamp_utc, kind enum (`thought |
  tool_call | tool_result | tool_error | system`), payload.

All extend `StrictModel`. Status and kind enums are `Literal[...]` — new
values fail validation, forcing the enum to be extended on purpose.

`BuildSession` lives in `state/current_build.json`. The transcript is
**not** embedded; it lives in `state/current_build.transcript.jsonl` and
gets appended one event per line during the run. On `advance_week`,
both files move into `state/archive/week_N/` along with the learning
and task ephemerals.

### 2.10 System prompt structure

Lives at `build/prompts/build_agent_system.md` (to be written; the
draft language is captured below). Sections, in order:

- **Role + framing.** Functional ("You implement one week of...");
  no "Junior SWE" persona language. The user reads the code to learn.
- **Scope.** Allowed dirs, required files, no future weeks.
  `implementation_steps` define the order; build in that order.
  Verification command + expectations define "working". Don't claim
  `completed` unless verification exits 0.
- **Tools.** Names + one-line each + the recovery rule on tool errors
  (read the message, fix the call, don't repeat the same failing
  call).
- **Pedagogy.** Aim for the level of abstraction the problem warrants.
  Reach for small factories, context managers, dataclasses when they
  help readability. Skip patterns added on speculation. Avoid
  single-call helpers, premature optimisation, and "in case" class
  hierarchies.
- **Self-correction.** 30-min wall clock; three-strikes rule on the
  same failing fix; no clarifications.
- **Narrating.** One or two sentences between tool calls *for the user
  watching*, not internal monologue. Deep reasoning happens privately
  (extended thinking).
- **Completion.** `done(status, summary, notes)`. Status enum. Summary
  100–300 words narrating what was built and non-obvious choices.

### 2.11 User-message template

Lives at `build/prompts/build_agent_user.md` (to be written). Rendered
once at run start from the current week's `GeneratedTask` + the ledger's
`required_metrics`. Fields:

```
Week {{WEEK}}
Title: {{TITLE}}
Objective: {{OBJECTIVE}}

Allowed directories: {{ALLOWED_DIRS}}
Required files: {{REQUIRED_FILES}}

Implementation steps:
{{IMPLEMENTATION_STEPS}}

Acceptance checks:
{{ACCEPTANCE_CHECKS}}

Verification expectations:
{{VERIFICATION_EXPECTATIONS}}

Required metrics: {{REQUIRED_METRICS}}
Verification command: {{VERIFICATION_COMMAND}}

Begin.
```

`verification_command` is a new field on `GeneratedTask` (not yet added
— see §4). Today the verification command is implicit in
`verification_expectations` prose; we'll add an explicit field so the
agent doesn't have to infer.

### 2.12 Extended thinking enabled

The agent call enables deep internal reasoning that doesn't appear in
the transcript:

- Anthropic: `thinking={"type": "enabled", "budget_tokens": 8000}`
- OpenAI: pick a reasoning model + `reasoning_effort="high"`

The visible text the model emits between tool calls becomes pure
narration *for the user*, not the model thinking out loud. That keeps
the transcript clean while preserving reasoning depth.

### 2.13 `review_build` pre-fills observation; reflection stays human-only

When `review_build` (Mentor) judges the agent's `BuildReport`, the
platform pre-fills the user's `ObservationRecord` with the factual
fields the agent already captured:

- `command` (the verification command that was run)
- `artifact_path` (the deliverable path being measured)
- `latency_p95_ms`, `tokens_per_sec`, `prompt_tokens`, `output_tokens`
  (from the agent's `record_metric` calls)
- `notes` (a short summary derived from the agent's narrative)

**`reliability` is *not* pre-filled.** It always lands at `"uncertain"`,
regardless of how the run looked. The user must explicitly upgrade
`reliability` to `"valid"` (or one of the invalid variants) in the
Verify UI after reviewing the pre-filled values. Since
`evidence_reliable` only flips when `reliability == "valid"`, the
human-judgment gate is preserved end-to-end: the agent provides data,
the user provides judgment, an agent that "lies" about a metric value
can't bypass anything.

The `ReflectionRecord` is **never** pre-filled. Reflection is the user's
own take on whether the result is trustworthy and what would change
their confidence — drafting it on the user's behalf would defeat its
purpose.

### 2.14 Tool use via `LLMProvider.run_agent_turn`

The provider interface gets one more method:

```python
class LLMProvider(ABC):
    ...
    @abstractmethod
    def run_agent_turn(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        deep_reasoning: bool = True,
    ) -> AgentTurnResult: ...
```

We do **not** introduce a separate `AgentProvider` interface. Reasons:

- The codebase has exactly one agentic client today (BuildAgent). A
  parallel interface would buy nothing.
- The existing `LLMProvider` already aggregates several call shapes
  (`generate_question_bank`, `score_learning_question`,
  `answer_topic_chat`, …) — agentic is one more.
- If multiple agentic clients show up later (e.g. an agentic
  `review_build`), refactoring to a separate interface is mechanical.

The `deep_reasoning` flag maps to provider-native extended thinking:
Anthropic's `thinking={"type": "enabled", "budget_tokens": 8000}`,
OpenAI's reasoning-model + `reasoning_effort="high"`.

`AgentTurnResult` is a small typed wrapper around what comes back from
the API — text deltas, any tool calls the model wants to make, and a
terminal flag. Defined in `engine/providers/base.py` alongside the
method declaration.

## 3. Module layout (planned)

```
build/
├── stage.py           # BuildStage — gains start_agent() method
├── models.py          # (already shipped)
├── prompts.py
├── prompts/
│   ├── generate_task.md        # (already shipped)
│   ├── build_agent_system.md   # to write
│   └── build_agent_user.md     # to write
├── agent/
│   ├── tools.py       # The seven tool functions + their JSON schemas
│   ├── executor.py    # LocalExecutor — subprocess + allowlist + timeout
│   ├── loop.py        # The think → tool → observe loop
│   └── runner.py      # BuildAgent class — wires prompts + tools + executor + budget
└── tests/
```

## 4. Required upstream changes

- **Done:** add `verification_command: str` to `GeneratedTask` in
  `engine/models.py`. `build/prompts/generate_task.md` now asks the
  provider for the command explicitly.
- **Done:** extend the provider interface (`engine/providers/base.py`) with
  `run_agent_turn(system_prompt, messages, tools, deep_reasoning=True)`,
  mapped by the Anthropic and OpenAI providers.
- **Add `review_build` to the provider interface** (Mentor's verdict
  over a `BuildReport`). See §6.

## 5. Operating flow (planned)

```
User clicks "Start Build" in UI
   -> POST /run_build -> ui/server.py
   -> WeekOrchestrator.build.start_agent()
        - precondition: learning_check_passed
        - load current_task.json (the brief)
        - render build_agent_user.md from the brief
        - construct BuildSession (week, started_at_utc)
        - save current_build.json
   -> build.agent.runner.BuildAgent.run()
        - loop: think -> tool_use -> execute -> tool_result -> ...
        - each event appended to current_build.transcript.jsonl
        - tool call observations recorded into the eventual BuildReport
        - terminates when:
            * agent calls done(...)        -> status as declared
            * wall clock hits 30 min       -> status="timed_out"
            * user clicks Stop             -> status="stopped_by_user"
            * unrecoverable platform error -> status="errored"
        - assembles BuildReport from declared status/summary/notes + observed tool calls
   -> BuildSession.report = BuildReport
   -> save current_build.json
   -> UI surfaces "Build complete; review pending"
   -> [next step: review_build, then Verify UI]
```

## 6. Still-open decisions

### 6.1 Post-failure UX

When Mentor halts on a failing verdict, what does the user see and what
can they do?

**Working sketch:**

- A per-facet verdict panel (each `verification_expectation` ↔ pass/fail
  + Mentor's reasoning).
- A "Re-evaluate" button that re-runs `review_build` against the
  current state of the repo without re-running the agent.
- A "Reset build" button that clears `current_build.json` and
  `current_build.transcript.jsonl` if the user wants to start fresh.
- The current week stays at the Build stage; no gates advance.

Final answer pending. Once locked, this is where the Verify-stage UI
redesign starts.

### 6.2 Verify-stage UI redesign

Today's `render_verify_stage` is form fields for manual entry. After
the agent ships and `review_build` produces a multi-facet verdict, the
Verify stage becomes "review the agent's diffs + read the Mentor's
verdict + confirm reliability". The redesign is downstream of 6.1 —
design after that's locked.

### 6.3 Cost / token budgets

Currently only a 30-min wall clock. We agreed to defer dollar / token
ceilings to v2. Worth revisiting once we have a few real runs and can
see what budget the agent actually needs.

## 7. What this design does NOT cover

- The exact JSON schemas for each of the seven tools — those live in
  code, not in this document, and will be finalised when `agent/tools.py`
  is written.
- The exact text of the system prompt — captured here as structure +
  intent; the final language lands in `build/prompts/build_agent_system.md`
  during implementation.
- The implementation of `review_build` — covered separately once 6.1
  settles.
- The Verify-stage UI redesign — covered separately once 6.1 settles.

## 8. Related docs

- [001_prd.md](001_prd.md) — original PRD (with stale-framing note).
  The pedagogy + gating model still holds.
- [008_workspace_restructure.md](008_workspace_restructure.md) — package
  layout this agent lands inside.
- `build/README.md` — the package the agent lives in.
- `build/models.py` — the data shapes the agent emits.

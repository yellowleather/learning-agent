# build/

Everything that's specific to the **Build** step of the weekly workflow. The
package owns the stage controller, the data models the agent produces, the
prompts that shape build-domain artefacts, and the upcoming `BuildAgent`
(multi-turn loop with tools, executor, 30-min wall-clock budget).

## Layout

```
build/
├── stage.py             # BuildStage — gate-protected brief generation
│                        #   agent start, and the artifact-completion scan
├── models.py            # CommandRun, FileTouched, BuildReport,
│                        #   BuildSession, TranscriptEvent
├── prompts.py           # load_prompt / render_prompt for build/prompts/
├── prompts/             # build-domain prompt assets
├── agent/               # tools, local executor, and BuildAgent runner
└── tests/               # stage tests + persistence tests
```

## What lives here vs in engine/

The split between this package and `engine/` follows one rule: anything that
is *specific to the Build step* lives in `build/`; the cross-stage workflow
scaffolding lives in `engine/`.

Concretely:

- `BuildStage` is here — it owns the implementation-brief lifecycle and the
  artifact-completion gate.
- The five terminal-report models (`CommandRun`, `FileTouched`,
  `BuildReport`, `BuildSession`, `TranscriptEvent`) are here — they describe
  what a `BuildAgent` run emits.
- The build prompt (`generate_task.md`) is here — it shapes a build-domain
  artefact. The matching `prompts.py` loader is here too so the prompt and
  the call that loads it stay in one package.
- The persistence *paths* (`state/current_build.json`,
  `state/current_build.transcript.jsonl`) and the archive lifecycle stay in
  `engine.state.StateStore` because they're part of the cross-stage state
  surface — `archive_week_state` moves all four ephemeral files (learning,
  task, build, transcript) at once and shouldn't fragment across packages.
- `GeneratedTask` and `TaskSession` stay in `engine.models` — they predate
  the agent work and are also consumed by `VerifyStage` (which writes a
  verification record into the task session).

## The principle: facts, not judgements

`BuildReport` is shaped around one rule: the agent reports facts, not
judgements. Every field is something observable:

- `status` is one of five terminal states the agent declares
  (`completed | gave_up | timed_out | stopped_by_user | errored`).
- `commands_run` lists subprocess invocations with exit codes and tails of
  stdout/stderr.
- `files_touched` lists net file effects with truncated unified diffs.
- `metrics_recorded` mirrors what the agent passed to the `record_metric`
  tool.

Nothing in `BuildReport` says "verification passed" or "the build is good".
Those are judgements that belong to:

- `review_build` (the Mentor's structured verdict over the report)
- the human (via `evidence_reliable`, reflection)

Keeping facts in the report and judgements out of it is what makes the
review loop in `docs/001_prd.md` enforceable.

## Strict validation

All models extend `StrictModel` (`extra="forbid"`). The `status` and `kind`
enums are `Literal[...]`, so an agent that emits a new terminal mode or a
new transcript event kind fails validation loudly. That's deliberate — it
forces the enum to be extended on purpose, not by accident.

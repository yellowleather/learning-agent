# verify/

Everything that's specific to the **Verify** step of the weekly workflow.
The package owns the stage controller, the evidence-side data models, and
its tests.

## Layout

```
verify/
├── stage.py        # VerifyStage — observation / reflection / verification
│                   #   ledger writes; evidence-required policy;
│                   #   Evidence Reliability checkpoint card
├── models.py       # VerificationRecord, ObservationRecord, ReflectionRecord
└── tests/          # stage tests
```

## What lives here vs in engine/

Same rule as build/ and learn/: anything specific to the Verify step lives
here; cross-stage workflow scaffolding stays in engine/.

Concretely in this package:

- `VerifyStage` — the orchestrator-mounted handle for evidence-side
  operations. Owns `verification_passed` and `evidence_reliable` gates.
- The three evidence-shaped models — `VerificationRecord`,
  `ObservationRecord`, `ReflectionRecord`.

Cross-stage scaffolding stays in `engine/`:

- The ledger paths and lifecycle (`current_task.json` is what
  `record_verification` writes into; the file itself is owned by
  `engine.state.StateStore`).
- The `Ledger` / `ProgressState` / `Gates` models — they include
  `verification`, `observation`, `reflection` slots because the ledger is
  the cross-stage state surface, but the types of those slots live here.
- `TaskSession` stays in `engine.models` because it bundles a build artefact
  (`GeneratedTask`) with its eventual verification result, crossing two
  stages.

## Two gates, two authorities

Verify exposes two distinct gates that flip on different evidence:

- **`verification_passed`** — flipped by `record_verification(passed,
  summary)`. Today the user records this directly. Once `BuildAgent` and
  `review_build` land, the Mentor's review will flip it based on the
  agent's multi-faceted report.
- **`evidence_reliable`** — flipped via `record_observation(observation)`
  when the observation's `reliability` is `"valid"`, *and* held against
  `record_reflection(reflection)` — a buggy or untrustworthy reflection
  clears it. This gate is the human checkpoint that survives the agent
  landing: even when Mentor says verification passed, the user is the
  final authority on whether the evidence is trustworthy.

Both gates must be true before `WeekOrchestrator.approve_week` will let
the week advance (alongside `learning_check_passed` and
`implementation_complete`).

# System Design Document: Dual-Persona Learning Agent Platform

## 1. Executive Summary

The **Dual-Persona Learning Agent** is a curriculum-driven software agent that helps a senior software engineer learn new technical domains by building real artifacts in a target repository.

The system uses a **Mentor / Junior SWE** operating model:

- The **Mentor** is responsible for pedagogy, progression, and review.
- The **Junior SWE** is responsible for scoped execution inside the target repository.

The purpose of this split is not roleplay. It is to enforce a learning loop in which:

- the human user must understand the current topic before progressing,
- implementation stays aligned to the current stage of the curriculum,
- future material remains hidden until it is unlocked,
- the repository evolves as a clean portfolio of functional systems instead of a pile of tutorial artifacts.

This document describes both:

- the **Ideal Design**: the fully enforced, long-term target architecture,
- the **Phase-wise Design**: the practical path to building the system incrementally in Codex / VS Code.

## 2. Product Goal

The system should make it difficult for the user to skip the learning process while still making it easy to build, test, and review real code.

At a high level, the platform must:

1. accept a curriculum as markdown,
2. keep persistent progress state outside model context,
3. expose only the currently unlocked week,
4. delegate implementation work to an execution persona,
5. verify that required work was actually completed,
6. preserve a strong artifact trail for later review.

## 3. Core Assumptions

The current version of the design assumes:

- the curriculum is provided as markdown,
- the curriculum markdown is immutable for the duration of a run,
- future curriculum material is always hidden from the user and the execution persona until unlocked,
- the target repository is a separate repo that contains the actual hands-on work,
- strict tool- and path-level enforcement may be deferred in early versions.

## 4. Ideal Design

## 4.1 System Topology

The ideal system operates across two logically separate workspaces:

```text
learning-agent/                  (Agent platform)
├── personas/                    # Mentor and Junior persona definitions
├── controllers/                 # Orchestration logic
├── parsers/                     # Curriculum parsing and normalization
├── policies/                    # Validation and enforcement policies
├── state/
│   └── progress_ledger.json     # Persistent runtime state
└── docs/
    └── design_doc.md

ai_inference_engineering/        (Target repository)
├── simple_server/
├── benchmarking/
├── vllm_experiments/
├── quantization_tests/
├── profiling/
├── scaling_tests/
└── inference_platform/
```

The agent platform owns orchestration and persistent state. The target repository owns learning artifacts and execution outputs.

## 4.2 Roles

### Human User

- provides architectural intent,
- answers concept checks,
- reviews outputs,
- approves progression between weeks.

### Mentor

- owns curriculum progression,
- reads and updates the progress ledger,
- decides what the current week allows,
- hides future material,
- asks the user conceptual questions before unlock,
- reviews execution outputs before marking work complete.

### Junior SWE

- receives only the currently unlocked scope,
- writes code and supporting artifacts for the active week,
- runs verification commands,
- reports results back to the Mentor,
- does not teach or broaden scope on its own.

## 4.3 Curriculum Model

The **markdown roadmap** is the user-facing source of curriculum truth.

Internally, the system may derive a structured representation from the markdown for execution and validation. That internal representation is an implementation detail; the user only needs to provide markdown.

The curriculum layer is responsible for defining, for each week:

- learning goals,
- conceptual topics,
- allowed implementation scope,
- expected artifacts,
- verification requirements,
- unlock conditions.

## 4.4 State Management

Persistent continuity is maintained via a ledger that lives outside model context.

The ledger tracks runtime state, not the full curriculum. In the ideal design it includes:

```json
{
  "curriculum_metadata": {
    "title": "AI Inference Engineering",
    "total_weeks": 8,
    "target_repo": "./ai_inference_engineering/"
  },
  "state": {
    "current_week": 1,
    "active_functional_dirs": ["simple_server"],
    "gates": {
      "socratic_check_passed": false,
      "implementation_complete": false,
      "verification_passed": false,
      "week_approved": false
    },
    "artifacts": {
      "required_files": [
        "simple_server/server.py",
        "simple_server/benchmark.py"
      ],
      "completed_files": []
    },
    "metrics": {
      "required": ["latency_p95", "tokens_per_sec"],
      "recorded": {}
    }
  }
}
```

Notes:

- This is an **example snapshot**, not a universal policy for every week.
- Values such as `active_functional_dirs`, required artifacts, or required metrics may vary by week.

## 4.5 Ideal Enforcement Model

In the ideal system, the platform enforces the following guarantees:

- the Junior SWE cannot write outside the currently allowed paths,
- the Mentor is the only component allowed to mutate progress state,
- future weeks are not exposed until unlocked,
- week progression requires both conceptual and execution completion,
- verification must succeed before a week can be approved.

This enforcement is implemented through platform-level validation and tool boundaries, not through prompts alone.

## 4.6 Ideal Tooling Interfaces

The exact host environment is not important. The ideal system requires equivalent capabilities to:

1. `ledger_read()` and `ledger_update()`
2. `curriculum_parse(path)`
3. `validate_scope(task_or_path, current_state)`
4. `workspace_write(path, content)`
5. `workspace_execute(command, execution_profile)`
6. `artifact_check(expected_artifacts, current_week)`

These are interface responsibilities, not commitments to a specific framework.

## 4.7 Ideal Operating Loop

The ideal end-state loop is:

1. Mentor reads the ledger and curriculum markdown.
2. Mentor derives the current week scope.
3. Mentor asks a concept question for the current unlock gate.
4. If the user passes, Mentor marks the conceptual gate as passed.
5. Mentor delegates a scoped task to the Junior SWE.
6. Junior SWE implements only within the active scope.
7. Junior SWE runs verification.
8. Mentor checks artifacts, metrics, and verification outputs.
9. Mentor presents results to the user.
10. User approves the week.
11. Mentor updates the ledger and unlocks the next week.

## 5. Phase-wise Design

The system will not start with the full ideal enforcement model. The implementation will progress in phases.

## 5.1 Phase 1: Guided Single-Controller MVP

### Goal

Build a practical version that works well in Codex / VS Code without requiring full multi-agent orchestration or hard tool-level isolation.

### Characteristics

- one controller owns the workflow,
- Mentor and Junior SWE exist as logical modes rather than fully isolated agents,
- the curriculum is read from markdown,
- the ledger is the only mutable source of runtime state,
- future weeks remain hidden,
- strict path enforcement is deferred,
- curriculum change detection is deferred,
- host-specific orchestration frameworks are ignored.

### Responsibilities

In Phase 1, the controller must still do the important learning work:

- read the markdown roadmap,
- determine the current week,
- hide future weeks,
- ask the user the current conceptual gate question,
- update the ledger when the concept gate is passed,
- generate a scoped implementation task,
- record verification status,
- record required metrics,
- require explicit approval before progression.

### Phase 1 State Model

Phase 1 should use a ledger shape close to the ideal model, even if enforcement is lighter:

```json
{
  "state": {
    "current_week": 1,
    "active_functional_dirs": ["simple_server"],
    "gates": {
      "socratic_check_passed": false,
      "implementation_complete": false,
      "verification_passed": false,
      "week_approved": false
    },
    "artifacts": {
      "required_files": [],
      "completed_files": []
    },
    "metrics": {
      "required": [],
      "recorded": {}
    }
  }
}
```

### What Is Explicitly Deferred

- hard write-path enforcement,
- host-level sandboxing,
- isolated multi-agent execution,
- curriculum markdown change detection,
- remote execution abstraction,
- strict tool authorization boundaries.

### Definition of Done for Phase 1

A week is complete only when:

1. the user passes the concept gate,
2. the expected implementation artifacts exist,
3. verification has run and passed,
4. required metrics are recorded,
5. the user approves progression.

## 5.2 Phase 2: Enforced Local Boundaries

### Goal

Add actual platform enforcement while staying within a local development environment.

### Additions

- path-level write validation against `active_functional_dirs`,
- explicit artifact validation,
- standardized execution profiles for local verification,
- clearer separation between Mentor-only state mutation and Junior-only execution,
- deterministic hiding of future weeks at the parser/task layer.

### Expected Outcome

At the end of Phase 2, the platform should no longer rely primarily on prompt discipline to keep the execution persona in bounds.

## 5.3 Phase 3: Full Dual-Persona Platform

### Goal

Reach the original ideal design with stronger role isolation, execution controls, and richer verification.

### Additions

- fully separated Mentor and Junior SWE runtime contexts,
- strict permission boundaries around ledger mutation and workspace writes,
- execution adapters for local, containerized, and remote/GPU environments,
- curriculum change detection and migration strategy,
- stronger auditability of week transitions and generated artifacts.

### Expected Outcome

At the end of Phase 3, the system behaves like a true dual-persona learning platform rather than a single-controller simulation of one.

## 6. Policy Design

## 6.1 Structure Policy

The target repository must reflect functional architecture, not chronological tutorial sprawl.

Rules:

- the system should prefer functional directories such as `simple_server/` or `profiling/`,
- temporal directories such as `week_1/` are discouraged and should eventually be forbidden,
- the active week may authorize one or more functional directories,
- only directories required by the current week should be active.

In Phase 1 this is mostly policy. In later phases it becomes an enforced constraint.

## 6.2 Pedagogy Policy

The Mentor must preserve the learning structure.

Rules:

- the user cannot progress without passing the current concept gate,
- future material remains hidden until unlocked,
- the Junior SWE receives only the current scoped task,
- week completion requires both conceptual and implementation evidence.

## 6.3 Verification Policy

The system should verify execution, not just generate code.

Verification evidence may include:

- tests,
- benchmark outputs,
- service startup checks,
- generated result files,
- required metrics logged for the week.

Phase 1 may use lightweight local verification. Later phases can introduce richer execution environments.

## 7. Open Later-Version Work

These items are intentionally kept in the design but deferred from the initial build:

- strict workspace write isolation,
- host-level sandboxed execution,
- explicit multi-agent runtime separation,
- curriculum change detection,
- migration strategy if the curriculum changes after progress has been recorded,
- remote verification on GPU-backed environments,
- more advanced audit and review workflows.

## 8. Recommended Initial Build Order

1. Define the ledger schema.
2. Implement markdown curriculum parsing.
3. Implement current-week extraction with future-week hiding.
4. Implement concept-gate flow.
5. Implement scoped task generation.
6. Implement verification and metric recording.
7. Add user approval flow for week progression.
8. Add hard enforcement features in later phases.

## 9. Summary

The long-term goal remains a rigorously enforced dual-persona learning system.

The near-term implementation should not overfit to a specific orchestration stack or pretend that strict isolation already exists. Instead, Phase 1 should deliver the core pedagogical loop with persistent state, hidden future scope, artifact tracking, and explicit approval-based progression.

Later phases can progressively harden the system until it matches the full ideal design.

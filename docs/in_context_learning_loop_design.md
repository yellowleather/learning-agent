# In-Context Learning Loop Design Doc

## 1. Purpose

This document defines the **In-Context Learning Loop**, a feature that brings a meaningful portion of learning onto the platform itself instead of relying primarily on out-of-context reading or ad hoc external questioning.

The feature is designed for a senior software engineer learning a new technical domain through real implementation work in a target repository.

The intent is not to replace all external reading. The intent is to ensure that, to a reasonable degree, the user can:

- learn the current week's core concepts on-platform,
- answer rigorous questions about those concepts,
- implement the current week's artifacts,
- produce and interpret observable results,
- unblock or halt progression when evidence is unreliable.

## 2. Problem Statement

The current platform design enforces progression and artifact completion, but most actual learning still happens outside the system. That is a gap for two reasons:

- the platform can verify completion more easily than it can verify understanding,
- later weeks can become unstable if earlier artifacts or measurements are wrong but still treated as valid.

The In-Context Learning Loop adds a structured learning-and-evidence loop around implementation so that progression depends on both execution and understanding.

## 3. Goals

The In-Context Learning Loop must:

1. provide on-platform concept teaching for the current unlocked week,
2. generate a sizable question bank per week for coverage, typically 12-50 questions,
3. support rigorous free-text questioning, not just lightweight checks,
4. connect questions to the current week's implementation artifacts and required metrics,
5. collect structured observations from actual runs,
6. ask evidence-based questions grounded in those observations,
7. allow the user to report buggy or unreliable outcomes without forcing fake certainty,
8. block progression if the platform cannot establish reliable evidence for the current week,
9. keep all learning scoped to the current unlocked week.

## 4. Non-Goals

The In-Context Learning Loop does not aim to:

- replace all external learning material,
- become a general-purpose tutoring product,
- introduce guided debugging as a standalone curriculum feature,
- guarantee that model-generated code is correct,
- automatically infer trustworthy conclusions from arbitrary logs without structured inputs.

## 5. Design Principles

### 5.1 Coverage Over Minimalism

The system should prefer broad coverage over a tiny assessment set. For new domains such as inference engineering, even foundational terminology and distinctions matter.

### 5.2 Academic Rigor Is Acceptable

Explicit conceptual questioning is not a flaw. Foundational and academic questions are useful, especially when the user's baseline in a new field may be shallow.

### 5.3 Free-Text Questions Remain Core

The system should rely primarily on free-text questions scored against rubrics. Multiple-choice questions are not the main vehicle for serious understanding.

### 5.4 Evidence Beats Assertion

The strongest understanding checks are questions grounded in the user's own artifacts, metrics, and observations.

### 5.5 Unreliable Evidence Blocks Progression

If the implementation or measurement is buggy enough that observations cannot be trusted, later modules must remain locked until the issue is fixed.

## 6. Core Concepts

The In-Context Learning Loop is built from four primitives.

### 6.1 Concept Card

A concept card is a short teaching unit for the current week. It contains:

- a concise explanation,
- why the concept matters for the current week's artifacts,
- a common mistake or misconception,
- optionally one quick check question.

Concept cards are user-optional in the UI, but they are part of the feature design scope.

Week 1 example:

- `concept`: `prefill_vs_decode`
- `explanation`: "Prefill processes the full prompt in parallel to establish initial model state. Decode generates output tokens one at a time, reusing cached state from earlier steps."
- `why_it_matters`: "This distinction helps the user interpret why prompt length affects latency and why generation remains sequential."
- `common_mistake`: "Treating total latency as one undifferentiated number and not separating prompt-processing cost from token-generation cost."
- `quick_check_question`: "If prompt length doubles but output length stays fixed, which part of end-to-end latency would you expect to grow first?"

### 6.2 Question

A question is an assessment unit. Questions are generated and stored with explicit metadata.

Each question should have:

- `type`
- `scope`
- `depth`
- `prompt_text`
- `scoring_rubric`
- `roadmap_anchor`
- `observation_required`

Field explanations:

- `type`: whether the question is conceptual, implementation-oriented, or grounded in observed results.
- `scope`: whether the question is required for the current week, adjacent enrichment, or better suited for a later week.
- `depth`: whether the question is baseline, deep, or stretch difficulty.
- `prompt_text`: the exact question shown to the user.
- `scoring_rubric`: the specific ideas required for a passing answer.
- `roadmap_anchor`: the curriculum concept, deliverable, or metric the question is tied to.
- `observation_required`: whether the question depends on actual measured output from the user's artifact.

Week 1 example:

- `type`: `concept`
- `scope`: `core`
- `depth`: `baseline`
- `prompt_text`: "What is the difference between prefill and decode, and why does that difference matter when benchmarking a simple inference server?"
- `scoring_rubric`: "A passing answer must explain that prefill processes the prompt, decode generates tokens sequentially, and the distinction matters because latency behavior differs across the two phases."
- `roadmap_anchor`: `{ "week": 1, "concept": "prefill_vs_decode", "deliverable": "simple_server/benchmark.py" }`
- `observation_required`: `false`

### 6.3 Observation

An observation is a structured record of what happened when the user ran or measured the current week's artifact.

Observations should be week-specific and schema-driven. For example, Week 1 may require:

- command run,
- prompt/input size,
- output size,
- latency metrics,
- tokens per second,
- artifact path where results were recorded.

Week 1 example:

```json
{
  "command": ".venv/bin/python simple_server/benchmark.py",
  "prompt_tokens": 512,
  "output_tokens": 128,
  "latency_p95_ms": 840,
  "tokens_per_sec": 32.4,
  "artifact_path": "docs/baseline_results.md"
}
```

### 6.4 Reflection

A reflection is a free-text interpretation of the result. It must allow the user to state:

- what happened,
- whether the result matches expectation,
- whether the result is trustworthy,
- whether the implementation or measurement appears buggy,
- what should be fixed next if the evidence is unreliable.

Week 1 example:

"Latency increased noticeably as prompt size grew, while tokens per second stayed in a similar range. That suggests prompt processing cost is a major factor here, which is consistent with prefill work growing with input length. I trust the result enough to reason from it because the benchmark was run after warm-up and produced consistent values across repeated runs."

## 7. Question Model

The system should not use a single tier axis for everything. It should separate question type from scope and depth.

### 7.1 Question Type

- `concept`
- `implementation`
- `evidence_based`

### 7.2 Scope

- `core`
- `adjacent`
- `later_week`

### 7.3 Depth

- `baseline`
- `deep`
- `stretch`

This model allows the system to keep broad question banks without confusing "interesting" with "required now."

Week 1 classification examples:

- `concept/core/baseline`: "What is TTFT, and how is it different from tokens per second?"
- `implementation/core/baseline`: "How would you load a HuggingFace causal language model and expose it through `POST /generate`?"
- `concept/adjacent/deep`: "Why is decode often described as more memory-bound than prefill?"
- `concept/later_week/stretch`: "Why might a production system separate prefill and decode into different schedulers?"

## 8. Weekly Question Bank Strategy

Each week should have a sizable question bank, typically 12-50 questions. The bank should include:

- foundational concept checks,
- implementation-readiness questions,
- evidence-based questions that activate only after observations exist.

The system should preserve both:

- broad foundational questions for coverage,
- deeper conceptual probes for stretch and advanced rigor.

Deep conceptual probes are valuable but should not automatically become mandatory unlock gates unless they align directly with the week's required scope.

## 9. Weekly Learning Flow

The In-Context Learning Loop for a given week is:

1. Load the current unlocked week.
2. Optionally show concept cards if `Learning Assist` is enabled in the UI.
3. Ask a sizable set of `concept` and `implementation` questions.
4. Score the responses against current-week rubrics.
5. Generate the Junior SWE task for the week.
6. Implement and verify the required artifacts.
7. Collect a structured observation from the resulting artifact or benchmark.
8. If the observation is sufficiently reliable, ask `evidence_based` questions tied to that observation.
9. Collect a reflection from the user.
10. Decide whether the week has satisfied conceptual, implementation, verification, and evidence reliability gates.
11. Unlock the next week only after all required gates pass and the user approves.

## 10. Subgates Within a Week

A single week may contain multiple learning loops.

The week remains the progression boundary for unlocking future material, but the platform may divide the week into smaller subgates or milestones. In this design, subgates are treated as **linear checkpoints** derived by the controller from the current week's content. The curriculum input remains week-level; the curriculum markdown does not need to declare subgates explicitly.

Each checkpoint runs its own mini learning loop:

1. teach the relevant concept,
2. ask the relevant questions,
3. perform the scoped build or measurement step,
4. collect an observation if applicable,
5. collect a reflection if applicable,
6. decide whether the checkpoint passes or fails.

Linear checkpoints are useful when later work in the same week depends on earlier work being correct and trustworthy, but the system does not need the complexity of a general dependency graph.

### 10.1 Design Rules for Subgates

- a week may have zero or more subgates,
- subgates are derived by the controller from the current week's concepts, deliverables, and verification needs,
- subgates must remain fully scoped to the current unlocked week,
- subgates should be used only when they materially reduce risk or improve clarity,
- a week should usually have a small number of subgates, typically 2-5,
- subgates are linear checkpoints, not a dependency graph,
- only the current checkpoint is active at any time,
- later checkpoints are unavailable until earlier required checkpoints pass,
- a required week-level pass means all required subgates have passed.

### 10.2 Week 1 Example Subgates

For Week 1, a reasonable subgate structure could be:

- `core_concepts`
  Covers token generation, prefill vs decode, latency vs throughput, and tokens per second.
- `model_serving`
  Confirms that the model loads, inference works, and `POST /generate` is functional.
- `benchmarking`
  Confirms that `simple_server/benchmark.py` produces the required measurements.
- `evidence_reliability`
  Confirms that the benchmark output is trustworthy enough to reason from.

This prevents the system from treating a finished file tree as sufficient when the benchmark or measurement logic is still broken.

### 10.3 Subgate Failure Handling

If a subgate check fails, the platform should not treat that as a vague error. It should record a clear checkpoint state and stop progression through the linear sequence.

Recommended subgate states:

- `not_started`
- `in_progress`
- `passed`
- `failed`

Where:

- `failed` means the current attempt did not satisfy the required rubric, implementation check, verification check, or evidence-reliability check.

When a required subgate fails:

1. the system records the failure reason,
2. later checkpoints do not open,
3. the Junior SWE agent may make a bounded remediation attempt if the issue is within agent scope,
4. if the agent cannot fix the issue, the user is prompted to intervene,
5. the week cannot pass until the required subgate passes.

Week 1 examples:

- if `core_concepts` fails, the user may retry after reviewing concept cards or feedback, but week completion remains blocked,
- if `model_serving` fails, the next checkpoint does not open,
- if `benchmarking` fails, the evidence checkpoint does not open,
- if `evidence_reliability` fails, later modules remain locked until trustworthy results are established.

## 11. Example Walkthrough: Week 1

The following example shows what the In-Context Learning Loop looks like in practice for Week 1 of the inference engineering roadmap.

### 11.1 Teach

The UI shows a concept card for `prefill_vs_decode`:

- explanation: prefill processes the prompt, while decode generates tokens sequentially,
- why it matters: benchmarking must distinguish prompt-processing cost from token-generation cost,
- common mistake: treating all latency as one number with no phase-level interpretation.

### 11.2 Concept and Implementation Questions

The system asks a sizable set of questions from the current week's larger bank. The examples below are illustrative only and do not represent the full coverage set:

- concept: "What is the difference between latency and throughput in a simple inference server?"
- concept: "Why does prompt length affect prefill more directly than decode?"
- implementation: "How would you measure tokens per second in `simple_server/benchmark.py`?"
- implementation: "Why should the server use inference mode or `torch.no_grad()` during generation?"

The user's answers are scored against current-week rubrics. A failed answer does not automatically end the session, but required coverage must eventually be satisfied.

### 11.3 Build

The Junior SWE task is generated for the current week. The user or agent implements:

- `simple_server/server.py`
- `simple_server/benchmark.py`
- `docs/baseline_results.md`

The system then runs or records normal artifact and verification checks.

### 11.4 Observe

After the benchmark runs, the user submits a structured observation such as:

```json
{
  "command": ".venv/bin/python simple_server/benchmark.py",
  "prompt_tokens": 512,
  "output_tokens": 128,
  "latency_p95_ms": 840,
  "tokens_per_sec": 32.4,
  "artifact_path": "docs/baseline_results.md"
}
```

### 11.5 Evidence-Based Questions

If the observation is reliable enough, the system asks questions grounded in the observed result, for example:

- "Latency rose as prompt length increased. Is that more consistent with prefill cost, decode cost, or both?"
- "If tokens per second remained in a similar range while total latency increased, what does that suggest about the bottleneck?"
- "Does the result in `docs/baseline_results.md` match your earlier expectation? If not, what assumption was wrong?"

These questions are stronger than pure concept checks because they require the user to reason from their own artifact.

### 11.6 Reflect

The user submits a reflection such as:

"The benchmark results suggest prompt-processing cost is a major contributor to latency growth. Tokens per second stayed relatively stable, so decode speed does not appear to have changed much across prompt sizes. I trust the observation because repeated runs were consistent after warm-up."

If instead the user reports:

"The benchmark output is inconsistent across runs and I think the timing code is buggy,"

then the system records the evidence as unreliable instead of pretending the result is good enough to learn from.

### 11.7 Gate Decision

The system decides whether the week can progress.

Week 1 can advance only if:

- concept and implementation coverage are sufficient,
- required artifacts are complete,
- verification passes,
- the benchmark evidence is reliable,
- the user approves progression.

If the evidence is unreliable and the agent cannot fix it, the user must intervene before Week 2 can unlock.

## 12. Required vs User-Optional Behavior

The distinction must be between runtime user choice and design scope.

### 12.1 User-Optional at Runtime

- showing concept cards,
- choosing a lighter or heavier assessment mode,
- answering deep/stretch questions beyond the required core set.

### 12.2 Required in Design Scope

- concept cards,
- sizable question banks,
- concept and implementation questioning,
- observation capture,
- evidence-based questioning,
- reflection capture,
- explicit evidence reliability gating.

User-optional at runtime does not mean out of scope for the design.

## 13. Evidence Reliability

Reliable evidence is required for progression.

### 13.1 Definition

Evidence is considered reliable when:

- the artifact executes or measures as intended,
- the measurement method is acceptable for the current week,
- the required observation fields are populated,
- the resulting data is trustworthy enough to reason from.

### 13.2 Invalid Evidence States

The system should be able to classify the current state as:

- `valid`
- `invalid_due_to_bug`
- `invalid_due_to_bad_measurement`
- `uncertain`

### 13.3 Progression Rule

If evidence is not reliable, the current week is blocked.

That means:

- evidence-based questions cannot be treated as valid proof of understanding,
- later modules remain locked,
- the Junior SWE agent cannot proceed to downstream work that depends on the current artifact,
- the user must be prompted to resolve the blocker if the agent cannot.

## 14. Blocker Handling

If the implementation or measurement is unreliable:

1. the system records the blocker,
2. the Junior SWE agent may make a bounded attempt to fix or clarify the issue,
3. if the agent succeeds, verification and observation are rerun,
4. if the agent cannot resolve the issue, the user is prompted to intervene,
5. progression remains blocked until reliable evidence is established.

This prevents later modules from inheriting unstable or misleading foundations.

## 15. Gates and State Transitions

The existing progression model should be extended with an explicit evidence-reliability gate.

### 15.1 Gates

- `concept_coverage_satisfied`
- `implementation_complete`
- `verification_passed`
- `evidence_reliable`
- `week_approved`

### 15.2 Advancement Rule

A week can advance only if all of the following are true:

- required concept and implementation coverage has been achieved,
- required files and artifacts are complete,
- verification has passed,
- evidence is reliable,
- the user has approved progression.

## 16. UI Design

The UI-facing name of the feature should be **Learning Assist**.

The design/system name remains **In-Context Learning Loop**.

### 16.1 Primary UI Elements

- `Learning Assist` toggle
- current week concept cards
- sizable question set view
- observation submission form
- reflection text area
- blocker state and next required action

### 16.2 UX Expectations

- the UI must clearly distinguish concept questions from evidence-based questions,
- the UI must make it clear when evidence is considered unreliable,
- the UI must tell the user whether the Junior SWE agent is blocked,
- the UI must not reveal future-week material.

## 17. Content Generation Strategy

The platform may use an LLM to generate:

- concept cards,
- question banks,
- rubrics,
- evidence-based follow-up questions.

Generated content must be constrained by:

- current unlocked week only,
- roadmap concepts for the week,
- current deliverables,
- required metrics,
- allowed directories and artifacts.

LLM generation is a bootstrap mechanism, not the final source of truth. Generated questions should be tagged, reviewed, and trimmed to current scope when necessary.

## 18. Phase 1 Fit

This feature fits Phase 1 if implemented incrementally.

### 18.1 Phase 1 Additions

- extend the provider layer to generate concept cards and question banks,
- add question metadata and observation models,
- add reflection capture,
- add the `evidence_reliable` gate,
- add blocked-state handling in the controller,
- extend the UI with `Learning Assist`, observation entry, and reflection entry.

### 18.2 Deferred Work

- long-term misconception memory across weeks,
- personalized remediation based on repeated errors,
- fully automated interpretation of arbitrary benchmark outputs,
- hard enforcement of agent write boundaries,
- richer adaptive assessment sequencing.

## 19. Open Design Decisions

The following still need explicit product decisions:

- how many `core` questions must be answered to satisfy coverage for a week,
- whether `Coverage mode` and `Focused mode` should both ship in Phase 1,
- how many retry attempts the agent gets before escalating to the user,
- whether observations are entered manually, uploaded from structured files, or both,
- how strict evidence-based scoring should be when the observation is only partially reliable.

## 20. Summary

The In-Context Learning Loop upgrades the platform from a progression engine into a tighter learning-and-evidence system.

It does this by combining:

- on-platform concept teaching,
- sizable question banks,
- implementation-linked assessment,
- structured observations,
- evidence-based questioning,
- explicit blockage when evidence is unreliable.

The key product rule is simple: later learning should not build on untrusted artifacts or untrusted measurements.

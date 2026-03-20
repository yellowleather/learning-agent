# Polished UI Modernization Plan

## 1. Purpose

This document captures the planned evolution of the Learning Agent UI from the current Phase 1 local control surface into a more polished product experience.

The goal is not a visual refresh alone. The goal is to support a better learning workflow:

- visual concept cards,
- chapter-style reading material with images,
- side-by-side reading and question answering,
- a more guided "open book exam" experience,
- a frontend architecture that can support richer interaction without fighting the implementation.

This plan is intentionally forward-looking. It complements the current implementation guide in:

- [phase_1_implementation.md](/Users/prakhar/learning_agent/docs/phase_1_implementation.md)

## 1.1 Current Status

The plan below is no longer purely aspirational. A first polished `Learn` vertical slice already exists in the current server-rendered UI:

- the app now uses a more product-like shell with a top bar, persistent side rails, and a dominant center workspace,
- the workspace header now includes a playful marathon-style progress strip with a runner, weekly markers, and a finish flag,
- the left rail now carries scope, progress, deliverables, benchmark metrics, and approval readiness,
- the main `Learn` surface is centered on a `Current Assessment` workspace rather than the older concept-card-first layout,
- the implementation section is visible directly below the assessment workspace,
- the right side now includes a multi-session `Assistant` rail with prompt shortcuts, thread switching, and browser-local week chat,
- side rails are resizable on desktop and persist their widths locally,
- the current question workspace remains a single assessment-focused answer section,
- a full question list is available in a closable modal,
- previous/next question navigation exists as compact arrow controls,
- in-progress answer drafts are autosaved client-side and restored when the user returns to a question,
- a persistent bottom course-position bar keeps the current week visible,
- top-level workflow sections have explicit disclosure indicators,
- small browser-side interaction cleanup is in place for details/summary toggles.

Earlier intermediate ideas in this document, especially around permanently visible concept cards and reading material in the primary `Learn` layout, should be read as forward-looking product exploration rather than a description of the current shipped surface.

The long-term architecture recommendation in this document is still valid: the product should eventually move to a proper frontend stack. But the immediate UX direction is already being prototyped in:

- [learning_agent/ui.py](/Users/prakhar/learning_agent/learning_agent/ui.py)

For the concrete near-term redesign target for the current server-rendered UI, see:

- [aspirational_ui_redesign_brief.md](/Users/prakhar/learning_agent/docs/aspirational_ui_redesign_brief.md)

## 2. Why The Current UI Is Not The Right Long-Term Surface

The current UI in:

- [learning_agent/ui.py](/Users/prakhar/learning_agent/learning_agent/ui.py)

is a server-rendered HTML string UI layered directly on top of the controller.

That was the correct tradeoff for Phase 1 because it was fast to build and easy to keep aligned with the CLI. It is not the right long-term foundation for the product direction now being targeted.

The main limitations are:

- image-rich concept cards are awkward to implement and maintain,
- chapter-style reading material with structured figures is cumbersome,
- split-pane "reading + questions" workflows are difficult to build well,
- sticky navigation, autosave, linked references, and richer interaction are all significantly harder than they should be,
- continued investment in HTML-string rendering will make product polish slower and more fragile over time.

## 3. Product Direction

The desired product shape is:

- concept cards that feel like real learning cards, not plain text blocks,
- reading material that sits between the cards and the question set,
- images and diagrams embedded throughout the learning experience,
- a right-side answer workspace where the user can answer while keeping the source material open,
- a more polished product experience overall, not just an internal control panel.

The "Learn" workflow should move toward an "open book exam" model:

- the user reads concept cards,
- the user reads a guided chapter for the current week,
- the user answers scoped questions while keeping the reading material visible,
- the UI makes it obvious which material supports which questions.

## 4. Recommended Architecture

The backend learning engine should remain in Python.

Recommended stack:

- backend API: `FastAPI`
- frontend: `React + TypeScript`
- frontend build tool: `Vite`
- server state fetching/caching: `TanStack Query`
- local UI state: `Zustand`
- styling: either `Tailwind CSS` or well-scoped CSS modules

This keeps the orchestration and learning logic in the existing Python codebase while replacing only the presentation layer with something that can support a modern product UI.

### 4.1 Backend Boundary

Keep these responsibilities in Python:

- roadmap parsing,
- week unlocking,
- ledger persistence,
- concept/question/task generation,
- scoring,
- verification and approval state transitions.

Do not reimplement the learning state machine in the frontend.

### 4.2 Frontend Boundary

Move these responsibilities into the new frontend:

- layout,
- navigation,
- image rendering,
- split-pane workspace behavior,
- answer drafts and local editor state,
- section highlighting and linked references,
- richer visual treatment of cards, reading sections, and question progress.

For the current server-rendered UI, the same responsibilities should continue to move out of the controller layer and into progressively richer client-side behavior where reasonable.

## 5. First Product Surface To Build

The first polished screen should be the `Learn Workspace`.

This is the highest-value slice because it directly affects the user's understanding and is where the current server-rendered UI is most limiting.

### 5.1 Learn Workspace Layout

Top strip:

- current week,
- goal,
- progress state,
- next recommended action.

Current server-rendered implementation note:

- this is now expressed as a compact workspace header plus a marathon-style course-progress strip rather than a plain utility-only top strip.
- the center workspace currently prioritizes the active assessment, with broader concept-card and reading-material presentation deferred from the primary surface.

Left pane:

- concept cards,
- reading material,
- inline figures and captions,
- sticky reading workspace.

Current server-rendered implementation note:

- this richer left-pane reading workspace is not the primary shipped layout today; the current UI instead keeps scope/progress utilities in the left rail and exposes broader question navigation through the assessment modal.

Right pane:

- single `Answer Question` workspace,
- current question position and status,
- previous/next navigation,
- progress bar for correctly answered required questions,
- answer editor,
- answer submission state,
- links to relevant concept cards and reading sections,
- a `See Full Question List` action that opens a closable modal with per-question status.

### 5.2 Interaction Model

The workspace should support:

- keeping reading material open while answering,
- moving between questions without losing context,
- opening the full question list only when needed,
- seeing whether a question is unanswered, failed, or passed,
- returning to the same reading section without losing place,
- preserving draft answers before submission.

The question list should not dominate the main workspace. It should be secondary navigation surfaced through a modal or other lightweight overlay, while the primary right-side surface stays focused on answering.

Accordion and disclosure behavior should also feel explicit and polished:

- top-level workflow sections should visibly read as collapsible,
- secondary explanation sections should not leave accidental text-selection artifacts after toggling,
- persistent navigation elements such as the course-position bar should remain visible without obscuring underlying content.

### 5.3 Draft Persistence Decision

Draft answers should be implemented client-side first.

Recommended first approach:

- use `localStorage`,
- key drafts by `week + question_id`,
- autosave on a short debounce while the user types,
- restore the draft when the user returns to that question,
- clear the draft on successful submission.

This is now the implemented behavior in the current UI. Drafts are treated as local interaction state, not ledger state.

This is the right first tradeoff because the current product is local-first and single-user. Server-side draft persistence can be added later if cross-browser/device recovery becomes important.

## 6. Content Model Changes

The polished UI depends on structured content, not monolithic blobs.

The system should move away from treating learning content as only:

- concept cards,
- raw/classified questions.

It should add a richer bundle for the learning experience.

### 6.1 Proposed Models

`ConceptCard`

- `id`
- `title`
- `summary`
- `why_it_matters`
- `common_mistake`
- `image`
- `related_section_ids`

`Figure`

- `id`
- `image_path`
- `caption`
- `alt_text`

`ReadingSection`

- `id`
- `title`
- `body_markdown`
- `figure_ids`
- `related_question_ids`
- `related_concept_ids`

`LearningBundle`

- `week`
- `concept_cards[]`
- `figures[]`
- `reading_sections[]`
- `questions[]`

### 6.2 Question Linking

Questions should be extended with:

- `related_concept_ids`
- `related_section_ids`

This is what enables the "open book exam" UX. The UI can surface "Relevant reading" and jump the user to the exact part of the chapter that supports the selected question.

### 6.3 Images

Images should be first-class content, not incidental attachments.

Initial approach:

- support local/static image assets,
- allow concept cards and reading sections to reference them by path,
- keep image generation optional for the first version.

Do not make the learning flow depend on AI image generation in the first release of the new UI.

## 7. Reading Material Strategy

Reading material should sit between concept cards and questions.

It should be:

- short enough to actually read,
- scoped to the current week,
- sufficient to answer the required question set,
- visual, with diagrams where they materially help,
- structured in sections rather than dumped as one large document.

The system should avoid storing this content as `.docx` for runtime rendering. Prefer:

- markdown plus structured metadata, or
- fully structured JSON blocks rendered by the frontend.

### 7.1 Week 1 Guidance

For Week 1, the chapter should stay tightly aligned with the required work:

- prefill vs decode,
- latency and `latency_p95`,
- tokens per second,
- role of `server.py`,
- role of `benchmark.py`,
- role of `baseline_results.md`.

Broader production topics should either move to later weeks or appear in a collapsed "Further Reading" section.

## 8. API Plan

The current UI should stop being the main integration point. The controller should be exposed through a JSON API.

Initial API shape:

- `GET /api/status`
- `POST /api/init`
- `POST /api/learning/generate`
- `GET /api/learning/session`
- `GET /api/learning/bundle`
- `POST /api/learning/answer`
- `POST /api/task/generate`
- `POST /api/artifacts/sync`
- `POST /api/metrics`
- `POST /api/observation`
- `POST /api/reflection`
- `POST /api/verification`
- `POST /api/approve`
- `POST /api/advance`

The most important new endpoint is:

- `GET /api/learning/bundle`

That endpoint should return the concept cards, figures, reading sections, question set, and progress state needed to render the `Learn Workspace`.

## 9. Rollout Plan

This should be built incrementally, not as a big-bang rewrite.

### Phase 1: API Foundation

- add a `FastAPI` app,
- expose controller-backed JSON routes,
- keep the current CLI untouched,
- leave the current local UI in place during transition.

### Phase 2: Schema Upgrade

- extend the learning models with figures and reading sections,
- add a learning bundle representation,
- persist the additional content alongside the learning session.

### Phase 3: Frontend Scaffold

- create a frontend app using React, TypeScript, and Vite,
- add routing, API client setup, and base layout,
- establish the visual system for cards, reading sections, and panels.

### Phase 4: Learn Workspace Vertical Slice

- concept cards with image support,
- reading material renderer,
- side-by-side reading + answer workspace,
- answer submission,
- question progress rendering,
- linked "relevant reading" navigation,
- full question list modal,
- compact previous/next navigation.

### Phase 5: Polish

- autosaved drafts,
- sticky navigation,
- keyboard navigation,
- figure lightbox behavior,
- improved transitions and loading states,
- higher-quality visual design across desktop and mobile.

Some of this has already started in the existing UI. In particular, the answer workspace, modal navigation, question-progress treatment, and client-side draft persistence should be treated as validated interaction direction rather than open questions.

That same category now also includes always-visible course context and small interaction polish around disclosure controls.

### Phase 6: Migrate Remaining Workflow Screens

After the new learning workspace is stable, migrate:

- build,
- verify,
- approve.

Only after those are stable should the old server-rendered UI be retired or frozen.

## 10. Suggested PR Sequence

PR 1:

- add `FastAPI`,
- expose `GET /api/status` and `POST /api/init`,
- keep the current UI functional.

PR 2:

- add figure and reading-section models,
- add `GET /api/learning/bundle`,
- keep content generation backward-compatible.

PR 3:

- scaffold `frontend/`,
- fetch and display status + learning bundle.

PR 4:

- build the split-pane `Learn Workspace`,
- render concept cards and chapter content with image support.

PR 5:

- wire answer submission, progress updates, draft autosave, and navigation between questions and reading.

For the current server-rendered UI, most of the PR 5 interaction direction is already prototyped and should serve as reference behavior for any eventual React rewrite.

PR 6:

- migrate the remaining workflow screens and deprecate the old UI path.

## 11. Non-Goals For The First Modern UI Milestone

The first milestone should not try to solve everything.

Specifically out of scope:

- mandatory AI-generated images,
- multi-user collaboration,
- production deployment architecture,
- replacing the Python controller logic,
- perfect visual design across all workflows before the `Learn Workspace` is complete.

## 12. Success Criteria

The modernization is successful when:

- concept cards are visually distinct and image-supported,
- reading material is clearly part of the learning flow,
- the user can answer questions while keeping source material visible,
- question navigation is available without cluttering the main answer surface,
- the full question list is available on demand and clearly shows per-question status,
- answer drafts survive question switching before submission,
- draft persistence feels instantaneous and does not require explicit save actions,
- the current week and course position remain visible without covering other important UI,
- accordion/disclosure interactions feel obvious and do not produce distracting browser-selection artifacts,
- the UI feels like a product workspace rather than a local control panel,
- the backend learning logic remains stable and testable,
- future UI improvements become easier instead of harder.

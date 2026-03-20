# Aspirational UI Redesign Brief

## 1. Purpose

This document captures the concrete redesign target for the current server-rendered Learning Agent UI.

The goal is not a light polish. The goal is to move the product from a local control surface that still feels internal and box-heavy to a UI that feels intentionally designed for aspirational engineers.

This brief is narrower and more implementation-facing than:

- [polished_ui_modernization_plan.md](/Users/prakhar/learning_agent/docs/polished_ui_modernization_plan.md)

It defines the next visual target for the current Python-rendered UI in:

- [ui.py](/Users/prakhar/learning_agent/learning_agent/ui.py)

## 2. Current Status

This redesign is no longer only a target. The app-shell direction described here is now the active direction in the server-rendered UI.

The current implementation in:

- [ui.py](/Users/prakhar/learning_agent/learning_agent/ui.py)

now follows this higher-level structure:

- a product top bar with brand, week/title route, progress state, and utility actions,
- a center header that now includes a playful marathon-progress strip with a runner, weekly flags, and a finish marker,
- a lighter left rail for scope, progress, deliverables, metrics, and approval readiness,
- a dominant center workspace for the current assessment and implementation work,
- a simplified right-side `Assistant` rail with prompt shortcuts, thread switching, and chat,
- a horizontal four-step workflow bar instead of the earlier accordion-first center flow.

This brief should therefore be read as the design record for the current direction and the reference for further refinement, not as a description of the superseded boxed/accordion layout.

## 3. Current Problems

The current UI is improved, but it still has the wrong product feel.

The main problems are:

- too many bordered rounded rectangles compete at the same visual weight,
- hero, rails, workflow sections, subpanels, cards, and utility blocks all look like the same container type,
- the center workflow still reads like stacked admin panels rather than a guided engineering workspace,
- the left and right rails feel like heavy side cabinets instead of lighter reference surfaces,
- status chips and utility chrome are visually overused,
- the page still feels more like an internal local tool than a premium learning product.

In short: the current UI is more user-focused than before, but it still feels too boxy and too operational.

## 4. Approved Target

The approved redesign target is a **near-identical** interpretation of the aspirational reference screenshot provided during planning, adapted to the Learning Agent product model.

“Near-identical” means:

- closely match the screenshot's composition,
- closely match its spacing rhythm and card proportions,
- closely match its hierarchy between rails, hero, next-step panel, progression block, and active workspace,
- closely match its lighter, calmer, more premium engineering feel,
- preserve the Learning Agent product content and state-driven behavior.

It does **not** mean:

- cloning browser chrome,
- cloning an external product shell,
- copying text that no longer matches the current product,
- rewriting the backend state machine.

It **does** mean that the implemented server-rendered UI should keep converging on this product shape:

- app-shell navigation,
- strong center-stage workspace,
- lighter rails,
- guided workflow progression,
- calmer surfaces with fewer repeated boxes.

## 5. Target Experience

The redesigned screen should feel like:

- a premium engineering workspace,
- a guided systems-learning product,
- a calm editorial interface with strong visual hierarchy,
- a tool built for ambitious practitioners rather than an internal admin surface.

The screen should communicate:

- this week matters,
- there is a clear next step,
- progress is staged and visible,
- the assistant is integrated into the workflow,
- the product is serious and well-crafted.

## 6. Layout Specification

The flagship target screen is the Week 1 `Learn` view in the new app-shell composition.

### 6.1 Top App Bar

The page should lead with a compact product/navigation bar.

It should contain:

- product label,
- current route context such as week and title,
- a compact progress state,
- utility actions such as search and account chrome.

This replaces the older “hero card at the top of the page” framing as the primary shell.

### 6.2 Left Rail

The left rail is now a persistent product rail, not an overflow status drawer.

It should contain:

- scope,
- progress,
- deliverables,
- benchmark metrics,
- approval readiness.

It should feel lighter than the older sidebar cabinet model, but it is still a visible part of the default desktop layout.

### 6.3 Center Header

The center column should begin with a concise workspace header:

- `Learn by Building Real Systems`,
- short promise copy,
- compact environment metadata,
- a marathon-style progress strip that visualizes course movement from start line to finish,
- one strong primary action.

This is now a workspace header, not a separate hero card and next-step card pair.

### 6.4 Workflow Stepper

The main workflow should be shown as a horizontal four-step bar:

- `Learn`,
- `Build`,
- `Verify`,
- `Approve`.

The current step should be visually emphasized, but the full path should stay visible at once.

### 6.5 Current Assessment

The dominant center surface should be the active step workspace.

For `Learn`, that means a large `Current Assessment` card containing:

- the active question,
- concise guidance,
- answer submission,
- autosave-backed draft support,
- question-list access,
- progress and concept coverage in a right-side companion panel.

This intentionally replaces the earlier “concept cards + reading material + answer column” center composition as the primary target for this redesign pass.

### 6.6 Implementation Section

Below the assessment, the page should show a clear implementation area with:

- a section header,
- task / scan actions,
- required-file status table,
- recent activity panel.

This keeps the product grounded in real deliverables instead of abstract progress alone.

### 6.7 Right Rail

The right rail is now framed as `Assistant`.

Its visible hierarchy should be:

- `Assistant`,
- lightweight `Ask / Hints / Context` tab strip,
- quick prompts,
- thread list,
- chat transcript,
- composer.

The underlying week-scoped multi-session chat behavior may remain, but the visible chrome should read like an integrated assistant product rather than a session manager.

## 7. Behavior Specification

The redesign should follow the screenshot's guided app-workspace model, not the earlier accordion-first workflow model.

Required behavior decisions:

- the main workflow should be visible as one horizontal staged path,
- the active step should dominate the center workspace,
- the current separate expandable step sections should no longer be the primary interaction pattern,
- existing step logic still governs progression:
  - `Learn`
  - `Build`
  - `Verify`
  - `Approve`
- existing controller actions and preconditions remain unchanged,
- existing forms and actions are remapped into the new workspace sections instead of remaining as independent boxed panels,
- topic chat can keep browser-local multi-session behavior even if the visible UI hides most session-management chrome by default.

This is a presentation-layer redesign with meaningful layout and interaction reorganization, not a backend state-machine rewrite.

## 8. Content Mapping From The Current UI

Map the current implementation into the new layout as follows:

- current week/title context moves into the top app bar,
- current user-facing product promise remains in the center header,
- current workflow state moves into the horizontal stepper,
- current active learning question becomes the `Current Assessment`,
- current question modal remains available,
- current draft-autosave behavior remains available,
- current build/file-sync actions move into the implementation section toolbar,
- current file completion data feeds the implementation table and deliverables rail,
- current metric state feeds the benchmark metrics rail,
- current approval readiness is summarized in the left rail,
- current chat capabilities remain, but the rail is reframed visually as `Assistant`,
- current browser-local week threads are surfaced directly in the assistant rail instead of older question-summary or resource cards.

## 9. Visual System Rules

The redesign should use only three surface roles:

- `stage` for major central areas,
- `utility` for rails and scoped support panels,
- `inline` for chips, status, and metadata.

Rules:

- sharply reduce nested borders,
- stop applying the same visual card treatment to everything,
- use spacing and dividers instead of repeated rounded rectangles,
- keep a restrained palette with one strong accent,
- keep serif/sans contrast unless implementation proves a better match using already-available assets,
- reduce chip and badge density,
- let the center stage feel dominant,
- prefer product-shell clarity over “local tool” framing.

## 10. Screenshot Deliverable

The implementation should produce a deterministic before/after comparison for one flagship screen.

Target capture:

- desktop viewport,
- Week 1,
- `Learn` active,
- both rails visible,
- current assessment visible,
- selected question visible.

Expected artifacts:

- `artifacts/ui-comparison/before-learn-workspace.png`
- `artifacts/ui-comparison/after-learn-workspace.png`

At the time of writing, the current generated artifact for the redesigned direction is:

- [after-learn-workspace.png](/Users/prakhar/learning_agent/artifacts/ui-comparison/after-learn-workspace.png)

## 11. Acceptance Criteria

The redesign is successful when:

- the screen no longer reads as “a page full of boxes,”
- the center feels like the main stage,
- the left and right rails feel lighter and more refined,
- the workflow feels guided rather than accordion-driven,
- the app shell reads like a product for ambitious engineers rather than a local admin tool,
- the assistant feels integrated into the working context rather than bolted on,
- the overall result feels closer to a premium engineering product than an internal dashboard,
- existing state-driven content remains understandable and usable.

# Week Chat Sidebar Redesign

## 1. Purpose

This document defines the redesign of the current right sidebar from a question-anchored helper into a real multi-session week tutor chat.

The goal is not to add more controls. The goal is to simplify the surface so it feels like a chat product and broadens the assistant's role from "help me answer this specific question" to "help me understand this week."

This is a focused design doc, narrower than the broader modernization plan in:

- [polished_ui_modernization_plan.md](/Users/prakhar/learning_agent/docs/polished_ui_modernization_plan.md)

It is intended to be implementation-oriented and directly actionable.

## 2. Current Problem

The current right sidebar in:

- [ui.py](/Users/prakhar/learning_agent/learning_agent/ui.py)

has the wrong product shape for the job it is trying to do.

The main issues are:

- the sidebar is too boxy and visually over-segmented,
- chat feels secondary to metadata instead of being the primary surface,
- the visible `Active Question` framing is too narrow,
- the transcript does not read like a normal chat interface,
- the assistant appears scoped to question help instead of week help,
- the empty state and context area look more like a settings panel than a conversation space.

At a product level, the current design overfits the `Learn` step. It implies that the assistant is mostly there to support a selected question, even though users should be able to ask about:

- the topic of the current week,
- the structure of the current week,
- what to expect next,
- concepts mentioned but not fully covered here,
- adjacent clarifications such as "what is an LLM?"

## 3. Product Direction

The right sidebar should become `Week Chat`.

This assistant is a week tutor, not a question helper.

The expected user mental model is:

- "Help me understand what this week is about."
- "Help me understand how this week's files and metrics fit together."
- "Explain a concept mentioned here."
- "Tell me what I should expect next in this week."

The assistant should stay grounded in the current week by default, but it should not feel artificially constrained to the currently selected question.

## 4. Core UX Decisions

The redesign adopts these decisions:

- the app-wide right sidebar remains,
- mirrored left/right rail mechanics remain unchanged,
- chat is week-scoped by default,
- the selected `Learn` question is not silently injected by default,
- multiple chat sessions exist per week,
- sessions persist in `localStorage`,
- each session title is auto-generated from the first user message,
- the right sidebar should visually read as a chat interface first and a context surface second.

This redesign supersedes the earlier "question helper" framing for the right sidebar while remaining consistent with the broader modernization direction.

## 5. Target UI Shape

The right sidebar should be simplified into four regions.

### 5.1 Minimal Week Header

The header should stay lightweight and identify only the current week context:

- week number,
- week title,
- optional small subtitle such as current step.

It should not lead with an `Active Question` card or other question-specific summary.

### 5.2 Compact Session List

The top of the sidebar should include a compact session switcher:

- current week's chat sessions,
- active session highlight,
- `New Chat` action,
- delete action per session or per active session.

The session list should feel lightweight, not card-heavy.

### 5.3 Active Transcript

The main body should be a chat transcript:

- chronological conversation,
- user and assistant messages,
- empty new-chat state with suggested prompts,
- transcript as the visual center of gravity.

This area should look like a chat interface, not a stack of status panels.

### 5.4 Anchored Composer

The bottom of the sidebar should include:

- message composer,
- send action,
- compact helper text if needed.

The composer should stay anchored consistently and feel like a normal messaging surface.

### 5.5 What Gets Removed

The redesign explicitly removes:

- the `Active Question` card,
- stacked week/context cards,
- box-heavy empty-state treatment,
- question-specific placeholder copy such as "active question" framing.

## 6. Interaction Model

The sidebar should support the following flow.

### 6.1 Session Creation

- the user clicks `New Chat`,
- a new empty session is created for the current week,
- the new session becomes active immediately,
- the first user message auto-generates the session title.

### 6.2 Session Switching

- the user can switch between multiple sessions for the same week,
- each session preserves its own transcript,
- switching sessions does not merge or rewrite conversation history.

### 6.3 Session Deletion

- the user can delete a chat session,
- deleting one session does not affect other sessions for the same week,
- if the active session is deleted, the UI should choose the next most recent session or create a fresh empty one.

### 6.4 Messaging

- the user sends a freeform message,
- the assistant replies in the active session,
- transcript updates in place without a full page reload,
- errors should appear inline in the chat surface.

### 6.5 Restore On Refresh

- active session is restored on reload,
- transcript is restored on reload,
- draft message in the active session may also be restored locally if that behavior remains useful.

### 6.6 New Chat Empty State

An empty chat should show a small set of suggested prompts, for example:

- "What is this week about?"
- "What should I expect next?"
- "How do the required files fit together?"
- "What is an LLM?"

These suggestions should feel like chat starters, not boxed documentation panels.

## 7. Context Model

The assistant should be grounded on the current week by default.

The default context sent to the model should include:

- week title,
- week goal,
- active step,
- active directories,
- required files,
- required metrics,
- recorded progress,
- blockers,
- current week state.

Question-specific context should not be included by default.

If a future version wants explicit question grounding, it should be added as an intentional user action or a clearly defined product feature, not as a silent default.

## 8. Storage Model

Chat sessions should be stored browser-locally per week.

Recommended local structure:

```json
{
  "week": 1,
  "active_session_id": "session_abc123",
  "sessions": [
    {
      "id": "session_abc123",
      "title": "What is this week about?",
      "created_at": 1710000000000,
      "updated_at": 1710000015000,
      "messages": [
        { "role": "user", "content": "What is this week about?" },
        { "role": "assistant", "content": "..." }
      ]
    }
  ]
}
```

This is a browser-state model, not ledger state.

Requirements:

- multiple sessions per week,
- active session id per week,
- no session leakage across weeks,
- no server-side persistence in v1.

## 9. Backend And API Notes

The current implementation points are:

- [ui.py](/Users/prakhar/learning_agent/learning_agent/ui.py)
- [controller.py](/Users/prakhar/learning_agent/learning_agent/controller.py)

The redesign changes the internal content model of the right sidebar, not the mirrored rail mechanics.

The backend contract should remain lightweight:

- keep `POST /api/topic-chat`,
- keep `message`,
- keep `history`,
- keep `current_step`,
- keep `selected_question_id` optional, but treat it as unused by default for chat grounding.

The controller should assemble week-scoped context by default and avoid silently anchoring the chat to the selected `Learn` question.

## 10. Visual Direction

The sidebar should look like a chat interface, not a settings panel.

Design principles:

- fewer containers,
- flatter hierarchy,
- stronger transcript focus,
- lighter header and session chrome,
- message bubbles or cards only where they improve readability,
- no excessive nesting of bordered panels.

The transcript should visually dominate the space. Metadata should be present, but visually quiet.

## 11. Out Of Scope

This redesign does not include:

- server-side chat persistence,
- manual session rename,
- modal session manager,
- cross-week shared chat memory,
- frontend stack migration,
- changing the mirrored rail mechanics already established for left and right rails.

## 12. Acceptance Criteria

This redesign is successful when:

- the user can maintain multiple chats per week,
- chat survives refresh in browser storage,
- the right sidebar no longer emphasizes the active question,
- the right sidebar visually reads as a chat product,
- the assistant can answer week-wide questions and adjacent concept questions,
- the chat surface feels simpler and less box-heavy than the current implementation.

## 13. Implementation Notes

The implementation should treat this as a redesign of the right sidebar's internal product model.

That means:

- keep left/right mirrored rail behavior,
- replace question-helper chrome with week-chat chrome,
- shift from one transcript per week to multiple sessions per week,
- remove default question anchoring from controller context assembly,
- keep the current server-rendered UI as the implementation surface for this version.

This document should be treated as the source of truth for the next right-sidebar redesign pass.

## 14. Test Scenarios

The redesign should be validated against these scenarios:

- rendering with no initialized week,
- rendering with initialized week and no chat sessions,
- creating the first chat session and auto-title generation,
- switching between multiple sessions within the same week,
- deleting a session without affecting other sessions,
- refresh persistence of active session and transcript,
- starting a new week without leaking previous week sessions,
- asking broad week questions such as:
  - "What is this week about?"
  - "What should I expect next?"
  - "What is an LLM?"
- regression check that left/right rail open-close behavior stays mirrored.

# topic_chat/

A standalone, week-scoped chat surface that any stage in the workflow can
use. It owns the chat-internal transformations (reply normalisation,
JSON-wrapped reply unwrapping, fenced-block parsing, selection-context
truncation, system-context formatting) and the streaming handshake with
the provider.

`TopicChat` is not a stage. It's a cross-stage service that the
orchestrator instantiates and wires up; the UI exposes it as a single
chat panel that adapts its grounding to whichever step the user is
currently on.

## Layout

```
topic_chat/
├── service.py       # TopicChat — the chat service class
├── models.py        # TopicChatTurn (one user/assistant message)
├── prompts.py       # load_prompt / render_prompt for topic_chat/prompts/
├── prompts/
│   └── topic_chat.md  # The user prompt template (week + ledger + history)
└── tests/
    └── test_service.py
```

## What lives here vs in engine/

Same rule as the rest of the workspace: anything that is *specific to the
topic chat surface* lives in this package; cross-stage scaffolding stays
in `engine/`.

In this package:

- `TopicChat` — the service class.
- `TopicChatTurn` — the one-message model used in chat histories.
- The chat user-prompt template and its loader.

In `engine/`:

- The orchestrator wiring (`WeekOrchestrator.answer_topic_chat`,
  `stream_topic_chat`, `_topic_chat_inputs`) — these are the cross-stage
  collectors that gather blockers / question progress / default-step
  fallback and hand them to `TopicChat`. They live in `engine/` because
  they aggregate facts from learn, build, and verify simultaneously.
- The Mentor system prompt (`engine/prompts/mentor.md`) — used for many
  Mentor-flavored calls, including topic chat.

## The data flow

```
user types -> UI form
   -> POST /run_topic_chat (or stream variant) -> ui/server.py
   -> WeekOrchestrator.answer_topic_chat / stream_topic_chat
        (gathers cross-stage facts: blockers, progress, default step)
   -> TopicChat.answer / .stream
        (formats system context, normalises history, streams provider)
   -> provider.answer_topic_chat or stream_topic_chat
        (uses topic_chat.prompts to render topic_chat.md as the user prompt;
         uses engine.prompts to load mentor.md as the system prompt)
```

## Strict event shape

`TopicChat.stream` yields one of three event kinds:

- `start` — emitted before the provider call. Carries `week` and
  `context_label`.
- `delta` — one or more, each carrying a streamed text chunk.
- `done` — final event, carrying the assembled reply (JSON-unwrapped if
  the provider wrapped it).

A `done` event with an empty reply, or no `done` at all, raises
`EngineError` — the surface treats an empty chat reply as a defect rather
than something to hide.

## Tests

`topic_chat/tests/test_service.py` covers reply normalisation,
JSON-unwrapping, fenced-block parsing, selection-context truncation,
default-step fallback, system-context content, and the streaming event
shape. The tests use a stub provider so no network is required.

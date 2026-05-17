"""Models owned by the topic_chat service.

Only TopicChatTurn lives here for now — one user/assistant message in a
chat history. The TopicChat service accepts either raw dicts or these
typed turns and normalises on the way in.
"""

from __future__ import annotations

from typing import Literal

from coach._base import StrictModel


class TopicChatTurn(StrictModel):
    role: Literal["user", "assistant"]
    content: str

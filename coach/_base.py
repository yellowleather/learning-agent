"""Shared model base class.

Lives in its own module so every domain package (verify, learn, build) can
import StrictModel without going through coach.models — keeping coach.models
free to import back into them where the cross-stage scaffolding (Ledger,
TaskSession) needs domain types.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Pydantic base with `extra="forbid"` so stale or hand-edited state
    files surface unknown fields loudly rather than silently dropping them."""

    model_config = ConfigDict(extra="forbid")

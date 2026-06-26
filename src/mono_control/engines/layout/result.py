"""Per-repo outcomes the layout engine produces."""

from __future__ import annotations

from typing import Literal

from ...base_models import StrictModel

LayoutStatus = Literal[
    "satisfied",   # already as desired; no action taken
    "placed",      # offline → materialized location (and checked out)
    "checked-out", # ref changed in place
    "relocated",   # materialized location A → materialized location B (and checked out)
    "retired",     # materialized → offline
    "blocked",     # could not act safely (dirty tree on ref change, commit not local, …)
    "failed",      # tried to act, the action raised
]


class LayoutOutcome(StrictModel):
    """One repo's layout-engine result."""

    slug: str
    status: LayoutStatus
    summary: str


class LayoutReport(StrictModel):
    """All per-repo outcomes; ``ok`` iff none failed and none were blocked."""

    outcomes: list[LayoutOutcome] = []

    @property
    def ok(self) -> bool:
        bad = {"blocked", "failed"}
        return all(o.status not in bad for o in self.outcomes)

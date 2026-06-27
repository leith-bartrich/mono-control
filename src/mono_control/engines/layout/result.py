"""Per-repo outcomes the layout engine produces."""

from __future__ import annotations

from typing import Literal

from ...base_models import StrictModel

LayoutStatus = Literal[
    "satisfied",     # already as desired; no action taken
    "placed",        # offline → materialized location (and checked out)
    "checked-out",   # ref changed in place
    "relocated",     # materialized location A → materialized location B (and checked out)
    "retired",       # materialized → offline
    "blocked",       # could not act safely (precondition fails: dirty tree, commit not local, …)
    "race-aborted",  # observed state changed between plan and execute; repo left untouched
    "partial",       # multi-step action partly applied; on-disk state is ambiguous (needs attention)
    "failed",        # known failure mode hit (e.g. move OSError); repo left untouched
]


class LayoutOutcome(StrictModel):
    """One repo's layout-engine result."""

    slug: str
    status: LayoutStatus
    summary: str


class LayoutReport(StrictModel):
    """All per-repo outcomes; ``ok`` iff every outcome reached its desired state."""

    outcomes: list[LayoutOutcome] = []

    @property
    def ok(self) -> bool:
        bad = {"blocked", "race-aborted", "partial", "failed"}
        return all(o.status not in bad for o in self.outcomes)

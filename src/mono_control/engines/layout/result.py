"""Per-repo outcomes the layout engine produces."""

from __future__ import annotations

from typing import Literal

from ...base_models import StrictModel

LayoutStatus = Literal[
    "satisfied",     # already as desired; no action taken
    "placed",        # offline → materialized: a worktree was created (and checked out)
    "checked-out",   # ref changed in place (in the existing worktree)
    "relocated",     # materialized location A → B: the worktree was moved (and checked out)
    "retired",       # materialized → offline: the worktree was removed (bare repo survives)
    "blocked",       # could not act safely (precondition fails: dirty worktree, commit not local, …)
    "race-aborted",  # observed state changed between plan and execute; repo left untouched
    "partial",       # multi-step action partly applied; on-disk state is ambiguous (needs attention)
    "failed",        # known failure mode hit (e.g. worktree add/move failure); repo left untouched
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

"""mono-control layout-target layer — the engines' shared input shape.

A layout-target is a *desired local layout* (per-slug discriminated desired
state plus a ``pre_clear`` exclusivity flag). It is **memory-only** — built
fresh and never serialized — the inverse of a [snapshot]. Source-free: a
target names *what state*, never *where to fetch from*.

See ``docs/design/layers/data/layout-target.md``.
"""

from .models import (
    DesiredState,
    LayoutTarget,
    LayoutTargetAbsent,
    LayoutTargetPresentBranchHead,
    LayoutTargetPresentCommit,
)

__all__ = [
    "DesiredState",
    "LayoutTarget",
    "LayoutTargetAbsent",
    "LayoutTargetPresentBranchHead",
    "LayoutTargetPresentCommit",
]

"""The layout-target model: per-slug discriminated desired state.

Each member repo's desired state is one of four discriminated kinds:

- ``commit`` — present at a location, pinned to a precise commit
  (placement + ref intent in one);
- ``branch-head`` — present at a location, tracking the head of a named
  branch (placement + ref intent in one);
- ``present-as-is`` — present at a location, **no opinion on the current
  ref** (placement only — the engine will place/move but never check out);
- ``absent`` — the repo should not be materialized.

Placement and ref intent are *orthogonal*. The three present kinds let
callers express either facet (or both): ``present-as-is`` is "I care
where, not what's checked out"; ``commit`` / ``branch-head`` are "I care
about both." Verbs typically express one facet at a time
(``mat moveto`` / ``mat branchat`` / ``mat commit``); the declarative
``layout-target`` verb combines them.

The layout-target itself carries the ``pre_clear`` exclusivity flag and the
``{slug -> DesiredState}`` map. Not a ``VersionedModel`` — layout-targets are
constructed in memory and never persisted (the durable record is a
[snapshot](../snapshot/)); see ``docs/design/layers/data/layout-target.md``.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field

from ..base_models import StrictModel


class LayoutTargetPresentCommit(StrictModel):
    """Pin a repo to a precise commit at a specific location."""

    kind: Literal["commit"] = "commit"
    commit: str
    location: str  # subdir under mono-work — place/move the repo's worktree here if not already here


class LayoutTargetPresentBranchHead(StrictModel):
    """Pin a repo to the head of a named branch at a specific location."""

    kind: Literal["branch-head"] = "branch-head"
    branch: str
    location: str  # subdir under mono-work — place/move the repo's worktree here if not already here


class LayoutTargetPresentAsIs(StrictModel):
    """Present at a specific location with no opinion on the current ref.

    The engine will place (offline → location) or relocate (location →
    location) as needed, but will **not** check out anything. The repo's
    on-disk HEAD is preserved through the move.
    """

    kind: Literal["present-as-is"] = "present-as-is"
    location: str  # subdir under mono-work — place/move the repo's worktree here if not already here


class LayoutTargetAbsent(StrictModel):
    """Declare a repo should not be materialized."""

    kind: Literal["absent"] = "absent"


DesiredState = Annotated[
    Union[
        LayoutTargetPresentCommit,
        LayoutTargetPresentBranchHead,
        LayoutTargetPresentAsIs,
        LayoutTargetAbsent,
    ],
    Field(discriminator="kind"),
]


class LayoutTarget(StrictModel):
    """A desired local layout: the layout engine's input.

    ``pre_clear`` toggles exclusivity: when **false** the target is *additive*
    (touch only the named repos); when **true** it is *exclusive* (every
    materialized repo not named is reconciled to absent — unsafe removals are
    blocked, never forced).
    """

    pre_clear: bool = False
    targets: dict[str, DesiredState] = {}

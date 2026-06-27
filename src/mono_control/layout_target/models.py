"""The layout-target model: per-slug discriminated desired state.

Each member repo's desired state is one of three discriminated kinds:

- ``commit`` — pinned to a precise commit (also names the desired location);
- ``branch-head`` — the head of a named branch (resolved at execution; the
  smarts of *which* branch live with the constructor — the engine only ever
  sees ``branch-head(name)``);
- ``absent`` — the repo should not be materialized.

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
    location: str  # subdir under mono-repos — place/move the repo here if not already here


class LayoutTargetPresentBranchHead(StrictModel):
    """Pin a repo to the head of a named branch at a specific location."""

    kind: Literal["branch-head"] = "branch-head"
    branch: str
    location: str  # subdir under mono-repos — place/move the repo here if not already here


class LayoutTargetAbsent(StrictModel):
    """Declare a repo should not be materialized."""

    kind: Literal["absent"] = "absent"


DesiredState = Annotated[
    Union[
        LayoutTargetPresentCommit,
        LayoutTargetPresentBranchHead,
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

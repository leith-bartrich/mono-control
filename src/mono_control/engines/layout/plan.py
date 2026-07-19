"""Plan stage: classify each (observed, desired) pair into an action.

This is the *pre-empt / diff* phase from
``docs/design/layers/layout/README.md`` — pure data: no filesystem writes, no
network. Race-safety lives in execute (which re-checks at the moment of
action); the plan is planning + UX.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from ...base_models import StrictModel
from ...layout_target import (
    DesiredState,
    LayoutTarget,
    LayoutTargetAbsent,
    LayoutTargetPresentAsIs,
    LayoutTargetPresentBranchHead,
    LayoutTargetPresentCommit,
)
from ...on_disk import OnDiskInventory, OnDiskRepo

PlanAction = Literal["none", "place", "checkout", "relocate", "retire"]
Classification = Literal["satisfied", "actionable", "blocked"]


class PlanItem(StrictModel):
    """One slug's plan row."""

    slug: str
    observed: OnDiskRepo | None
    desired: DesiredState | None  # None means an implicit pre_clear-driven retire
    classification: Classification
    action: PlanAction
    resolved_commit: str | None = None  # for present states, the concrete commit
    target_location: Path | None = None  # absolute path under workspace_root, if relevant
    reason: str | None = None  # populated when blocked


def _resolve_branch_head(
    slug: str, branch: str, resolved_refs: dict[str, dict[str, str]]
) -> str | None:
    """Look up a branch's commit in the acquire-resolved ref map (plain data).

    The source engine's ``acquire`` verb ran before planning and returned, per
    slug, the concrete commit each requested ref resolved to. A branch-head
    target requests ``refs/heads/<branch>`` (see ``from_layout_target``), so its
    commit is read straight from that map — no git call, keeping ``plan()`` pure.
    ``None`` if the branch was not resolved (absent locally / not fetched).
    """
    return resolved_refs.get(slug, {}).get(f"refs/heads/{branch}")


def _plan_present(
    slug: str,
    observed: OnDiskRepo | None,
    desired: LayoutTargetPresentCommit | LayoutTargetPresentBranchHead,
    *,
    workspace_root: Path,
    resolved_refs: dict[str, dict[str, str]],
) -> PlanItem:
    target_location = workspace_root / desired.location

    # Resolve the desired commit from plan-time data (never a git read).
    resolved: str | None
    if isinstance(desired, LayoutTargetPresentCommit):
        resolved = desired.commit
    else:
        if observed is None:
            # Need a local checkout to read the branch from; source must run first.
            return PlanItem(
                slug=slug,
                observed=None,
                desired=desired,
                classification="blocked",
                action="none",
                reason=f"{slug!r} is absent; cannot resolve branch {desired.branch!r}",
            )
        resolved = _resolve_branch_head(slug, desired.branch, resolved_refs)
        if resolved is None:
            return PlanItem(
                slug=slug,
                observed=observed,
                desired=desired,
                classification="blocked",
                action="none",
                reason=(
                    f"branch {desired.branch!r} not present locally for {slug!r}; "
                    f"source engine must fetch first"
                ),
            )

    if observed is None:
        # Absent but desired present: source engine must acquire first.
        return PlanItem(
            slug=slug,
            observed=None,
            desired=desired,
            classification="blocked",
            action="none",
            resolved_commit=resolved,
            target_location=target_location,
            reason=f"{slug!r} is absent; source engine must acquire it first",
        )

    if observed.state == "offline":
        return PlanItem(
            slug=slug,
            observed=observed,
            desired=desired,
            classification="actionable",
            action="place",
            resolved_commit=resolved,
            target_location=target_location,
        )

    # observed.state == "materialized"
    same_location = observed.location == target_location
    ref_change = observed.commit != resolved

    if same_location and not ref_change:
        return PlanItem(
            slug=slug,
            observed=observed,
            desired=desired,
            classification="satisfied",
            action="none",
            resolved_commit=resolved,
            target_location=target_location,
        )
    if same_location and ref_change:
        if observed.dirty:
            return PlanItem(
                slug=slug,
                observed=observed,
                desired=desired,
                classification="blocked",
                action="none",
                resolved_commit=resolved,
                target_location=target_location,
                reason=(
                    f"{slug!r} working tree is dirty; refusing to change ref over "
                    f"uncommitted work"
                ),
            )
        return PlanItem(
            slug=slug,
            observed=observed,
            desired=desired,
            classification="actionable",
            action="checkout",
            resolved_commit=resolved,
            target_location=target_location,
        )
    # different location → relocate (a ref change too if needed)
    if observed.dirty and ref_change:
        return PlanItem(
            slug=slug,
            observed=observed,
            desired=desired,
            classification="blocked",
            action="none",
            resolved_commit=resolved,
            target_location=target_location,
            reason=(
                f"{slug!r} working tree is dirty; refusing to relocate-and-change-ref "
                f"over uncommitted work"
            ),
        )
    return PlanItem(
        slug=slug,
        observed=observed,
        desired=desired,
        classification="actionable",
        action="relocate",
        resolved_commit=resolved,
        target_location=target_location,
    )


def _plan_present_as_is(
    slug: str,
    observed: OnDiskRepo | None,
    desired: LayoutTargetPresentAsIs,
    *,
    workspace_root: Path,
) -> PlanItem:
    """Plan a placement-only desired state — no ref change ever.

    Pure placement: ``resolved_commit`` stays ``None`` so the execute stage
    moves the checkout but skips the post-move checkout. No dirty gate is
    needed (a move preserves working-tree state).
    """
    target_location = workspace_root / desired.location

    if observed is None:
        return PlanItem(
            slug=slug,
            observed=None,
            desired=desired,
            classification="blocked",
            action="none",
            target_location=target_location,
            reason=f"{slug!r} is absent; source engine must acquire it first",
        )

    if observed.state == "offline":
        return PlanItem(
            slug=slug,
            observed=observed,
            desired=desired,
            classification="actionable",
            action="place",
            target_location=target_location,
        )

    # observed.state == "materialized"
    if observed.location == target_location:
        return PlanItem(
            slug=slug,
            observed=observed,
            desired=desired,
            classification="satisfied",
            action="none",
            target_location=target_location,
        )

    return PlanItem(
        slug=slug,
        observed=observed,
        desired=desired,
        classification="actionable",
        action="relocate",
        target_location=target_location,
    )


def _plan_absent(slug: str, observed: OnDiskRepo | None) -> PlanItem:
    if observed is None or observed.state == "offline":
        # Already not materialized.
        return PlanItem(
            slug=slug,
            observed=observed,
            desired=LayoutTargetAbsent(),
            classification="satisfied",
            action="none",
        )
    return PlanItem(
        slug=slug,
        observed=observed,
        desired=LayoutTargetAbsent(),
        classification="actionable",
        action="retire",
    )


def plan(
    target: LayoutTarget,
    inventory: OnDiskInventory,
    *,
    workspace_root: Path,
    resolved_refs: dict[str, dict[str, str]] | None = None,
) -> list[PlanItem]:
    """Classify every (observed, desired) pair into a ``PlanItem``.

    Pure data — no filesystem writes, no network, no git reads. ``resolved_refs``
    is the ``{slug: {ref: commit}}`` map the source engine's ``acquire`` produced;
    it supplies the concrete commit for a ``PresentBranchHead`` target. With
    ``pre_clear=True`` every materialized repo not named in the target becomes an
    implicit retire.
    """
    resolved_refs = resolved_refs or {}
    items: list[PlanItem] = []
    handled_slugs: set[str] = set()

    for slug, desired in target.targets.items():
        observed = inventory.repos.get(slug)
        if isinstance(desired, LayoutTargetAbsent):
            items.append(_plan_absent(slug, observed))
        elif isinstance(desired, LayoutTargetPresentAsIs):
            items.append(
                _plan_present_as_is(
                    slug, observed, desired, workspace_root=workspace_root
                )
            )
        else:
            items.append(
                _plan_present(
                    slug,
                    observed,
                    desired,
                    workspace_root=workspace_root,
                    resolved_refs=resolved_refs,
                )
            )
        handled_slugs.add(slug)

    if target.pre_clear:
        for slug, observed in inventory.repos.items():
            if slug in handled_slugs:
                continue
            if observed.state != "materialized":
                continue
            items.append(
                PlanItem(
                    slug=slug,
                    observed=observed,
                    desired=None,
                    classification="actionable",
                    action="retire",
                    reason="implicit pre_clear retire",
                )
            )

    return items

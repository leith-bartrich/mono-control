"""Execute stage: race-safe per-item action.

Principles (see ``docs/design/layers/layout/README.md``):

- **Failure-as-guard.** Let the rename fail if the destination exists rather
  than check-then-act.
- **Atomic placement.** Use ``os.rename`` (single syscall on POSIX); a
  partially-moved tree never appears.
- **Minimize the window.** Re-check destructive preconditions immediately
  before the rename / checkout.
- **No partial state.** A failure on one slug aborts that slug only.
"""

from __future__ import annotations

import os
from pathlib import Path

from ...git import GitError, GitRepo
from ...on_disk import OnDiskRepo
from .plan import PlanItem
from .result import LayoutOutcome


def _move(src: Path, dst: Path) -> None:
    """Atomic-rename ``src`` → ``dst``; raise if ``dst`` already exists.

    The pre-check is racy on its own; the ``os.rename`` is the real guard on
    POSIX for non-empty dirs (ENOTEMPTY). On Windows ``rename`` itself refuses
    to overwrite, so the pre-check is belt-and-suspenders.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise FileExistsError(f"destination already exists: {dst}")
    os.rename(src, dst)


def _verify_slug(checkout: Path, expected_slug: str) -> None:
    """Re-verify the slug stamp at action time. Foreign checkouts are refused."""
    actual = GitRepo(checkout).slug()
    if actual != expected_slug:
        raise RuntimeError(
            f"slug mismatch at {checkout}: expected {expected_slug!r}, got {actual!r}"
        )


def _execute_one(item: PlanItem, *, offline_root: Path) -> LayoutOutcome:
    slug = item.slug
    if item.classification == "satisfied":
        return LayoutOutcome(slug=slug, status="satisfied", summary="already as desired")
    if item.classification == "blocked":
        return LayoutOutcome(
            slug=slug, status="blocked", summary=item.reason or "blocked"
        )

    try:
        if item.action == "place":
            return _do_place(item, offline_root=offline_root)
        if item.action == "checkout":
            return _do_checkout(item)
        if item.action == "relocate":
            return _do_relocate(item)
        if item.action == "retire":
            return _do_retire(item, offline_root=offline_root)
    except (FileExistsError, FileNotFoundError, OSError, GitError, RuntimeError) as e:
        return LayoutOutcome(
            slug=slug,
            status="failed",
            summary=f"{item.action} failed for {slug!r}: {e}",
        )

    return LayoutOutcome(
        slug=slug, status="failed", summary=f"unknown action {item.action!r}"
    )


def _do_place(item: PlanItem, *, offline_root: Path) -> LayoutOutcome:
    assert item.observed is not None and item.target_location is not None
    _verify_slug(item.observed.location, item.slug)  # re-check before move
    _move(item.observed.location, item.target_location)
    if item.resolved_commit is not None:
        GitRepo(item.target_location).checkout(item.resolved_commit)
    return LayoutOutcome(
        slug=item.slug,
        status="placed",
        summary=f"placed {item.slug!r} at {item.target_location}",
    )


def _do_checkout(item: PlanItem) -> LayoutOutcome:
    assert item.observed is not None and item.resolved_commit is not None
    repo = GitRepo(item.observed.location)
    _verify_slug(item.observed.location, item.slug)
    if repo.is_dirty():
        return LayoutOutcome(
            slug=item.slug,
            status="blocked",
            summary=f"{item.slug!r} became dirty between plan and execute",
        )
    repo.checkout(item.resolved_commit)
    return LayoutOutcome(
        slug=item.slug,
        status="checked-out",
        summary=f"checked out {item.resolved_commit[:12]} at {item.observed.location}",
    )


def _do_relocate(item: PlanItem) -> LayoutOutcome:
    assert item.observed is not None and item.target_location is not None
    _verify_slug(item.observed.location, item.slug)
    _move(item.observed.location, item.target_location)
    if item.resolved_commit is not None:
        GitRepo(item.target_location).checkout(item.resolved_commit)
    return LayoutOutcome(
        slug=item.slug,
        status="relocated",
        summary=(
            f"relocated {item.slug!r} → {item.target_location}"
        ),
    )


def _do_retire(item: PlanItem, *, offline_root: Path) -> LayoutOutcome:
    observed = item.observed
    assert observed is not None
    _verify_slug(observed.location, item.slug)
    destination = offline_root / item.slug
    # Retire is non-destructive: if the offline spot is occupied, refuse rather
    # than clobber. (The doc's one edge case.)
    if destination.exists():
        return LayoutOutcome(
            slug=item.slug,
            status="blocked",
            summary=f"offline holding spot {destination} is already occupied",
        )
    _move(observed.location, destination)
    return LayoutOutcome(
        slug=item.slug,
        status="retired",
        summary=f"retired {item.slug!r} to {destination}",
    )


def execute(items: list[PlanItem], *, offline_root: Path) -> list[LayoutOutcome]:
    """Execute every plan item independently; one failure does not stop the rest."""
    offline_root.mkdir(parents=True, exist_ok=True)
    return [_execute_one(item, offline_root=offline_root) for item in items]

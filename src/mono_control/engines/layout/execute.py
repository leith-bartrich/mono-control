"""Execute stage: race-safe per-item action.

Principles (see ``docs/design/layers/layout/README.md``):

- **Failure-as-guard.** Let the rename fail if the destination exists rather
  than check-then-act.
- **Atomic placement.** Use ``os.rename`` (single syscall on POSIX); a
  partially-moved tree never appears.
- **Minimize the window.** Re-check destructive preconditions immediately
  before the rename / checkout.
- **No partial state surprise.** Within a multi-step action (move + checkout),
  a checkout failure after a successful move is reported as ``partial`` so
  the user knows the on-disk state is ambiguous.

Failure handling: every known failure mode raises a typed exception
(:mod:`.errors`) and is caught at the specific site that knows how to map it
to a ``LayoutOutcome``. There is no catch-all — anything unexpected
propagates, to be handled by the UI layer's top-level safety net. Per-repo
independence still holds for every *known* failure (which is the 99% case),
since those become outcomes rather than exceptions.
"""

from __future__ import annotations

import os
from pathlib import Path

from ...git import GitError, GitRepo, UnmanagedCheckoutError
from .errors import (
    DestinationOccupiedError,
    MoveFailedError,
    SlugMismatchError,
)
from .plan import PlanItem
from .result import LayoutOutcome


def _move(src: Path, dst: Path) -> None:
    """Atomic-rename ``src`` → ``dst``; raise specific errors for known failures.

    ``DestinationOccupiedError`` covers both the pre-check and the
    failure-as-guard race (``os.rename`` refuses to overwrite a non-empty dir
    on POSIX and any dir on Windows). ``MoveFailedError`` wraps other OS-level
    failures (permissions, cross-device, source vanished).
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise DestinationOccupiedError(dst)
    try:
        os.rename(src, dst)
    except FileExistsError as e:
        raise DestinationOccupiedError(dst) from e
    except OSError as e:
        # ENOTEMPTY is POSIX's "rename onto non-empty dir"; treat as a race-style
        # destination-occupied case for consistent reporting.
        if e.errno is not None and e.errno == 39:  # errno.ENOTEMPTY
            raise DestinationOccupiedError(dst) from e
        raise MoveFailedError(src, dst, str(e)) from e


def _verify_slug(checkout: Path, expected_slug: str) -> None:
    """Re-verify the slug stamp at action time.

    Raises ``SlugMismatchError`` if the stamp changed since plan, or lets
    ``UnmanagedCheckoutError`` from the git layer propagate (also handled as
    a race by callers — the stamp vanished).
    """
    actual = GitRepo(checkout).slug()  # may raise UnmanagedCheckoutError
    if actual != expected_slug:
        raise SlugMismatchError(checkout, expected_slug, actual)


def _race_outcome(slug: str, action: str, detail: object) -> LayoutOutcome:
    return LayoutOutcome(
        slug=slug,
        status="race-aborted",
        summary=f"{action} aborted for {slug!r}: {detail}",
    )


def _execute_one(item: PlanItem, *, offline_root: Path) -> LayoutOutcome:
    slug = item.slug
    if item.classification == "satisfied":
        return LayoutOutcome(slug=slug, status="satisfied", summary="already as desired")
    if item.classification == "blocked":
        return LayoutOutcome(
            slug=slug, status="blocked", summary=item.reason or "blocked"
        )

    # Each _do_* handles its own known failures and returns an outcome.
    # Anything unexpected propagates to the UI layer's safety net.
    if item.action == "place":
        return _do_place(item, offline_root=offline_root)
    if item.action == "checkout":
        return _do_checkout(item)
    if item.action == "relocate":
        return _do_relocate(item)
    if item.action == "retire":
        return _do_retire(item, offline_root=offline_root)
    # Unreachable in a well-formed plan; if hit, it's an engine bug.
    raise AssertionError(f"unknown layout action {item.action!r} for slug {slug!r}")


def _do_place(item: PlanItem, *, offline_root: Path) -> LayoutOutcome:
    assert item.observed is not None and item.target_location is not None
    try:
        _verify_slug(item.observed.location, item.slug)
    except (SlugMismatchError, UnmanagedCheckoutError) as e:
        return _race_outcome(item.slug, "place", e)
    try:
        _move(item.observed.location, item.target_location)
    except DestinationOccupiedError as e:
        return _race_outcome(item.slug, "place", e)
    except MoveFailedError as e:
        return LayoutOutcome(
            slug=item.slug,
            status="failed",
            summary=str(e),
        )
    # Move succeeded; from here on a failure leaves the repo placed-but-wrong-ref
    # — flag as `partial` so the user knows on-disk state is ambiguous.
    if item.resolved_commit is not None:
        try:
            GitRepo(item.target_location).checkout(item.resolved_commit)
        except GitError as e:
            return LayoutOutcome(
                slug=item.slug,
                status="partial",
                summary=(
                    f"placed {item.slug!r} at {item.target_location} but checkout "
                    f"to {item.resolved_commit[:12]} failed: {e}"
                ),
            )
    return LayoutOutcome(
        slug=item.slug,
        status="placed",
        summary=f"placed {item.slug!r} at {item.target_location}",
    )


def _do_checkout(item: PlanItem) -> LayoutOutcome:
    assert item.observed is not None and item.resolved_commit is not None
    repo = GitRepo(item.observed.location)
    try:
        _verify_slug(item.observed.location, item.slug)
    except (SlugMismatchError, UnmanagedCheckoutError) as e:
        return _race_outcome(item.slug, "checkout", e)
    if repo.is_dirty():
        # Plan said clean, became dirty under us — still treat as the same
        # plan-time dirty-blocks-ref-change rule.
        return LayoutOutcome(
            slug=item.slug,
            status="blocked",
            summary=f"{item.slug!r} became dirty between plan and execute",
        )
    try:
        repo.checkout(item.resolved_commit)
    except GitError as e:
        return LayoutOutcome(
            slug=item.slug,
            status="failed",
            summary=f"checkout {item.resolved_commit[:12]} failed for {item.slug!r}: {e}",
        )
    return LayoutOutcome(
        slug=item.slug,
        status="checked-out",
        summary=f"checked out {item.resolved_commit[:12]} at {item.observed.location}",
    )


def _do_relocate(item: PlanItem) -> LayoutOutcome:
    assert item.observed is not None and item.target_location is not None
    try:
        _verify_slug(item.observed.location, item.slug)
    except (SlugMismatchError, UnmanagedCheckoutError) as e:
        return _race_outcome(item.slug, "relocate", e)
    try:
        _move(item.observed.location, item.target_location)
    except DestinationOccupiedError as e:
        return _race_outcome(item.slug, "relocate", e)
    except MoveFailedError as e:
        return LayoutOutcome(slug=item.slug, status="failed", summary=str(e))
    if item.resolved_commit is not None:
        try:
            GitRepo(item.target_location).checkout(item.resolved_commit)
        except GitError as e:
            return LayoutOutcome(
                slug=item.slug,
                status="partial",
                summary=(
                    f"relocated {item.slug!r} → {item.target_location} but checkout "
                    f"to {item.resolved_commit[:12]} failed: {e}"
                ),
            )
    return LayoutOutcome(
        slug=item.slug,
        status="relocated",
        summary=f"relocated {item.slug!r} → {item.target_location}",
    )


def _do_retire(item: PlanItem, *, offline_root: Path) -> LayoutOutcome:
    observed = item.observed
    assert observed is not None
    try:
        _verify_slug(observed.location, item.slug)
    except (SlugMismatchError, UnmanagedCheckoutError) as e:
        return _race_outcome(item.slug, "retire", e)
    destination = offline_root / item.slug
    # Retire is non-destructive: an occupied offline spot is a known
    # precondition violation, not a race — reported as `blocked`.
    if destination.exists():
        return LayoutOutcome(
            slug=item.slug,
            status="blocked",
            summary=f"offline holding spot {destination} is already occupied",
        )
    try:
        _move(observed.location, destination)
    except DestinationOccupiedError as e:
        # Lost the race against another process that just retired into the spot.
        return _race_outcome(item.slug, "retire", e)
    except MoveFailedError as e:
        return LayoutOutcome(slug=item.slug, status="failed", summary=str(e))
    return LayoutOutcome(
        slug=item.slug,
        status="retired",
        summary=f"retired {item.slug!r} to {destination}",
    )


def execute(items: list[PlanItem], *, offline_root: Path) -> list[LayoutOutcome]:
    """Execute every plan item.

    Per-repo independence holds for known failures (every action returns an
    outcome rather than raising). Truly unexpected exceptions propagate — the
    UI layer is the safety net for those.
    """
    offline_root.mkdir(parents=True, exist_ok=True)
    return [_execute_one(item, offline_root=offline_root) for item in items]

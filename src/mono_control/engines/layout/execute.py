"""Execute stage: dispatch each plan item to the broker's layout verbs.

The race-safe, on-disk mutations themselves — the ``git worktree add`` /
``worktree move`` / ``worktree remove``, the plan-time slug re-verification,
occupancy guards, and the git checkout — are filesystem + git *effects*, so they
run broker-side behind the thin ``place`` / ``relocate`` / ``retire`` /
``checkout`` verbs (the broker re-observes and keeps the race guards). This module
is the container half: it turns each ``PlanItem`` into the right verb call(s) and
rehydrates the broker's ``{status, summary}`` result into a typed ``LayoutOutcome``.

Composite intents (a place / relocate that also changes ref) are orchestrated
here as ``place`` **then** ``checkout``: a checkout failure *after* a successful
worktree add/move is reported as ``partial`` so the user knows the on-disk state
is ambiguous — the same "no partial-state surprise" contract the single-process
engine had.
"""

from __future__ import annotations

from ...broker import BrokerProtocol
from .plan import PlanItem
from .result import LayoutOutcome

# Layout statuses the broker returns that mean the primary move succeeded — a
# subsequent checkout may still run to complete a composite intent.
_PLACED_OK = {"placed", "relocated"}


def _outcome(slug: str, result) -> LayoutOutcome:
    """Rehydrate a broker ``LayoutOpResult`` into a typed ``LayoutOutcome``."""
    return LayoutOutcome(slug=slug, status=result.status, summary=result.summary)


def _relative_location(item: PlanItem, *, workspace_root) -> str:
    """The plan's target location as a path relative to the workspace root.

    The container speaks slugs + relative locations to the broker, never the
    absolute ``/workspaces/...`` paths (those are host constants on the broker).
    """
    assert item.target_location is not None
    return item.target_location.relative_to(workspace_root).as_posix()


def _do_place_or_relocate(
    item: PlanItem, *, broker: BrokerProtocol, workspace_root
) -> LayoutOutcome:
    """Move (place / relocate), then check out a ref if the intent carries one."""
    location = _relative_location(item, workspace_root=workspace_root)
    if item.action == "place":
        moved = broker.place(item.slug, location)
    else:
        moved = broker.relocate(item.slug, location)

    if moved.status not in _PLACED_OK or item.resolved_commit is None:
        # Move failed / was aborted, or there is no ref to change — report as-is.
        return _outcome(item.slug, moved)

    # Move succeeded; a checkout failure from here leaves the repo placed-but-
    # wrong-ref → flag `partial` so the ambiguous on-disk state is visible.
    checked = broker.checkout(item.slug, item.resolved_commit)
    if checked.status == "checked-out":
        return _outcome(item.slug, moved)
    verb = "placed" if item.action == "place" else "relocated"
    short = item.resolved_commit[:12]
    return LayoutOutcome(
        slug=item.slug,
        status="partial",
        summary=(
            f"{verb} {item.slug!r} at {location} but checkout to {short} "
            f"failed: {checked.summary}"
        ),
    )


def _execute_one(
    item: PlanItem, *, broker: BrokerProtocol, workspace_root
) -> LayoutOutcome:
    slug = item.slug
    if item.classification == "satisfied":
        return LayoutOutcome(slug=slug, status="satisfied", summary="already as desired")
    if item.classification == "blocked":
        return LayoutOutcome(
            slug=slug, status="blocked", summary=item.reason or "blocked"
        )

    if item.action in ("place", "relocate"):
        return _do_place_or_relocate(
            item, broker=broker, workspace_root=workspace_root
        )
    if item.action == "checkout":
        assert item.resolved_commit is not None
        return _outcome(slug, broker.checkout(slug, item.resolved_commit))
    if item.action == "retire":
        return _outcome(slug, broker.retire(slug))
    # Unreachable in a well-formed plan; if hit, it's an engine bug.
    raise AssertionError(f"unknown layout action {item.action!r} for slug {slug!r}")


def execute(
    items: list[PlanItem], *, broker: BrokerProtocol, workspace_root
) -> list[LayoutOutcome]:
    """Execute every plan item via the broker's layout verbs.

    Per-repo independence holds: each verb answers with an outcome rather than
    raising, so a known failure on one slug never aborts the rest.
    """
    return [
        _execute_one(item, broker=broker, workspace_root=workspace_root)
        for item in items
    ]

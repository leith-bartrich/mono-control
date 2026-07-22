"""The source engine: per-repo acquisition + ref refresh, never destructive.

The engine owns the *request* logic — deriving each slug's requested refs from a
layout target (:func:`from_layout_target`), driving one independent acquisition
per slug, and building the typed ``SourceReport`` — while the *effecting* half
(resolve the source URL from mono-config, clone / init / fetch, verify each ref)
runs broker-side behind the single ``acquire`` verb. URLs are never trusted from
the container, so the whole clone-vs-init-vs-fetch decision (which needs the
authoritative URL and a fresh on-disk observation) lives with the broker; the
container keeps per-repo independence, outcome construction, and the
scan → source → re-scan → layout ordering.

The engine never **mats / demats** a checkout (that's the layout engine's
domain) and never **pushes** (the publish engine's). It only ever adds
availability. A failure on one slug does not abort the rest.
"""

from __future__ import annotations

from ...broker import BrokerProtocol
from .request import SourceRequest
from .result import SourceOutcome, SourceReport

# ``acquire`` returns a ``SourceOutcome``-shaped status literal; anything the
# container doesn't recognize is surfaced verbatim (rehydrated as-is) so a broker
# contract drift is visible rather than silently coerced.


def _acquire_one(
    slug: str,
    refs: set[str],
    *,
    broker: BrokerProtocol,
    initial_branch: str | None,
) -> SourceOutcome:
    """Acquire one slug via the broker and rehydrate its ``SourceOutcome``."""
    result = broker.acquire(
        slug, sorted(refs), initial_branch=initial_branch
    )
    return SourceOutcome(
        slug=slug,
        status=result.status,  # validated against SourceStatus here
        summary=result.summary,
        unresolved_refs=set(result.unresolved_refs),
        resolved=dict(result.resolved),
    )


def run(request: SourceRequest, *, broker: BrokerProtocol) -> SourceReport:
    """Execute the source request, per-repo independent.

    A failure on one slug does **not** abort the rest; every requested slug
    yields one outcome record. The broker re-observes on-disk state at acquire
    time, so the container passes no plan-time inventory as authority.
    """
    outcomes = [
        _acquire_one(
            slug,
            refs,
            broker=broker,
            initial_branch=request.initial_branch,
        )
        for slug, refs in request.refs_by_slug.items()
    ]
    return SourceReport(outcomes=outcomes)

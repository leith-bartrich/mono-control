"""The shared verb implementations the CLI + aspects both build on.

``apply_target`` is the single layout-target orchestrator and the container's
core broker client: run the source half, re-scan the (broker-observed) on-disk
inventory, run the layout half, return both reports. Every mat / demat verb
builds its own ``LayoutTarget`` and hands it here, preserving the
source → re-scan → layout ordering (the broker re-observes and re-verifies at each
effecting verb). ``acquire`` runs the source half alone (clone/fetch into offline,
no placement) for callers that need a repo present before deciding placement.
``init`` and ``mark_aspect`` are the two verbs that *don't* fit that shape (one
creates a repo def, one toggles a flag).
"""

from __future__ import annotations

from pathlib import Path

from ..broker import BrokerProtocol
from ..config import Repo, RepoStore, make_slug
from ..engines import layout as layout_engine
from ..engines import source as source_engine
from ..layout_target import LayoutTarget
from ..on_disk import scan


def init(
    name: str,
    *,
    slug: str | None = None,
    aspects: set[str] | None = None,
    branches: dict[str, str] | None = None,
    initial_branch: str | None = None,
    repo_store: RepoStore,
    broker: BrokerProtocol,
) -> tuple[str, source_engine.SourceReport]:
    """Create a brand-new repo def + ``git init`` it into offline (broker-side).

    ``name`` is the primary user-facing handle; the slug is derived
    mechanically via :func:`make_slug` unless ``slug`` is supplied (the
    power-user escape hatch). ``branches`` seeds the def's named-branch map (e.g.
    ``{"dev": "main"}``), and ``initial_branch`` names the branch the new repo is
    ``git init``-ed on. Returns ``(slug, source_report)`` so callers can surface
    the resolved slug. Raises ``ConfigConflictError`` if an explicit ``slug`` is
    already taken, or ``RuntimeError`` if the derived slug couldn't be made unique
    within the retry cap (astronomically unlikely).
    """
    if slug is None:
        slug = make_slug(name, exists=repo_store.exists)
    repo = Repo(
        version=1,
        slug=slug,
        name=name,
        aspects=aspects or set(),
        branches=branches or {},
    )
    repo_store.create(repo)  # raises ConfigConflictError on duplicate
    report = source_engine.run(
        source_engine.SourceRequest(
            refs_by_slug={slug: set()}, initial_branch=initial_branch
        ),
        broker=broker,
    )
    return slug, report


def apply_target(
    target: LayoutTarget,
    *,
    broker: BrokerProtocol,
    workspace_root: Path,
    offline_root: Path,
) -> tuple[source_engine.SourceReport, layout_engine.LayoutReport]:
    """Orchestrate source → layout against ``target``.

    Runs the source engine on the derived source request (the broker re-observes
    per-slug and returns each ref's resolved commit), then re-scans the on-disk
    inventory so layout sees the post-acquisition state, then runs the layout
    engine — with the source engine's ``resolved`` map pinning any branch-head
    target's commit. Returns both reports so callers decide what to do on failure.

    Demat targets (only ``Absent`` slugs) work through this same function
    because ``from_layout_target`` omits ``Absent`` slugs from the source
    request — source engine is a no-op for them.
    """
    source_report = source_engine.run(
        source_engine.from_layout_target(target), broker=broker
    )
    resolved_refs = {o.slug: o.resolved for o in source_report.outcomes}

    inventory = scan(broker, workspace_root, offline_root)
    layout_report = layout_engine.run(
        target,
        broker=broker,
        inventory=inventory,
        workspace_root=workspace_root,
        resolved_refs=resolved_refs,
    )
    return source_report, layout_report


def acquire(
    slugs: set[str],
    *,
    broker: BrokerProtocol,
) -> source_engine.SourceReport:
    """Acquire repos into offline (clone / init / fetch) **without placing them**.

    The source half of :func:`apply_target` used on its own — when a caller needs
    a repo present locally to read its contents before deciding placement (e.g.
    reading a product cluster's layout before a swap tears the workspace down, so
    an unreachable cluster fails *before* anything is cleared).
    """
    return source_engine.run(
        source_engine.SourceRequest(refs_by_slug={s: set() for s in slugs}),
        broker=broker,
    )


def mark_aspect(slug: str, aspect_name: str, *, repo_store: RepoStore) -> bool:
    """Add ``aspect_name`` to ``slug``'s repo def. Returns ``True`` if newly added.

    Raises whatever ``RepoStore.load`` raises if the def doesn't exist;
    callers should let that surface.
    """
    repo = repo_store.load(slug)
    if aspect_name in repo.aspects:
        return False
    repo.aspects.add(aspect_name)
    repo_store.save(repo)
    return True

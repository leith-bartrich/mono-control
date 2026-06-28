"""The shared verb implementations the CLI + aspects both build on.

``apply_target`` is the single layout-target orchestrator: scan, run the
source engine, re-scan, run the layout engine, return both reports. Every
mat / demat verb builds its own ``LayoutTarget`` and hands it here. ``init``
and ``mark_aspect`` are the two verbs that *don't* fit that shape (one
creates a repo def, one toggles a flag).
"""

from __future__ import annotations

from pathlib import Path

from ..config import Repo, RepoStore, make_slug
from ..engines import layout as layout_engine
from ..engines import source as source_engine
from ..host_platform import FsProfile
from ..layout_target import LayoutTarget
from ..on_disk import scan


def init(
    name: str,
    *,
    slug: str | None = None,
    aspects: set[str] | None = None,
    repo_store: RepoStore,
    workspace_root: Path,
    offline_root: Path,
    profile: FsProfile,
) -> tuple[str, source_engine.SourceReport]:
    """Create a brand-new repo def + ``git init`` it into offline.

    ``name`` is the primary user-facing handle; the slug is derived
    mechanically via :func:`make_slug` unless ``slug`` is supplied (the
    power-user escape hatch). Returns ``(slug, source_report)`` so callers can
    surface the resolved slug. Raises ``ConfigConflictError`` if an explicit
    ``slug`` is already taken, or ``RuntimeError`` if the derived slug
    couldn't be made unique within the retry cap (astronomically unlikely).
    """
    if slug is None:
        slug = make_slug(name, exists=repo_store.exists)
    repo = Repo(
        version=1,
        slug=slug,
        name=name,
        aspects=aspects or set(),
    )
    repo_store.create(repo)  # raises ConfigConflictError on duplicate
    inventory = scan(workspace_root, offline_root)
    report = source_engine.run(
        source_engine.SourceRequest(refs_by_slug={slug: set()}),
        repo_store=repo_store,
        inventory=inventory,
        offline_root=offline_root,
        profile=profile,
    )
    return slug, report


def apply_target(
    target: LayoutTarget,
    *,
    repo_store: RepoStore,
    workspace_root: Path,
    offline_root: Path,
    profile: FsProfile,
) -> tuple[source_engine.SourceReport, layout_engine.LayoutReport]:
    """Orchestrate source → layout against ``target``.

    Scans the on-disk inventory, runs the source engine on the derived
    source request, re-scans (so layout sees the post-acquisition state),
    then runs the layout engine. Returns both reports so callers decide
    what to do on failure.

    Demat targets (only ``Absent`` slugs) work through this same function
    because ``from_layout_target`` omits ``Absent`` slugs from the source
    request — source engine is a no-op for them.
    """
    inventory = scan(workspace_root, offline_root)
    source_report = source_engine.run(
        source_engine.from_layout_target(target),
        repo_store=repo_store,
        inventory=inventory,
        offline_root=offline_root,
        profile=profile,
    )

    inventory = scan(workspace_root, offline_root)
    layout_report = layout_engine.run(
        target,
        inventory=inventory,
        workspace_root=workspace_root,
        offline_root=offline_root,
    )
    return source_report, layout_report


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

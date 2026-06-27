"""The four shared verb implementations the CLI + aspects both build on."""

from __future__ import annotations

from pathlib import Path

from ..config import Repo, RepoStore, make_slug
from ..engines import layout as layout_engine
from ..engines import source as source_engine
from ..host_platform import FsProfile
from ..layout_target import (
    LayoutTarget,
    LayoutTargetAbsent,
    LayoutTargetPresentBranchHead,
)
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


def materialize(
    slug: str,
    *,
    location: str,
    branch: str,
    repo_store: RepoStore,
    workspace_root: Path,
    offline_root: Path,
    profile: FsProfile,
) -> tuple[source_engine.SourceReport, layout_engine.LayoutReport]:
    """Place ``slug`` at ``workspace_root/location`` (source-then-layout).

    Re-scans between the engines so the layout step sees the post-acquisition
    state. Returns both reports; the caller decides what to do on failure.
    """
    target = LayoutTarget(
        targets={
            slug: LayoutTargetPresentBranchHead(branch=branch, location=location),
        }
    )

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


def dematerialize(
    slug: str,
    *,
    workspace_root: Path,
    offline_root: Path,
) -> layout_engine.LayoutReport:
    """Retire ``slug`` from its location back to offline (layout-only)."""
    target = LayoutTarget(targets={slug: LayoutTargetAbsent()})
    inventory = scan(workspace_root, offline_root)
    return layout_engine.run(
        target,
        inventory=inventory,
        workspace_root=workspace_root,
        offline_root=offline_root,
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

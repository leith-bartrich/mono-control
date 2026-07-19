"""The shared verb implementations the CLI + aspects both build on.

``apply_target`` is the single layout-target orchestrator: scan, run the
source engine, re-scan, run the layout engine, return both reports. Every
mat / demat verb builds its own ``LayoutTarget`` and hands it here.
``acquire`` runs the source half alone (clone/fetch into offline, no
placement) for callers that need a repo present before deciding placement.
``init`` and ``mark_aspect`` are the two verbs that *don't* fit that shape
(one creates a repo def, one toggles a flag).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import ConfigError, Repo, RepoStore, make_slug, slugify
from ..config import source_names as sn
from ..engines import layout as layout_engine
from ..engines import source as source_engine
from ..git import GitError, GitRepo
from ..host_platform import FsProfile
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
    workspace_root: Path,
    offline_root: Path,
    profile: FsProfile,
) -> tuple[str, source_engine.SourceReport]:
    """Create a brand-new repo def + ``git init`` it into offline.

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
    inventory = scan(workspace_root, offline_root)
    report = source_engine.run(
        source_engine.SourceRequest(
            refs_by_slug={slug: set()}, initial_branch=initial_branch
        ),
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


def acquire(
    slugs: set[str],
    *,
    repo_store: RepoStore,
    workspace_root: Path,
    offline_root: Path,
    profile: FsProfile,
) -> source_engine.SourceReport:
    """Acquire repos into offline (clone / init / fetch) **without placing them**.

    The source half of :func:`apply_target` used on its own — when a caller needs
    a repo present locally to read its contents before deciding placement (e.g.
    reading a product cluster's layout before a swap tears the workspace down, so
    an unreachable cluster fails *before* anything is cleared).
    """
    inventory = scan(workspace_root, offline_root)
    return source_engine.run(
        source_engine.SourceRequest(refs_by_slug={s: set() for s in slugs}),
        repo_store=repo_store,
        inventory=inventory,
        offline_root=offline_root,
        profile=profile,
    )


@dataclass(frozen=True)
class ForkAdoption:
    """What :func:`adopt_fork` did — config changes plus the eager remote stamp."""

    slug: str
    source_key: str  # "fork-ours" or "fork-<purpose>"
    url: str
    dev_repointed: bool
    old_dev: str | None  # recorded as branches["dev-upstream"] when repointed
    new_dev: str | None
    checkout: Path | None  # on-disk location, or None (config-only)
    remote_stamped: bool
    remote_error: str | None  # stamp failed; config was still saved


def adopt_fork(
    slug: str,
    url: str,
    *,
    purpose: str = "ours",
    dev_branch: str | None = None,
    repo_store: RepoStore,
    workspace_root: Path,
    offline_root: Path,
) -> ForkAdoption:
    """The governed upstream→fork transition (see ``docs/design/layers/data/repo.md``).

    Adds ``fork-<purpose>`` beside the repo's ``upstream`` — upstream-only for
    now: an ``origin`` repo gaining a fork is a plain ``source add``, and an
    ``origin`` *adopting* an upstream is the other governed migration. When the
    fork is ours and ``dev_branch`` differs from the current dev line, ``dev``
    repoints to it and the old line is preserved as ``dev-upstream``.

    The new key is appended after ``upstream``, so first-declared source
    resolution is unchanged. Config is saved first; when a checkout exists on
    disk the fork remote is then eagerly stamped into ``.git/config`` — a
    failed stamp is reported via ``remote_error``, never rolled back (engines
    will conform remotes later).
    """
    repo = repo_store.load(slug)
    if sn.UPSTREAM not in repo.sources:
        raise ConfigError(
            f"repo {slug!r} has no {sn.UPSTREAM!r} source — the fork transition "
            "applies to upstream-based repos (for an origin repo, just add the "
            "source directly)"
        )
    key = sn.FORK_OURS if purpose == "ours" else sn.fork_key(slugify(purpose))
    if key in repo.sources:
        raise ConfigError(
            f"repo {slug!r} already has source {key!r} — use `repo source add` "
            "to change its URL"
        )
    if dev_branch is not None and key != sn.FORK_OURS:
        raise ConfigError(
            "a third-party fork is a tracked reference and never repoints "
            f"{sn.DEV!r} — drop the dev branch or use purpose 'ours'"
        )

    old_dev = repo.branches.get(sn.DEV)
    dev_repointed = dev_branch is not None and dev_branch != old_dev
    if dev_repointed:
        existing = repo.branches.get(sn.DEV_UPSTREAM)
        if existing is not None and existing != old_dev:
            raise ConfigError(
                f"repo {slug!r} already records {sn.DEV_UPSTREAM!r} = "
                f"{existing!r}; refusing to overwrite it"
            )
        if old_dev is not None:
            repo.branches[sn.DEV_UPSTREAM] = old_dev
        repo.branches[sn.DEV] = dev_branch

    repo.sources[key] = url  # plain append — upstream stays first-declared
    repo_store.save(repo)

    checkout: Path | None = None
    remote_stamped = False
    remote_error: str | None = None
    observed = scan(workspace_root, offline_root).repos.get(slug)
    if observed is not None:
        checkout = observed.location
        try:
            GitRepo(checkout).set_remote(key, url)
            remote_stamped = True
        except GitError as e:
            remote_error = str(e)

    return ForkAdoption(
        slug=slug,
        source_key=key,
        url=url,
        dev_repointed=dev_repointed,
        old_dev=old_dev,
        new_dev=repo.branches.get(sn.DEV),
        checkout=checkout,
        remote_stamped=remote_stamped,
        remote_error=remote_error,
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

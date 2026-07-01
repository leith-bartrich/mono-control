"""Shared product-cluster operations behind both the CLI and the interactive manager.

Pure logic (no Typer): each verb renders its per-slug outcomes via the given
``console`` and returns whether it **succeeded** — the scriptable CLI turns that into
an exit code, the interactive manager stays in its menu. This is the "thin
presentation over shared logic" split from ``docs/design/ui/README.md``; keeping the
place / clear / relayout / swap / demat logic here is what stops the two surfaces from
drifting.
"""

from __future__ import annotations

from typing import Callable

from rich.console import Console

from mono_control import paths, repo_ops
from mono_control.config import Repo, RepoStore
from mono_control.host_platform import profile as host_profile
from mono_control.layout_target import (
    LayoutTarget,
    LayoutTargetAbsent,
    LayoutTargetPresentAsIs,
)
from mono_control.on_disk import scan

from ..registry import discover_repos
from .cluster_layout import (
    ClusterLayoutError,
    ClusterLayoutStore,
    resolve_cluster_checkout,
)
from .naming import default_subdir

ASPECT = "product-cluster"


def aspect_location(repo: Repo, subdir: str | None = None) -> str:
    """Compose ``products/<subdir>`` (subdir defaults to the slugified repo name)."""
    return f"products/{subdir or default_subdir(repo)}"


def _err(console: Console, message: object) -> None:
    console.print(f"[red]error:[/red] {message}")


def apply(target: LayoutTarget, *, store: RepoStore, console: Console) -> bool:
    """Run source → layout for ``target``, render both reports, return success."""
    source_report, layout_report = repo_ops.apply_target(
        target,
        repo_store=store,
        workspace_root=paths.REPOS_DIR,
        offline_root=paths.OFFLINE_DIR,
        profile=host_profile(),
    )
    repo_ops.render_outcomes("source", source_report.outcomes, console=console)
    repo_ops.render_outcomes("layout", layout_report.outcomes, console=console)
    return source_report.ok and layout_report.ok


def dirty_clusters(store: RepoStore) -> list[str]:
    """All materialized product-clusters with uncommitted changes.

    A product cluster's *committed* state anchors reproducibility, so tearing a dirty
    one down (clear / swap / demat) would un-pin the current layout. Member repos are
    exempt — their work rides to offline on retire and is restored on re-place. Each
    caller filters this to the clusters *it* would retire (see :func:`_gate`).
    """
    inv = scan(paths.REPOS_DIR, paths.OFFLINE_DIR)
    return sorted(
        r.slug
        for r in discover_repos(store, ASPECT)
        if (o := inv.repos.get(r.slug)) is not None
        and o.state == "materialized"
        and o.dirty
    )


def _gate(
    dirty: list[str], console: Console, on_dirty: Callable[[list[str]], bool] | None
) -> bool:
    """Decide whether a teardown may proceed given the dirty clusters it would retire.

    Empty → yes. Otherwise the caller's ``on_dirty`` decides (CLI ``--allow-dirty`` →
    always yes; the interactive manager → a "proceed anyway?" prompt). With no
    ``on_dirty`` the gate refuses and prints why — the default scriptable behavior.
    The gate guards *reproducibility*, not data: retire is non-destructive, so an
    override loses nothing, it just accepts an un-pinned teardown.
    """
    if not dirty:
        return True
    if on_dirty is not None:
        return bool(on_dirty(dirty))
    _err(
        console,
        f"product-cluster(s) have uncommitted changes ({', '.join(dirty)}); "
        f"commit them first so the current layout stays reproducible",
    )
    return False


def place(repo: Repo, subdir: str | None, *, store: RepoStore, console: Console) -> bool:
    """Place a cluster at ``products/<subdir>`` (placement only, no ref change)."""
    target = LayoutTarget(
        targets={repo.slug: LayoutTargetPresentAsIs(location=aspect_location(repo, subdir))}
    )
    return apply(target, store=store, console=console)


def demat(
    repo: Repo,
    *,
    store: RepoStore,
    console: Console,
    on_dirty: Callable[[list[str]], bool] | None = None,
) -> bool:
    """Retire a cluster to offline; gated if *that* cluster is dirty."""
    dirty = [repo.slug] if repo.slug in dirty_clusters(store) else []
    if not _gate(dirty, console, on_dirty):
        return False
    return apply(
        LayoutTarget(targets={repo.slug: LayoutTargetAbsent()}), store=store, console=console
    )


def clear(
    *,
    store: RepoStore,
    console: Console,
    on_dirty: Callable[[list[str]], bool] | None = None,
) -> bool:
    """Reset the whole workspace to empty; gated if *any* cluster is dirty."""
    if not _gate(dirty_clusters(store), console, on_dirty):
        return False
    return apply(LayoutTarget(pre_clear=True, targets={}), store=store, console=console)


def relayout(
    repo: Repo,
    *,
    store: RepoStore,
    console: Console,
    on_dirty: Callable[[list[str]], bool] | None = None,
) -> bool:
    """Incrementally reconcile the workspace to ``repo``'s layout — the core verb.

    Places members that are missing, retires ones no longer in the layout, and leaves
    already-correct repos untouched (one exclusive ``pre_clear`` reconcile). The target
    cluster is *kept*, so its own dirtiness never gates — editing a layout then
    re-laying-it-out is the normal case, and relayout reads its working-tree layout.
    """
    # Gate only the clusters this reconcile would retire: everything dirty *except* the
    # target (which stays placed).
    dirty = [s for s in dirty_clusters(store) if s != repo.slug]
    if not _gate(dirty, console, on_dirty):
        return False

    # Ensure the cluster is present so its layout is readable; acquire only if absent
    # (no churn for the common already-present case).
    if repo.slug not in scan(paths.REPOS_DIR, paths.OFFLINE_DIR).repos:
        src = repo_ops.acquire(
            {repo.slug},
            repo_store=store,
            workspace_root=paths.REPOS_DIR,
            offline_root=paths.OFFLINE_DIR,
            profile=host_profile(),
        )
        repo_ops.render_outcomes("acquire", src.outcomes, console=console)
        if not src.ok:
            return False

    try:
        checkout = resolve_cluster_checkout(
            repo.slug,
            workspace_root=paths.REPOS_DIR,
            offline_root=paths.OFFLINE_DIR,
            require_materialized=False,
        )
        layout = ClusterLayoutStore(checkout).load_or_empty()
    except ClusterLayoutError as e:
        _err(console, e)
        return False

    targets = {repo.slug: LayoutTargetPresentAsIs(location=aspect_location(repo))}
    for slug, member in layout.members.items():
        targets[slug] = LayoutTargetPresentAsIs(location=member.location)
    return apply(LayoutTarget(pre_clear=True, targets=targets), store=store, console=console)


def swap(
    repo: Repo,
    *,
    store: RepoStore,
    console: Console,
    on_dirty: Callable[[list[str]], bool] | None = None,
) -> bool:
    """Switch to ``repo``'s layout from a clean slate — ``clear`` then ``relayout``.

    The target is acquired **up front** (fail-early), so an unreachable cluster aborts
    before anything is torn down. ``clear`` then removes the current cluster (and
    everything else) — gating all clusters, including this one, which swap *does* tear
    down — and ``relayout`` lays out the now-offline target with no two-cluster window.
    """
    src = repo_ops.acquire(
        {repo.slug},
        repo_store=store,
        workspace_root=paths.REPOS_DIR,
        offline_root=paths.OFFLINE_DIR,
        profile=host_profile(),
    )
    repo_ops.render_outcomes("acquire", src.outcomes, console=console)
    if not src.ok:
        return False
    if not clear(store=store, console=console, on_dirty=on_dirty):
        return False
    return relayout(repo, store=store, console=console, on_dirty=on_dirty)

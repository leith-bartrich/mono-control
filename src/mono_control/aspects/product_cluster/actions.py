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
from mono_control.config import Repo, RepoStore, source_names
from mono_control.layout_target import (
    LayoutTarget,
    LayoutTargetAbsent,
    LayoutTargetPresentAsIs,
    LayoutTargetPresentBranchHead,
)
from mono_control.on_disk import scan

from ..registry import discover_repos
from . import composition
from .cluster_layout import (
    ClusterLayout,
    ClusterLayoutError,
    ClusterLayoutStore,
    require_cluster_present,
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
        broker=store.broker,
        work_root=paths.WORK_DIR,
        bare_root=paths.BARE_DIR,
    )
    repo_ops.render_outcomes("source", source_report.outcomes, console=console)
    repo_ops.render_outcomes("layout", layout_report.outcomes, console=console)
    return source_report.ok and layout_report.ok


def dirty_clusters(store: RepoStore) -> list[str]:
    """All materialized product-clusters with uncommitted changes.

    A product cluster's *committed* state anchors reproducibility, so tearing a dirty
    one down (clear / swap / demat) would un-pin the current layout. Member repos are
    not surfaced here, but the broker's ``retire`` is itself dirty-gated (a worktree
    with uncommitted changes is refused rather than discarded), so a dirty member is
    never silently lost either. Each caller filters this to the clusters *it* would
    retire (see :func:`_gate`).
    """
    inv = scan(store.broker, paths.WORK_DIR, paths.BARE_DIR)
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
    """Retire a cluster to offline (remove its worktree); gated if *that* cluster is dirty."""
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
    """Reset the whole workspace to empty (remove every worktree); gated if *any* cluster is dirty."""
    if not _gate(dirty_clusters(store), console, on_dirty):
        return False
    return apply(LayoutTarget(pre_clear=True, targets={}), store=store, console=console)


def _read_layout(repo: Repo, *, store: RepoStore, console: Console):
    """Acquire ``repo`` if absent, then read its layout — or ``None`` if unreadable.

    Acquiring is free (a bare clone, no worktree) and makes an unreachable remote fail
    here rather than halfway through a reconcile. Reading tolerates an *offline*
    cluster: the layout comes from the bare repo's HEAD blob when there's no worktree.
    """
    if repo.slug not in scan(store.broker, paths.WORK_DIR, paths.BARE_DIR).repos:
        src = repo_ops.acquire({repo.slug}, broker=store.broker)
        repo_ops.render_outcomes("acquire", src.outcomes, console=console)
        if not src.ok:
            return None
    try:
        require_cluster_present(
            store.broker,
            repo.slug,
            work_root=paths.WORK_DIR,
            bare_root=paths.BARE_DIR,
            require_materialized=False,
        )
        return ClusterLayoutStore(store.broker, repo.slug).load_or_empty()
    except ClusterLayoutError as e:
        _err(console, e)
        return None


def relayout(
    repo: Repo,
    *,
    store: RepoStore,
    console: Console,
    on_dirty: Callable[[list[str]], bool] | None = None,
    on_missing_required: Callable[[list[str]], bool] | None = None,
) -> bool:
    """Reconcile the workspace to the layouts of ``repo`` and everything it requires.

    The core verb. Resolves the co-activation closure from ``repo`` (see
    :mod:`.composition`), merges the active clusters' members into one arrangement,
    and applies it as a single exclusive ``pre_clear`` reconcile: missing members are
    placed, ones no longer claimed by any active cluster are retired, and already
    correct repos are left untouched.

    Ordering never enters. The closure is a fixpoint over a visited set (so a
    ``requires`` cycle just means those clusters are always co-active) and the merge
    is commutative, so the result does not depend on which cluster was named.

    A required cluster is always **acquired** — free, and it fails early. Whether its
    *worktree* is then placed is an intent question, so it is the caller's: with no
    ``on_missing_required`` the reconcile refuses and says which clusters are missing
    (the scriptable default); the callback opts in.
    """
    known = {r.slug: r for r in discover_repos(store, ASPECT)}

    layouts: dict[str, ClusterLayout] = {}
    unknown: list[str] = []

    def read(slug: str) -> ClusterLayout | None:
        target = known.get(slug)
        if target is None:
            unknown.append(slug)
            return None
        layout = _read_layout(target, store=store, console=console)
        if layout is not None:
            layouts[slug] = layout
        return layout

    closure = composition.resolve_closure(repo.slug, read)

    if unknown:
        _err(
            console,
            f"required cluster(s) not declared as {ASPECT} in config: "
            f"{', '.join(sorted(set(unknown)))}",
        )
        return False
    if closure.unresolved:
        _err(console, f"could not read layout for: {', '.join(closure.unresolved)}")
        return False
    if closure.cycles:
        console.print(
            f"[yellow]note:[/yellow] `requires` cycle among "
            f"{', '.join(closure.cycles)} — they can only ever be active together, "
            f"which usually means they are one cluster"
        )

    # Gate only the clusters this reconcile would retire: everything dirty that isn't
    # staying active.
    active = set(closure.active)
    if not _gate([s for s in dirty_clusters(store) if s not in active], console, on_dirty):
        return False

    merge = composition.merge_members(layouts)
    for join in merge.joins:
        console.print(f"[yellow]dev override:[/yellow] {join.describe()}")
    if not merge.ok:
        for conflict in merge.conflicts:
            _err(console, conflict.describe())
        return False

    inv = scan(store.broker, paths.WORK_DIR, paths.BARE_DIR)
    materialized = {s for s, o in inv.repos.items() if o.state == "materialized"}
    missing = composition.missing_worktrees(
        (s for s in closure.active if s != repo.slug), materialized
    )
    if missing:
        if on_missing_required is None:
            _err(
                console,
                f"required cluster(s) not placed ({', '.join(missing)}); place them "
                f"first (`mat moveto`) or re-run opting in to placing them",
            )
            return False
        if not on_missing_required(list(missing)):
            return False

    targets: dict[str, LayoutTargetPresentAsIs | LayoutTargetPresentBranchHead] = {
        slug: _placement_target(
            slug, aspect_location(known[slug]), follow_dev=True,
            materialized=materialized, store=store,
        )
        for slug in closure.active
    }
    for slug, member in merge.members.items():
        targets[slug] = _placement_target(
            slug, member.location, follow_dev=member.role == "dev",
            materialized=materialized, store=store,
        )
    return apply(LayoutTarget(pre_clear=True, targets=targets), store=store, console=console)


def _placement_target(
    slug: str,
    location: str,
    *,
    follow_dev: bool,
    materialized: set[str],
    store: RepoStore,
) -> LayoutTargetPresentAsIs | LayoutTargetPresentBranchHead:
    """The ref intent relayout expresses for one repo at ``location``.

    Two rules, both from #30.

    **Only on fresh placement.** An already-materialized worktree keeps whatever
    ref it is on. Relayout means *membership and location*; a developer sitting on
    a feature branch in a dev member must not be yanked back to the dev line
    because someone re-ran a layout. That also means no migration pass: existing
    worktrees are left exactly as they are, and `mat branchat` is how you move one.

    **Dev members and the cluster follow their line; deps stay detached.** A dev
    member's latest *is* a living branch head and ``branches.dev`` names it, so the
    intent is determined by inputs relayout already holds. A dep's revision comes
    from the snapshot ledger — inputs relayout does not read and, by contract,
    should not — so expressing a line for it would assert a revision policy it has
    no authority over. Detached is the honest form of "no policy applied yet".

    A repo that declares no ``dev`` line gets no opinion either: ``branches.dev``
    is what names the line, and inventing one from the remote's default would be
    guessing at policy rather than reading it.
    """
    if slug in materialized or not follow_dev:
        return LayoutTargetPresentAsIs(location=location)
    try:
        dev = store.load(slug).branches.get(source_names.DEV)
    except Exception:  # noqa: BLE001 - an unreadable def is the layout engine's to report
        dev = None
    if not dev:
        return LayoutTargetPresentAsIs(location=location)
    return LayoutTargetPresentBranchHead(branch=dev, location=location)


def swap(
    repo: Repo,
    *,
    store: RepoStore,
    console: Console,
    on_dirty: Callable[[list[str]], bool] | None = None,
    on_missing_required: Callable[[list[str]], bool] | None = None,
) -> bool:
    """Switch to ``repo``'s layout from a clean slate — ``clear`` then ``relayout``.

    The target is acquired **up front** (fail-early), so an unreachable cluster aborts
    before anything is torn down. ``clear`` then removes the current cluster (and
    everything else) — gating all clusters, including this one, which swap *does* tear
    down — and ``relayout`` lays out the now-offline target.

    Swapping to a cluster that ``requires`` others activates them too, so the result
    may hold more than one cluster. What ``swap`` still guarantees is that nothing
    from the *previous* arrangement survives into the new one.
    """
    src = repo_ops.acquire({repo.slug}, broker=store.broker)
    repo_ops.render_outcomes("acquire", src.outcomes, console=console)
    if not src.ok:
        return False
    if not clear(store=store, console=console, on_dirty=on_dirty):
        return False
    return relayout(
        repo,
        store=store,
        console=console,
        on_dirty=on_dirty,
        on_missing_required=on_missing_required,
    )

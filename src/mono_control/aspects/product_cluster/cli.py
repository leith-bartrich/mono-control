"""``mproj control product-cluster <verb>`` — the first user-facing feature.

Thin shell over :mod:`mono_control.repo_ops` and the aspect's shared
:mod:`.actions` logic: the scriptable commands here translate a verb's success into
an exit code, while the interactive manager (:mod:`.manager_ui`) drives the same
``actions`` from a menu — two presentations over one logic layer (see
``docs/design/ui/README.md``). Only resolution / validation helpers and the
``list-available`` / ``mark`` / ``init`` verbs live here directly.

Lookup verbs accept ``<name_or_slug>`` and support ``--slug`` / ``-s`` to
force slug-only lookup. ``init`` takes ``<name>`` and derives its slug.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from mono_control import paths, repo_ops
from mono_control.config import (
    AmbiguousNameError,
    ConfigConflictError,
    ConfigError,
    Repo,
    RepoStore,
    resolve_repo,
)
from mono_control.host_platform import profile as host_profile
from mono_control.layout_target import (
    LayoutTarget,
    LayoutTargetPresentAsIs,
    LayoutTargetPresentBranchHead,
    LayoutTargetPresentCommit,
)
from mono_control.on_disk import scan

from ..registry import discover_repos
from . import actions
from .actions import ASPECT
from .cluster_layout import (
    ClusterLayoutError,
    ClusterLayoutStore,
    LayoutMember,
    resolve_cluster_checkout,
)

console = Console()
app = typer.Typer(help="Manage product-cluster repos.", no_args_is_help=True)

_SLUG_FLAG = typer.Option(
    False, "--slug", "-s", help="Treat the argument as a slug; skip name fallback."
)

_ALLOW_DIRTY = typer.Option(
    False, "--allow-dirty", help="Proceed even if a product cluster has uncommitted changes."
)


def _store(ctx: typer.Context) -> RepoStore:
    return RepoStore.from_config_dir(ctx.obj)


def _fail(message: object) -> typer.Exit:
    console.print(f"[red]error:[/red] {message}")
    return typer.Exit(code=1)


def _exit_unless(ok: bool) -> None:
    """Translate an action's success flag into a process exit code."""
    if not ok:
        raise typer.Exit(code=1)


def _allow(flag: bool):
    """Map ``--allow-dirty`` to an ``on_dirty`` callback (None gates normally)."""
    return (lambda _dirty: True) if flag else None


def _resolve(ctx: typer.Context, query: str, *, slug_only: bool) -> Repo:
    try:
        return resolve_repo(_store(ctx), query, slug_only=slug_only)
    except (AmbiguousNameError, ConfigError) as e:
        raise _fail(e)


def _require_aspect(repo: Repo) -> None:
    if ASPECT not in repo.aspects:
        raise _fail(
            f"repo {repo.slug!r} does not declare the {ASPECT} aspect; mark it first"
        )


@app.command("list-available")
def list_available(ctx: typer.Context) -> None:
    """Show every repo def that declares the product-cluster aspect."""
    matches = discover_repos(_store(ctx), ASPECT)
    if not matches:
        console.print("no product-cluster repos declared")
        return
    table = Table("slug", "name", box=None)
    for repo in matches:
        table.add_row(repo.slug, repo.name)
    console.print(table)


@app.command("mark")
def mark(
    ctx: typer.Context,
    name_or_slug: str,
    slug_only: bool = _SLUG_FLAG,
) -> None:
    """Add the product-cluster aspect to an existing repo def."""
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    try:
        newly = repo_ops.mark_aspect(repo.slug, ASPECT, repo_store=_store(ctx))
    except ConfigError as e:
        raise _fail(e)
    if not newly:
        console.print(f"[yellow]already marked[/yellow] {repo.slug}")
        return
    console.print(f"[green]marked[/green] {repo.slug} as {ASPECT}")


@app.command("init")
def init(
    ctx: typer.Context,
    name: str,
    slug: str = typer.Option(
        None,
        "--slug",
        help="Slug override (default: derived as `slugify(name)-<4 hex>`).",
    ),
) -> None:
    """Create a brand-new product-cluster repo def + init it into offline."""
    store = _store(ctx)
    try:
        resolved_slug, report = repo_ops.init(
            name,
            slug=slug,
            aspects={ASPECT},
            repo_store=store,
            workspace_root=paths.REPOS_DIR,
            offline_root=paths.OFFLINE_DIR,
            profile=host_profile(),
        )
    except (ConfigConflictError, ConfigError) as e:
        raise _fail(e)
    console.print(f"[green]created[/green] {resolved_slug}")
    repo_ops.render_outcomes(f"init {resolved_slug}", report.outcomes, console=console)
    _exit_unless(report.ok)


@app.command("manage")
def manage(ctx: typer.Context) -> None:
    """Interactively manage product clusters (menu-driven; needs a TTY).

    The top-level interactive surface — the peer of ``repo manage`` — over the same
    ``actions`` the scriptable verbs use.
    """
    from .manager_ui import manage as run_manage

    run_manage(_store(ctx))


# --------------------------------------------------------------------------- #
# `product-cluster mat <intent>` — bring/keep the cluster repo on disk
# --------------------------------------------------------------------------- #
mat_app = typer.Typer(
    help="Bring/keep a cluster on disk. Sub-intents: moveto / branchat / commit / layout-target.",
    no_args_is_help=True,
)
app.add_typer(mat_app, name="mat")


def _observed_materialized_location(repo: Repo) -> str:
    """Return the cluster's current subdir under REPOS_DIR, or fail."""
    inv = scan(paths.REPOS_DIR, paths.OFFLINE_DIR)
    observed = inv.repos.get(repo.slug)
    if observed is None or observed.state != "materialized":
        raise _fail(
            f"{repo.slug!r} is not materialized; use `mat moveto` first, "
            f"or `mat layout-target` to place and check out in one command"
        )
    try:
        return str(observed.location.relative_to(paths.REPOS_DIR))
    except ValueError:
        raise _fail(
            f"{repo.slug!r} is at {observed.location}, which is not under "
            f"the workspace root {paths.REPOS_DIR}"
        )


def _validate_branchat_sub(value: str) -> str:
    if value != "head":
        raise typer.BadParameter(
            f"unsupported sub-intent {value!r}; only 'head' is implemented"
        )
    return value


def _validate_commit_sub(value: str) -> str:
    if value != "detached":
        raise typer.BadParameter(
            f"unsupported sub-intent {value!r}; only 'detached' is implemented"
        )
    return value


@mat_app.command("moveto")
def mat_moveto(
    ctx: typer.Context,
    name_or_slug: str,
    subdir_override: str = typer.Argument(
        None,
        help="Subdir name under products/ (default: derived from repo name).",
    ),
    slug_only: bool = _SLUG_FLAG,
) -> None:
    """Place a cluster at ``mono-repos/products/<subdir>``, no ref change."""
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    _require_aspect(repo)
    _exit_unless(actions.place(repo, subdir_override, store=_store(ctx), console=console))


@mat_app.command("branchat")
def mat_branchat(
    ctx: typer.Context,
    name_or_slug: str,
    branch: str,
    sub_intent: str = typer.Argument("head", callback=_validate_branchat_sub),
    slug_only: bool = _SLUG_FLAG,
) -> None:
    """Check out a branch's head at the cluster's current location."""
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    _require_aspect(repo)
    location = _observed_materialized_location(repo)
    target = LayoutTarget(
        targets={
            repo.slug: LayoutTargetPresentBranchHead(branch=branch, location=location),
        }
    )
    _exit_unless(actions.apply(target, store=_store(ctx), console=console))
    del sub_intent


@mat_app.command("commit")
def mat_commit(
    ctx: typer.Context,
    name_or_slug: str,
    commit: str,
    sub_intent: str = typer.Argument("detached", callback=_validate_commit_sub),
    slug_only: bool = _SLUG_FLAG,
) -> None:
    """Check out a specific commit (detached HEAD) at the cluster's current location."""
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    _require_aspect(repo)
    location = _observed_materialized_location(repo)
    target = LayoutTarget(
        targets={
            repo.slug: LayoutTargetPresentCommit(commit=commit, location=location),
        }
    )
    _exit_unless(actions.apply(target, store=_store(ctx), console=console))
    del sub_intent


@mat_app.command("layout-target")
def mat_layout_target(
    ctx: typer.Context,
    name_or_slug: str,
    name: str = typer.Option(
        None,
        "--name",
        help="Subdir under mono-repos/products/ (default: slugified repo name).",
    ),
    branch: str = typer.Option(
        None, "--branch", help="Branch whose head to check out (mutually exclusive with --commit)."
    ),
    commit: str = typer.Option(
        None, "--commit", help="Specific commit to check out (mutually exclusive with --branch)."
    ),
    slug_only: bool = _SLUG_FLAG,
) -> None:
    """Declarative one-liner: place at ``products/<name>`` + (optionally) check out a ref."""
    if branch and commit:
        raise _fail("--branch and --commit are mutually exclusive")
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    _require_aspect(repo)
    location = actions.aspect_location(repo, name)
    if branch:
        desired = LayoutTargetPresentBranchHead(branch=branch, location=location)
    elif commit:
        desired = LayoutTargetPresentCommit(commit=commit, location=location)
    else:
        desired = LayoutTargetPresentAsIs(location=location)
    target = LayoutTarget(targets={repo.slug: desired})
    _exit_unless(actions.apply(target, store=_store(ctx), console=console))


@app.command("demat")
def demat(
    ctx: typer.Context,
    name_or_slug: str,
    slug_only: bool = _SLUG_FLAG,
    allow_dirty: bool = _ALLOW_DIRTY,
) -> None:
    """Retire a product-cluster from its location back to offline.

    Non-destructive, but refused if the cluster is dirty (its committed state
    anchors reproducibility — see :mod:`.actions`). ``--allow-dirty`` overrides.
    """
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    _require_aspect(repo)
    _exit_unless(
        actions.demat(repo, store=_store(ctx), console=console, on_dirty=_allow(allow_dirty))
    )


# --------------------------------------------------------------------------- #
# Cluster-targeting helpers shared by `conform` and `layout`
# --------------------------------------------------------------------------- #
def _resolve_cluster(
    ctx: typer.Context, name_or_slug: str | None, *, slug_only: bool = False
) -> Repo:
    """Resolve the target cluster: a named one, or the sole materialized one.

    When ``name_or_slug`` is omitted, resolve to the single materialized repo
    that declares the aspect; error on zero or more than one (never guess).
    """
    store = _store(ctx)
    if name_or_slug is not None:
        repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
        _require_aspect(repo)
        return repo
    inv = scan(paths.REPOS_DIR, paths.OFFLINE_DIR)
    materialized = [
        repo
        for repo in discover_repos(store, ASPECT)
        if (o := inv.repos.get(repo.slug)) is not None and o.state == "materialized"
    ]
    if len(materialized) == 1:
        return materialized[0]
    if not materialized:
        raise _fail(
            "no materialized product-cluster; name one or place it first "
            "(`mat moveto` / `conform swap`)"
        )
    slugs = ", ".join(sorted(r.slug for r in materialized))
    raise _fail(f"multiple materialized product-clusters ({slugs}); name one")


def _layout_store_for(repo: Repo) -> ClusterLayoutStore:
    """Build a layout store rooted at ``repo``'s materialized checkout, or fail."""
    try:
        checkout = resolve_cluster_checkout(
            repo.slug,
            workspace_root=paths.REPOS_DIR,
            offline_root=paths.OFFLINE_DIR,
        )
    except ClusterLayoutError as e:
        raise _fail(e)
    return ClusterLayoutStore(checkout)


# --------------------------------------------------------------------------- #
# `product-cluster conform <intent>` — bring the WORKSPACE to a target
# --------------------------------------------------------------------------- #
conform_app = typer.Typer(
    help="Conform the workspace to a target. Sub-intents: relayout / clear / swap.",
    no_args_is_help=True,
)
app.add_typer(conform_app, name="conform")


@conform_app.command("relayout")
def conform_relayout(
    ctx: typer.Context,
    name_or_slug: str = typer.Argument(
        None, help="Cluster name or slug (default: the sole materialized one)."
    ),
    allow_dirty: bool = _ALLOW_DIRTY,
) -> None:
    """Reconcile the workspace to a cluster's layout — the core verb.

    Pulls in members missing from the workspace, retires ones no longer in the layout,
    and leaves already-correct repos untouched (one exclusive reconcile, no teardown).
    """
    repo = _resolve_cluster(ctx, name_or_slug)
    _exit_unless(
        actions.relayout(repo, store=_store(ctx), console=console, on_dirty=_allow(allow_dirty))
    )


@conform_app.command("clear")
def conform_clear(ctx: typer.Context, allow_dirty: bool = _ALLOW_DIRTY) -> None:
    """Reset the whole workspace to empty (retire every repo to offline).

    Non-destructive — repos move to ``mono-repos-offline/`` — but refused if any
    materialized product-cluster is dirty (its committed state anchors
    reproducibility); ``--allow-dirty`` overrides. Member repos may be dirty: their
    work rides to offline and is restored on re-place.
    """
    _exit_unless(actions.clear(store=_store(ctx), console=console, on_dirty=_allow(allow_dirty)))


@conform_app.command("swap")
def conform_swap(
    ctx: typer.Context,
    name_or_slug: str,
    slug_only: bool = _SLUG_FLAG,
    allow_dirty: bool = _ALLOW_DIRTY,
) -> None:
    """Switch to a different cluster from a clean slate — `clear` then `relayout`.

    The target is acquired up front (fail-early), so an unreachable cluster aborts
    before anything is torn down; the `clear` removes the current cluster before the
    new one lands (no two-cluster window). Placement only, no refs.
    """
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    _require_aspect(repo)
    _exit_unless(
        actions.swap(repo, store=_store(ctx), console=console, on_dirty=_allow(allow_dirty))
    )


# --------------------------------------------------------------------------- #
# `product-cluster layout <verb>` — author/inspect a cluster's layout document
# --------------------------------------------------------------------------- #
layout_app = typer.Typer(
    help="Author/inspect a cluster's layout. Verbs: show / add / remove / validate / manage.",
    no_args_is_help=True,
)
app.add_typer(layout_app, name="layout")

# The cluster is an option (not a positional) so it can default to the sole
# materialized cluster while leaving the member slug as the positional for
# add/remove.
_CLUSTER_OPT = typer.Option(
    None, "--cluster", "-c", help="Cluster name or slug (default: the sole materialized one)."
)


def _validate_role(value: str) -> str:
    if value not in ("dev", "dep"):
        raise typer.BadParameter(f"role must be 'dev' or 'dep', not {value!r}")
    return value


@layout_app.command("show")
def layout_show(ctx: typer.Context, cluster: str = _CLUSTER_OPT) -> None:
    """Show a cluster's authored layout (members, locations, roles)."""
    repo = _resolve_cluster(ctx, cluster)
    layout = _layout_store_for(repo).load_or_empty()
    if not layout.members:
        console.print(f"no layout authored for {repo.slug}")
        return
    table = Table("slug", "location", "role", box=None)
    for slug, member in sorted(layout.members.items()):
        table.add_row(slug, member.location, member.role)
    console.print(table)


@layout_app.command("add")
def layout_add(
    ctx: typer.Context,
    member: str,
    location: str = typer.Option(
        ..., "--location", "-l", help="Subdir under mono-repos/ for the member."
    ),
    role: str = typer.Option(
        ..., "--role", "-r", callback=_validate_role, help="Member role: dev | dep."
    ),
    cluster: str = _CLUSTER_OPT,
) -> None:
    """Add or update a member in the cluster's layout."""
    repo = _resolve_cluster(ctx, cluster)
    member_repo = _resolve(ctx, member, slug_only=False)  # must resolve to a repo def
    store = _layout_store_for(repo)
    layout = store.load_or_empty()
    layout.members[member_repo.slug] = LayoutMember(location=location, role=role)
    store.save(layout)
    console.print(f"[green]set[/green] {member_repo.slug} → {location} ({role})")


@layout_app.command("remove")
def layout_remove(
    ctx: typer.Context,
    member: str,
    cluster: str = _CLUSTER_OPT,
) -> None:
    """Remove a member from the cluster's layout."""
    repo = _resolve_cluster(ctx, cluster)
    store = _layout_store_for(repo)
    layout = store.load_or_empty()
    # Accept a slug already in the layout (survives a purged def) or a resolvable name.
    key = member if member in layout.members else _resolve(ctx, member, slug_only=False).slug
    if layout.members.pop(key, None) is None:
        console.print(f"[yellow]not a member[/yellow] {member}")
        return
    store.save(layout)
    console.print(f"[green]removed[/green] {key}")


@layout_app.command("validate")
def layout_validate(ctx: typer.Context, cluster: str = _CLUSTER_OPT) -> None:
    """Check that every layout member resolves to a live repo def."""
    repo = _resolve_cluster(ctx, cluster)
    store = _layout_store_for(repo)
    try:
        layout = store.load()
    except ClusterLayoutError as e:
        raise _fail(e)
    known = set(_store(ctx).list(include_retired=True))
    missing = sorted(set(layout.members) - known)
    if missing:
        raise _fail(f"unknown member slugs: {', '.join(missing)}")
    console.print(f"[green]ok[/green] {repo.slug}: {len(layout.members)} member(s)")


@layout_app.command("manage")
def layout_manage(ctx: typer.Context, cluster: str = _CLUSTER_OPT) -> None:
    """Interactively author a cluster's layout (menu-driven; needs a TTY)."""
    repo = _resolve_cluster(ctx, cluster)
    store = _layout_store_for(repo)
    from .layout_ui import manage as run_manage

    run_manage(store, _store(ctx), repo.slug)

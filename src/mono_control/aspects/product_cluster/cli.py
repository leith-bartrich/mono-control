"""``mproj control product-cluster <verb>`` — the first user-facing feature.

Thin shell over :mod:`mono_control.repo_ops`: the verbs that aren't
aspect-specific (init, mat, demat) delegate to shared helpers; only
``list-available`` and ``mark`` (and the aspect's default-subdir convention)
live here. Composition, not inheritance.

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
    LayoutTargetAbsent,
    LayoutTargetPresentAsIs,
    LayoutTargetPresentBranchHead,
    LayoutTargetPresentCommit,
)
from mono_control.on_disk import scan

from ..registry import discover_repos
from .naming import default_subdir

ASPECT = "product-cluster"

console = Console()
app = typer.Typer(help="Manage product-cluster repos.", no_args_is_help=True)

_SLUG_FLAG = typer.Option(
    False, "--slug", "-s", help="Treat the argument as a slug; skip name fallback."
)


def _store(ctx: typer.Context) -> RepoStore:
    return RepoStore.from_config_dir(ctx.obj)


def _fail(message: object) -> typer.Exit:
    console.print(f"[red]error:[/red] {message}")
    return typer.Exit(code=1)


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
    if not report.ok:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# `product-cluster mat <intent>` — intent-verb subcommands
# --------------------------------------------------------------------------- #

mat_app = typer.Typer(
    help="Bring/keep a cluster on disk. Sub-intents: moveto / branchat / commit / layout-target.",
    no_args_is_help=True,
)
app.add_typer(mat_app, name="mat")


def _aspect_default_location(repo: Repo, subdir_override: str | None) -> str:
    """Compose ``products/<subdir>`` from the aspect convention."""
    subdir = subdir_override or default_subdir(repo)
    return f"products/{subdir}"


def _apply_and_exit(ctx: typer.Context, target: LayoutTarget) -> None:
    source_report, layout_report = repo_ops.apply_target(
        target,
        repo_store=_store(ctx),
        workspace_root=paths.REPOS_DIR,
        offline_root=paths.OFFLINE_DIR,
        profile=host_profile(),
    )
    repo_ops.render_outcomes("source", source_report.outcomes, console=console)
    repo_ops.render_outcomes("layout", layout_report.outcomes, console=console)
    if not (source_report.ok and layout_report.ok):
        raise typer.Exit(code=1)


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
    location = _aspect_default_location(repo, subdir_override)
    target = LayoutTarget(
        targets={repo.slug: LayoutTargetPresentAsIs(location=location)}
    )
    _apply_and_exit(ctx, target)


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
    _apply_and_exit(ctx, target)
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
    _apply_and_exit(ctx, target)
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
    location = _aspect_default_location(repo, name)
    if branch:
        desired = LayoutTargetPresentBranchHead(branch=branch, location=location)
    elif commit:
        desired = LayoutTargetPresentCommit(commit=commit, location=location)
    else:
        desired = LayoutTargetPresentAsIs(location=location)
    target = LayoutTarget(targets={repo.slug: desired})
    _apply_and_exit(ctx, target)


@app.command("demat")
def demat(
    ctx: typer.Context,
    name_or_slug: str,
    slug_only: bool = _SLUG_FLAG,
) -> None:
    """Retire a product-cluster from its location back to offline."""
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    _require_aspect(repo)
    target = LayoutTarget(targets={repo.slug: LayoutTargetAbsent()})
    _apply_and_exit(ctx, target)

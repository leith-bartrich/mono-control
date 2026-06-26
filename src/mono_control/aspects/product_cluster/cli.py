"""``mproj control product-cluster <verb>`` — the first user-facing feature.

Verbs:

- ``list-available`` — show every repo def declaring the ``product-cluster``
  aspect (cheap; no checkouts).
- ``mark <slug>`` — add the ``product-cluster`` aspect to an existing repo def.
- ``init <slug>`` — create a brand-new cluster repo def + init it into
  offline via the source engine. Mat it separately once it has commits.
- ``mat <slug>`` — place the cluster at ``mono-repos/products/<name>``,
  driving source-then-layout engine.
- ``demat <slug>`` — retire the cluster from its location back to offline.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from mono_control import paths
from mono_control.config import ConfigConflictError, ConfigError, Repo, RepoStore
from mono_control.engines import layout as layout_engine
from mono_control.engines import source as source_engine
from mono_control.host_platform import profile as host_profile
from mono_control.layout_target import (
    LayoutTarget,
    LayoutTargetAbsent,
    LayoutTargetPresentBranchHead,
)
from mono_control.on_disk import scan

from ..registry import discover_repos
from .naming import default_subdir

ASPECT = "product-cluster"

console = Console()

app = typer.Typer(help="Manage product-cluster repos.", no_args_is_help=True)


def _store(ctx: typer.Context) -> RepoStore:
    return RepoStore.from_config_dir(ctx.obj)


def _fail(message: object) -> typer.Exit:
    console.print(f"[red]error:[/red] {message}")
    return typer.Exit(code=1)


def _status_color(status: str) -> str:
    if status in {"ok", "cloned", "initialized", "fetched", "placed", "checked-out",
                  "relocated", "retired", "satisfied"}:
        return "green"
    if status == "blocked":
        return "yellow"
    return "red"


def _render_outcomes(title: str, outcomes: list) -> None:
    if not outcomes:
        return
    table = Table(title=title, show_edge=False, box=None)
    table.add_column("slug")
    table.add_column("status")
    table.add_column("summary")
    for o in outcomes:
        color = _status_color(o.status)
        table.add_row(o.slug, f"[{color}]{o.status}[/{color}]", o.summary)
    console.print(table)


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
def mark(ctx: typer.Context, slug: str) -> None:
    """Add the product-cluster aspect to an existing repo def."""
    store = _store(ctx)
    try:
        repo = store.load(slug)
    except ConfigError as e:
        raise _fail(e)
    if ASPECT in repo.aspects:
        console.print(f"[yellow]already marked[/yellow] {slug}")
        return
    repo.aspects.add(ASPECT)
    store.save(repo)
    console.print(f"[green]marked[/green] {slug} as {ASPECT}")


@app.command("init")
def init(
    ctx: typer.Context,
    slug: str,
    name: str = typer.Option(
        None, "--name", help="Display name for the new repo def (defaults to slug)."
    ),
) -> None:
    """Create a brand-new product-cluster repo def + init it into offline."""
    store = _store(ctx)
    if store.exists(slug):
        raise _fail(
            f"repo {slug!r} already exists; use `mark` to add the aspect to an existing repo"
        )
    repo = Repo(version=1, slug=slug, name=name or slug, aspects={ASPECT})
    try:
        store.create(repo)
    except (ConfigConflictError, ConfigError) as e:
        raise _fail(e)
    # Run source engine: no sources declared → it will `git init` into offline.
    inventory = scan(paths.REPOS_DIR, paths.OFFLINE_DIR)
    report = source_engine.run(
        source_engine.SourceRequest(refs_by_slug={slug: set()}),
        repo_store=store,
        inventory=inventory,
        offline_root=paths.OFFLINE_DIR,
        profile=host_profile(),
    )
    _render_outcomes(f"init {slug}", report.outcomes)
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("mat")
def mat(
    ctx: typer.Context,
    slug: str,
    name: str = typer.Option(
        None,
        "--name",
        help="Subdir under mono-repos/products/ (defaults to derived from slug).",
    ),
    branch: str = typer.Option(
        "main", "--branch", help="Which branch's head to check out."
    ),
) -> None:
    """Place a product-cluster at mono-repos/products/<name>."""
    store = _store(ctx)
    try:
        repo = store.load(slug)
    except ConfigError as e:
        raise _fail(e)
    if ASPECT not in repo.aspects:
        raise _fail(
            f"repo {slug!r} does not declare the {ASPECT} aspect; mark it first"
        )

    subdir = name or default_subdir(slug)
    target = LayoutTarget(
        targets={
            slug: LayoutTargetPresentBranchHead(
                branch=branch, location=f"products/{subdir}"
            ),
        }
    )

    inventory = scan(paths.REPOS_DIR, paths.OFFLINE_DIR)
    source_report = source_engine.run(
        source_engine.from_layout_target(target),
        repo_store=store,
        inventory=inventory,
        offline_root=paths.OFFLINE_DIR,
        profile=host_profile(),
    )
    _render_outcomes("source", source_report.outcomes)

    # Re-observe after acquisition so the layout engine sees the post-source state.
    inventory = scan(paths.REPOS_DIR, paths.OFFLINE_DIR)
    layout_report = layout_engine.run(
        target,
        inventory=inventory,
        workspace_root=paths.REPOS_DIR,
        offline_root=paths.OFFLINE_DIR,
    )
    _render_outcomes("layout", layout_report.outcomes)
    if not (source_report.ok and layout_report.ok):
        raise typer.Exit(code=1)


@app.command("demat")
def demat(ctx: typer.Context, slug: str) -> None:
    """Retire a product-cluster from its location back to offline."""
    store = _store(ctx)
    try:
        repo = store.load(slug)
    except ConfigError as e:
        raise _fail(e)
    if ASPECT not in repo.aspects:
        raise _fail(
            f"repo {slug!r} does not declare the {ASPECT} aspect; nothing to demat"
        )

    target = LayoutTarget(targets={slug: LayoutTargetAbsent()})
    inventory = scan(paths.REPOS_DIR, paths.OFFLINE_DIR)
    report = layout_engine.run(
        target,
        inventory=inventory,
        workspace_root=paths.REPOS_DIR,
        offline_root=paths.OFFLINE_DIR,
    )
    _render_outcomes("layout", report.outcomes)
    if not report.ok:
        raise typer.Exit(code=1)

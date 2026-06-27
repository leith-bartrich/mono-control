"""`mono-control repo` commands for managing repo definitions and on-disk state.

Reads the effective config directory from the Typer context (set by the root
``--config-dir`` option) so these commands are not hardwired to the container
path and are testable against a scratch directory.

Lookup commands accept ``<name_or_slug>`` and resolve via
:func:`mono_control.config.resolve_repo` — slug-first, then a case-insensitive
``slugify``-comparing name fallback. ``--slug`` (`-s`) forces slug-only
lookup (skips the name fallback) for unambiguous scripting.
"""

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from mono_control import paths, repo_ops
from mono_control.config import (
    AmbiguousNameError,
    ConfigConflictError,
    ConfigError,
    Repo,
    RepoStore,
    make_slug,
    resolve_repo,
)
from mono_control.host_platform import profile as host_profile

console = Console()

repo_app = typer.Typer(
    help="Manage repo definitions and on-disk state.", no_args_is_help=True
)
source_app = typer.Typer(help="Manage a repo's named sources.", no_args_is_help=True)
branch_app = typer.Typer(help="Manage a repo's named branches.", no_args_is_help=True)
repo_app.add_typer(source_app, name="source")
repo_app.add_typer(branch_app, name="branch")


def _store(ctx: typer.Context) -> RepoStore:
    return RepoStore.from_config_dir(ctx.obj)


def _fail(message: object) -> None:
    console.print(f"[red]error:[/red] {message}")
    raise typer.Exit(code=1)


def _resolve(ctx: typer.Context, query: str, *, slug_only: bool) -> Repo:
    """Resolve ``query`` via :func:`resolve_repo`; CLI-surface errors as exit 1."""
    try:
        return resolve_repo(_store(ctx), query, slug_only=slug_only)
    except (AmbiguousNameError, ConfigError) as e:
        _fail(e)


def _parse_pairs(items: list[str] | None, kind: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep or not key or not value:
            _fail(f"invalid {kind} {item!r}, expected name=value")
        result[key] = value
    return result


# --------------------------------------------------------------------------- #
# Shared Typer option definitions
# --------------------------------------------------------------------------- #

_SLUG_FLAG = typer.Option(
    False, "--slug", "-s", help="Treat the argument as a slug; skip name fallback."
)


# --------------------------------------------------------------------------- #
# Read commands
# --------------------------------------------------------------------------- #

@repo_app.command("list")
def list_repos(
    ctx: typer.Context,
    show_all: bool = typer.Option(False, "--all", help="Include retired repos."),
) -> None:
    """List repo definitions."""
    store = _store(ctx)
    slugs = store.list(include_retired=show_all)
    if not slugs:
        console.print("no repos")
        return
    table = Table("slug", "name", "sources", "branches", "retired", box=None)
    for slug in slugs:
        repo = store.load(slug)
        table.add_row(
            repo.slug,
            repo.name,
            str(len(repo.sources)),
            str(len(repo.branches)),
            "[red]yes[/red]" if repo.retired else "",
        )
    console.print(table)


@repo_app.command()
def show(
    ctx: typer.Context,
    name_or_slug: str,
    slug_only: bool = _SLUG_FLAG,
) -> None:
    """Show a repo definition in detail."""
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    retired = " [red](retired)[/red]" if repo.retired else ""
    console.print(f"[bold]{repo.slug}[/bold] — {repo.name}{retired}")
    for label, mapping in (("sources", repo.sources), ("branches", repo.branches)):
        console.print(f"  {label}:")
        if not mapping:
            console.print("    (none)")
        for name, value in mapping.items():
            console.print(f"    {name} = {value}")


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #

@repo_app.command()
def add(
    ctx: typer.Context,
    name: str,
    slug: str = typer.Option(
        None,
        "--slug",
        help="Slug override (default: derived as `slugify(name)-<4 hex>`).",
    ),
    source: list[str] = typer.Option(None, "--source", help="name=url (repeatable)."),
    branch: list[str] = typer.Option(None, "--branch", help="name=branch (repeatable)."),
) -> None:
    """Create a new repo definition.

    The slug is derived mechanically from ``name`` for uniqueness. Pass
    ``--slug`` to choose an exact slug yourself.
    """
    store = _store(ctx)
    resolved_slug = slug if slug is not None else make_slug(name, exists=store.exists)
    try:
        repo = Repo(
            version=1,
            slug=resolved_slug,
            name=name,
            sources=_parse_pairs(source, "source"),
            branches=_parse_pairs(branch, "branch"),
        )
    except ValidationError as e:
        _fail(e)
    try:
        store.create(repo)
    except (ConfigConflictError, ConfigError) as e:
        _fail(e)
    console.print(f"[green]created[/green] {resolved_slug}")


@repo_app.command()
def manage(ctx: typer.Context) -> None:
    """Interactively manage repo definitions (menu-driven)."""
    from .repo_ui import manage as run_manage

    run_manage(_store(ctx))


# --------------------------------------------------------------------------- #
# Mutations on an existing repo
# --------------------------------------------------------------------------- #

@repo_app.command()
def rename(
    ctx: typer.Context,
    name_or_slug: str,
    name: str,
    slug_only: bool = _SLUG_FLAG,
) -> None:
    """Change a repo's display name (the slug is immutable).

    Note: renaming changes the default subdir for aspects whose
    ``default_subdir`` derives from name — the next ``mat`` will relocate.
    """
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    repo.name = name
    _store(ctx).save(repo)
    console.print(f"[green]renamed[/green] {repo.slug} -> {name}")


@source_app.command("add")
def source_add(
    ctx: typer.Context,
    name_or_slug: str,
    source_name: str,
    url: str,
    slug_only: bool = _SLUG_FLAG,
) -> None:
    """Add or update a named source on a repo."""
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    repo.sources[source_name] = url
    _store(ctx).save(repo)
    console.print(f"[green]set[/green] source {source_name} on {repo.slug}")


@source_app.command("remove")
def source_remove(
    ctx: typer.Context,
    name_or_slug: str,
    source_name: str,
    slug_only: bool = _SLUG_FLAG,
) -> None:
    """Remove a named source from a repo."""
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    if repo.sources.pop(source_name, None) is None:
        _fail(f"repo {repo.slug!r} has no source {source_name!r}")
    _store(ctx).save(repo)
    console.print(f"[green]removed[/green] source {source_name} from {repo.slug}")


@branch_app.command("add")
def branch_add(
    ctx: typer.Context,
    name_or_slug: str,
    branch_name: str,
    branch: str,
    slug_only: bool = _SLUG_FLAG,
) -> None:
    """Add or update a named branch on a repo."""
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    repo.branches[branch_name] = branch
    _store(ctx).save(repo)
    console.print(f"[green]set[/green] branch {branch_name} on {repo.slug}")


@branch_app.command("remove")
def branch_remove(
    ctx: typer.Context,
    name_or_slug: str,
    branch_name: str,
    slug_only: bool = _SLUG_FLAG,
) -> None:
    """Remove a named branch from a repo."""
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    if repo.branches.pop(branch_name, None) is None:
        _fail(f"repo {repo.slug!r} has no branch {branch_name!r}")
    _store(ctx).save(repo)
    console.print(f"[green]removed[/green] branch {branch_name} from {repo.slug}")


# --------------------------------------------------------------------------- #
# Soft-delete / restore / purge
# --------------------------------------------------------------------------- #

@repo_app.command()
def retire(
    ctx: typer.Context,
    name_or_slug: str,
    slug_only: bool = _SLUG_FLAG,
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt."),
) -> None:
    """Soft-delete a repo (reversible; the slug stays reserved)."""
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    if not yes and not typer.confirm(f"Retire {repo.slug!r}?"):
        raise typer.Abort()
    _store(ctx).retire(repo.slug)
    console.print(f"[yellow]retired[/yellow] {repo.slug}")


@repo_app.command()
def restore(
    ctx: typer.Context,
    name_or_slug: str,
    slug_only: bool = _SLUG_FLAG,
) -> None:
    """Reverse a retire."""
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    _store(ctx).restore(repo.slug)
    console.print(f"[green]restored[/green] {repo.slug}")


@repo_app.command()
def purge(
    ctx: typer.Context,
    name_or_slug: str,
    slug_only: bool = _SLUG_FLAG,
    yes: bool = typer.Option(False, "--yes", help="Required acknowledgement."),
    confirm_slug: str = typer.Option(
        None, "--confirm-slug", help="Re-type the slug to confirm (else prompted)."
    ),
) -> None:
    """Hard-delete a repo definition. Heavily guarded and irreversible."""
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    if not yes:
        _fail("refusing to purge without --yes (purge is irreversible)")
    typed = confirm_slug if confirm_slug is not None else typer.prompt(
        f"Type the slug '{repo.slug}' to confirm permanent deletion"
    )
    if typed != repo.slug:
        _fail("slug confirmation did not match; aborting")
    _store(ctx).purge(repo.slug)
    console.print(f"[red]purged[/red] {repo.slug}")


# --------------------------------------------------------------------------- #
# On-disk state verbs
# --------------------------------------------------------------------------- #

@repo_app.command("init")
def init_cmd(
    ctx: typer.Context,
    name: str,
    slug: str = typer.Option(
        None,
        "--slug",
        help="Slug override (default: derived as `slugify(name)-<4 hex>`).",
    ),
) -> None:
    """Create a brand-new repo def + ``git init`` it into offline."""
    store = _store(ctx)
    try:
        resolved_slug, report = repo_ops.init(
            name,
            slug=slug,
            repo_store=store,
            workspace_root=paths.REPOS_DIR,
            offline_root=paths.OFFLINE_DIR,
            profile=host_profile(),
        )
    except (ConfigConflictError, ConfigError) as e:
        _fail(e)
    console.print(f"[green]created[/green] {resolved_slug}")
    repo_ops.render_outcomes(f"init {resolved_slug}", report.outcomes, console=console)
    if not report.ok:
        raise typer.Exit(code=1)


@repo_app.command("mat")
def mat_cmd(
    ctx: typer.Context,
    name_or_slug: str,
    location: str = typer.Option(
        ...,
        "--location",
        help="Subdir under mono-repos where the repo should be placed.",
    ),
    branch: str = typer.Option(
        "main", "--branch", help="Branch whose head to check out."
    ),
    slug_only: bool = _SLUG_FLAG,
) -> None:
    """Place a repo at ``mono-repos/<location>`` (source → layout)."""
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    source_report, layout_report = repo_ops.materialize(
        repo.slug,
        location=location,
        branch=branch,
        repo_store=_store(ctx),
        workspace_root=paths.REPOS_DIR,
        offline_root=paths.OFFLINE_DIR,
        profile=host_profile(),
    )
    repo_ops.render_outcomes("source", source_report.outcomes, console=console)
    repo_ops.render_outcomes("layout", layout_report.outcomes, console=console)
    if not (source_report.ok and layout_report.ok):
        raise typer.Exit(code=1)


@repo_app.command("demat")
def demat_cmd(
    ctx: typer.Context,
    name_or_slug: str,
    slug_only: bool = _SLUG_FLAG,
) -> None:
    """Retire a repo from its location back to offline (layout only)."""
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    report = repo_ops.dematerialize(
        repo.slug,
        workspace_root=paths.REPOS_DIR,
        offline_root=paths.OFFLINE_DIR,
    )
    repo_ops.render_outcomes("layout", report.outcomes, console=console)
    if not report.ok:
        raise typer.Exit(code=1)

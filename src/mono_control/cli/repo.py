"""`mono-control repo` commands for managing repo definitions.

Reads the effective config directory from the Typer context (set by the root
``--config-dir`` option) so these commands are not hardwired to the container
path and are testable against a scratch directory.
"""

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from mono_control.config import ConfigConflictError, ConfigError, Repo, RepoStore

console = Console()

repo_app = typer.Typer(help="Manage repo definitions.", no_args_is_help=True)
source_app = typer.Typer(help="Manage a repo's named sources.", no_args_is_help=True)
branch_app = typer.Typer(help="Manage a repo's named branches.", no_args_is_help=True)
repo_app.add_typer(source_app, name="source")
repo_app.add_typer(branch_app, name="branch")


def _store(ctx: typer.Context) -> RepoStore:
    return RepoStore.from_config_dir(ctx.obj)


def _fail(message: object) -> None:
    console.print(f"[red]error:[/red] {message}")
    raise typer.Exit(code=1)


def _load(ctx: typer.Context, slug: str) -> Repo:
    try:
        return _store(ctx).load(slug)
    except ConfigError as e:
        _fail(e)


def _parse_pairs(items: list[str] | None, kind: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep or not key or not value:
            _fail(f"invalid {kind} {item!r}, expected name=value")
        result[key] = value
    return result


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
def show(ctx: typer.Context, slug: str) -> None:
    """Show a repo definition in detail."""
    repo = _load(ctx, slug)
    retired = " [red](retired)[/red]" if repo.retired else ""
    console.print(f"[bold]{repo.slug}[/bold] — {repo.name}{retired}")
    for label, mapping in (("sources", repo.sources), ("branches", repo.branches)):
        console.print(f"  {label}:")
        if not mapping:
            console.print("    (none)")
        for name, value in mapping.items():
            console.print(f"    {name} = {value}")


@repo_app.command()
def add(
    ctx: typer.Context,
    slug: str,
    name: str = typer.Option(None, "--name", help="Display name (defaults to slug)."),
    source: list[str] = typer.Option(None, "--source", help="name=url (repeatable)."),
    branch: list[str] = typer.Option(None, "--branch", help="name=branch (repeatable)."),
) -> None:
    """Create a new repo definition."""
    try:
        repo = Repo(
            version=1,
            slug=slug,
            name=name or slug,
            sources=_parse_pairs(source, "source"),
            branches=_parse_pairs(branch, "branch"),
        )
    except ValidationError as e:
        _fail(e)
    try:
        _store(ctx).create(repo)
    except (ConfigConflictError, ConfigError) as e:
        _fail(e)
    console.print(f"[green]created[/green] {slug}")


@repo_app.command()
def manage(ctx: typer.Context) -> None:
    """Interactively manage repo definitions (menu-driven)."""
    from .repo_ui import manage as run_manage

    run_manage(_store(ctx))


@repo_app.command()
def rename(ctx: typer.Context, slug: str, name: str) -> None:
    """Change a repo's display name (the slug is immutable)."""
    repo = _load(ctx, slug)
    repo.name = name
    _store(ctx).save(repo)
    console.print(f"[green]renamed[/green] {slug} -> {name}")


@source_app.command("add")
def source_add(ctx: typer.Context, slug: str, name: str, url: str) -> None:
    """Add or update a named source on a repo."""
    repo = _load(ctx, slug)
    repo.sources[name] = url
    _store(ctx).save(repo)
    console.print(f"[green]set[/green] source {name} on {slug}")


@source_app.command("remove")
def source_remove(ctx: typer.Context, slug: str, name: str) -> None:
    """Remove a named source from a repo."""
    repo = _load(ctx, slug)
    if repo.sources.pop(name, None) is None:
        _fail(f"repo {slug!r} has no source {name!r}")
    _store(ctx).save(repo)
    console.print(f"[green]removed[/green] source {name} from {slug}")


@branch_app.command("add")
def branch_add(ctx: typer.Context, slug: str, name: str, branch: str) -> None:
    """Add or update a named branch on a repo."""
    repo = _load(ctx, slug)
    repo.branches[name] = branch
    _store(ctx).save(repo)
    console.print(f"[green]set[/green] branch {name} on {slug}")


@branch_app.command("remove")
def branch_remove(ctx: typer.Context, slug: str, name: str) -> None:
    """Remove a named branch from a repo."""
    repo = _load(ctx, slug)
    if repo.branches.pop(name, None) is None:
        _fail(f"repo {slug!r} has no branch {name!r}")
    _store(ctx).save(repo)
    console.print(f"[green]removed[/green] branch {name} from {slug}")


@repo_app.command()
def retire(
    ctx: typer.Context,
    slug: str,
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt."),
) -> None:
    """Soft-delete a repo (reversible; the slug stays reserved)."""
    store = _store(ctx)
    if not store.exists(slug):
        _fail(f"repo {slug!r} not found")
    if not yes and not typer.confirm(f"Retire {slug!r}?"):
        raise typer.Abort()
    store.retire(slug)
    console.print(f"[yellow]retired[/yellow] {slug}")


@repo_app.command()
def restore(ctx: typer.Context, slug: str) -> None:
    """Reverse a retire."""
    store = _store(ctx)
    if not store.exists(slug):
        _fail(f"repo {slug!r} not found")
    store.restore(slug)
    console.print(f"[green]restored[/green] {slug}")


@repo_app.command()
def purge(
    ctx: typer.Context,
    slug: str,
    yes: bool = typer.Option(False, "--yes", help="Required acknowledgement."),
    confirm_slug: str = typer.Option(
        None, "--confirm-slug", help="Re-type the slug to confirm (else prompted)."
    ),
) -> None:
    """Hard-delete a repo definition. Heavily guarded and irreversible."""
    store = _store(ctx)
    if not store.exists(slug):
        _fail(f"repo {slug!r} not found")
    if not yes:
        _fail("refusing to purge without --yes (purge is irreversible)")
    typed = confirm_slug if confirm_slug is not None else typer.prompt(
        f"Type the slug '{slug}' to confirm permanent deletion"
    )
    if typed != slug:
        _fail("slug confirmation did not match; aborting")
    store.purge(slug)
    console.print(f"[red]purged[/red] {slug}")

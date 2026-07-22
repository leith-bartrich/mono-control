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
from mono_control.app_context import AppContext
from mono_control.config import (
    AmbiguousNameError,
    ConfigConflictError,
    ConfigError,
    Repo,
    RepoStore,
    make_slug,
    resolve_repo,
)
from mono_control.layout_target import (
    LayoutTarget,
    LayoutTargetAbsent,
    LayoutTargetPresentAsIs,
    LayoutTargetPresentBranchHead,
    LayoutTargetPresentCommit,
)
from mono_control.on_disk import scan

console = Console()

repo_app = typer.Typer(
    help="Manage repo definitions and on-disk state.", no_args_is_help=True
)
source_app = typer.Typer(help="Manage a repo's named sources.", no_args_is_help=True)
branch_app = typer.Typer(help="Manage a repo's named branches.", no_args_is_help=True)
fork_app = typer.Typer(
    help="Governed fork transitions on a repo's sources.", no_args_is_help=True
)
repo_app.add_typer(source_app, name="source")
repo_app.add_typer(branch_app, name="branch")
repo_app.add_typer(fork_app, name="fork")


def _app(ctx: typer.Context) -> AppContext:
    return ctx.obj


def _store(ctx: typer.Context) -> RepoStore:
    return RepoStore(_app(ctx).broker)


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


@fork_app.command("add")
def fork_add(
    ctx: typer.Context,
    name_or_slug: str,
    url: str,
    purpose: str = typer.Option(
        "ours",
        "--purpose",
        help="'ours' (default) or a tracked-reference name (-> fork-<name>).",
    ),
    dev: str = typer.Option(
        None,
        "--dev",
        help=(
            "The fork's dev branch; repoints `dev` and keeps the old line as "
            "`dev-upstream` (fork-ours only)."
        ),
    ),
    slug_only: bool = _SLUG_FLAG,
) -> None:
    """Governed upstream→fork transition: add a fork source to an upstream repo.

    Adds ``fork-ours`` (or ``fork-<purpose>``) beside the repo's ``upstream``
    and eagerly stamps the remote into an on-disk checkout when one exists.
    """
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    try:
        result = repo_ops.adopt_fork(
            repo.slug,
            url,
            purpose=purpose,
            dev_branch=dev,
            repo_store=_store(ctx),
            broker=_app(ctx).broker,
        )
    except (ConfigError, ValueError) as e:
        _fail(e)
    console.print(f"[green]set[/green] source {result.source_key} on {result.slug}")
    if result.dev_repointed:
        old = (
            f" (old dev {result.old_dev!r} kept as dev-upstream)"
            if result.old_dev is not None
            else ""
        )
        console.print(f"[green]repointed[/green] dev -> {result.new_dev}{old}")
    if result.remote_stamped:
        console.print(
            f"[green]stamped[/green] remote {result.source_key} in {result.checkout}"
        )
    elif result.remote_error is not None:
        console.print(
            "[yellow]warning:[/yellow] config saved, but remote stamp failed: "
            f"{result.remote_error}"
        )
        raise typer.Exit(code=1)
    else:
        console.print("no on-disk checkout — config only (engines will conform the remote later)")


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
    initial_branch: str = typer.Option(
        None,
        "--initial-branch",
        help="Branch to init the new repo on (also recorded as its `dev` branch).",
    ),
) -> None:
    """Create a brand-new repo def + ``git init`` it into offline."""
    store = _store(ctx)
    try:
        resolved_slug, report = repo_ops.init(
            name,
            slug=slug,
            branches={"dev": initial_branch} if initial_branch else None,
            initial_branch=initial_branch,
            repo_store=store,
            broker=_app(ctx).broker,
        )
    except (ConfigConflictError, ConfigError) as e:
        _fail(e)
    console.print(f"[green]created[/green] {resolved_slug}")
    repo_ops.render_outcomes(f"init {resolved_slug}", report.outcomes, console=console)
    if not report.ok:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# `repo mat <intent>` — intent-verb subcommands
# --------------------------------------------------------------------------- #

mat_app = typer.Typer(
    help="Bring/keep a repo on disk. Sub-intents: moveto / branchat / commit / layout-target.",
    no_args_is_help=True,
)
repo_app.add_typer(mat_app, name="mat")


def _apply_and_exit(ctx: typer.Context, target: LayoutTarget) -> None:
    """Run apply_target with the standard render-and-exit-on-failure pattern."""
    source_report, layout_report = repo_ops.apply_target(
        target,
        broker=_app(ctx).broker,
        workspace_root=paths.REPOS_DIR,
        offline_root=paths.OFFLINE_DIR,
    )
    repo_ops.render_outcomes("source", source_report.outcomes, console=console)
    repo_ops.render_outcomes("layout", layout_report.outcomes, console=console)
    if not (source_report.ok and layout_report.ok):
        raise typer.Exit(code=1)


def _observed_materialized_location(ctx: typer.Context, repo: Repo) -> str:
    """Return ``repo``'s currently materialized subdir (relative to REPOS_DIR).

    Errors out if the repo isn't materialized — the user should ``moveto``
    first (or use ``layout-target`` to combine placement and ref intent).
    """
    inv = scan(_app(ctx).broker, paths.REPOS_DIR, paths.OFFLINE_DIR)
    observed = inv.repos.get(repo.slug)
    if observed is None:
        _fail(
            f"{repo.slug!r} is not on disk; use `mat moveto` to place it first, "
            f"or `mat layout-target` to place and check out in one command"
        )
    if observed.state != "materialized":
        _fail(
            f"{repo.slug!r} is offline; use `mat moveto` to place it first, "
            f"or `mat layout-target` to place and check out in one command"
        )
    try:
        return str(observed.location.relative_to(paths.REPOS_DIR))
    except ValueError:
        _fail(
            f"{repo.slug!r} is materialized at {observed.location}, which is not "
            f"under the workspace root {paths.REPOS_DIR}"
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
    relpath: str,
    slug_only: bool = _SLUG_FLAG,
) -> None:
    """Place a repo at ``mono-repos/<relpath>`` without touching the ref."""
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    target = LayoutTarget(
        targets={repo.slug: LayoutTargetPresentAsIs(location=relpath)}
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
    """Check out a branch's head at the repo's current location."""
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    location = _observed_materialized_location(ctx, repo)
    target = LayoutTarget(
        targets={
            repo.slug: LayoutTargetPresentBranchHead(branch=branch, location=location),
        }
    )
    _apply_and_exit(ctx, target)
    del sub_intent  # reserved-grammar token; only "head" is supported today


@mat_app.command("commit")
def mat_commit(
    ctx: typer.Context,
    name_or_slug: str,
    commit: str,
    sub_intent: str = typer.Argument("detached", callback=_validate_commit_sub),
    slug_only: bool = _SLUG_FLAG,
) -> None:
    """Check out a specific commit (detached HEAD) at the repo's current location."""
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    location = _observed_materialized_location(ctx, repo)
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
    location: str = typer.Option(
        ..., "--location", help="Subdir under mono-repos."
    ),
    branch: str = typer.Option(
        None, "--branch", help="Branch whose head to check out (mutually exclusive with --commit)."
    ),
    commit: str = typer.Option(
        None, "--commit", help="Specific commit to check out (mutually exclusive with --branch)."
    ),
    slug_only: bool = _SLUG_FLAG,
) -> None:
    """Declarative one-liner: place + (optionally) check out a ref."""
    if branch and commit:
        _fail("--branch and --commit are mutually exclusive")
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    if branch:
        desired = LayoutTargetPresentBranchHead(branch=branch, location=location)
    elif commit:
        desired = LayoutTargetPresentCommit(commit=commit, location=location)
    else:
        desired = LayoutTargetPresentAsIs(location=location)
    target = LayoutTarget(targets={repo.slug: desired})
    _apply_and_exit(ctx, target)


@repo_app.command("demat")
def demat_cmd(
    ctx: typer.Context,
    name_or_slug: str,
    slug_only: bool = _SLUG_FLAG,
) -> None:
    """Retire a repo from its location back to offline (layout only)."""
    repo = _resolve(ctx, name_or_slug, slug_only=slug_only)
    target = LayoutTarget(targets={repo.slug: LayoutTargetAbsent()})
    _apply_and_exit(ctx, target)

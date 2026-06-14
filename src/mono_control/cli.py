"""Command-line entrypoint for mono-control (Typer + Rich)."""

import shlex
from importlib.metadata import version
from pathlib import Path

import click
import typer
from rich.console import Console
from rich.table import Table

from mono_control.config import ConfigError, RepoStore, load_config
from mono_control.paths import CONFIG_DIR, REPOS_DIR
from mono_control.repo_cli import repo_app
from mono_control.sandbox import require_container

app = typer.Typer(
    name="mono-control",
    help="Repo state manager for the fiemono workspace.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(repo_app, name="repo")
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"mono-control {version('mono-control')}")
        raise typer.Exit()


@app.callback()
def _root(
    ctx: typer.Context,
    config_dir: Path = typer.Option(
        CONFIG_DIR, "--config-dir", help="Path to the mono-config directory."
    ),
    _version: bool = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Repo state manager for the fiemono workspace."""
    ctx.obj = config_dir


@app.command()
def status(ctx: typer.Context) -> None:
    """Report which managed workspace directories are visible."""
    table = Table("status", "path", show_edge=False, box=None)
    for path in (ctx.obj, REPOS_DIR):
        if path.is_dir():
            table.add_row("[green]ok[/green]", str(path))
        else:
            table.add_row("[red]missing[/red]", str(path))
    console.print(table)


@app.command()
def validate(ctx: typer.Context) -> None:
    """Load and validate the mono-config directory (including repo definitions)."""
    config_dir: Path = ctx.obj
    try:
        load_config(config_dir)
    except ConfigError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=1)

    store = RepoStore.from_config_dir(config_dir)
    slugs = store.list(include_retired=True)
    errors = []
    for slug in slugs:
        try:
            store.load(slug)
        except ConfigError as e:
            errors.append((slug, e))
    if errors:
        for slug, e in errors:
            console.print(f"[red]error[/red] repo {slug}: {e}")
        raise typer.Exit(code=1)
    console.print(f"[green]ok:[/green] config is valid ({len(slugs)} repo(s))")


_REPL_EXIT = {":exit", ":quit", "exit", "quit"}


@app.command()
def repl(ctx: typer.Context) -> None:
    """Start an interactive REPL over mono-control commands."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.history import InMemoryHistory

    # The Typer app compiles to a Click group; dispatch each REPL line against it.
    group: click.Group = ctx.parent.command if ctx.parent else ctx.command
    names = [n for n in group.commands if n != "repl"]
    session = PromptSession(
        history=InMemoryHistory(),
        completer=WordCompleter(names + sorted(_REPL_EXIT), ignore_case=True),
    )

    console.print(
        "mono-control REPL — run a command, [bold]--help[/bold], or [bold]:exit[/bold]."
    )
    while True:
        try:
            line = session.prompt("mono-control> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in _REPL_EXIT:
            break
        try:
            # standalone_mode=False: return instead of sys.exit, raise on usage errors.
            group.main(args=shlex.split(line), prog_name="mono-control", standalone_mode=False)
        except click.ClickException as e:
            e.show()
        except SystemExit:
            pass
        except Exception as e:  # keep the REPL alive on command errors
            console.print(f"[red]error:[/red] {e}")


def main() -> None:
    """Console-script entrypoint: gate on the sandbox, then dispatch."""
    require_container()
    app()

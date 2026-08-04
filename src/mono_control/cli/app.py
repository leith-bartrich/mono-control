"""Command-line entrypoint for mono-control (Typer + Rich)."""

import json
import shlex
from importlib.metadata import version
from pathlib import Path

import click
import typer
from rich.console import Console
from rich.table import Table

from mono_control.app_context import AppContext
from mono_control.aspects import attach_aspect_commands
from mono_control.broker import BrokerClient, emit_schema
from mono_control.config import ConfigError, RepoStore, load_config_status
from mono_control.paths import CONFIG_DIR
from mono_control.sandbox import require_broker, require_container

from .config import config_app
from .repo import repo_app

app = typer.Typer(
    name="mono-control",
    help="Repo state manager for the fiemono workspace.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(repo_app, name="repo")
app.add_typer(config_app, name="config")
attach_aspect_commands(app)
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
    if not config_dir.is_absolute():
        # A relative path here silently mkdir-s a junk tree under the container's
        # working dir (the bind-mounted repo). A forward-slash Windows path like
        # 'C:/...' is the classic offender — absolute on the host, relative here.
        raise typer.BadParameter(
            f"--config-dir must be an absolute path, got {str(config_dir)!r}. "
            "A Windows-style path like 'C:/...' is relative inside the container.",
            param_hint="--config-dir",
        )
    # Preserve a broker injected by tests (via ``obj=``); otherwise build the real
    # stdlib HTTP client from the shim-injected ``MONO_BROKER_*`` environment.
    injected = ctx.obj if isinstance(ctx.obj, AppContext) else None
    broker = injected.broker if injected is not None else BrokerClient()
    ctx.obj = AppContext(config_dir=config_dir, broker=broker)


@app.command()
def status(ctx: typer.Context) -> None:
    """Report which managed workspace directories are visible (host-side, via the broker)."""
    app_ctx: AppContext = ctx.obj
    table = Table("status", "path", show_edge=False, box=None)
    # The container has no mounts of its own; report what the broker observes.
    try:
        inventory = app_ctx.broker.scan()
        table.add_row("[green]ok[/green]", "broker reachable")
        table.add_row(
            "[green]ok[/green]",
            f"{len(inventory.repos)} managed repo(s), "
            f"{len(inventory.unmanaged)} unmanaged",
        )
    except Exception as e:  # broker unreachable / misconfigured
        table.add_row("[red]missing[/red]", f"broker unreachable: {e}")
    console.print(table)


@app.command()
def validate(ctx: typer.Context) -> None:
    """Load and validate the workspace config (including repo definitions).

    An absent ``system.json`` is not a failure — it means workspace defaults (see
    ``config/loader.py``). Repo definitions are validated exactly as before.
    """
    app_ctx: AppContext = ctx.obj
    try:
        _, system_from_disk = load_config_status(app_ctx.broker)
    except ConfigError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=1)

    store = RepoStore(app_ctx.broker)
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
    if not system_from_disk:
        console.print(
            "[dim]note: no system.json - workspace defaults in use; "
            "`config init` writes them out[/dim]"
        )


@app.command("emit-schema")
def emit_schema_cmd() -> None:
    """Print the broker wire-contract JSON Schema to stdout.

    Pure and effect-free — no broker connection needed. This is what the shim's
    future ``json-schema-control`` invokes to publish the contract.
    """
    typer.echo(json.dumps(emit_schema(), indent=2, sort_keys=True))


@app.command("version")
def version_cmd() -> None:
    """Show the mono-control version (a command form of ``--version``)."""
    console.print(f"mono-control {version('mono-control')}")


@app.command("help")
def help_cmd(
    ctx: typer.Context,
    command: str = typer.Argument(
        None, help="Command to show help for (default: the whole CLI)."
    ),
) -> None:
    """Show help — for the whole CLI, or for a specific command.

    A friendlier alias for ``--help``, especially in the REPL where a bare
    ``help`` reads better than a ``--help`` flag.
    """
    group: click.Group = ctx.parent.command if ctx.parent else ctx.command
    parent_ctx = ctx.parent or ctx
    if command is None:
        typer.echo(group.get_help(parent_ctx))
        return
    sub = group.get_command(parent_ctx, command)
    if sub is None:
        console.print(f"[red]error:[/red] unknown command: {command!r}")
        raise typer.Exit(code=1)
    with click.Context(sub, info_name=command, parent=parent_ctx) as sub_ctx:
        typer.echo(sub.get_help(sub_ctx))


_REPL_EXIT = {":exit", ":quit", "exit", "quit"}


def _completion_candidates(group: click.Group, text: str, extra: list[str]) -> list[str]:
    """Names completing the last token of ``text`` against the command tree.

    Walks the already-typed tokens into sub-groups and returns the current
    node's subcommands (plus ``extra`` at the root) that match the trailing
    prefix. UI-agnostic (no prompt_toolkit) so it is unit-testable.
    """
    tokens = text.split()
    completing_new = not text or text[-1].isspace()
    consumed = tokens if completing_new else tokens[:-1]
    prefix = "" if completing_new else tokens[-1]

    # Duck-type the group interface: a command *group* exposes get_command /
    # list_commands, a leaf command does not. (Don't isinstance-check click.Group —
    # Typer's group class doesn't reliably satisfy it across click versions.)
    node: object = group
    for tok in consumed:
        get_command = getattr(node, "get_command", None)
        node = get_command(None, tok) if get_command else None
        if node is None:
            return []
    list_commands = getattr(node, "list_commands", None)
    options: list[str] = list(list_commands(None)) if list_commands else []
    if node is group:
        options.extend(extra)
    return [n for n in sorted(set(options)) if n.startswith(prefix)]


@app.command()
def repl(ctx: typer.Context) -> None:
    """Start an interactive REPL over mono-control commands."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.history import InMemoryHistory

    # The Typer app compiles to a Click group; dispatch each REPL line against it.
    group: click.Group = ctx.parent.command if ctx.parent else ctx.command
    exit_words = sorted(_REPL_EXIT)

    class _TreeCompleter(Completer):
        """Complete against the command tree, descending into sub-groups."""

        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            prefix = "" if (not text or text[-1].isspace()) else text.split()[-1]
            for name in _completion_candidates(group, text, exit_words):
                yield Completion(name, start_position=-len(prefix))

    session = PromptSession(history=InMemoryHistory(), completer=_TreeCompleter())

    console.print(
        "mono-control REPL — run a command, [bold]help[/bold], or [bold]:exit[/bold]."
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
    """Console-script entrypoint: gate on sandbox + broker, then dispatch."""
    require_container()
    require_broker()
    app()

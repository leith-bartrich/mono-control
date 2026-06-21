"""`mono-control config` commands for the top-level workspace config.

The workspace config is a singleton ``system.json`` (the ``WorkspaceConfig``
model), so these commands go through the ``load_config`` / ``save_config``
function pair rather than a per-slug store. Like the repo commands, the effective
config directory comes from the Typer context (the root ``--config-dir`` option),
so they are testable against a scratch directory.

``WorkspaceConfig`` is still just ``{"version": 1}``; this group exists to bring
config to parity in *shape* with repos (load / validate / save), so real commands
slot in as the model grows.
"""

import typer
from rich.console import Console

from mono_control.config import (
    ConfigError,
    WorkspaceConfig,
    load_config,
    save_config,
)
from mono_control.paths import SYSTEM_FILE

console = Console()

config_app = typer.Typer(help="Manage the workspace config.", no_args_is_help=True)


def _fail(message: object) -> None:
    console.print(f"[red]error:[/red] {message}")
    raise typer.Exit(code=1)


@config_app.command()
def show(ctx: typer.Context) -> None:
    """Load and display the workspace config."""
    try:
        config = load_config(ctx.obj)
    except ConfigError as e:
        _fail(e)
    console.print(f"[bold]workspace config[/bold] (version {config.version})")


@config_app.command()
def validate(ctx: typer.Context) -> None:
    """Validate just the workspace config (system.json)."""
    try:
        load_config(ctx.obj)
    except ConfigError as e:
        _fail(e)
    console.print("[green]ok:[/green] workspace config is valid")


@config_app.command()
def init(ctx: typer.Context) -> None:
    """Create a default system.json, refusing to overwrite an existing one."""
    if (ctx.obj / SYSTEM_FILE).exists():
        _fail(f"{SYSTEM_FILE} already exists")
    save_config(WorkspaceConfig(version=1), ctx.obj)
    console.print(f"[green]created[/green] {SYSTEM_FILE}")


@config_app.command()
def manage(ctx: typer.Context) -> None:
    """Interactively manage the workspace config (menu-driven)."""
    from .config_ui import manage as run_manage

    run_manage(ctx.obj)

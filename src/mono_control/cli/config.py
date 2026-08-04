"""`mono-control config` commands for the top-level workspace config.

The workspace config is a singleton ``system.json`` (the ``WorkspaceConfig``
model), so these commands go through the ``load_config`` / ``save_config``
function pair rather than a per-slug store. Like the repo commands, the effective
config directory comes from the Typer context (the root ``--config-dir`` option),
so they are testable against a scratch directory.

``WorkspaceConfig`` is still just ``{"version": 1}``; this group exists to bring
config to parity in *shape* with repos (load / validate / save), so real commands
slot in as the model grows.

``system.json`` is optional (see ``config/loader.py``), so these commands report
*which* they are looking at rather than assuming a file. That reporting is the
point: making the document optional is only safe if its absence stays visible.
"""

import typer
from rich.console import Console

from mono_control.app_context import AppContext
from mono_control.config import (
    ConfigError,
    WorkspaceConfig,
    load_config_status,
    save_config,
    system_exists,
)

console = Console()

config_app = typer.Typer(help="Manage the workspace config.", no_args_is_help=True)


def _fail(message: object) -> None:
    console.print(f"[red]error:[/red] {message}")
    raise typer.Exit(code=1)


# How a defaulted (file-absent) config is described wherever one is reported. The
# wording is deliberate: "no system.json" states the fact, and naming `config init`
# alongside it means the reader learns the file is *creatable* without being told
# it is required — which it is not.
_DEFAULTS_NOTE = "no system.json - workspace defaults in use (`config init` writes them out)"


@config_app.command()
def show(ctx: typer.Context) -> None:
    """Load and display the workspace config (defaults when system.json is absent)."""
    app_ctx: AppContext = ctx.obj
    try:
        config, from_disk = load_config_status(app_ctx.broker)
    except ConfigError as e:
        _fail(e)
    console.print(f"[bold]workspace config[/bold] (version {config.version})")
    console.print(f"  source: {'system.json' if from_disk else _DEFAULTS_NOTE}")


@config_app.command()
def validate(ctx: typer.Context) -> None:
    """Validate just the workspace config (system.json).

    An absent ``system.json`` is valid — it means defaults. A *present* one is
    held to the same schema as ever.
    """
    app_ctx: AppContext = ctx.obj
    try:
        _, from_disk = load_config_status(app_ctx.broker)
    except ConfigError as e:
        _fail(e)
    if from_disk:
        console.print("[green]ok:[/green] workspace config is valid")
    else:
        console.print(f"[green]ok:[/green] {_DEFAULTS_NOTE}")


@config_app.command()
def init(ctx: typer.Context) -> None:
    """Write the default system.json, refusing to overwrite an existing one.

    Optional: the workspace runs on defaults without it. Use this to materialize
    those defaults as a file you can edit and commit.
    """
    app_ctx: AppContext = ctx.obj
    if system_exists(app_ctx.broker):
        _fail("system.json already exists")
    save_config(WorkspaceConfig(version=1), app_ctx.broker)
    console.print("[green]created[/green] system.json")


@config_app.command()
def manage(ctx: typer.Context) -> None:
    """Interactively manage the workspace config (menu-driven)."""
    app_ctx: AppContext = ctx.obj
    from .config_ui import manage as run_manage

    run_manage(app_ctx.broker)

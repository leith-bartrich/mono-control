"""Interactive, questionary-driven management of the workspace config.

Exposed as ``mono-control config manage``. The menu loop needs a TTY; all reads
and writes go through the ``load_config`` / ``save_config`` pair, which is what
the unit tests exercise directly.

Deliberately thin while ``WorkspaceConfig`` is just ``{"version": 1}`` — it
mirrors ``repo_ui.py``'s shape so richer fields slot in as the model grows.
"""

from pathlib import Path

import questionary
from rich.console import Console

from mono_control.config import ConfigError, WorkspaceConfig, load_config, save_config

console = Console()

_QUIT = "[quit]"


def manage(config_dir: Path) -> None:
    """Run the interactive workspace-config loop until the user quits."""
    while True:
        action = questionary.select(
            "Workspace config",
            choices=["view", "validate", "save default", _QUIT],
        ).ask()
        if action in (None, _QUIT):
            return
        if action == "view":
            _view(config_dir)
        elif action == "validate":
            _validate(config_dir)
        elif action == "save default":
            save_config(WorkspaceConfig(version=1), config_dir)
            console.print("[green]saved[/green] default config")


def _view(config_dir: Path) -> None:
    try:
        config = load_config(config_dir)
    except ConfigError as e:
        console.print(f"[yellow](missing)[/yellow] {e}")
        return
    console.print(f"  version = {config.version}")


def _validate(config_dir: Path) -> None:
    try:
        load_config(config_dir)
    except ConfigError as e:
        console.print(f"[red]invalid:[/red] {e}")
        return
    console.print("[green]ok[/green]")

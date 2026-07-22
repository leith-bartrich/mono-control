"""Interactive, questionary-driven management of the workspace config.

Exposed as ``mono-control config manage``. The menu loop needs a TTY; all reads
and writes go through the ``load_config`` / ``save_config`` pair, which is what
the unit tests exercise directly.

Deliberately thin while ``WorkspaceConfig`` is just ``{"version": 1}`` — it
mirrors ``repo_ui.py``'s shape so richer fields slot in as the model grows.
"""

import questionary
from rich.console import Console

from mono_control.broker import BrokerProtocol
from mono_control.config import ConfigError, WorkspaceConfig, load_config, save_config

console = Console()

_EXIT = "[exit config manager]"


def manage(broker: BrokerProtocol) -> None:
    """Run the interactive workspace-config loop until the user exits."""
    while True:
        action = questionary.select(
            "Workspace config",
            choices=["view", "validate", "save default", _EXIT],
        ).ask()
        if action in (None, _EXIT):
            return
        if action == "view":
            _view(broker)
        elif action == "validate":
            _validate(broker)
        elif action == "save default":
            save_config(WorkspaceConfig(version=1), broker)
            console.print("[green]saved[/green] default config")


def _view(broker: BrokerProtocol) -> None:
    try:
        config = load_config(broker)
    except ConfigError as e:
        console.print(f"[yellow](missing)[/yellow] {e}")
        return
    console.print(f"  version = {config.version}")


def _validate(broker: BrokerProtocol) -> None:
    try:
        load_config(broker)
    except ConfigError as e:
        console.print(f"[red]invalid:[/red] {e}")
        return
    console.print("[green]ok[/green]")

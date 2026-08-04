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
from mono_control.config import (
    ConfigError,
    WorkspaceConfig,
    load_config_status,
    save_config,
)

console = Console()

_EXIT = "[exit config manager]"

# ``system.json`` is optional; absence means defaults. The manager says so rather
# than rendering values that look like they came from a file.
_DEFAULTS = "defaults - no system.json"


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
        config, from_disk = load_config_status(broker)
    except ConfigError as e:
        console.print(f"[red]invalid:[/red] {e}")
        return
    console.print(f"  version = {config.version}")
    console.print(f"  source  = {'system.json' if from_disk else _DEFAULTS}")


def _validate(broker: BrokerProtocol) -> None:
    try:
        _, from_disk = load_config_status(broker)
    except ConfigError as e:
        console.print(f"[red]invalid:[/red] {e}")
        return
    console.print("[green]ok[/green]" if from_disk else f"[green]ok[/green] ({_DEFAULTS})")

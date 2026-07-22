"""Load, validate, and save the workspace ``system.json``, via the broker.

The workspace config is a singleton document the container used to read from a
bind mount; it now travels over the ``mono_config`` verb-pack (``get_system`` /
``save_system``). ``load_config`` validates the raw JSON into a
``WorkspaceConfig``; ``save_config`` is its write-side counterpart. The marked
seam below is where additional named documents get merged in once the config
directory layout is designed.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..base_models import VersionError
from ..broker import BrokerProtocol
from .errors import (
    ConfigNotFoundError,
    ConfigValidationError,
    ConfigVersionError,
)
from .models import WorkspaceConfig


def load_config(broker: BrokerProtocol) -> WorkspaceConfig:
    """Load the workspace config into a validated ``WorkspaceConfig``.

    Reads ``system.json`` over the broker. Raises ``ConfigNotFoundError`` if it
    does not exist, mirroring the old missing-file behavior.
    """
    data: Any = broker.get_system().system
    if data is None:
        raise ConfigNotFoundError("Config file not found: system.json")
    # FUTURE: merge additional named documents here.
    try:
        return WorkspaceConfig.load(data)
    except VersionError as e:
        raise ConfigVersionError(str(e)) from e
    except ValidationError as e:
        raise ConfigValidationError(f"system.json failed validation:\n{e}") from e


def save_config(config: WorkspaceConfig, broker: BrokerProtocol) -> None:
    """Write ``config`` to ``system.json`` over the broker."""
    broker.save_system(config.model_dump(mode="json"))


def system_exists(broker: BrokerProtocol) -> bool:
    """True when ``system.json`` already exists (for create-refuses-overwrite)."""
    return broker.get_system().system is not None

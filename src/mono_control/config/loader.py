"""Load, validate, and save the workspace ``system.json``, via the broker.

The workspace config is a singleton document the container used to read from a
bind mount; it now travels over the ``mono_config`` verb-pack (``get_system`` /
``save_system``). ``load_config`` validates the raw JSON into a
``WorkspaceConfig``; ``save_config`` is its write-side counterpart. The marked
seam below is where additional named documents get merged in once the config
directory layout is designed.

**``system.json`` is optional.** Its absence yields defaults, not an error. This
is not leniency for its own sake — it is what the evidence supports. Real
workspaces ran for months without the file: repos were created, cluster layouts
edited, worktrees materialized, and nothing noticed. Only three commands failed,
on a document that at present carries a single field (``version``) which is
already a constant. A requirement no subsystem enforces and no user can satisfy
by accident is not a requirement; it is a trap.

Optional is **not** unvalidated. A ``system.json`` that *exists* is validated
exactly as strictly as before — a bad version or an unknown key still fails
loudly. The change is only to what absence means.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..base_models import VersionError
from ..broker import BrokerProtocol
from .errors import (
    ConfigValidationError,
    ConfigVersionError,
)
from .models import WorkspaceConfig


def load_config_status(broker: BrokerProtocol) -> tuple[WorkspaceConfig, bool]:
    """The workspace config, plus whether it came from disk.

    Returns ``(config, from_disk)``. ``from_disk=False`` means no ``system.json``
    exists and the returned config is the defaults.

    Callers that want to *report* which they got use this; ``load_config`` is the
    plain form for callers that only need the values. Both share one broker
    round-trip's worth of work, so provenance costs nothing extra to ask for —
    which matters, because "optional" must not become "silently invisible".
    """
    data: Any = broker.get_system().system
    if data is None:
        return WorkspaceConfig(), False
    # FUTURE: merge additional named documents here.
    try:
        return WorkspaceConfig.load(data), True
    except VersionError as e:
        raise ConfigVersionError(str(e)) from e
    except ValidationError as e:
        raise ConfigValidationError(f"system.json failed validation:\n{e}") from e


def load_config(broker: BrokerProtocol) -> WorkspaceConfig:
    """Load the workspace config, defaulting when ``system.json`` is absent.

    Raises only when a file that *does* exist fails validation.
    """
    return load_config_status(broker)[0]


def save_config(config: WorkspaceConfig, broker: BrokerProtocol) -> None:
    """Write ``config`` to ``system.json`` over the broker."""
    broker.save_system(config.model_dump(mode="json"))


def system_exists(broker: BrokerProtocol) -> bool:
    """True when ``system.json`` already exists (for create-refuses-overwrite).

    Distinct from ``load_config_status``'s second element only in that this makes
    no attempt to validate: ``config init`` must refuse to overwrite a file even
    when that file is malformed.
    """
    return broker.get_system().system is not None

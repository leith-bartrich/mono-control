"""Observe the workspace + offline holding area into an ``OnDiskInventory``.

The observation itself — walking each root for ``.git`` checkouts, reading each
``mono-control.slug`` stamp, its commit and dirty state — is a git + filesystem
effect, so it runs **broker-side** (the container has no checkouts to walk). This
module is the thin container half: it calls ``broker.scan()`` and rehydrates the
JSON-native ``WireInventory`` into the in-memory ``OnDiskInventory`` the engines
consume, reconstructing absolute paths against the nominal roots.

Duplicate slugs across checkouts are the broker's concern (it observes the raw
trees); the container trusts the inventory it is handed.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .models import OnDiskInventory

if TYPE_CHECKING:
    from ..broker import BrokerProtocol


def scan(
    broker: "BrokerProtocol", workspace_root: Path, offline_root: Path
) -> OnDiskInventory:
    """Observe both roots via the broker and return an ``OnDiskInventory``.

    ``workspace_root`` / ``offline_root`` are the nominal roots the wire's
    *relative* locations are reconstructed against; the broker performs the real
    walk on the host and the container never touches the filesystem here.
    """
    # Imported lazily: the broker package imports ``on_disk.models`` for the wire
    # converters, so a top-level import here would form a package-init cycle.
    from ..broker import wire_inventory_to_on_disk

    wire = broker.scan()
    return wire_inventory_to_on_disk(wire, workspace_root, offline_root)

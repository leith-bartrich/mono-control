"""Observe the bare repos + their worktrees into an ``OnDiskInventory``.

The observation itself — walking the bare root for bare repos, reading each
``mono-control.slug`` stamp, and detecting whether a worktree exists under the
work root (materialized) or not (offline) — is a git + filesystem effect, so it
runs **broker-side** (the container has no repos to walk). This module is the thin
container half: it calls ``broker.scan()`` and rehydrates the JSON-native
``WireInventory`` into the in-memory ``OnDiskInventory`` the engines consume,
reconstructing absolute paths against the nominal roots.

Duplicate slugs across bares are the broker's concern (it observes the raw
repos); the container trusts the inventory it is handed.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .models import OnDiskInventory

if TYPE_CHECKING:
    from ..broker import BrokerProtocol


def scan(
    broker: "BrokerProtocol", work_root: Path, bare_root: Path
) -> OnDiskInventory:
    """Observe the bare + work roots via the broker and return an ``OnDiskInventory``.

    ``work_root`` (worktrees) / ``bare_root`` (bare repos) are the nominal roots
    the wire's *relative* locations are reconstructed against; the broker performs
    the real walk on the host and the container never touches the filesystem here.
    """
    # Imported lazily: the broker package imports ``on_disk.models`` for the wire
    # converters, so a top-level import here would form a package-init cycle.
    from ..broker import wire_inventory_to_on_disk

    wire = broker.scan()
    return wire_inventory_to_on_disk(wire, work_root, bare_root)

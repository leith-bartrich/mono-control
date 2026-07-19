"""mono-control broker layer — host-side git + filesystem effects over JSON-RPC.

The container holds no token and performs no git/filesystem effects directly;
it calls back to a host-side broker (a JSON-RPC 2.0 endpoint injected by the
shim). This package is the container-side half: the wire models, a stdlib-only
client, an in-process fake for tests, and the schema the contract publishes.

This is additive foundation (a walking skeleton) — nothing here is wired into
the existing scanner/engine/CLI flows yet.
"""

from __future__ import annotations

from .client import BrokerClient, BrokerProtocol, BrokerTransportError
from .fake import FakeBroker
from .models import (
    BrokerError,
    WireInventory,
    WireRepo,
    WireUnmanaged,
    wire_inventory_from_on_disk,
    wire_inventory_to_on_disk,
    wire_repo_from_on_disk,
    wire_repo_to_on_disk,
    wire_unmanaged_from_on_disk,
    wire_unmanaged_to_on_disk,
)
from .schema import emit_schema

__all__ = [
    "BrokerClient",
    "BrokerError",
    "BrokerProtocol",
    "BrokerTransportError",
    "FakeBroker",
    "WireInventory",
    "WireRepo",
    "WireUnmanaged",
    "emit_schema",
    "wire_inventory_from_on_disk",
    "wire_inventory_to_on_disk",
    "wire_repo_from_on_disk",
    "wire_repo_to_on_disk",
    "wire_unmanaged_from_on_disk",
    "wire_unmanaged_to_on_disk",
]

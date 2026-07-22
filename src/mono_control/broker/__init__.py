"""mono-control broker layer — host-side git + filesystem effects over JSON-RPC.

The container holds no token and performs no git/filesystem effects directly;
it calls back to a host-side broker (a JSON-RPC 2.0 endpoint injected by the
shim). This package is the container-side half: the wire models, a stdlib-only
client, an in-process fake for tests, and the schema the contract publishes.

This broker layer is now the live effect path: it is wired into
``on_disk/scanner.py``, both engines, ``cli/app.py``, ``RepoStore``, and
``config/loader.py``. The container performs no git/filesystem effects of its
own — every such effect routes through here to the host-side broker.
"""

from __future__ import annotations

from .client import (
    BrokerClient,
    BrokerProtocol,
    BrokerTransportError,
    TypedBrokerMixin,
)
from .fake import FakeBroker
from .models import (
    AcquireRequest,
    AcquireResult,
    BrokerError,
    CheckoutRequest,
    LayoutOpRequest,
    LayoutOpResult,
    OkResult,
    ReadLayoutRequest,
    ReadLayoutResult,
    RemoteDefaultBranchRequest,
    RemoteDefaultBranchResult,
    RepoDefsRequest,
    RepoDefsResult,
    SaveRepoDefRequest,
    SaveSystemRequest,
    SetRemoteRequest,
    SlugRequest,
    SystemResult,
    WireInventory,
    WireRepo,
    WireUnmanaged,
    WriteLayoutRequest,
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
    "TypedBrokerMixin",
    "FakeBroker",
    "AcquireRequest",
    "AcquireResult",
    "CheckoutRequest",
    "LayoutOpRequest",
    "LayoutOpResult",
    "OkResult",
    "ReadLayoutRequest",
    "ReadLayoutResult",
    "RemoteDefaultBranchRequest",
    "RemoteDefaultBranchResult",
    "RepoDefsRequest",
    "RepoDefsResult",
    "SaveRepoDefRequest",
    "SaveSystemRequest",
    "SetRemoteRequest",
    "SlugRequest",
    "SystemResult",
    "WireInventory",
    "WireRepo",
    "WireUnmanaged",
    "WriteLayoutRequest",
    "emit_schema",
    "wire_inventory_from_on_disk",
    "wire_inventory_to_on_disk",
    "wire_repo_from_on_disk",
    "wire_repo_to_on_disk",
    "wire_unmanaged_from_on_disk",
    "wire_unmanaged_to_on_disk",
]

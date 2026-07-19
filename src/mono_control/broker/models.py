"""Wire models for the host-side broker contract.

The broker relocates git + filesystem *effects* to a host-side JSON-RPC endpoint
the container calls back to. These are the JSON-native shapes that cross that
wire — the serializable mirror of the in-memory ``on_disk`` observation
(``OnDiskRepo`` / ``OnDiskInventory``).

Where the ``on_disk`` models carry *absolute* ``Path`` s (they never leave the
process), the wire models carry *relative* location strings plus the observed
``state``. Absolute paths are reconstructed at the container boundary from the
workspace / offline roots via the free functions below, so the rest of the app
keeps consuming its internal ``OnDiskInventory`` type unchanged.

These run in the container (where pydantic already lives), so they subclass the
repo's ``StrictModel`` and reject unknown keys — a wire-typo guard.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Literal

from ..base_models import StrictModel
from ..on_disk.models import OnDiskInventory, OnDiskRepo

State = Literal["offline", "materialized"]


class BrokerError(Exception):
    """A JSON-RPC error returned by the broker (carries the wire ``code``).

    Raised by the client when the broker answers with an ``error`` envelope, and
    by the in-process fake for unregistered methods. ``code`` is the JSON-RPC
    error code; ``message`` the human-readable text.
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


class WireRepo(StrictModel):
    """One observed checkout in JSON-native form (relative location + state)."""

    slug: str
    location: str  # RELATIVE to the state's root, e.g. "ltx-2" or an offline dir
    state: State
    commit: str | None
    dirty: bool


class WireInventory(StrictModel):
    """The on-disk observation in JSON-native form: managed repos + unmanaged."""

    repos: list[WireRepo] = []
    unmanaged: list[str] = []  # RELATIVE to the workspace root


def _root_for(state: State, workspace_root: Path, offline_root: Path) -> Path:
    """The root a ``state``'s relative location is reconstructed against."""
    return workspace_root if state == "materialized" else offline_root


def wire_repo_from_on_disk(
    repo: OnDiskRepo, workspace_root: Path, offline_root: Path
) -> WireRepo:
    """Project an ``OnDiskRepo`` to its wire form (absolute -> relative location)."""
    root = _root_for(repo.state, workspace_root, offline_root)
    relative = repo.location.relative_to(root)
    return WireRepo(
        slug=repo.slug,
        location=relative.as_posix(),
        state=repo.state,
        commit=repo.commit,
        dirty=repo.dirty,
    )


def wire_repo_to_on_disk(
    wire: WireRepo, workspace_root: Path, offline_root: Path
) -> OnDiskRepo:
    """Reconstruct an ``OnDiskRepo`` (absolute location) from its wire form."""
    root = _root_for(wire.state, workspace_root, offline_root)
    location = root / PurePosixPath(wire.location)
    return OnDiskRepo(
        slug=wire.slug,
        location=location,
        state=wire.state,
        commit=wire.commit,
        dirty=wire.dirty,
    )


def wire_inventory_from_on_disk(
    inventory: OnDiskInventory, workspace_root: Path, offline_root: Path
) -> WireInventory:
    """Project an ``OnDiskInventory`` to its wire form.

    Repo locations are made relative to the root implied by their ``state``.
    Unmanaged checkouts are expressed relative to the workspace root (the common
    case for foreign trees found in the materialized area).
    """
    return WireInventory(
        repos=[
            wire_repo_from_on_disk(repo, workspace_root, offline_root)
            for repo in inventory.repos.values()
        ],
        unmanaged=[
            path.relative_to(workspace_root).as_posix() for path in inventory.unmanaged
        ],
    )


def wire_inventory_to_on_disk(
    wire: WireInventory, workspace_root: Path, offline_root: Path
) -> OnDiskInventory:
    """Reconstruct an ``OnDiskInventory`` (absolute paths) from its wire form.

    The inverse of ``wire_inventory_from_on_disk``: each repo's absolute location
    is rebuilt from ``state`` + the matching root, and unmanaged paths are rebuilt
    against the workspace root. Keyed by slug, matching ``scanner.scan``.
    """
    repos = {
        w.slug: wire_repo_to_on_disk(w, workspace_root, offline_root)
        for w in wire.repos
    }
    unmanaged = [workspace_root / PurePosixPath(rel) for rel in wire.unmanaged]
    return OnDiskInventory(repos=repos, unmanaged=unmanaged)

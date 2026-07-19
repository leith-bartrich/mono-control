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


class WireUnmanaged(StrictModel):
    """An unmanaged (unstamped) checkout found under one of the roots.

    Like ``WireRepo`` it carries a relative ``location`` plus the ``state`` that
    says which root the location is relative to — so a foreign tree found under
    the offline root round-trips back to the offline root, not the workspace one.
    """

    location: str  # RELATIVE to the state's root
    state: State


class WireInventory(StrictModel):
    """The on-disk observation in JSON-native form: managed repos + unmanaged."""

    repos: list[WireRepo] = []
    unmanaged: list[WireUnmanaged] = []


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


def wire_unmanaged_from_on_disk(
    path: Path, workspace_root: Path, offline_root: Path
) -> WireUnmanaged:
    """Project an unmanaged absolute path to its wire form.

    The discriminator is which root the path lives under, so an offline foreign
    tree round-trips back to the offline root rather than the workspace one.
    """
    if path.is_relative_to(workspace_root):
        return WireUnmanaged(
            location=path.relative_to(workspace_root).as_posix(), state="materialized"
        )
    if path.is_relative_to(offline_root):
        return WireUnmanaged(
            location=path.relative_to(offline_root).as_posix(), state="offline"
        )
    raise ValueError(f"unmanaged path {path} is under neither root")


def wire_unmanaged_to_on_disk(
    wire: WireUnmanaged, workspace_root: Path, offline_root: Path
) -> Path:
    """Reconstruct an unmanaged absolute path from its wire form."""
    root = _root_for(wire.state, workspace_root, offline_root)
    return root / PurePosixPath(wire.location)


def wire_inventory_from_on_disk(
    inventory: OnDiskInventory, workspace_root: Path, offline_root: Path
) -> WireInventory:
    """Project an ``OnDiskInventory`` to its wire form.

    Repo and unmanaged locations are each made relative to the root implied by
    their ``state``, so both round-trip back to the root they were found under.
    """
    return WireInventory(
        repos=[
            wire_repo_from_on_disk(repo, workspace_root, offline_root)
            for repo in inventory.repos.values()
        ],
        unmanaged=[
            wire_unmanaged_from_on_disk(path, workspace_root, offline_root)
            for path in inventory.unmanaged
        ],
    )


def wire_inventory_to_on_disk(
    wire: WireInventory, workspace_root: Path, offline_root: Path
) -> OnDiskInventory:
    """Reconstruct an ``OnDiskInventory`` (absolute paths) from its wire form.

    The inverse of ``wire_inventory_from_on_disk``: each repo and unmanaged path's
    absolute location is rebuilt from its ``state`` + the matching root. Repos are
    keyed by slug, matching ``scanner.scan``.
    """
    repos = {
        w.slug: wire_repo_to_on_disk(w, workspace_root, offline_root)
        for w in wire.repos
    }
    unmanaged = [
        wire_unmanaged_to_on_disk(u, workspace_root, offline_root)
        for u in wire.unmanaged
    ]
    return OnDiskInventory(repos=repos, unmanaged=unmanaged)

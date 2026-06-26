"""Models for an observed on-disk inventory.

An ``OnDiskRepo`` is an *observed* record (slug, location, state, commit,
dirty) — never authored. An ``OnDiskInventory`` is the full observation: the
managed checkouts keyed by slug, plus any foreign/unmanaged checkouts found
(reported, never touched).

See ``docs/design/layers/data/on-disk-repo.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from ..base_models import StrictModel


class OnDiskRepo(StrictModel):
    """One observed checkout — its self-stamped slug + where/what it is now."""

    slug: str
    location: Path  # absolute path to the checkout root
    state: Literal["offline", "materialized"]
    commit: str | None  # None if no commits yet (a freshly init'd repo)
    dirty: bool


class OnDiskInventory(StrictModel):
    """The on-disk observation: managed checkouts + any foreign ones found."""

    repos: dict[str, OnDiskRepo] = {}
    unmanaged: list[Path] = []

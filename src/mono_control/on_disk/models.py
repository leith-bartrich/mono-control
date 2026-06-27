"""Models for an observed on-disk inventory.

An ``OnDiskRepo`` is an *observed* record (slug, location, state, commit,
dirty) — never authored. An ``OnDiskInventory`` is the full observation: the
managed checkouts keyed by slug, plus any foreign/unmanaged checkouts found
(reported, never touched).

Both are memory-only — built by ``scanner.scan()``, consumed by the engines,
never serialized — so they're plain ``@dataclass(frozen=True)`` rather than
``StrictModel``: the strict-extras guard exists to catch typos in manifests
we *load*, which doesn't apply here.

See ``docs/design/layers/data/on-disk-repo.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class OnDiskRepo:
    """One observed checkout — its self-stamped slug + where/what it is now."""

    slug: str
    location: Path  # absolute path to the checkout root
    state: Literal["offline", "materialized"]
    commit: str | None  # None if no commits yet (a freshly init'd repo)
    dirty: bool


@dataclass(frozen=True)
class OnDiskInventory:
    """The on-disk observation: managed checkouts + any foreign ones found."""

    repos: dict[str, OnDiskRepo] = field(default_factory=dict)
    unmanaged: list[Path] = field(default_factory=list)

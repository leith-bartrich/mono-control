"""The snapshot model: a concrete, self-contained record of workspace state.

A snapshot is pydantic/versioned but is **not config** — it's produced/logged
output (where artifact builds and dev runs are recorded), so it lives outside the
``config`` package and reuses ``base_models``. See
``docs/design/layers/data/snapshot.md``.

Its authoritative content is ``entries`` (``{slug → (commit, location)}``); the
rest is provenance. ``members()`` projects the member slugs, which is what makes a
snapshot satisfy the repo-set ``members()`` interface (see ``repo_set``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import ValidationError

from ..base_models import StrictModel, VersionedModel, VersionError
from .errors import SnapshotValidationError, SnapshotVersionError


class SnapshotEntry(StrictModel):
    """One repo's pinned state within a snapshot."""

    commit: str  # the exact commit
    location: str  # subdirectory the repo's worktree is at, relative to mono-work


class Snapshot(VersionedModel):
    """A concrete, reproducible resolution of a set of repos.

    ``entries`` is the authoritative thing the snapshot executes against;
    ``repo_set_id`` and ``created_at`` are non-authoritative provenance.
    """

    CURRENT_VERSION = 1
    version: Literal[1] = 1
    entries: dict[str, SnapshotEntry] = {}  # slug -> entry
    repo_set_id: str | None = None  # the originating repo-set id (provenance)
    created_at: datetime | None = None  # when produced; caller-supplied, never auto

    def members(self) -> set[str]:
        """Project the member slugs — a snapshot *is* a repo set's membership."""
        return set(self.entries)


def load_snapshot(data: dict) -> Snapshot:
    """Deserialize-and-validate a snapshot dict, surfacing snapshot-typed errors.

    The deserialize boundary (counterpart to ``config.load_config``); file IO /
    where snapshots live is still deferred, so this takes an already-parsed dict.
    """
    try:
        return Snapshot.load(data)
    except VersionError as e:
        raise SnapshotVersionError(str(e)) from e
    except ValidationError as e:
        raise SnapshotValidationError(str(e)) from e

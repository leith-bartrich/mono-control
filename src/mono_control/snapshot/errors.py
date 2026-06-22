"""Typed errors for the snapshot data layer.

Parallels ``config/errors.py``: ``load_snapshot`` translates the base
``VersionError`` and pydantic ``ValidationError`` into these so callers get a
snapshot-typed failure instead of a foreign error.
"""

from __future__ import annotations


class SnapshotError(Exception):
    """Base class for snapshot load/validation failures."""


class SnapshotValidationError(SnapshotError):
    """A snapshot document parsed but did not match the model."""


class SnapshotVersionError(SnapshotError):
    """A snapshot's version is missing, unknown, too new, or un-migratable."""

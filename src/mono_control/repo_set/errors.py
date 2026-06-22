"""Typed errors for the repo-set data layer.

Parallels ``config/errors.py``: ``load_repo_set`` translates the base
``VersionError`` and pydantic ``ValidationError`` into these.
"""

from __future__ import annotations


class RepoSetError(Exception):
    """Base class for repo-set load/validation failures."""


class RepoSetValidationError(RepoSetError):
    """A repo-set document parsed but did not match the model."""


class RepoSetVersionError(RepoSetError):
    """A repo-set's version is missing, unknown, too new, or un-migratable."""

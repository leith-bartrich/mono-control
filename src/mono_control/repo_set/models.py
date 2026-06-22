"""The repo-set model and its membership protocol.

A repo set is fundamentally an **enumerable set of member slugs** resolved against
the current config — the ``members()`` interface (``RepoSetLike``). Both the
persisted, authored ``RepoSet`` and a ``snapshot.Snapshot`` projection satisfy it.
See ``docs/design/layers/data/repo-set.md``.

``missing_members`` is the existence gate: the one semantic "validity" check,
purely against a supplied set of known slugs (so it stays decoupled from config
and works on snapshots too).
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import ValidationError

from ..base_models import VersionedModel, VersionError
from .errors import RepoSetValidationError, RepoSetVersionError


@runtime_checkable
class RepoSetLike(Protocol):
    """Anything that can enumerate a set of member repo slugs."""

    def members(self) -> set[str]: ...


class RepoSet(VersionedModel):
    """A persisted, authored named subset of repos.

    ``kind`` reserves the discriminator for specializations (``product`` is a thin
    kind today; product-oriented capabilities are deferred). ``slugs`` is the
    stored membership; ``members()`` exposes it via the ``RepoSetLike`` interface.
    """

    CURRENT_VERSION = 1
    version: Literal[1] = 1
    id: str
    kind: Literal["repo_set", "product"] = "repo_set"
    slugs: set[str] = set()

    def members(self) -> set[str]:
        return set(self.slugs)


def missing_members(repo_set: RepoSetLike, known_slugs: set[str]) -> set[str]:
    """Return member slugs that are absent from ``known_slugs`` (empty = valid).

    The existence gate: a member whose repo definition still exists — including a
    **retired** one — passes; a **purged** one (absent) fails. Callers pass
    ``known_slugs`` from ``RepoStore.list(include_retired=True)``.
    """
    return repo_set.members() - known_slugs


def load_repo_set(data: dict) -> RepoSet:
    """Deserialize-and-validate a repo-set dict, surfacing repo-set-typed errors."""
    try:
        return RepoSet.load(data)
    except VersionError as e:
        raise RepoSetVersionError(str(e)) from e
    except ValidationError as e:
        raise RepoSetValidationError(str(e)) from e

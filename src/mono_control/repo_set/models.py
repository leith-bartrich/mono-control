"""The repo-set membership protocol and its existence-gate check.

A repo set is fundamentally an **enumerable set of member slugs** — the
``members()`` interface (``RepoSetLike``). Both a [snapshot] projection and the
authored form (a *product* inside a product-cluster repo, TBD) satisfy it; a bare
repo-set is a memory-only abstraction, never persisted as a standalone document.

``missing_members`` is the one semantic check: an existence gate over any
``RepoSetLike``, decoupled from config (the caller supplies the known slugs).
See ``docs/design/layers/data/repo-set.md``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class RepoSetLike(Protocol):
    """Anything that can enumerate a set of member repo slugs."""

    def members(self) -> set[str]: ...


def missing_members(repo_set: RepoSetLike, known_slugs: set[str]) -> set[str]:
    """Return member slugs that are absent from ``known_slugs`` (empty = valid).

    The existence gate: a member whose repo definition still exists — including a
    **retired** one — passes; a **purged** one (absent) fails. Callers pass
    ``known_slugs`` from ``RepoStore.list(include_retired=True)``.
    """
    return repo_set.members() - known_slugs

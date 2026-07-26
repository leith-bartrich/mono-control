"""Typed errors for the on-disk observer."""

from __future__ import annotations

from pathlib import Path


class OnDiskError(Exception):
    """Base class for on-disk observation failures."""


class DuplicateSlugError(OnDiskError):
    """The same slug was stamped on two distinct bare repos.

    A slug is meant to identify exactly one bare repo (with at most one worktree).
    Encountering the same slug twice means the bare root is in an inconsistent
    state — surfaced rather than silently picking a winner.
    """

    def __init__(self, slug: str, first: Path, second: Path) -> None:
        self.slug = slug
        self.first = first
        self.second = second
        super().__init__(
            f"slug {slug!r} stamped on two bare repos: {first} and {second}"
        )

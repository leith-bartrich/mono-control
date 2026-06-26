"""Typed errors for the on-disk observer."""

from __future__ import annotations

from pathlib import Path


class OnDiskError(Exception):
    """Base class for on-disk observation failures."""


class DuplicateSlugError(OnDiskError):
    """The same slug was stamped on two distinct checkouts.

    A repo is meant to exist at most once on disk (the one-materialization rule
    plus an offline holding spot). Encountering the same slug twice means the
    workspace is in an inconsistent state — surfaced rather than silently
    picking a winner.
    """

    def __init__(self, slug: str, first: Path, second: Path) -> None:
        self.slug = slug
        self.first = first
        self.second = second
        super().__init__(
            f"slug {slug!r} stamped on two checkouts: {first} and {second}"
        )

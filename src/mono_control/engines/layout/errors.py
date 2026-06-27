"""Typed exceptions for the layout-engine execute stage.

Each known failure mode raises one of these so the execute step can catch it
*specifically* and map it to a precise ``LayoutOutcome``. Anything that
escapes these — i.e. truly unexpected — propagates; the engine never wraps
"the world broke" as a generic ``failed`` outcome (catch-alls hide bugs).
"""

from __future__ import annotations

from pathlib import Path


class LayoutEngineError(Exception):
    """Base class for layout-engine internal failures."""


class SlugMismatchError(LayoutEngineError):
    """The slug stamp at a location changed between plan and execute.

    A race: someone (another process, a developer) re-stamped or replaced the
    checkout while the engine was planning.
    """

    def __init__(self, location: Path, expected: str, actual: str) -> None:
        self.location = location
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"slug mismatch at {location}: expected {expected!r}, got {actual!r}"
        )


class DestinationOccupiedError(LayoutEngineError):
    """A move target became occupied between plan and execute (the rename guard).

    Also the failure-as-guard mode: even if we pre-check, ``os.rename`` itself
    fails on most platforms when the destination exists.
    """

    def __init__(self, destination: Path) -> None:
        self.destination = destination
        super().__init__(f"destination already exists: {destination}")


class MoveFailedError(LayoutEngineError):
    """A move failed for a reason other than destination occupancy.

    Permission denied, cross-device move, source vanished, etc. — the kinds
    of OS errors that aren't a recoverable race but a real, situational
    failure the user needs to act on.
    """

    def __init__(self, src: Path, dst: Path, detail: str) -> None:
        self.src = src
        self.dst = dst
        self.detail = detail
        super().__init__(f"move {src} → {dst} failed: {detail}")

"""Shared Rich rendering for engine outcomes (CLI + aspects)."""

from __future__ import annotations

from typing import Iterable, Protocol

from rich.console import Console
from rich.table import Table


class _OutcomeLike(Protocol):
    slug: str
    status: str
    summary: str


_GOOD = {
    "ok",
    "cloned",
    "initialized",
    "fetched",
    "placed",
    "checked-out",
    "relocated",
    "retired",
    "satisfied",
}
_RECOVERABLE = {"blocked", "race-aborted"}


def status_color(status: str) -> str:
    """Color for a status token: green ok, yellow recoverable, red the rest."""
    if status in _GOOD:
        return "green"
    if status in _RECOVERABLE:
        return "yellow"
    return "red"


def render_outcomes(
    title: str,
    outcomes: Iterable[_OutcomeLike],
    *,
    console: Console | None = None,
) -> None:
    """Render a per-slug outcome table; no-op for an empty iterable."""
    outcomes = list(outcomes)
    if not outcomes:
        return
    console = console or Console()
    table = Table(title=title, show_edge=False, box=None)
    table.add_column("slug")
    table.add_column("status")
    table.add_column("summary")
    for o in outcomes:
        color = status_color(o.status)
        table.add_row(o.slug, f"[{color}]{o.status}[/{color}]", o.summary)
    console.print(table)

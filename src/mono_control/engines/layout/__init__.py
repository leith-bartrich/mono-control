"""Layout engine — arranges the local layout to match a layout-target.

Local-only: never touches a remote, never creates a checkout. Moves
checkouts between **offline ↔ materialized** (place / retire / relocate) and
checks them out to specific commits, on the toolkit the
[source engine](../source/) already brought into local availability.

See ``docs/design/layers/layout/README.md``.
"""

from .engine import run
from .plan import PlanItem, plan
from .result import LayoutOutcome, LayoutReport

__all__ = [
    "LayoutOutcome",
    "LayoutReport",
    "PlanItem",
    "plan",
    "run",
]

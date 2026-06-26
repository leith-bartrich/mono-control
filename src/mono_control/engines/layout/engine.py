"""The layout engine entry point: plan, then execute, per the design doc.

Capture (writing the resulting state as a snapshot) is left to the caller
for now — see the open thread in
``docs/design/layers/layout/README.md`` (capture may be opt-in / where to
store it is TBD).
"""

from __future__ import annotations

from pathlib import Path

from ...layout_target import LayoutTarget
from ...on_disk import OnDiskInventory
from .execute import execute
from .plan import plan
from .result import LayoutReport


def run(
    target: LayoutTarget,
    *,
    inventory: OnDiskInventory,
    workspace_root: Path,
    offline_root: Path,
) -> LayoutReport:
    """Reconcile the workspace toward ``target`` using the observed inventory."""
    items = plan(target, inventory, workspace_root=workspace_root)
    outcomes = execute(items, offline_root=offline_root)
    return LayoutReport(outcomes=outcomes)

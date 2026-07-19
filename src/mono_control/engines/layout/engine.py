"""The layout engine entry point: plan (pure), then execute (via the broker).

Capture (writing the resulting state as a snapshot) is left to the caller
for now — see the open thread in
``docs/design/layers/layout/README.md`` (capture may be opt-in / where to
store it is TBD).
"""

from __future__ import annotations

from pathlib import Path

from ...broker import BrokerProtocol
from ...layout_target import LayoutTarget
from ...on_disk import OnDiskInventory
from .execute import execute
from .plan import plan
from .result import LayoutReport


def run(
    target: LayoutTarget,
    *,
    broker: BrokerProtocol,
    inventory: OnDiskInventory,
    workspace_root: Path,
    resolved_refs: dict[str, dict[str, str]] | None = None,
) -> LayoutReport:
    """Reconcile the workspace toward ``target`` using the observed inventory.

    ``resolved_refs`` is the source engine's ``{slug: {ref: commit}}`` map, which
    pins a ``PresentBranchHead`` target's commit at plan time. The offline
    holding root is a host constant on the broker, so it is no longer passed here.
    """
    items = plan(
        target, inventory, workspace_root=workspace_root, resolved_refs=resolved_refs
    )
    outcomes = execute(items, broker=broker, workspace_root=workspace_root)
    return LayoutReport(outcomes=outcomes)

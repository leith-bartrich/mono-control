"""mono-control snapshot layer — the persisted, concrete record of workspace state.

Pydantic/versioned but deliberately *not* config: a snapshot is produced/logged
output. See docs/design/layers/data/snapshot.md.
"""

from .errors import SnapshotError, SnapshotValidationError, SnapshotVersionError
from .models import Snapshot, SnapshotEntry, load_snapshot

__all__ = [
    "Snapshot",
    "SnapshotEntry",
    "load_snapshot",
    "SnapshotError",
    "SnapshotValidationError",
    "SnapshotVersionError",
]

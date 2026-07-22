"""mono-control on-disk layer — observed state of the bare repos + their worktrees.

The eyes for both engines: scan ``mono-repos-bare`` for bare repos and detect a
worktree under ``mono-work`` (materialized) or its absence (offline), identify each
repo by its self-stamped ``mono-control.slug``, and report its observed state.

See ``docs/design/layers/data/on-disk-repo.md``.
"""

from .errors import DuplicateSlugError, OnDiskError
from .models import OnDiskInventory, OnDiskRepo
from .scanner import scan

__all__ = [
    "DuplicateSlugError",
    "OnDiskError",
    "OnDiskInventory",
    "OnDiskRepo",
    "scan",
]

"""mono-control on-disk layer — observed state of checkouts in the workspace.

The eyes for both engines: scan ``mono-repos`` (materialized) and
``mono-repos-offline`` (holding area), identify each checkout by its
self-stamped ``mono-control.slug``, and report its observed state.

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

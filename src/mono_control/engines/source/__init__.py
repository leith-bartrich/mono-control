"""Source engine — brings repos into local availability (inbound only).

Per-repo additive: clone an absent repo into offline (or init a brand-new one
with no remote), fetch refs on a present one, verify the requested refs now
resolve locally. Never places, retires, or pushes. See
docs/design/layers/source/README.md.
"""

from .engine import run
from .request import SourceRequest, from_layout_target
from .result import SourceOutcome, SourceReport

__all__ = [
    "SourceRequest",
    "from_layout_target",
    "run",
    "SourceOutcome",
    "SourceReport",
]

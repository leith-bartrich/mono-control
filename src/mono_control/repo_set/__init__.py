"""mono-control repo-set layer — the membership interface over repos.

A repo set is the ``members()`` interface (``RepoSetLike``); a bare repo-set is
memory-only (projected from a product or a snapshot). The authored form is a
*product* inside a product-cluster repo (TBD). See
docs/design/layers/data/repo-set.md.
"""

from .models import RepoSetLike, missing_members

__all__ = ["RepoSetLike", "missing_members"]

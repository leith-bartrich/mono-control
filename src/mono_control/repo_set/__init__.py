"""mono-control repo-set layer — named, enumerable subsets of repos.

A repo set is the ``members()`` interface (``RepoSetLike``) resolved against the
current config; both a persisted authored ``RepoSet`` and a snapshot projection
satisfy it. See docs/design/layers/data/repo-set.md.
"""

from .errors import RepoSetError, RepoSetValidationError, RepoSetVersionError
from .models import RepoSet, RepoSetLike, load_repo_set, missing_members

__all__ = [
    "RepoSet",
    "RepoSetLike",
    "missing_members",
    "load_repo_set",
    "RepoSetError",
    "RepoSetValidationError",
    "RepoSetVersionError",
]

"""mono-control git operations layer — the thin wrapper over the git CLI.

Pure mechanism over paths and refs (see docs/design/layers/git/README.md). This
pass covers the skeleton plus the two repo-creating operations, ``clone`` and
``init``, both of which stamp the host filesystem-capability profile.
"""

from .errors import GitCommandError, GitError
from .repo import GitRepo, clone, init

__all__ = [
    "GitError",
    "GitCommandError",
    "GitRepo",
    "clone",
    "init",
]

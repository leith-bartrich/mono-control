"""mono-control git operations layer — the thin wrapper over the git CLI.

Pure mechanism over paths and refs (see docs/design/layers/git/README.md). Both
repo-creating operations (``clone``, ``init``) stamp the host filesystem
profile + the repo's ``mono-control.slug`` identity; ``GitRepo`` exposes the
inspection/local-action verbs (``slug``, ``is_dirty``, ``fetch``, ``checkout``,
``ahead_behind``) the engines drive.
"""

from .errors import GitAuthError, GitCommandError, GitError, UnmanagedCheckoutError
from .repo import GitRepo, clone, init, ls_remote, remote_default_branch

__all__ = [
    "GitError",
    "GitCommandError",
    "GitAuthError",
    "UnmanagedCheckoutError",
    "GitRepo",
    "clone",
    "init",
    "ls_remote",
    "remote_default_branch",
]

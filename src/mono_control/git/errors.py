"""Typed errors for the git operations layer.

Parallels ``config/errors.py``: callers catch ``GitError`` to surface a clear
message instead of a raw ``CalledProcessError`` or stray ``FileNotFoundError``.
"""

from __future__ import annotations


class GitError(Exception):
    """Base class for git operation failures."""


class GitCommandError(GitError):
    """A git invocation exited non-zero.

    Carries the command (as a list), its return code, and captured stderr so the
    message is actionable rather than an opaque exit status.
    """

    def __init__(self, command: list[str], returncode: int, stderr: str) -> None:
        self.command = command
        self.returncode = returncode
        self.stderr = stderr.strip()
        shown = " ".join(command)
        detail = f": {self.stderr}" if self.stderr else ""
        super().__init__(f"`{shown}` failed (exit {returncode}){detail}")


class UnmanagedCheckoutError(GitError):
    """A checkout is missing the ``mono-control.slug`` identity stamp.

    The stamp is an *invariant* of a managed checkout: any tree we created we
    stamped, so an unstamped tree is foreign — never assumed, never operated on.
    Adopting a pre-existing checkout means *explicitly* stamping it (assigning a
    slug), not silently trusting it.
    """

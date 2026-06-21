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

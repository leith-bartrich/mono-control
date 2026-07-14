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
        super().__init__(f"`{shown}` failed (exit {returncode}){detail}{self._hint()}")

    def _hint(self) -> str:
        """Guidance appended after the raw failure. Overridden by subclasses."""
        return ""


# Substrings git (or GitHub, through git) emits when a failure is really "no usable
# credential". Matched case-insensitively against stderr.
#
# `repository not found` is deliberately in this list. GitHub answers an
# unauthenticated request for a private repo with a 404, never a 403 — so a missing
# token and a genuinely wrong URL are indistinguishable from the outside. Treating
# it as an auth symptom and naming BOTH possibilities in the hint beats guessing.
AUTH_MARKERS = (
    "could not read username",
    "could not read password",
    "terminal prompts disabled",
    "authentication failed",
    "invalid username or password",
    "repository not found",
)

_AUTH_HINT = (
    "\n  No usable GitHub credential in the container: MONO_CONTROL_GITHUB_TOKEN is"
    " unset, expired,\n  or lacks access to this repo. The container cannot obtain one"
    " itself — your host's lives in an\n  OS keyring no Linux container can reach — so"
    " the shim supplies it per run. Either:\n"
    "    - export MONO_CONTROL_GITHUB_TOKEN (a read-only, repo-scoped fine-grained PAT), or\n"
    "    - run `gh auth login` and let `mproj` fall back to your gh token.\n"
    "  If instead the remote genuinely does not exist, the URL in mono-config is wrong:"
    " GitHub\n  reports a private repo you cannot see as 'not found', not 'forbidden'."
)


def is_auth_failure(stderr: str) -> bool:
    """True if *stderr* looks like a missing, expired, or insufficient credential."""
    haystack = stderr.lower()
    return any(marker in haystack for marker in AUTH_MARKERS)


class GitAuthError(GitCommandError):
    """A git invocation failed for lack of a usable GitHub credential.

    Split out from the generic ``GitCommandError`` because the remedy is specific and
    lives *outside* the container: a token has to be handed in. Subclasses
    ``GitCommandError`` so existing ``except GitCommandError`` handlers keep working;
    only the message differs.

    The image sets ``GIT_TERMINAL_PROMPT=0``, so a missing credential surfaces here as
    a clean error rather than as git blocking on an interactive prompt.
    """

    def _hint(self) -> str:
        return _AUTH_HINT


class UnmanagedCheckoutError(GitError):
    """A checkout is missing the ``mono-control.slug`` identity stamp.

    The stamp is an *invariant* of a managed checkout: any tree we created we
    stamped, so an unstamped tree is foreign — never assumed, never operated on.
    Adopting a pre-existing checkout means *explicitly* stamping it (assigning a
    slug), not silently trusting it.
    """

"""``GitRepo`` plus the repo-creating operations ``clone`` and ``init``.

Pure mechanism: these know paths and refs, not repo definitions. Both create
operations are the *consistency anchor* — they stamp two values into the new
repo's ``.git/config`` so every later git on that tree (ours or a developer's
native git) behaves consistently and the checkout is self-identifying:

- the host filesystem-capability ``FsProfile`` (``core.filemode`` /
  ``core.symlinks`` / ``core.ignorecase``), supplied by the caller from
  ``host_platform.profile()``;
- the repo's ``mono-control.slug`` — its immutable identity, so reverse-lookup
  (location → slug) needs no external index.

Both stamps are **mandatory** at create time and **verified to round-trip**.
A checkout this layer creates is never left unstamped, and a checkout without
the slug stamp is foreign — ``GitRepo.slug()`` refuses it with
``UnmanagedCheckoutError`` rather than silently trusting it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ..host_platform import FsProfile
from .errors import GitCommandError, UnmanagedCheckoutError
from .runner import run_git

_SLUG_KEY = "mono-control.slug"

# The FS-capability settings stamped at create time, in (config key, attr) form.
_PROFILE_KEYS = (
    ("core.filemode", "filemode"),
    ("core.symlinks", "symlinks"),
    ("core.ignorecase", "ignorecase"),
)


class GitRepo:
    """A handle on a git working tree at ``path``."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _git(self, *args: str) -> str:
        return run_git(list(args), cwd=self.path)

    def current_commit(self) -> str | None:
        """The commit HEAD points at, or ``None`` if there are no commits yet."""
        return self.resolve_ref("HEAD")

    def resolve_ref(self, ref: str) -> str | None:
        """Return the commit ``ref`` resolves to locally, or ``None`` if it doesn't."""
        try:
            return self._git("rev-parse", "--verify", f"{ref}^{{commit}}")
        except GitCommandError:
            return None

    def config_get(self, key: str) -> str:
        """Return a local git config value (raises if the key is unset)."""
        return self._git("config", "--get", key)

    def slug(self) -> str:
        """Return the ``mono-control.slug`` stamp; raise if the checkout is foreign."""
        try:
            return self.config_get(_SLUG_KEY)
        except GitCommandError as e:
            raise UnmanagedCheckoutError(
                f"{self.path} has no {_SLUG_KEY!r} stamp (foreign / unmanaged)"
            ) from e

    def is_dirty(self) -> bool:
        """True if the working tree has uncommitted changes (``status --porcelain``)."""
        return bool(self._git("status", "--porcelain"))

    def fetch(self, remote: str, refs: Iterable[str] | None = None) -> None:
        """Fetch from ``remote``; optionally limited to the named ``refs``."""
        args = ["fetch", remote]
        if refs is not None:
            args.extend(refs)
        self._git(*args)

    def checkout(self, ref: str) -> None:
        """Check out ``ref`` (a branch, tag, or commit)."""
        self._git("checkout", ref)

    def ahead_behind(self, ref: str) -> tuple[int, int]:
        """``(ahead, behind)`` of HEAD relative to ``ref`` (via ``rev-list --count``)."""
        out = self._git("rev-list", "--left-right", "--count", f"{ref}...HEAD")
        # `git rev-list --left-right --count A...B` prints "<left>\t<right>":
        # left = commits in A not in B (behind), right = commits in B not in A (ahead).
        behind_str, ahead_str = out.split()
        return int(ahead_str), int(behind_str)

    def _apply_profile(self, profile: FsProfile) -> None:
        """Stamp the FS-capability profile into this repo's ``.git/config``."""
        for key, attr in _PROFILE_KEYS:
            value = "true" if getattr(profile, attr) else "false"
            self._git("config", key, value)

    def _apply_slug(self, slug: str) -> None:
        """Stamp ``mono-control.slug`` and verify it round-trips."""
        self._git("config", _SLUG_KEY, slug)
        readback = self.config_get(_SLUG_KEY)
        if readback != slug:
            raise UnmanagedCheckoutError(
                f"slug stamp on {self.path} did not round-trip: "
                f"wrote {slug!r}, read back {readback!r}"
            )


def clone(
    url: str | Path, dest: Path | str, *, profile: FsProfile, slug: str
) -> GitRepo:
    """Clone ``url`` into ``dest`` and stamp ``profile`` + ``slug`` before checkout.

    Clones with ``--no-checkout`` so the working tree is empty, stamps the profile
    and slug into ``.git/config``, then populates the tree from HEAD — so the
    stamp governs the checkout (notably symlink/filemode handling).
    """
    dest = Path(dest)
    run_git(["clone", "--no-checkout", str(url), str(dest)])
    repo = GitRepo(dest)
    repo._apply_profile(profile)
    repo._apply_slug(slug)
    repo._git("checkout", "HEAD", "--", ".")
    return repo


def init(
    path: Path | str, *, profile: FsProfile, slug: str, initial_branch: str | None = None
) -> GitRepo:
    """Initialize a new empty repo at ``path`` and stamp ``profile`` + ``slug``.

    ``initial_branch`` names the (unborn) HEAD branch via ``git init
    --initial-branch``; when omitted, git uses its configured default. No checkout
    exists yet, so the returned repo's ``current_commit()`` is ``None``.
    """
    path = Path(path)
    args = ["init"]
    if initial_branch is not None:
        args += ["--initial-branch", initial_branch]
    args.append(str(path))
    run_git(args)
    repo = GitRepo(path)
    repo._apply_profile(profile)
    repo._apply_slug(slug)
    return repo


def ls_remote(url: str | Path, ref: str) -> str | None:
    """Resolve ``ref`` at the remote ``url`` to a commit hash, or ``None`` if absent.

    Probes without cloning — the resolvability gate. Network/transport failures
    bubble up as ``GitCommandError``; *only* a successful ``ls-remote`` whose
    output doesn't mention ``ref`` returns ``None``.
    """
    out = run_git(["ls-remote", str(url), ref])
    if not out:
        return None
    # Output lines are "<sha>\t<refname>"; take the SHA on the first match.
    first_line = out.splitlines()[0]
    sha, _, _ = first_line.partition("\t")
    return sha or None


def remote_default_branch(url: str | Path) -> str | None:
    """Read the remote's default branch (its symbolic HEAD), or ``None``.

    Runs ``git ls-remote --symref <url> HEAD`` and returns the branch HEAD points
    at (e.g. ``main``). Network/transport failures bubble up as ``GitCommandError``;
    ``None`` means the remote reported no ``refs/heads/*`` symref for HEAD.
    """
    out = run_git(["ls-remote", "--symref", str(url), "HEAD"])
    for line in out.splitlines():
        # e.g. "ref: refs/heads/main\tHEAD"
        if line.startswith("ref:"):
            target = line[len("ref:") :].strip().split()[0]
            if target.startswith("refs/heads/"):
                return target[len("refs/heads/") :]
    return None

"""``GitRepo`` plus the repo-creating operations ``clone`` and ``init``.

Pure mechanism: these know paths and refs, not repo definitions. Both create
operations are the *consistency anchor* — they stamp the host's
filesystem-capability ``FsProfile`` into the new repo's ``.git/config`` so every
later git on that tree (ours or a developer's native git) behaves the same. The
profile is supplied by the caller (from ``host_platform.profile()``); this layer
only applies it.
"""

from __future__ import annotations

from pathlib import Path

from ..host_platform import FsProfile
from .errors import GitCommandError
from .runner import run_git

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
        try:
            return self._git("rev-parse", "HEAD")
        except GitCommandError:
            return None

    def config_get(self, key: str) -> str:
        """Return a local git config value (raises if the key is unset)."""
        return self._git("config", "--get", key)

    def _apply_profile(self, profile: FsProfile) -> None:
        """Stamp the FS-capability profile into this repo's ``.git/config``."""
        for key, attr in _PROFILE_KEYS:
            value = "true" if getattr(profile, attr) else "false"
            self._git("config", key, value)


def clone(url: str | Path, dest: Path | str, *, profile: FsProfile) -> GitRepo:
    """Clone ``url`` into ``dest`` and stamp ``profile`` before materializing files.

    Clones with ``--no-checkout`` so the working tree is empty, stamps the profile
    into ``.git/config``, then populates the tree from HEAD — so the stamp governs
    the checkout (notably symlink/filemode handling).
    """
    dest = Path(dest)
    run_git(["clone", "--no-checkout", str(url), str(dest)])
    repo = GitRepo(dest)
    repo._apply_profile(profile)
    repo._git("checkout", "HEAD", "--", ".")
    return repo


def init(path: Path | str, *, profile: FsProfile) -> GitRepo:
    """Initialize a new empty repo at ``path`` and stamp ``profile``.

    No checkout exists yet, so the returned repo's ``current_commit()`` is ``None``.
    """
    path = Path(path)
    run_git(["init", str(path)])
    repo = GitRepo(path)
    repo._apply_profile(profile)
    return repo

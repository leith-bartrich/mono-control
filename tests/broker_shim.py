"""An in-process fake broker that performs real git + filesystem effects.

Step 2 relocates the container's git/FS/config effects to a host-side broker
(a different repo). The container is now a pure JSON-RPC client; this module is
the test-side stand-in for that broker — the *same* effect logic reassembled
behind a ``call(method, params)`` dispatcher that returns plain JSON. Because it
does the *real* work on real temp directories, the end-to-end CLI tests keep
asserting real on-disk state; only the wiring (inject this broker via ``ctx.obj``
/ ``RepoStore(broker)``) changes.

Physical model: **bare repos + git worktrees**, mirroring the real shim
(``mono-control-shim/.../verbs/git.py``). ``acquire`` creates a *bare* repo under
the bare root (``bare_root``) that never moves; ``place`` adds a worktree under the
work root (``work_root``) with ``git worktree add``; ``relocate`` is ``git worktree
move``; ``retire`` is ``git worktree remove`` (dirty-gated — the bare repo and its
commits survive). The ``state`` literal is reinterpreted: **offline = a bare repo
with no worktree**, **materialized = a bare repo with a worktree**. ``read_layout``
is bare-aware (a worktree file when materialized, the HEAD blob when offline).

It inherits :class:`TypedBrokerMixin`, so callers use the same typed verbs
(``scan`` / ``acquire`` / ``place`` / …) they use against the real client.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.parse
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable

from mono_control.broker import (
    BrokerError,
    TypedBrokerMixin,
    wire_inventory_from_on_disk,
)
from mono_control.on_disk import OnDiskInventory, OnDiskRepo


@dataclass(frozen=True)
class FsProfile:
    """The git filesystem-capability config a host's working tree needs.

    The real (host-side) broker derives this natively from the host it runs on;
    this test-side shim keeps a self-contained copy so the stamping logic below
    can mirror what the broker does.
    """

    filemode: bool
    symlinks: bool
    ignorecase: bool


# A concrete profile for tests (a Linux-ish host filesystem). The real broker
# derives this natively from the host; here it is fixed.
PROFILE = FsProfile(filemode=True, symlinks=True, ignorecase=False)

# The slug stamp (dir -> slug) and the FS-capability profile, stamped into a bare
# repo's config so every worktree added off it inherits them.
_SLUG_KEY = "mono-control.slug"

# The governed source names and the refspec every conformed remote fetches, mirroring
# the real shim. Remote-tracking, deliberately not mirror (`+refs/heads/*:refs/heads/*`),
# which would force-overwrite local branches and collapse under multiple remotes.
ORIGIN = "origin"
UPSTREAM = "upstream"
FORK_OURS = "fork-ours"
_FETCH_REFSPEC = "+refs/heads/*:refs/remotes/{name}/*"


def _default_source(sources: dict[str, str]) -> str | None:
    """The source name `origin` aliases: writable canonical, else read canonical."""
    for name in (ORIGIN, FORK_OURS, UPSTREAM):
        if sources.get(name):
            return name
    return next(iter(sources), None)


def conform_remotes(repo: GitRepo, sources: dict[str, str]) -> list[str]:
    """Git remotes per declared source, plus `origin` aliasing the default.

    Mirrors the real shim's `conform_remotes`. Additive — unrecognised remotes are left
    alone and returned. Repoint is remove+re-add so stale tracking refs go with the old
    URL rather than sitting beside the new one.
    """
    desired = dict(sources)
    default = _default_source(sources)
    if default is not None:
        desired[ORIGIN] = sources[default]

    existing = set(repo.remotes())
    for name, url in desired.items():
        if name in existing and repo.remote_url(name) != url:
            repo.remove_remote(name)
            existing.discard(name)
        if name not in existing:
            repo.set_remote(name, url)
        repo.set_fetch_refspec(name)
    return sorted(existing - set(desired))
_PROFILE_KEYS = (
    ("core.filemode", "filemode"),
    ("core.symlinks", "symlinks"),
    ("core.ignorecase", "ignorecase"),
)

# Identity for the root commit ``init`` writes, used only for fields the host has not
# configured. Unroutable by design (RFC 2606 ``.invalid``).
_FALLBACK_IDENTITY = (
    ("user.name", "mono-control"),
    ("user.email", "mono-control@invalid"),
)


def _identity_config(repo: GitRepo) -> list[str]:
    """``-c user.*`` pairs for identity fields the host hasn't set.

    Prefers the user's own identity, falling back per field so a machine with no git
    identity configured can still init a repo.
    """
    config: list[str] = []
    for key, fallback in _FALLBACK_IDENTITY:
        try:
            if repo.config_get(key):
                continue
        except GitError:
            pass  # unset: `config --get` exits non-zero on a missing key
        config += ["-c", f"{key}={fallback}"]
    return config

# The cluster layout document, relative to a repo's working tree (a worktree, or
# the committed tree read out of the bare repo's HEAD).
_LAYOUT_REL = "product-cluster/default-layout.json"


# --------------------------------------------------------------------------- #
# Minimal git layer (mirrors the real shim's GitRepo)
# --------------------------------------------------------------------------- #
class GitError(Exception):
    """A git operation failed (missing binary or non-zero exit)."""


class UnmanagedCheckoutError(GitError):
    """A repo has no ``mono-control.slug`` stamp (foreign / unmanaged)."""


def run_git(args: list[str], *, cwd: Path | None = None) -> str:
    """Run ``git <args>`` and return stripped stdout, raising ``GitError`` on failure."""
    command = ["git", *args]
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as e:  # pragma: no cover - git is present in CI
        raise GitError("git executable not found on PATH") from e
    if result.returncode != 0:
        raise GitError(f"`{' '.join(command)}` failed: {result.stderr.strip()}")
    return result.stdout.strip()


class GitRepo:
    """A handle on a git dir — a bare repo, or one of its worktrees.

    Every method runs ``git -C <path> ...``, so the same handle works for a bare
    repo (config / rev-parse / worktree management / ``show``) and for a worktree
    (status / checkout). The worktree-management methods are only meaningful on the
    bare repo.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _git(self, *args: str) -> str:
        return run_git(list(args), cwd=self.path)

    def is_bare_repository(self) -> bool:
        """True if ``path`` is a bare repo; False if it is a worktree or not a git dir."""
        try:
            return self._git("rev-parse", "--is-bare-repository") == "true"
        except GitError:
            return False

    def current_commit(self) -> str | None:
        return self.resolve_ref("HEAD")

    def resolve_ref(self, ref: str) -> str | None:
        try:
            return self._git("rev-parse", "--verify", f"{ref}^{{commit}}")
        except GitError:
            return None

    def config_get(self, key: str) -> str:
        return self._git("config", "--get", key)

    def head_branch(self) -> str:
        """The branch HEAD names — meaningful even while that branch is *unborn*."""
        return self._git("symbolic-ref", "--short", "HEAD")

    def write_root_commit(self, message: str = "initial commit") -> str:
        """Give an empty repo an empty root commit, so HEAD resolves to something.

        ``git init --bare`` leaves HEAD on an **unborn** branch, which
        ``git worktree add <path> HEAD`` cannot resolve — so a brand-new repo could be
        created and then never placed. Plumbing rather than ``worktree add --orphan``
        because that flag needs git >= 2.42 and this fake runs on the container's older
        git; the real shim uses the same commands for the same reason.
        """
        branch = self.head_branch()
        tree = self._git("hash-object", "-w", "-t", "tree", os.devnull)
        # `-c` pairs must precede the subcommand; identity falls back per field so this
        # works on a machine with no git identity configured.
        commit = self._git(*_identity_config(self), "commit-tree", tree, "-m", message)
        self._git("update-ref", f"refs/heads/{branch}", commit)
        return commit

    def slug(self) -> str:
        try:
            return self.config_get(_SLUG_KEY)
        except GitError as e:
            raise UnmanagedCheckoutError(f"{self.path} has no {_SLUG_KEY!r} stamp") from e

    def is_dirty(self) -> bool:
        return bool(self._git("status", "--porcelain"))

    def unreachable_commit_count(self) -> int:
        """Commits reachable from *this worktree's* HEAD but from no branch, tag or remote.

        Non-zero means removing the worktree would **orphan** committed work: a detached
        HEAD's commits are anchored only by that worktree's HEAD. ``--all`` is unusable
        here because it counts HEAD itself; naming the namespaces explicitly is what
        makes the question meaningful, and lets a branch *or* a tag clear the block.
        """
        try:
            out = self._git(
                "rev-list", "--count", "HEAD", "--not", "--branches", "--tags", "--remotes"
            )
        except GitError:
            return 0  # unborn HEAD: nothing committed here, nothing to orphan
        return int(out or 0)

    def fetch(self, remote: str, refs: Iterable[str] | None = None) -> None:
        args = ["fetch", remote]
        if refs is not None:
            args.extend(refs)
        self._git(*args)

    def checkout(self, ref: str) -> None:
        # ``--`` guards a ref beginning with ``-`` from being read as a flag.
        self._git("checkout", ref, "--")

    def show_head_blob(self, rel: str) -> str:
        """Return the contents of ``rel`` as committed at HEAD (``git show HEAD:rel``)."""
        return self._git("show", f"HEAD:{rel}")

    def remotes(self) -> list[str]:
        return self._git("remote").split()

    def remote_url(self, name: str) -> str | None:
        try:
            return self._git("remote", "get-url", name)
        except GitError:
            return None

    def remove_remote(self, name: str) -> None:
        """Drop a remote *and its remote-tracking refs* — why repoint is remove+re-add."""
        self._git("remote", "remove", name)

    def set_fetch_refspec(self, name: str) -> None:
        """Give `name` the standard tracking refspec; `clone --bare` sets none."""
        self._git("config", f"remote.{name}.fetch", _FETCH_REFSPEC.format(name=name))

    def set_remote(self, name: str, url: str) -> None:
        """Add remote ``name`` -> ``url``, or repoint it if it already exists."""
        existing = self._git("remote").split()
        if name in existing:
            self._git("remote", "set-url", name, url)
        else:
            self._git("remote", "add", name, url)

    # -- worktree management (meaningful on the bare repo) ------------------- #
    def worktree_add(self, dest: Path, ref: str) -> None:
        """Materialize a worktree at ``dest`` checked out at ``ref`` (additive)."""
        self._git("worktree", "add", str(dest), ref)

    def worktree_move(self, src: Path, dst: Path) -> None:
        """Move the worktree at ``src`` to ``dst`` (native; preserves its state)."""
        self._git("worktree", "move", str(src), str(dst))

    def worktree_remove(self, path: Path) -> None:
        """Remove the worktree at ``path`` (the bare repo — and its commits — survive)."""
        self._git("worktree", "remove", str(path))

    def worktree_under(self, root: Path) -> Path | None:
        """The path of this bare repo's worktree that lives under ``root``, or ``None``.

        Parses ``git worktree list --porcelain``: the bare repo lists itself with a
        ``bare`` marker (skipped); a real worktree lists its path. The first
        worktree whose resolved path is at or under ``root`` is returned.
        """
        out = self._git("worktree", "list", "--porcelain")
        root_real = root.resolve()
        for record in out.split("\n\n"):
            lines = record.splitlines()
            if not lines or not lines[0].startswith("worktree "):
                continue
            if any(line == "bare" for line in lines):
                continue  # the bare repo's own entry, not a worktree
            wt = Path(lines[0][len("worktree "):])
            try:
                wt_real = wt.resolve()
            except OSError:  # pragma: no cover - defensive
                continue
            if wt_real == root_real or root_real in wt_real.parents:
                return wt
        return None

    def _apply_profile(self, profile: FsProfile) -> None:
        for key, attr in _PROFILE_KEYS:
            self._git("config", key, "true" if getattr(profile, attr) else "false")

    def _apply_slug(self, slug: str) -> None:
        self._git("config", _SLUG_KEY, slug)


def clone(url: str | Path, dest: Path | str, *, profile: FsProfile, slug: str) -> GitRepo:
    """Clone ``url`` into a **bare** repo at ``dest``, stamping ``profile`` + ``slug``.

    ``--bare`` — there is no working tree; a worktree is added later by ``place``.
    """
    dest = Path(dest)
    run_git(["clone", "--bare", str(url), str(dest)])
    repo = GitRepo(dest)
    repo._apply_profile(profile)
    repo._apply_slug(slug)
    return repo


def init(
    path: Path | str, *, profile: FsProfile, slug: str, initial_branch: str | None = None
) -> GitRepo:
    """Initialize a new **bare** repo at ``path`` and stamp ``profile`` + ``slug``.

    The repo gets an empty root commit (see :meth:`GitRepo.write_root_commit`) so it is
    placeable immediately — a repo whose HEAD is still unborn cannot have a worktree
    added off it.
    """
    path = Path(path)
    args = ["init", "--bare"]
    if initial_branch is not None:
        args += ["--initial-branch", initial_branch]
    args.append(str(path))
    run_git(args)
    repo = GitRepo(path)
    repo._apply_profile(profile)
    repo._apply_slug(slug)
    repo.write_root_commit()
    return repo


def add_worktree(bare: Path | str, dest: Path | str, ref: str = "HEAD") -> GitRepo:
    """Test helper: add a worktree at ``dest`` off the bare repo at ``bare``.

    Materializing a repo in the bare+worktree model is two steps — a bare repo in
    the bare root, then a ``git worktree add`` into the work root. Tests that set up
    a *materialized* fixture directly (rather than through ``place``) use this to
    mirror what the broker does.
    """
    GitRepo(bare).worktree_add(Path(dest), ref)
    return GitRepo(dest)


# --------------------------------------------------------------------------- #
# Input validation (the security boundary)
#
# The real host-side shim (mono-control-shim/.../verbs/git.py) validates every
# container-supplied parameter at the boundary before it touches disk or spawns
# git, rejecting hostile input with ``VerbError(INVALID_PARAMS, ...)``. This fake
# mirrors those rejections exactly — same predicates, same JSON-RPC code (which
# surfaces to the container as ``BrokerError(INVALID_PARAMS, ...)``) — so the
# container's suite exercises the security boundary it otherwise couldn't reach.
# Keep these in lockstep with the real ``_valid_slug`` / ``_valid_hex_commit`` /
# ``_sanitize_remote_url`` / ``_resolve_inside``.
# --------------------------------------------------------------------------- #
INVALID_PARAMS = -32602  # JSON-RPC code the real shim raises for rejected input.
SERVER_ERROR = -32000  # JSON-RPC code for a known, reported business failure.

_SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_REMOTE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_HEX_RE = re.compile(r"[0-9a-fA-F]{4,64}")
_ALLOWED_URL_SCHEMES = frozenset({"https"})


def _valid_slug(slug: Any) -> str:
    """A slug must be a bare name (no separators, no ``..``, no leading dot)."""
    if not isinstance(slug, str) or not _SLUG_RE.fullmatch(slug):
        raise BrokerError(INVALID_PARAMS, f"invalid slug: {slug!r}")
    return slug


def _valid_remote_name(name: Any) -> str:
    """A git remote name must be a bare token — no slashes, spaces, or ``..``."""
    if not isinstance(name, str) or not _REMOTE_NAME_RE.fullmatch(name):
        raise BrokerError(INVALID_PARAMS, f"invalid remote name: {name!r}")
    return name


def _valid_hex_commit(commit: Any) -> str:
    """A commit must be a bare hex object id — never a ref, ``HEAD``, or a flag."""
    if not isinstance(commit, str) or not _HEX_RE.fullmatch(commit):
        raise BrokerError(INVALID_PARAMS, f"commit must be a hex object id: {commit!r}")
    return commit


def _sanitize_remote_url(url: Any) -> str:
    """A remote URL must be https and must not use a ``transport::`` helper."""
    if not isinstance(url, str) or not url:
        raise BrokerError(INVALID_PARAMS, f"invalid url: {url!r}")
    if "::" in url:
        raise BrokerError(INVALID_PARAMS, "url uses a transport helper (refused)")
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in _ALLOWED_URL_SCHEMES:
        raise BrokerError(
            INVALID_PARAMS, f"url scheme {scheme or '(none)'!r} not allowed (https only)"
        )
    return url


def _resolve_inside(root: Path, location: Any) -> Path:
    """Resolve ``location`` to a path inside ``root`` or reject it.

    Rejects absolutes (POSIX or Windows) and any ``..`` component, then guards
    against a symlinked parent redirecting the destination out of ``root``.
    """
    if not isinstance(location, str) or not location:
        raise BrokerError(INVALID_PARAMS, f"invalid location: {location!r}")
    pure = PurePosixPath(location)
    if (
        pure.is_absolute()
        or PureWindowsPath(location).is_absolute()
        or any(part == ".." for part in pure.parts)
    ):
        raise BrokerError(INVALID_PARAMS, f"location escapes the workspace: {location!r}")
    dst = root.joinpath(*pure.parts)
    root_real = root.resolve()
    ancestor = dst
    while not ancestor.exists():
        ancestor = ancestor.parent
    ancestor_real = ancestor.resolve()
    if ancestor_real != root_real and root_real not in ancestor_real.parents:
        raise BrokerError(INVALID_PARAMS, f"location escapes the workspace: {location!r}")
    return dst


# --------------------------------------------------------------------------- #
# Observation (scan the bare root; a worktree under work_root => materialized)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _Observed:
    slug: str
    bare: Path  # absolute path to the bare repo (always present)
    worktree: Path | None  # absolute worktree path if materialized, else None
    state: str  # "materialized" | "offline"
    commit: str | None
    dirty: bool


# --------------------------------------------------------------------------- #
# The broker itself
# --------------------------------------------------------------------------- #
class ShimBroker(TypedBrokerMixin):
    """A stateful, real-effect broker over ``(config_dir, work_root, bare_root)`` dirs.

    ``work_root`` holds worktrees (materialized); ``bare_root`` holds the bare
    repos (offline). Constructor argument order mirrors the host-side
    ``HostContext`` fields (work root + bare root), with ``config_dir`` first so
    existing ``ShimBroker(config, work, bare)`` call sites keep working.
    """

    def __init__(
        self,
        config_dir: Path,
        work_root: Path,
        bare_root: Path,
        *,
        profile: FsProfile = PROFILE,
    ) -> None:
        self.config_dir = Path(config_dir)
        self.work_root = Path(work_root)
        self.bare_root = Path(bare_root)
        self.repos_dir = self.config_dir / "repos"
        self.profile = profile
        self.calls: list[tuple[str, dict | None]] = []
        # Canned answers for ``remote_default_branch`` — kept hermetic (no network
        # probe). Per-URL overrides win; otherwise the fixed default is returned.
        self.default_remote_branch: str | None = "main"
        self.remote_default_branches: dict[str, str | None] = {}

    # -- dispatch ---------------------------------------------------------- #
    def call(self, method: str, params: dict | None = None) -> Any:
        self.calls.append((method, params))
        handler = getattr(self, f"_v_{method}", None)
        if handler is None:
            raise BrokerError(-32601, f"method not found: {method!r}")
        return handler(params or {})

    # -- observation ------------------------------------------------------- #
    def _observe(self, bare: Path) -> _Observed | None:
        """Observe one bare repo. ``None`` if it is unstamped (foreign / unmanaged)."""
        repo = GitRepo(bare)
        try:
            slug = repo.slug()
        except UnmanagedCheckoutError:
            return None
        wt = repo.worktree_under(self.work_root)
        if wt is not None:
            tree = GitRepo(wt)
            return _Observed(slug, bare, wt, "materialized", tree.current_commit(), tree.is_dirty())
        return _Observed(slug, bare, None, "offline", repo.current_commit(), False)

    def _inventory(self) -> tuple[dict[str, _Observed], list[Path]]:
        """Iterate ``bare_root/*``: managed bares keyed by slug, plus unstamped bares.

        Only *bare repositories* directly under the bare root are considered;
        anything else is ignored. A bare with no slug stamp is reported unmanaged.
        """
        repos: dict[str, _Observed] = {}
        unmanaged: list[Path] = []
        if not self.bare_root.is_dir():
            return repos, unmanaged
        for entry in sorted(self.bare_root.iterdir()):
            if not entry.is_dir() or not GitRepo(entry).is_bare_repository():
                continue
            observed = self._observe(entry)
            if observed is None:
                unmanaged.append(entry)
            elif observed.slug not in repos:
                repos[observed.slug] = observed
        return repos, unmanaged

    def _location_of(self, slug: str) -> _Observed | None:
        return self._inventory()[0].get(slug)

    def _on_disk_inventory(self) -> OnDiskInventory:
        """Project the raw observation onto the container's ``OnDiskInventory``.

        A materialized repo's location is its worktree (under the work root); an
        offline repo's location is its bare repo (under the bare root) — the two
        roots the wire converters resolve relative locations against.
        """
        repos, unmanaged = self._inventory()
        on_disk: dict[str, OnDiskRepo] = {}
        for slug, obs in repos.items():
            location = obs.worktree if obs.state == "materialized" else obs.bare
            on_disk[slug] = OnDiskRepo(
                slug=slug,
                location=location,  # type: ignore[arg-type]
                state=obs.state,  # type: ignore[arg-type]
                commit=obs.commit,
                dirty=obs.dirty,
            )
        return OnDiskInventory(repos=on_disk, unmanaged=unmanaged)

    def _v_scan(self, params: dict) -> dict:
        wire = wire_inventory_from_on_disk(
            self._on_disk_inventory(), self.work_root, self.bare_root
        )
        return wire.model_dump(mode="json")

    # -- source (acquire) -------------------------------------------------- #
    def _repo_def_path(self, slug: str) -> Path:
        return self.repos_dir / f"{slug}.json"

    def _sources(self, slug: str) -> dict[str, str]:
        data = json.loads(self._repo_def_path(slug).read_text())
        return dict(data.get("sources") or {})

    @staticmethod
    def _resolve(repo: GitRepo, ref: str) -> str | None:
        commit = repo.resolve_ref(ref)
        if commit is None and ref.startswith("refs/heads/"):
            commit = repo.resolve_ref("refs/remotes/origin/" + ref[len("refs/heads/") :])
        return commit

    def _v_acquire(self, params: dict) -> dict:
        slug = _valid_slug(params.get("slug"))
        refs = list(params.get("refs") or [])
        initial_branch = params.get("initial_branch")
        if not self._repo_def_path(slug).is_file():
            return _src(slug, "definition-missing", f"repo def for {slug!r} not found")

        sources = self._sources(slug)
        default = _default_source(sources)
        source_url = sources.get(default) if default is not None else None
        observed = self._location_of(slug)

        if observed is None:
            # Absent locally -> create the BARE repo under the bare root.
            if source_url is None:
                if refs:
                    return _src(
                        slug, "source-missing",
                        f"{slug!r} is absent and declares no sources",
                        unresolved=refs,
                    )
                init(
                    self.bare_root / slug,
                    profile=self.profile,
                    slug=slug,
                    initial_branch=initial_branch,
                )
                return _src(slug, "initialized", f"initialized {slug!r}")
            try:
                repo = clone(
                    source_url, self.bare_root / slug, profile=self.profile, slug=slug
                )
            except GitError as e:
                return _src(slug, "create-failed", f"clone {slug!r} failed: {e}")
            conform_remotes(repo, sources)
            # `clone --bare` creates no remote-tracking refs; fetch so an acquired repo
            # has the same ref layout however it got here.
            try:
                repo.fetch(ORIGIN)
            except GitError as e:
                return _src(slug, "fetch-failed", f"fetch {slug!r} failed: {e}")
            return self._verify(slug, repo, refs, "cloned", f"cloned {slug!r}")

        # Present (offline or materialized) -> conform remotes, then fetch.
        repo = GitRepo(observed.bare)
        conform_remotes(repo, sources)
        if source_url is not None:
            try:
                repo.fetch(ORIGIN)
            except GitError as e:
                return _src(slug, "fetch-failed", f"fetch {slug!r} failed: {e}")
        if source_url is None and not refs:
            return _src(slug, "ok", f"{slug!r} present, no source to fetch")
        return self._verify(slug, repo, refs, "fetched", f"fetched {slug!r}")

    def _verify(
        self, slug: str, repo: GitRepo, refs: list[str], ok_status: str, ok_summary: str
    ) -> dict:
        resolved = {}
        for ref in refs:
            commit = self._resolve(repo, ref)
            if commit is not None:
                resolved[ref] = commit
        unresolved = [r for r in refs if r not in resolved]
        if unresolved:
            return _src(
                slug, "ref-missing",
                f"{slug!r}: {len(unresolved)} ref(s) did not resolve",
                unresolved=unresolved, resolved=resolved,
            )
        return _src(slug, ok_status, ok_summary, resolved=resolved)

    # -- layout effects ---------------------------------------------------- #
    @staticmethod
    def _relative(location: Path, root: Path) -> str:
        return location.relative_to(root).as_posix()

    def _v_place(self, params: dict) -> dict:
        """Materialize ``slug`` as a worktree at ``location`` under the work root."""
        slug = _valid_slug(params.get("slug"))
        dst = _resolve_inside(self.work_root, params.get("location"))
        observed = self._location_of(slug)
        if observed is None:
            return _race(slug, "place", "repository vanished")
        location = self._relative(dst, self.work_root)
        if dst.exists():
            return _race(slug, "place", f"destination {location} is occupied")
        try:
            GitRepo(observed.bare).worktree_add(dst, "HEAD")
        except GitError as e:
            return _lay(slug, "failed", f"place {slug!r} failed: {e}")
        return _lay(slug, "placed", f"placed {slug!r} at {location}")

    def _v_relocate(self, params: dict) -> dict:
        """Move ``slug``'s worktree to a new ``location`` (native ``git worktree move``)."""
        slug = _valid_slug(params.get("slug"))
        dst = _resolve_inside(self.work_root, params.get("location"))
        observed = self._location_of(slug)
        if observed is None or observed.worktree is None:
            return _race(slug, "relocate", "worktree vanished")
        location = self._relative(dst, self.work_root)
        if dst.exists():
            return _race(slug, "relocate", f"destination {location} is occupied")
        # ``git worktree move`` does not create intermediate parents; make them.
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            GitRepo(observed.bare).worktree_move(observed.worktree, dst)
        except GitError as e:
            return _lay(slug, "failed", f"relocate {slug!r} failed: {e}")
        return _lay(slug, "relocated", f"relocated {slug!r} at {location}")

    def _v_retire(self, params: dict) -> dict:
        """Remove ``slug``'s worktree; the bare repo (and its commits) survive.

        Two guards, covering opposite halves of "retire never loses work": *uncommitted*
        changes are refused, and so is *committed* work no ref anchors — a detached
        HEAD's commits are held by the worktree alone, and the dirty check cannot see
        them because committing is what cleans the tree.
        """
        slug = _valid_slug(params.get("slug"))
        observed = self._location_of(slug)
        if observed is None or observed.worktree is None:
            return _race(slug, "retire", "worktree vanished")
        if observed.dirty:
            return _lay(
                slug, "blocked",
                f"{slug!r} has uncommitted changes; refusing to discard its worktree",
            )
        orphans = GitRepo(observed.worktree).unreachable_commit_count()
        if orphans:
            return _lay(
                slug, "blocked",
                f"{slug!r} has {orphans} commit(s) on no branch, tag or remote — removing its "
                f"worktree would leave them unreachable; put them on a branch or tag them first",
            )
        try:
            GitRepo(observed.bare).worktree_remove(observed.worktree)
        except GitError as e:
            return _lay(slug, "failed", f"retire {slug!r} failed: {e}")
        return _lay(slug, "retired", f"retired {slug!r} to offline")

    def _v_checkout(self, params: dict) -> dict:
        slug = _valid_slug(params.get("slug"))
        commit = _valid_hex_commit(params.get("commit"))
        observed = self._location_of(slug)
        if observed is None or observed.worktree is None:
            return _race(slug, "checkout", "worktree vanished")
        repo = GitRepo(observed.worktree)
        if repo.is_dirty():
            return _lay(slug, "blocked", f"{slug!r} became dirty between plan and execute")
        try:
            repo.checkout(commit)
        except GitError as e:
            return _lay(slug, "failed", f"checkout {commit[:12]} failed for {slug!r}: {e}")
        return _lay(slug, "checked-out", f"checked out {commit[:12]} for {slug!r}")

    # -- cluster layout document ------------------------------------------- #
    def _v_read_layout(self, params: dict) -> dict:
        """Read a cluster's layout doc — from its worktree, or the bare HEAD blob."""
        cluster_slug = _valid_slug(params.get("cluster_slug"))
        observed = self._location_of(cluster_slug)
        if observed is None:
            return {"exists": False, "layout": None}
        if observed.worktree is not None:
            path = observed.worktree / "product-cluster" / "default-layout.json"
            if not path.is_file():
                return {"exists": False, "layout": None}
            return {"exists": True, "layout": json.loads(path.read_text())}
        try:
            blob = GitRepo(observed.bare).show_head_blob(_LAYOUT_REL)
        except GitError:
            return {"exists": False, "layout": None}
        return {"exists": True, "layout": json.loads(blob)}

    def _v_write_layout(self, params: dict) -> dict:
        """Author a cluster's layout doc (requires a materialized worktree)."""
        cluster_slug = _valid_slug(params.get("cluster_slug"))
        observed = self._location_of(cluster_slug)
        if observed is None or observed.worktree is None:
            raise BrokerError(SERVER_ERROR, f"{cluster_slug!r} is not materialized")
        path = observed.worktree / "product-cluster" / "default-layout.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(params["layout"], indent=2) + "\n")
        return {"ok": True}

    # -- mono_config ------------------------------------------------------- #
    def _v_get_repo_defs(self, params: dict) -> dict:
        slugs = params.get("slugs")
        repos: dict[str, Any] = {}
        if not self.repos_dir.is_dir():
            return {"repos": repos}
        for path in sorted(self.repos_dir.glob("*.json")):
            stem = path.stem
            if slugs is not None and stem not in slugs:
                continue
            repos[stem] = json.loads(path.read_text())
        return {"repos": repos}

    def _v_save_repo_def(self, params: dict) -> dict:
        repo = params["repo"]
        slug = _valid_slug(repo.get("slug"))
        self.repos_dir.mkdir(parents=True, exist_ok=True)
        (self.repos_dir / f"{slug}.json").write_text(json.dumps(repo, indent=2) + "\n")
        return {"ok": True}

    def _v_purge_repo_def(self, params: dict) -> dict:
        slug = _valid_slug(params.get("slug"))
        path = self._repo_def_path(slug)
        try:
            path.unlink()
        except FileNotFoundError as e:
            raise BrokerError(SERVER_ERROR, f"repo {slug!r} not found") from e
        return {"ok": True}

    def _v_get_system(self, params: dict) -> dict:
        path = self.config_dir / "system.json"
        if not path.is_file():
            return {"system": None}
        return {"system": json.loads(path.read_text())}

    def _v_save_system(self, params: dict) -> dict:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        (self.config_dir / "system.json").write_text(
            json.dumps(params["system"], indent=2) + "\n"
        )
        return {"ok": True}

    # -- remote stamp (real `git remote add/set-url` on the bare repo) ------ #
    def _v_set_remote(self, params: dict) -> dict:
        # Validate at the boundary (slug shape, remote-name shape, https url)
        # before touching disk, mirroring the real shim's ``set_remote`` verb.
        slug = _valid_slug(params.get("slug"))
        name = _valid_remote_name(params.get("name"))
        url = _sanitize_remote_url(params.get("url"))
        observed = self._location_of(slug)
        if observed is None:
            raise BrokerError(SERVER_ERROR, f"{slug!r} is not on disk")
        GitRepo(observed.bare).set_remote(name, url)
        return {"ok": True}

    # -- remote probe (canned; no real network) ---------------------------- #
    def _v_remote_default_branch(self, params: dict) -> dict:
        url = _sanitize_remote_url(params.get("url"))
        branch = self.remote_default_branches.get(url, self.default_remote_branch)
        return {"branch": branch}


# --------------------------------------------------------------------------- #
# Small JSON-result helpers
# --------------------------------------------------------------------------- #
def _src(
    slug: str,
    status: str,
    summary: str,
    *,
    unresolved: list[str] | None = None,
    resolved: dict[str, str] | None = None,
) -> dict:
    return {
        "status": status,
        "summary": summary,
        "unresolved_refs": unresolved or [],
        "resolved": resolved or {},
    }


def _lay(slug: str, status: str, summary: str) -> dict:
    return {"status": status, "summary": summary}


def _race(slug: str, verb: str, detail: str) -> dict:
    return {"status": "race-aborted", "summary": f"{verb} aborted for {slug!r}: {detail}"}

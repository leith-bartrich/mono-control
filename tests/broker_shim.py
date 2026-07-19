"""An in-process fake broker that performs real git + filesystem effects.

Step 2 relocates the container's git/FS/config effects to a host-side broker
(a different repo). The container is now a pure JSON-RPC client; this module is
the test-side stand-in for that broker — the same effect logic (git clone / init
/ fetch, the atomic move, the scanner walk, the repo-def / system / layout file
IO) reassembled behind a ``call(method, params)`` dispatcher that returns plain
JSON. Because it does the *real* work on real temp directories, the end-to-end
CLI tests keep asserting real on-disk state; only the wiring (inject this broker
via ``ctx.obj`` / ``RepoStore(broker)``) changes.

It inherits :class:`TypedBrokerMixin`, so callers use the same typed verbs
(``scan`` / ``acquire`` / ``place`` / …) they use against the real client.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable, Iterator

from mono_control.broker import (
    BrokerError,
    TypedBrokerMixin,
    wire_inventory_from_on_disk,
)
from mono_control.host_platform import FsProfile
from mono_control.on_disk import OnDiskInventory, OnDiskRepo

# A concrete profile for tests (a Linux-ish host filesystem). The real broker
# derives this from ``MONO_CONTROL_HOST_PLATFORM``; here it is fixed.
PROFILE = FsProfile(filemode=True, symlinks=True, ignorecase=False)

_SLUG_KEY = "mono-control.slug"
_PROFILE_KEYS = (
    ("core.filemode", "filemode"),
    ("core.symlinks", "symlinks"),
    ("core.ignorecase", "ignorecase"),
)


# --------------------------------------------------------------------------- #
# Minimal git layer (relocated from the deleted container ``git`` package)
# --------------------------------------------------------------------------- #
class GitError(Exception):
    """A git operation failed (missing binary or non-zero exit)."""


class UnmanagedCheckoutError(GitError):
    """A checkout has no ``mono-control.slug`` stamp (foreign / unmanaged)."""


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
    """A handle on a git working tree (the inspection/action verbs tests use)."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _git(self, *args: str) -> str:
        return run_git(list(args), cwd=self.path)

    def current_commit(self) -> str | None:
        return self.resolve_ref("HEAD")

    def resolve_ref(self, ref: str) -> str | None:
        try:
            return self._git("rev-parse", "--verify", f"{ref}^{{commit}}")
        except GitError:
            return None

    def config_get(self, key: str) -> str:
        return self._git("config", "--get", key)

    def slug(self) -> str:
        try:
            return self.config_get(_SLUG_KEY)
        except GitError as e:
            raise UnmanagedCheckoutError(f"{self.path} has no {_SLUG_KEY!r} stamp") from e

    def is_dirty(self) -> bool:
        return bool(self._git("status", "--porcelain"))

    def fetch(self, remote: str, refs: Iterable[str] | None = None) -> None:
        args = ["fetch", remote]
        if refs is not None:
            args.extend(refs)
        self._git(*args)

    def checkout(self, ref: str) -> None:
        self._git("checkout", ref)

    def _apply_profile(self, profile: FsProfile) -> None:
        for key, attr in _PROFILE_KEYS:
            self._git("config", key, "true" if getattr(profile, attr) else "false")

    def _apply_slug(self, slug: str) -> None:
        self._git("config", _SLUG_KEY, slug)


def clone(url: str | Path, dest: Path | str, *, profile: FsProfile, slug: str) -> GitRepo:
    """Clone ``url`` into ``dest`` and stamp ``profile`` + ``slug`` before checkout."""
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
    """Initialize a new empty repo at ``path`` and stamp ``profile`` + ``slug``."""
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


# --------------------------------------------------------------------------- #
# Scanner walk + atomic move (relocated from scanner.py / execute.py)
# --------------------------------------------------------------------------- #
def _find_checkouts(root: Path) -> Iterator[Path]:
    if not root.is_dir():
        return
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        if (current / ".git").exists():
            yield current
            continue
        try:
            stack.extend(p for p in current.iterdir() if p.is_dir())
        except PermissionError:  # pragma: no cover
            continue


def _move(src: Path, dst: Path) -> None:
    """Atomic move with a cross-device copy fallback; raises ``OSError`` families."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise FileExistsError(dst)
    try:
        os.rename(src, dst)
        return
    except OSError as e:
        if e.errno not in (errno.EXDEV,):
            raise
    tmp = dst.parent / f".{dst.name}.tmp-move"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(src, tmp, symlinks=True)
    os.rename(tmp, dst)
    shutil.rmtree(src)


# --------------------------------------------------------------------------- #
# The broker itself
# --------------------------------------------------------------------------- #
class ShimBroker(TypedBrokerMixin):
    """A stateful, real-effect broker over ``(config_dir, workspace, offline)`` dirs."""

    def __init__(
        self,
        config_dir: Path,
        workspace_root: Path,
        offline_root: Path,
        *,
        profile: FsProfile = PROFILE,
    ) -> None:
        self.config_dir = Path(config_dir)
        self.workspace_root = Path(workspace_root)
        self.offline_root = Path(offline_root)
        self.repos_dir = self.config_dir / "repos"
        self.profile = profile
        self.calls: list[tuple[str, dict | None]] = []

    # -- dispatch ---------------------------------------------------------- #
    def call(self, method: str, params: dict | None = None) -> Any:
        self.calls.append((method, params))
        handler = getattr(self, f"_v_{method}", None)
        if handler is None:
            raise BrokerError(-32601, f"method not found: {method!r}")
        return handler(params or {})

    # -- observation ------------------------------------------------------- #
    def _observe(self, checkout: Path, state: str) -> OnDiskRepo | None:
        repo = GitRepo(checkout)
        try:
            slug = repo.slug()
        except UnmanagedCheckoutError:
            return None
        return OnDiskRepo(
            slug=slug,
            location=checkout,
            state=state,  # type: ignore[arg-type]
            commit=repo.current_commit(),
            dirty=repo.is_dirty(),
        )

    def _inventory(self) -> OnDiskInventory:
        repos: dict[str, OnDiskRepo] = {}
        unmanaged: list[Path] = []
        for root, state in (
            (self.workspace_root, "materialized"),
            (self.offline_root, "offline"),
        ):
            for checkout in _find_checkouts(root):
                observed = self._observe(checkout, state)
                if observed is None:
                    unmanaged.append(checkout)
                elif observed.slug not in repos:
                    repos[observed.slug] = observed
        return OnDiskInventory(repos=repos, unmanaged=unmanaged)

    def _location_of(self, slug: str) -> OnDiskRepo | None:
        return self._inventory().repos.get(slug)

    def _v_scan(self, params: dict) -> dict:
        wire = wire_inventory_from_on_disk(
            self._inventory(), self.workspace_root, self.offline_root
        )
        return wire.model_dump(mode="json")

    # -- source (acquire) -------------------------------------------------- #
    def _repo_def_path(self, slug: str) -> Path:
        return self.repos_dir / f"{slug}.json"

    def _source_url(self, slug: str) -> str | None:
        data = json.loads(self._repo_def_path(slug).read_text())
        sources = data.get("sources") or {}
        return next(iter(sources.values())) if sources else None

    @staticmethod
    def _resolve(repo: GitRepo, ref: str) -> str | None:
        commit = repo.resolve_ref(ref)
        if commit is None and ref.startswith("refs/heads/"):
            commit = repo.resolve_ref("refs/remotes/origin/" + ref[len("refs/heads/") :])
        return commit

    def _v_acquire(self, params: dict) -> dict:
        slug = params["slug"]
        refs = list(params.get("refs") or [])
        initial_branch = params.get("initial_branch")
        if not self._repo_def_path(slug).is_file():
            return _src(slug, "definition-missing", f"repo def for {slug!r} not found")

        source_url = self._source_url(slug)
        observed = self._location_of(slug)

        if observed is None:
            if source_url is None:
                if refs:
                    return _src(
                        slug, "source-missing",
                        f"{slug!r} is absent and declares no sources",
                        unresolved=refs,
                    )
                init(
                    self.offline_root / slug,
                    profile=self.profile,
                    slug=slug,
                    initial_branch=initial_branch,
                )
                return _src(slug, "initialized", f"initialized {slug!r}")
            try:
                repo = clone(
                    source_url, self.offline_root / slug, profile=self.profile, slug=slug
                )
            except GitError as e:
                return _src(slug, "create-failed", f"clone {slug!r} failed: {e}")
            return self._verify(slug, repo, refs, "cloned", f"cloned {slug!r}")

        repo = GitRepo(observed.location)
        if source_url is not None:
            try:
                repo.fetch("origin")
            except GitError:
                try:
                    repo.fetch(source_url)
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
    def _v_place(self, params: dict) -> dict:
        return self._move_into_workspace(params, "placed", "place")

    def _v_relocate(self, params: dict) -> dict:
        return self._move_into_workspace(params, "relocated", "relocate")

    def _move_into_workspace(self, params: dict, ok_status: str, verb: str) -> dict:
        slug = params["slug"]
        location = params["location"]
        observed = self._location_of(slug)
        if observed is None:
            return _race(slug, verb, "checkout vanished")
        dst = self.workspace_root / location
        try:
            _move(observed.location, dst)
        except FileExistsError:
            return _race(slug, verb, f"destination {location} is occupied")
        except OSError as e:
            return _lay(slug, "failed", f"{verb} {slug!r} failed: {e}")
        return _lay(slug, ok_status, f"{verb}d {slug!r} at {location}")

    def _v_retire(self, params: dict) -> dict:
        slug = params["slug"]
        observed = self._location_of(slug)
        if observed is None:
            return _race(slug, "retire", "checkout vanished")
        dst = self.offline_root / slug
        if dst.exists():
            return _lay(slug, "blocked", f"offline holding spot {slug} already occupied")
        try:
            _move(observed.location, dst)
        except FileExistsError:
            return _race(slug, "retire", "offline spot occupied")
        except OSError as e:
            return _lay(slug, "failed", f"retire {slug!r} failed: {e}")
        return _lay(slug, "retired", f"retired {slug!r} to offline")

    def _v_checkout(self, params: dict) -> dict:
        slug = params["slug"]
        commit = params["commit"]
        observed = self._location_of(slug)
        if observed is None:
            return _race(slug, "checkout", "checkout vanished")
        repo = GitRepo(observed.location)
        if repo.is_dirty():
            return _lay(slug, "blocked", f"{slug!r} became dirty between plan and execute")
        try:
            repo.checkout(commit)
        except GitError as e:
            return _lay(slug, "failed", f"checkout {commit[:12]} failed for {slug!r}: {e}")
        return _lay(slug, "checked-out", f"checked out {commit[:12]} for {slug!r}")

    # -- cluster layout document ------------------------------------------- #
    def _layout_path(self, cluster_slug: str) -> Path | None:
        observed = self._location_of(cluster_slug)
        if observed is None:
            return None
        return observed.location / "product-cluster" / "default-layout.json"

    def _v_read_layout(self, params: dict) -> dict:
        path = self._layout_path(params["cluster_slug"])
        if path is None or not path.is_file():
            return {"exists": False, "layout": None}
        return {"exists": True, "layout": json.loads(path.read_text())}

    def _v_write_layout(self, params: dict) -> dict:
        path = self._layout_path(params["cluster_slug"])
        if path is None:
            raise BrokerError(-32000, f"{params['cluster_slug']!r} is not on disk")
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
        self.repos_dir.mkdir(parents=True, exist_ok=True)
        (self.repos_dir / f"{repo['slug']}.json").write_text(
            json.dumps(repo, indent=2) + "\n"
        )
        return {"ok": True}

    def _v_purge_repo_def(self, params: dict) -> dict:
        path = self._repo_def_path(params["slug"])
        try:
            path.unlink()
        except FileNotFoundError as e:
            raise BrokerError(-32000, f"repo {params['slug']!r} not found") from e
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

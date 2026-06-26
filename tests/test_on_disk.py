from pathlib import Path

import pytest

from mono_control.git import clone, init
from mono_control.git.runner import run_git
from mono_control.host_platform import FsProfile
from mono_control.on_disk import DuplicateSlugError, OnDiskInventory, scan

PROFILE = FsProfile(filemode=True, symlinks=True, ignorecase=False)


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")


def _origin(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", str(path)])
    (path / "README.md").write_text("hello\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "initial"], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path)


def test_scan_empty_roots(tmp_path):
    inv = scan(tmp_path / "absent-workspace", tmp_path / "absent-offline")
    assert inv == OnDiskInventory()


def test_scan_identifies_materialized_and_offline(tmp_path):
    origin = tmp_path / "origin"
    head = _origin(origin)

    workspace = tmp_path / "ws"
    offline = tmp_path / "off"
    workspace.mkdir()
    offline.mkdir()

    clone(origin, workspace / "alpha", profile=PROFILE, slug="alpha")
    clone(origin, offline / "beta", profile=PROFILE, slug="beta")

    inv = scan(workspace, offline)
    assert set(inv.repos) == {"alpha", "beta"}
    assert inv.repos["alpha"].state == "materialized"
    assert inv.repos["alpha"].commit == head
    assert inv.repos["alpha"].location == workspace / "alpha"
    assert inv.repos["beta"].state == "offline"
    assert inv.unmanaged == []


def test_scan_reports_unmanaged_checkout(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    raw = workspace / "stranger"
    raw.mkdir()
    run_git(["init", str(raw)])  # no stamp applied

    inv = scan(workspace, tmp_path / "missing-offline")
    assert inv.repos == {}
    assert inv.unmanaged == [raw]


def test_scan_descends_into_nested_subdirs(tmp_path):
    origin = tmp_path / "origin"
    _origin(origin)

    workspace = tmp_path / "ws"
    nested = workspace / "products"
    nested.mkdir(parents=True)
    clone(origin, nested / "cluster", profile=PROFILE, slug="cluster")

    inv = scan(workspace, tmp_path / "off")
    assert "cluster" in inv.repos
    assert inv.repos["cluster"].location == nested / "cluster"


def test_scan_does_not_descend_into_a_checkout(tmp_path):
    """A nested .git dir inside a managed checkout must not be re-observed."""
    origin = tmp_path / "origin"
    _origin(origin)

    workspace = tmp_path / "ws"
    workspace.mkdir()
    repo = clone(origin, workspace / "alpha", profile=PROFILE, slug="alpha")
    # Plant a directory shaped like a checkout *inside* alpha; the scanner must
    # stop at alpha rather than recursing.
    submodule_like = repo.path / "vendor" / "stranger"
    submodule_like.mkdir(parents=True)
    run_git(["init", str(submodule_like)])

    inv = scan(workspace, tmp_path / "off")
    assert set(inv.repos) == {"alpha"}
    assert inv.unmanaged == []  # stranger was never visited


def test_duplicate_slug_raises(tmp_path):
    origin = tmp_path / "origin"
    _origin(origin)
    workspace = tmp_path / "ws"
    offline = tmp_path / "off"
    workspace.mkdir()
    offline.mkdir()

    clone(origin, workspace / "place", profile=PROFILE, slug="dup")
    clone(origin, offline / "dup", profile=PROFILE, slug="dup")

    with pytest.raises(DuplicateSlugError):
        scan(workspace, offline)


def test_scan_reports_dirty(tmp_path):
    origin = tmp_path / "origin"
    _origin(origin)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    repo = clone(origin, workspace / "alpha", profile=PROFILE, slug="alpha")

    (repo.path / "README.md").write_text("changed\n")
    inv = scan(workspace, tmp_path / "off")
    assert inv.repos["alpha"].dirty is True


def test_init_only_repo_has_no_commit(tmp_path):
    offline = tmp_path / "off"
    offline.mkdir()
    init(offline / "fresh", profile=PROFILE, slug="fresh")
    inv = scan(tmp_path / "ws", offline)
    assert inv.repos["fresh"].commit is None

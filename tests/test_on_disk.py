"""Scanner: the container rehydrates the broker's ``scan`` into an OnDiskInventory.

The observation itself runs broker-side (real bare-repo + worktree walk); the shim
performs it on real temp dirs, so these assert the container's reconstruction of
absolute paths + state from the wire form. Physical model: a managed **bare** repo
lives under the bare root; a ``git worktree add`` under the work root makes it
*materialized*, its absence leaves it *offline*.
"""

from pathlib import Path

from broker_shim import ShimBroker, add_worktree, clone, init, run_git, GitRepo, PROFILE
from mono_control.on_disk import OnDiskInventory, scan


def _broker(tmp_path):
    return ShimBroker(tmp_path / "config", tmp_path / "ws", tmp_path / "off")


def _origin(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", str(path)])
    (path / "README.md").write_text("hello\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "initial"], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path)


def test_scan_empty_roots(tmp_path):
    broker = _broker(tmp_path)
    inv = scan(broker, tmp_path / "ws", tmp_path / "off")
    assert inv == OnDiskInventory()


def test_scan_identifies_materialized_and_offline(tmp_path):
    origin = tmp_path / "origin"
    head = _origin(origin)
    ws, off = tmp_path / "ws", tmp_path / "off"
    ws.mkdir()
    off.mkdir()
    # alpha: a bare repo with a worktree -> materialized (located at the worktree).
    clone(origin, off / "alpha", profile=PROFILE, slug="alpha")
    add_worktree(off / "alpha", ws / "alpha")
    # beta: a bare repo with no worktree -> offline (located at the bare repo).
    clone(origin, off / "beta", profile=PROFILE, slug="beta")

    inv = scan(_broker(tmp_path), ws, off)
    assert set(inv.repos) == {"alpha", "beta"}
    assert inv.repos["alpha"].state == "materialized"
    assert inv.repos["alpha"].commit == head
    assert inv.repos["alpha"].location == ws / "alpha"
    assert inv.repos["beta"].state == "offline"
    assert inv.repos["beta"].location == off / "beta"
    assert inv.unmanaged == []


def test_scan_reports_unmanaged_bare(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    off = tmp_path / "off"
    off.mkdir()
    raw = off / "stranger"
    run_git(["init", "--bare", str(raw)])  # a bare repo with no slug stamp

    inv = scan(_broker(tmp_path), ws, off)
    assert inv.repos == {}
    assert inv.unmanaged == [raw]


def test_scan_finds_nested_worktree_location(tmp_path):
    origin = tmp_path / "origin"
    _origin(origin)
    ws = tmp_path / "ws"
    off = tmp_path / "off"
    ws.mkdir()
    off.mkdir()
    clone(origin, off / "cluster", profile=PROFILE, slug="cluster")
    add_worktree(off / "cluster", ws / "products" / "cluster")

    inv = scan(_broker(tmp_path), ws, off)
    assert "cluster" in inv.repos
    assert inv.repos["cluster"].location == ws / "products" / "cluster"


def test_scan_ignores_repos_inside_a_worktree(tmp_path):
    """scan considers only bare repos directly under the bare root — never trees
    vendored inside a worktree under the work root."""
    origin = tmp_path / "origin"
    _origin(origin)
    ws = tmp_path / "ws"
    off = tmp_path / "off"
    ws.mkdir()
    off.mkdir()
    clone(origin, off / "alpha", profile=PROFILE, slug="alpha")
    repo = add_worktree(off / "alpha", ws / "alpha")
    submodule_like = repo.path / "vendor" / "stranger"
    submodule_like.mkdir(parents=True)
    run_git(["init", str(submodule_like)])

    inv = scan(_broker(tmp_path), ws, off)
    assert set(inv.repos) == {"alpha"}
    assert inv.unmanaged == []


def test_scan_reports_dirty(tmp_path):
    origin = tmp_path / "origin"
    _origin(origin)
    ws = tmp_path / "ws"
    off = tmp_path / "off"
    ws.mkdir()
    off.mkdir()
    clone(origin, off / "alpha", profile=PROFILE, slug="alpha")
    repo = add_worktree(off / "alpha", ws / "alpha")
    (repo.path / "README.md").write_text("changed\n")

    inv = scan(_broker(tmp_path), ws, off)
    assert inv.repos["alpha"].dirty is True


def test_init_only_bare_has_no_commit(tmp_path):
    off = tmp_path / "off"
    off.mkdir()
    (tmp_path / "ws").mkdir()
    init(off / "fresh", profile=PROFILE, slug="fresh")  # empty bare repo, no worktree
    inv = scan(_broker(tmp_path), tmp_path / "ws", off)
    assert inv.repos["fresh"].state == "offline"
    assert inv.repos["fresh"].commit is None
    assert GitRepo(off / "fresh").is_bare_repository()

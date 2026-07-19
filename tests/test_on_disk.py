"""Scanner: the container rehydrates the broker's ``scan`` into an OnDiskInventory.

The observation itself runs broker-side (real git walk); the shim performs it on
real temp dirs, so these assert the container's reconstruction of absolute paths
+ state from the wire form.
"""

from pathlib import Path

from broker_shim import ShimBroker, clone, init, run_git, PROFILE
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
    clone(origin, ws / "alpha", profile=PROFILE, slug="alpha")
    clone(origin, off / "beta", profile=PROFILE, slug="beta")

    inv = scan(_broker(tmp_path), ws, off)
    assert set(inv.repos) == {"alpha", "beta"}
    assert inv.repos["alpha"].state == "materialized"
    assert inv.repos["alpha"].commit == head
    assert inv.repos["alpha"].location == ws / "alpha"
    assert inv.repos["beta"].state == "offline"
    assert inv.unmanaged == []


def test_scan_reports_unmanaged_checkout(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    raw = ws / "stranger"
    raw.mkdir()
    run_git(["init", str(raw)])  # no stamp applied
    (tmp_path / "off").mkdir()

    inv = scan(_broker(tmp_path), ws, tmp_path / "off")
    assert inv.repos == {}
    assert inv.unmanaged == [raw]


def test_scan_descends_into_nested_subdirs(tmp_path):
    origin = tmp_path / "origin"
    _origin(origin)
    ws = tmp_path / "ws"
    nested = ws / "products"
    nested.mkdir(parents=True)
    (tmp_path / "off").mkdir()
    clone(origin, nested / "cluster", profile=PROFILE, slug="cluster")

    inv = scan(_broker(tmp_path), ws, tmp_path / "off")
    assert "cluster" in inv.repos
    assert inv.repos["cluster"].location == nested / "cluster"


def test_scan_does_not_descend_into_a_checkout(tmp_path):
    origin = tmp_path / "origin"
    _origin(origin)
    ws = tmp_path / "ws"
    ws.mkdir()
    (tmp_path / "off").mkdir()
    repo = clone(origin, ws / "alpha", profile=PROFILE, slug="alpha")
    submodule_like = repo.path / "vendor" / "stranger"
    submodule_like.mkdir(parents=True)
    run_git(["init", str(submodule_like)])

    inv = scan(_broker(tmp_path), ws, tmp_path / "off")
    assert set(inv.repos) == {"alpha"}
    assert inv.unmanaged == []


def test_scan_reports_dirty(tmp_path):
    origin = tmp_path / "origin"
    _origin(origin)
    ws = tmp_path / "ws"
    ws.mkdir()
    (tmp_path / "off").mkdir()
    repo = clone(origin, ws / "alpha", profile=PROFILE, slug="alpha")
    (repo.path / "README.md").write_text("changed\n")

    inv = scan(_broker(tmp_path), ws, tmp_path / "off")
    assert inv.repos["alpha"].dirty is True


def test_init_only_repo_has_no_commit(tmp_path):
    off = tmp_path / "off"
    off.mkdir()
    (tmp_path / "ws").mkdir()
    init(off / "fresh", profile=PROFILE, slug="fresh")
    inv = scan(_broker(tmp_path), tmp_path / "ws", off)
    assert inv.repos["fresh"].commit is None

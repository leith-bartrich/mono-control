"""Tests for `product-cluster conform clear / swap`."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mono_control import paths
from mono_control.aspects.product_cluster.cli import app as cluster_app
from mono_control.config import Repo, RepoStore
from mono_control.git import GitRepo, clone
from mono_control.git.runner import run_git
from mono_control.host_platform import FsProfile

runner = CliRunner()
PROFILE = FsProfile(filemode=True, symlinks=True, ignorecase=False)


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "test@example.com")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    ws = tmp_path / "ws"
    off = tmp_path / "off"
    ws.mkdir()
    off.mkdir()
    monkeypatch.setattr(paths, "REPOS_DIR", ws)
    monkeypatch.setattr(paths, "OFFLINE_DIR", off)
    return config_dir, ws, off


def _invoke(args, *, config_dir: Path):
    return runner.invoke(cluster_app, args, obj=config_dir)


def _origin(path: Path, branch: str = "main") -> str:
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--initial-branch", branch, str(path)])
    (path / "README.md").write_text("hello\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "initial"], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path)


def _cluster_origin(path: Path, members: dict, branch: str = "main") -> str:
    """A cluster origin carrying a committed product-cluster/default-layout.json."""
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--initial-branch", branch, str(path)])
    layout_dir = path / "product-cluster"
    layout_dir.mkdir()
    (layout_dir / "default-layout.json").write_text(
        json.dumps({"version": 1, "members": members}, indent=2) + "\n"
    )
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "layout"], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path)


def _seed(config_dir: Path, slug: str, origin: Path, *, aspects=None) -> None:
    RepoStore.from_config_dir(config_dir).create(
        Repo(
            version=1,
            slug=slug,
            name=slug,
            sources={"origin": str(origin)},
            aspects=aspects or set(),
        )
    )


def test_conform_swap_materializes_cluster_and_members(workspace, tmp_path):
    config_dir, ws, _ = workspace
    _origin(tmp_path / "m1o")
    _origin(tmp_path / "m2o")
    _cluster_origin(
        tmp_path / "clo",
        {
            "m1": {"location": "src/m1", "role": "dev"},
            "m2": {"location": "libs/m2", "role": "dep"},
        },
    )
    _seed(config_dir, "m1", tmp_path / "m1o")
    _seed(config_dir, "m2", tmp_path / "m2o")
    _seed(config_dir, "cluster1", tmp_path / "clo", aspects={"product-cluster"})

    res = _invoke(["conform", "swap", "cluster1"], config_dir=config_dir)
    assert res.exit_code == 0, res.output
    assert (ws / "products" / "cluster1" / ".git").is_dir()
    assert GitRepo(ws / "src" / "m1").slug() == "m1"
    assert GitRepo(ws / "libs" / "m2").slug() == "m2"


def test_conform_swap_pre_clears_extras(workspace, tmp_path):
    config_dir, ws, off = workspace
    # an extra repo already materialized, not part of the cluster layout
    _origin(tmp_path / "extrao")
    clone(tmp_path / "extrao", ws / "extra", profile=PROFILE, slug="extra")
    _seed(config_dir, "extra", tmp_path / "extrao")

    _cluster_origin(tmp_path / "clo", {})  # empty layout: just the cluster
    _seed(config_dir, "cluster1", tmp_path / "clo", aspects={"product-cluster"})

    res = _invoke(["conform", "swap", "cluster1"], config_dir=config_dir)
    assert res.exit_code == 0, res.output
    assert (ws / "products" / "cluster1" / ".git").is_dir()
    # extra retired to offline (non-destructive), gone from the workspace
    assert not (ws / "extra").exists()
    assert (off / "extra" / ".git").is_dir()


def test_conform_clear_retires_all(workspace, tmp_path):
    config_dir, ws, off = workspace
    _origin(tmp_path / "ao")
    clone(tmp_path / "ao", ws / "alpha", profile=PROFILE, slug="alpha")
    _seed(config_dir, "alpha", tmp_path / "ao")

    res = _invoke(["conform", "clear"], config_dir=config_dir)
    assert res.exit_code == 0, res.output
    assert not (ws / "alpha").exists()
    assert (off / "alpha" / ".git").is_dir()


def test_conform_clear_is_nondestructive_for_dirty(workspace, tmp_path):
    """Retire moves to offline (preserving work), so a dirty repo clears safely."""
    config_dir, ws, off = workspace
    _origin(tmp_path / "ao")
    clone(tmp_path / "ao", ws / "alpha", profile=PROFILE, slug="alpha")
    _seed(config_dir, "alpha", tmp_path / "ao")
    (ws / "alpha" / "README.md").write_text("uncommitted change\n")  # dirty (tracked)

    res = _invoke(["conform", "clear"], config_dir=config_dir)
    assert res.exit_code == 0, res.output
    assert not (ws / "alpha").exists()
    assert (off / "alpha" / ".git").is_dir()
    # the uncommitted change rode along to offline
    assert (off / "alpha" / "README.md").read_text() == "uncommitted change\n"


def test_conform_swap_requires_aspect(workspace, tmp_path):
    config_dir, _, _ = workspace
    RepoStore.from_config_dir(config_dir).create(
        Repo(version=1, slug="plain", name="plain")
    )
    res = _invoke(["conform", "swap", "plain"], config_dir=config_dir)
    assert res.exit_code != 0
    assert "does not declare" in res.output


def test_conform_clear_blocks_dirty_cluster(workspace, tmp_path):
    """A dirty product-cluster blocks clear (its committed state anchors reproducibility)."""
    config_dir, ws, _ = workspace
    _origin(tmp_path / "pco")
    _seed(config_dir, "pc1", tmp_path / "pco", aspects={"product-cluster"})
    assert _invoke(["mat", "moveto", "pc1"], config_dir=config_dir).exit_code == 0
    (ws / "products" / "pc1" / "README.md").write_text("uncommitted\n")  # dirty cluster

    res = _invoke(["conform", "clear"], config_dir=config_dir)
    assert res.exit_code != 0
    assert "pc1" in res.output
    assert (ws / "products" / "pc1" / ".git").is_dir()  # untouched


def test_conform_swap_blocks_dirty_cluster(workspace, tmp_path):
    config_dir, ws, _ = workspace
    _origin(tmp_path / "ao")
    _seed(config_dir, "pca", tmp_path / "ao", aspects={"product-cluster"})
    assert _invoke(["mat", "moveto", "pca"], config_dir=config_dir).exit_code == 0
    (ws / "products" / "pca" / "README.md").write_text("dirty\n")

    _cluster_origin(tmp_path / "bo", {})
    _seed(config_dir, "pcb", tmp_path / "bo", aspects={"product-cluster"})

    res = _invoke(["conform", "swap", "pcb"], config_dir=config_dir)
    assert res.exit_code != 0
    assert "pca" in res.output
    assert (ws / "products" / "pca" / ".git").is_dir()  # not torn down


def test_conform_swap_unreachable_cluster_leaves_workspace(workspace, tmp_path):
    """Sourcing the cluster first means an unreachable one fails before any clear."""
    config_dir, ws, _ = workspace
    _origin(tmp_path / "ao")
    clone(tmp_path / "ao", ws / "alpha", profile=PROFILE, slug="alpha")
    _seed(config_dir, "alpha", tmp_path / "ao")
    # cluster whose source path does not exist → acquire fails up front
    _seed(config_dir, "pcbad", tmp_path / "missing", aspects={"product-cluster"})

    res = _invoke(["conform", "swap", "pcbad"], config_dir=config_dir)
    assert res.exit_code != 0
    assert (ws / "alpha" / ".git").is_dir()  # workspace NOT cleared


def test_relayout_applies_layout_delta(workspace, tmp_path):
    """relayout pulls in missing members, retires extras, leaves the cluster in place."""
    config_dir, ws, off = workspace
    _origin(tmp_path / "m1o")
    _origin(tmp_path / "m2o")
    _cluster_origin(
        tmp_path / "clo",
        {
            "m1": {"location": "src/m1", "role": "dev"},
            "m2": {"location": "libs/m2", "role": "dep"},
        },
    )
    _seed(config_dir, "m1", tmp_path / "m1o")
    _seed(config_dir, "m2", tmp_path / "m2o")
    _seed(config_dir, "cluster1", tmp_path / "clo", aspects={"product-cluster"})
    # materialize the cluster; its committed layout rides along
    assert _invoke(["mat", "moveto", "cluster1"], config_dir=config_dir).exit_code == 0
    # a pre-existing extra repo not in the layout
    _origin(tmp_path / "extrao")
    clone(tmp_path / "extrao", ws / "extra", profile=PROFILE, slug="extra")
    _seed(config_dir, "extra", tmp_path / "extrao")

    res = _invoke(["conform", "relayout", "cluster1"], config_dir=config_dir)
    assert res.exit_code == 0, res.output
    assert (ws / "products" / "cluster1" / ".git").is_dir()  # cluster untouched
    assert GitRepo(ws / "src" / "m1").slug() == "m1"          # members pulled in
    assert GitRepo(ws / "libs" / "m2").slug() == "m2"
    assert not (ws / "extra").exists()                        # extra retired
    assert (off / "extra" / ".git").is_dir()


def test_relayout_allows_dirty_target_cluster(workspace, tmp_path):
    """relayout keeps the target cluster, so its dirtiness must NOT gate (unlike clear/swap)."""
    config_dir, ws, _ = workspace
    _origin(tmp_path / "m1o")
    _cluster_origin(tmp_path / "clo", {"m1": {"location": "src/m1", "role": "dev"}})
    _seed(config_dir, "m1", tmp_path / "m1o")
    _seed(config_dir, "cluster1", tmp_path / "clo", aspects={"product-cluster"})
    assert _invoke(["mat", "moveto", "cluster1"], config_dir=config_dir).exit_code == 0
    (ws / "products" / "cluster1" / "README.md").write_text("uncommitted\n")  # dirty cluster

    res = _invoke(["conform", "relayout", "cluster1"], config_dir=config_dir)
    assert res.exit_code == 0, res.output  # not gated — cluster stays placed
    assert (ws / "products" / "cluster1" / ".git").is_dir()
    assert GitRepo(ws / "src" / "m1").slug() == "m1"


def test_relayout_implied_cluster(workspace, tmp_path):
    config_dir, ws, _ = workspace
    _origin(tmp_path / "m1o")
    _cluster_origin(tmp_path / "clo", {"m1": {"location": "m1", "role": "dev"}})
    _seed(config_dir, "m1", tmp_path / "m1o")
    _seed(config_dir, "cluster1", tmp_path / "clo", aspects={"product-cluster"})
    assert _invoke(["mat", "moveto", "cluster1"], config_dir=config_dir).exit_code == 0

    res = _invoke(["conform", "relayout"], config_dir=config_dir)  # no arg → sole cluster
    assert res.exit_code == 0, res.output
    assert GitRepo(ws / "m1").slug() == "m1"


def test_conform_clear_allow_dirty_override(workspace, tmp_path):
    config_dir, ws, off = workspace
    _origin(tmp_path / "pco")
    _seed(config_dir, "pc1", tmp_path / "pco", aspects={"product-cluster"})
    assert _invoke(["mat", "moveto", "pc1"], config_dir=config_dir).exit_code == 0
    (ws / "products" / "pc1" / "README.md").write_text("dirty\n")

    assert _invoke(["conform", "clear"], config_dir=config_dir).exit_code != 0  # gated
    res = _invoke(["conform", "clear", "--allow-dirty"], config_dir=config_dir)  # override
    assert res.exit_code == 0, res.output
    assert not (ws / "products" / "pc1").exists()
    assert (off / "pc1" / ".git").is_dir()

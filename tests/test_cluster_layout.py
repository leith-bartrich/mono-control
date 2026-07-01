"""Tests for the ClusterLayout model/store and the `layout` CLI verbs."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from mono_control import paths
from mono_control.aspects.product_cluster.cli import app as cluster_app
from mono_control.aspects.product_cluster.cluster_layout import (
    ClusterLayout,
    ClusterLayoutNotFoundError,
    ClusterLayoutParseError,
    ClusterLayoutStore,
    ClusterLayoutValidationError,
    ClusterLayoutVersionError,
    LayoutMember,
)
from mono_control.config import Repo, RepoStore
from mono_control.git.runner import run_git

runner = CliRunner()


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "test@example.com")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    workspace_root = tmp_path / "ws"
    offline_root = tmp_path / "off"
    workspace_root.mkdir()
    offline_root.mkdir()
    monkeypatch.setattr(paths, "REPOS_DIR", workspace_root)
    monkeypatch.setattr(paths, "OFFLINE_DIR", offline_root)
    return config_dir, workspace_root, offline_root


def _invoke(args, *, config_dir: Path):
    return runner.invoke(cluster_app, args, obj=config_dir)


def _origin(path: Path, branch: str = "main") -> str:
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--initial-branch", branch, str(path)])
    (path / "README.md").write_text("hello\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "initial"], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path)


def _make_cluster(config_dir: Path, tmp_path: Path, *, slug="cluster1", name="cluster1"):
    """Create + materialize a product-cluster; return its RepoStore."""
    origin = tmp_path / f"{slug}-origin"
    _origin(origin)
    store = RepoStore.from_config_dir(config_dir)
    store.create(
        Repo(
            version=1,
            slug=slug,
            name=name,
            sources={"origin": str(origin)},
            aspects={"product-cluster"},
        )
    )
    res = _invoke(["mat", "moveto", slug], config_dir=config_dir)
    assert res.exit_code == 0, res.output
    return store


# --------------------------------------------------------------------------- #
# Model + store
# --------------------------------------------------------------------------- #
def test_layout_round_trip():
    layout = ClusterLayout(
        version=1, members={"m1": LayoutMember(location="src/m1", role="dev")}
    )
    again = ClusterLayout.load(json.loads(layout.model_dump_json()))
    assert again == layout
    assert again.members["m1"].role == "dev"


def test_store_save_then_load(tmp_path):
    store = ClusterLayoutStore(tmp_path)  # tmp_path stands in for the checkout root
    assert not store.exists()
    assert store.load_or_empty().members == {}

    layout = ClusterLayout(
        version=1, members={"m1": LayoutMember(location="a", role="dep")}
    )
    store.save(layout)
    assert store.exists()
    assert store.path() == tmp_path / "product-cluster" / "default-layout.json"
    assert store.load() == layout


def test_store_load_missing_raises(tmp_path):
    with pytest.raises(ClusterLayoutNotFoundError):
        ClusterLayoutStore(tmp_path).load()


def test_store_load_bad_json_raises(tmp_path):
    store = ClusterLayoutStore(tmp_path)
    store.directory.mkdir(parents=True)
    store.path().write_text("{not json")
    with pytest.raises(ClusterLayoutParseError):
        store.load()


def test_store_load_bad_version_raises(tmp_path):
    store = ClusterLayoutStore(tmp_path)
    store.directory.mkdir(parents=True)
    store.path().write_text(json.dumps({"version": 99, "members": {}}))
    with pytest.raises(ClusterLayoutVersionError):
        store.load()


def test_store_load_schema_mismatch_raises(tmp_path):
    store = ClusterLayoutStore(tmp_path)
    store.directory.mkdir(parents=True)
    # member missing the required `location`
    store.path().write_text(json.dumps({"version": 1, "members": {"m1": {"role": "dev"}}}))
    with pytest.raises(ClusterLayoutValidationError):
        store.load()


def test_bad_role_rejected():
    with pytest.raises(ValidationError):
        LayoutMember(location="a", role="prod")  # not dev|dep


# --------------------------------------------------------------------------- #
# `layout` CLI verbs
# --------------------------------------------------------------------------- #
def test_layout_add_show_validate_remove(workspace, tmp_path):
    config_dir, workspace_root, _ = workspace
    store = _make_cluster(config_dir, tmp_path)
    store.create(Repo(version=1, slug="m1", name="m1"))  # member def must exist

    add = _invoke(
        ["layout", "add", "m1", "--location", "src/m1", "--role", "dev", "--cluster", "cluster1"],
        config_dir=config_dir,
    )
    assert add.exit_code == 0, add.output
    assert "set" in add.output

    layout_file = (
        workspace_root / "products" / "cluster1" / "product-cluster" / "default-layout.json"
    )
    assert layout_file.is_file()

    show = _invoke(["layout", "show", "--cluster", "cluster1"], config_dir=config_dir)
    assert show.exit_code == 0
    assert "m1" in show.output and "src/m1" in show.output and "dev" in show.output

    valid = _invoke(["layout", "validate", "--cluster", "cluster1"], config_dir=config_dir)
    assert valid.exit_code == 0, valid.output

    rm = _invoke(["layout", "remove", "m1", "--cluster", "cluster1"], config_dir=config_dir)
    assert rm.exit_code == 0, rm.output
    show2 = _invoke(["layout", "show", "--cluster", "cluster1"], config_dir=config_dir)
    assert "no layout authored" in show2.output


def test_layout_implied_cluster(workspace, tmp_path):
    config_dir, _, _ = workspace
    store = _make_cluster(config_dir, tmp_path)
    store.create(Repo(version=1, slug="m1", name="m1"))
    # omit --cluster: resolves to the sole materialized cluster
    add = _invoke(
        ["layout", "add", "m1", "--location", "src/m1", "--role", "dep"],
        config_dir=config_dir,
    )
    assert add.exit_code == 0, add.output
    show = _invoke(["layout", "show"], config_dir=config_dir)
    assert "m1" in show.output


def test_layout_add_rejects_bad_role(workspace, tmp_path):
    config_dir, _, _ = workspace
    store = _make_cluster(config_dir, tmp_path)
    store.create(Repo(version=1, slug="m1", name="m1"))
    res = _invoke(
        ["layout", "add", "m1", "--location", "x", "--role", "prod", "--cluster", "cluster1"],
        config_dir=config_dir,
    )
    assert res.exit_code != 0


def test_layout_validate_flags_unknown_member(workspace, tmp_path):
    config_dir, workspace_root, _ = workspace
    _make_cluster(config_dir, tmp_path)
    # author a layout referencing a non-existent member, directly via the store
    store = ClusterLayoutStore(workspace_root / "products" / "cluster1")
    store.save(
        ClusterLayout(version=1, members={"ghost": LayoutMember(location="x", role="dev")})
    )
    res = _invoke(["layout", "validate", "--cluster", "cluster1"], config_dir=config_dir)
    assert res.exit_code != 0
    assert "ghost" in res.output


def test_layout_needs_materialized_cluster(workspace, tmp_path):
    """A layout verb on an un-materialized cluster fails (the file lives inside it)."""
    config_dir, _, _ = workspace
    store = RepoStore.from_config_dir(config_dir)
    store.create(Repo(version=1, slug="cold", name="cold", aspects={"product-cluster"}))
    res = _invoke(["layout", "show", "--cluster", "cold"], config_dir=config_dir)
    assert res.exit_code != 0
    assert "not present" in res.output or "not materialized" in res.output


def test_member_candidates_excludes_cluster(workspace):
    """The manager never offers the cluster itself as a member of its own layout."""
    from mono_control.aspects.product_cluster.layout_ui import _member_candidates

    config_dir, _, _ = workspace
    store = RepoStore.from_config_dir(config_dir)
    store.create(Repo(version=1, slug="pc", name="pc", aspects={"product-cluster"}))
    store.create(Repo(version=1, slug="m1", name="m1"))
    store.create(Repo(version=1, slug="m2", name="m2"))
    assert _member_candidates(store, "pc") == ["m1", "m2"]

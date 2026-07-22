"""Tests for the ClusterLayout model/store and the `layout` CLI verbs (shim broker)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from broker_shim import ShimBroker, run_git
from mono_control.aspects.product_cluster.cli import app as cluster_app
from mono_control.aspects.product_cluster.cluster_layout import (
    ClusterLayout,
    ClusterLayoutNotFoundError,
    ClusterLayoutStore,
    ClusterLayoutValidationError,
    ClusterLayoutVersionError,
    LayoutMember,
)
from mono_control.config import Repo, RepoStore

runner = CliRunner()


def _invoke(env, args):
    return runner.invoke(cluster_app, args, obj=env.app)


def _origin(path: Path, branch: str = "main") -> str:
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--initial-branch", branch, str(path)])
    (path / "README.md").write_text("hello\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "initial"], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path)


def _make_cluster(env, tmp_path: Path, *, slug="cluster1", name="cluster1") -> RepoStore:
    """Create + materialize a product-cluster; return its RepoStore."""
    origin = tmp_path / f"{slug}-origin"
    _origin(origin)
    store = RepoStore(env.broker)
    store.create(
        Repo(
            version=1,
            slug=slug,
            name=name,
            sources={"origin": str(origin)},
            aspects={"product-cluster"},
        )
    )
    res = _invoke(env, ["mat", "moveto", slug])
    assert res.exit_code == 0, res.output
    return store


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #
def test_layout_round_trip():
    layout = ClusterLayout(
        version=1, members={"m1": LayoutMember(location="src/m1", role="dev")}
    )
    again = ClusterLayout.load(json.loads(layout.model_dump_json()))
    assert again == layout
    assert again.members["m1"].role == "dev"


def test_bad_role_rejected():
    with pytest.raises(ValidationError):
        LayoutMember(location="a", role="prod")  # not dev|dep


# --------------------------------------------------------------------------- #
# Broker-backed store — needs a materialized cluster to hold the document
# --------------------------------------------------------------------------- #
def test_store_save_then_load(broker_env, tmp_path):
    env = broker_env
    _make_cluster(env, tmp_path)
    store = ClusterLayoutStore(env.broker, "cluster1")
    assert not store.exists()
    assert store.load_or_empty().members == {}

    layout = ClusterLayout(
        version=1, members={"m1": LayoutMember(location="a", role="dep")}
    )
    store.save(layout)
    assert store.exists()
    assert store.load() == layout


def test_store_load_missing_raises(broker_env, tmp_path):
    env = broker_env
    _make_cluster(env, tmp_path)
    with pytest.raises(ClusterLayoutNotFoundError):
        ClusterLayoutStore(env.broker, "cluster1").load()


def test_store_load_bad_version_raises(broker_env, tmp_path):
    env = broker_env
    _make_cluster(env, tmp_path)
    # Author a bad document directly on the (broker-side) checkout.
    path = env.ws / "products" / "cluster1" / "product-cluster" / "default-layout.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 99, "members": {}}))
    with pytest.raises(ClusterLayoutVersionError):
        ClusterLayoutStore(env.broker, "cluster1").load()


def test_store_load_schema_mismatch_raises(broker_env, tmp_path):
    env = broker_env
    _make_cluster(env, tmp_path)
    path = env.ws / "products" / "cluster1" / "product-cluster" / "default-layout.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "members": {"m1": {"role": "dev"}}}))
    with pytest.raises(ClusterLayoutValidationError):
        ClusterLayoutStore(env.broker, "cluster1").load()


# --------------------------------------------------------------------------- #
# `layout` CLI verbs
# --------------------------------------------------------------------------- #
def test_layout_add_show_validate_remove(broker_env, tmp_path):
    env = broker_env
    store = _make_cluster(env, tmp_path)
    store.create(Repo(version=1, slug="m1", name="m1"))  # member def must exist

    add = _invoke(
        env,
        ["layout", "add", "m1", "--location", "src/m1", "--role", "dev", "--cluster", "cluster1"],
    )
    assert add.exit_code == 0, add.output
    assert "set" in add.output

    layout_file = (
        env.ws / "products" / "cluster1" / "product-cluster" / "default-layout.json"
    )
    assert layout_file.is_file()

    show = _invoke(env, ["layout", "show", "--cluster", "cluster1"])
    assert show.exit_code == 0
    assert "m1" in show.output and "src/m1" in show.output and "dev" in show.output

    valid = _invoke(env, ["layout", "validate", "--cluster", "cluster1"])
    assert valid.exit_code == 0, valid.output

    rm = _invoke(env, ["layout", "remove", "m1", "--cluster", "cluster1"])
    assert rm.exit_code == 0, rm.output
    show2 = _invoke(env, ["layout", "show", "--cluster", "cluster1"])
    assert "no layout authored" in show2.output


def test_layout_implied_cluster(broker_env, tmp_path):
    env = broker_env
    store = _make_cluster(env, tmp_path)
    store.create(Repo(version=1, slug="m1", name="m1"))
    add = _invoke(env, ["layout", "add", "m1", "--location", "src/m1", "--role", "dep"])
    assert add.exit_code == 0, add.output
    show = _invoke(env, ["layout", "show"])
    assert "m1" in show.output


def test_layout_add_rejects_bad_role(broker_env, tmp_path):
    env = broker_env
    store = _make_cluster(env, tmp_path)
    store.create(Repo(version=1, slug="m1", name="m1"))
    res = _invoke(
        env,
        ["layout", "add", "m1", "--location", "x", "--role", "prod", "--cluster", "cluster1"],
    )
    assert res.exit_code != 0


def test_layout_validate_flags_unknown_member(broker_env, tmp_path):
    env = broker_env
    _make_cluster(env, tmp_path)
    # Author a layout referencing a non-existent member, directly via the store.
    ClusterLayoutStore(env.broker, "cluster1").save(
        ClusterLayout(version=1, members={"ghost": LayoutMember(location="x", role="dev")})
    )
    res = _invoke(env, ["layout", "validate", "--cluster", "cluster1"])
    assert res.exit_code != 0
    assert "ghost" in res.output


def test_layout_needs_materialized_cluster(broker_env):
    """A layout verb on an un-materialized cluster fails (the file lives inside it)."""
    env = broker_env
    RepoStore(env.broker).create(
        Repo(version=1, slug="cold", name="cold", aspects={"product-cluster"})
    )
    res = _invoke(env, ["layout", "show", "--cluster", "cold"])
    assert res.exit_code != 0
    assert "not present" in res.output or "not materialized" in res.output


def test_member_candidates_excludes_cluster(broker_env):
    """The manager never offers the cluster itself as a member of its own layout."""
    from mono_control.aspects.product_cluster.layout_ui import _member_candidates

    store = RepoStore(broker_env.broker)
    store.create(Repo(version=1, slug="pc", name="pc", aspects={"product-cluster"}))
    store.create(Repo(version=1, slug="m1", name="m1"))
    store.create(Repo(version=1, slug="m2", name="m2"))
    assert _member_candidates(store, "pc") == ["m1", "m2"]

"""Tests for `product-cluster conform clear / swap / relayout` (via the shim broker)."""

import json
from pathlib import Path

from typer.testing import CliRunner

from broker_shim import GitRepo, clone, run_git, PROFILE
from mono_control.aspects.product_cluster.cli import app as cluster_app
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


def _seed(env, slug: str, origin: Path, *, aspects=None) -> None:
    RepoStore(env.broker).create(
        Repo(
            version=1,
            slug=slug,
            name=slug,
            sources={"origin": str(origin)},
            aspects=aspects or set(),
        )
    )


def test_conform_swap_materializes_cluster_and_members(broker_env, tmp_path):
    env = broker_env
    _origin(tmp_path / "m1o")
    _origin(tmp_path / "m2o")
    _cluster_origin(
        tmp_path / "clo",
        {
            "m1": {"location": "src/m1", "role": "dev"},
            "m2": {"location": "libs/m2", "role": "dep"},
        },
    )
    _seed(env, "m1", tmp_path / "m1o")
    _seed(env, "m2", tmp_path / "m2o")
    _seed(env, "cluster1", tmp_path / "clo", aspects={"product-cluster"})

    res = _invoke(env, ["conform", "swap", "cluster1"])
    assert res.exit_code == 0, res.output
    assert (env.ws / "products" / "cluster1" / ".git").is_dir()
    assert GitRepo(env.ws / "src" / "m1").slug() == "m1"
    assert GitRepo(env.ws / "libs" / "m2").slug() == "m2"


def test_conform_swap_pre_clears_extras(broker_env, tmp_path):
    env = broker_env
    _origin(tmp_path / "extrao")
    clone(tmp_path / "extrao", env.ws / "extra", profile=PROFILE, slug="extra")
    _seed(env, "extra", tmp_path / "extrao")

    _cluster_origin(tmp_path / "clo", {})  # empty layout: just the cluster
    _seed(env, "cluster1", tmp_path / "clo", aspects={"product-cluster"})

    res = _invoke(env, ["conform", "swap", "cluster1"])
    assert res.exit_code == 0, res.output
    assert (env.ws / "products" / "cluster1" / ".git").is_dir()
    assert not (env.ws / "extra").exists()
    assert (env.off / "extra" / ".git").is_dir()


def test_conform_clear_retires_all(broker_env, tmp_path):
    env = broker_env
    _origin(tmp_path / "ao")
    clone(tmp_path / "ao", env.ws / "alpha", profile=PROFILE, slug="alpha")
    _seed(env, "alpha", tmp_path / "ao")

    res = _invoke(env, ["conform", "clear"])
    assert res.exit_code == 0, res.output
    assert not (env.ws / "alpha").exists()
    assert (env.off / "alpha" / ".git").is_dir()


def test_conform_clear_is_nondestructive_for_dirty(broker_env, tmp_path):
    """Retire moves to offline (preserving work), so a dirty repo clears safely."""
    env = broker_env
    _origin(tmp_path / "ao")
    clone(tmp_path / "ao", env.ws / "alpha", profile=PROFILE, slug="alpha")
    _seed(env, "alpha", tmp_path / "ao")
    (env.ws / "alpha" / "README.md").write_text("uncommitted change\n")  # dirty

    res = _invoke(env, ["conform", "clear"])
    assert res.exit_code == 0, res.output
    assert not (env.ws / "alpha").exists()
    assert (env.off / "alpha" / ".git").is_dir()
    assert (env.off / "alpha" / "README.md").read_text() == "uncommitted change\n"


def test_conform_swap_requires_aspect(broker_env, tmp_path):
    env = broker_env
    RepoStore(env.broker).create(Repo(version=1, slug="plain", name="plain"))
    res = _invoke(env, ["conform", "swap", "plain"])
    assert res.exit_code != 0
    assert "does not declare" in res.output


def test_conform_clear_blocks_dirty_cluster(broker_env, tmp_path):
    """A dirty product-cluster blocks clear (its committed state anchors reproducibility)."""
    env = broker_env
    _origin(tmp_path / "pco")
    _seed(env, "pc1", tmp_path / "pco", aspects={"product-cluster"})
    assert _invoke(env, ["mat", "moveto", "pc1"]).exit_code == 0
    (env.ws / "products" / "pc1" / "README.md").write_text("uncommitted\n")

    res = _invoke(env, ["conform", "clear"])
    assert res.exit_code != 0
    assert "pc1" in res.output
    assert (env.ws / "products" / "pc1" / ".git").is_dir()  # untouched


def test_conform_swap_blocks_dirty_cluster(broker_env, tmp_path):
    env = broker_env
    _origin(tmp_path / "ao")
    _seed(env, "pca", tmp_path / "ao", aspects={"product-cluster"})
    assert _invoke(env, ["mat", "moveto", "pca"]).exit_code == 0
    (env.ws / "products" / "pca" / "README.md").write_text("dirty\n")

    _cluster_origin(tmp_path / "bo", {})
    _seed(env, "pcb", tmp_path / "bo", aspects={"product-cluster"})

    res = _invoke(env, ["conform", "swap", "pcb"])
    assert res.exit_code != 0
    assert "pca" in res.output
    assert (env.ws / "products" / "pca" / ".git").is_dir()  # not torn down


def test_conform_swap_unreachable_cluster_leaves_workspace(broker_env, tmp_path):
    """Sourcing the cluster first means an unreachable one fails before any clear."""
    env = broker_env
    _origin(tmp_path / "ao")
    clone(tmp_path / "ao", env.ws / "alpha", profile=PROFILE, slug="alpha")
    _seed(env, "alpha", tmp_path / "ao")
    _seed(env, "pcbad", tmp_path / "missing", aspects={"product-cluster"})

    res = _invoke(env, ["conform", "swap", "pcbad"])
    assert res.exit_code != 0
    assert (env.ws / "alpha" / ".git").is_dir()  # workspace NOT cleared


def test_relayout_applies_layout_delta(broker_env, tmp_path):
    """relayout pulls in missing members, retires extras, leaves the cluster in place."""
    env = broker_env
    _origin(tmp_path / "m1o")
    _origin(tmp_path / "m2o")
    _cluster_origin(
        tmp_path / "clo",
        {
            "m1": {"location": "src/m1", "role": "dev"},
            "m2": {"location": "libs/m2", "role": "dep"},
        },
    )
    _seed(env, "m1", tmp_path / "m1o")
    _seed(env, "m2", tmp_path / "m2o")
    _seed(env, "cluster1", tmp_path / "clo", aspects={"product-cluster"})
    assert _invoke(env, ["mat", "moveto", "cluster1"]).exit_code == 0
    _origin(tmp_path / "extrao")
    clone(tmp_path / "extrao", env.ws / "extra", profile=PROFILE, slug="extra")
    _seed(env, "extra", tmp_path / "extrao")

    res = _invoke(env, ["conform", "relayout", "cluster1"])
    assert res.exit_code == 0, res.output
    assert (env.ws / "products" / "cluster1" / ".git").is_dir()
    assert GitRepo(env.ws / "src" / "m1").slug() == "m1"
    assert GitRepo(env.ws / "libs" / "m2").slug() == "m2"
    assert not (env.ws / "extra").exists()
    assert (env.off / "extra" / ".git").is_dir()


def test_relayout_allows_dirty_target_cluster(broker_env, tmp_path):
    """relayout keeps the target cluster, so its dirtiness must NOT gate (unlike clear/swap)."""
    env = broker_env
    _origin(tmp_path / "m1o")
    _cluster_origin(tmp_path / "clo", {"m1": {"location": "src/m1", "role": "dev"}})
    _seed(env, "m1", tmp_path / "m1o")
    _seed(env, "cluster1", tmp_path / "clo", aspects={"product-cluster"})
    assert _invoke(env, ["mat", "moveto", "cluster1"]).exit_code == 0
    (env.ws / "products" / "cluster1" / "README.md").write_text("uncommitted\n")

    res = _invoke(env, ["conform", "relayout", "cluster1"])
    assert res.exit_code == 0, res.output
    assert (env.ws / "products" / "cluster1" / ".git").is_dir()
    assert GitRepo(env.ws / "src" / "m1").slug() == "m1"


def test_relayout_implied_cluster(broker_env, tmp_path):
    env = broker_env
    _origin(tmp_path / "m1o")
    _cluster_origin(tmp_path / "clo", {"m1": {"location": "m1", "role": "dev"}})
    _seed(env, "m1", tmp_path / "m1o")
    _seed(env, "cluster1", tmp_path / "clo", aspects={"product-cluster"})
    assert _invoke(env, ["mat", "moveto", "cluster1"]).exit_code == 0

    res = _invoke(env, ["conform", "relayout"])  # no arg → sole cluster
    assert res.exit_code == 0, res.output
    assert GitRepo(env.ws / "m1").slug() == "m1"


def test_conform_clear_allow_dirty_override(broker_env, tmp_path):
    env = broker_env
    _origin(tmp_path / "pco")
    _seed(env, "pc1", tmp_path / "pco", aspects={"product-cluster"})
    assert _invoke(env, ["mat", "moveto", "pc1"]).exit_code == 0
    (env.ws / "products" / "pc1" / "README.md").write_text("dirty\n")

    assert _invoke(env, ["conform", "clear"]).exit_code != 0  # gated
    res = _invoke(env, ["conform", "clear", "--allow-dirty"])  # override
    assert res.exit_code == 0, res.output
    assert not (env.ws / "products" / "pc1").exists()
    assert (env.off / "pc1" / ".git").is_dir()

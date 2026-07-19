import json
from pathlib import Path

from typer.testing import CliRunner

from broker_shim import GitRepo, run_git
from mono_control.aspects.product_cluster.cli import app as cluster_app
from mono_control.config import Repo, RepoStore

runner = CliRunner()


def _invoke(env, args: list[str]):
    return runner.invoke(cluster_app, args, obj=env.app)


def _origin(path: Path, branch: str = "main") -> str:
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--initial-branch", branch, str(path)])
    (path / "README.md").write_text("hello\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "initial"], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path)


def test_list_available_empty(broker_env):
    result = _invoke(broker_env, ["list-available"])
    assert result.exit_code == 0
    assert "no product-cluster repos declared" in result.output


def test_mark_and_list_available(broker_env):
    env = broker_env
    RepoStore(env.broker).create(Repo(version=1, slug="alpha", name="Alpha"))

    marked = _invoke(env, ["mark", "alpha"])
    assert marked.exit_code == 0
    assert "marked" in marked.output

    listed = _invoke(env, ["list-available"])
    assert listed.exit_code == 0
    assert "alpha" in listed.output


def test_init_creates_offline_repo_with_aspect(broker_env):
    env = broker_env
    result = _invoke(env, ["init", "Fresh", "--slug", "fresh"])
    assert result.exit_code == 0

    repo = RepoStore(env.broker).load("fresh")
    assert "product-cluster" in repo.aspects
    assert repo.name == "Fresh"
    assert (env.off / "fresh" / ".git").is_dir()
    assert GitRepo(env.off / "fresh").slug() == "fresh"


def test_init_derives_slug_from_name(broker_env):
    env = broker_env
    result = _invoke(env, ["init", "My Cluster"])
    assert result.exit_code == 0
    slugs = RepoStore(env.broker).list()
    assert len(slugs) == 1
    assert slugs[0].startswith("my-cluster-")
    assert (env.off / slugs[0] / ".git").is_dir()


def test_init_refuses_existing_slug(broker_env):
    env = broker_env
    RepoStore(env.broker).create(Repo(version=1, slug="taken", name="Taken"))
    result = _invoke(env, ["init", "Taken Two", "--slug", "taken"])
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_mat_moveto_then_demat_round_trip(broker_env, tmp_path):
    """moveto places at the default products/<subdir>; demat retires it back."""
    env = broker_env
    origin = tmp_path / "origin"
    _origin(origin, branch="main")

    RepoStore(env.broker).create(
        Repo(
            version=1,
            slug="cluster1",
            name="Cluster 1",
            sources={"origin": str(origin)},
            aspects={"product-cluster"},
        )
    )

    mat_result = _invoke(env, ["mat", "moveto", "cluster1"])
    assert mat_result.exit_code == 0, mat_result.output
    placed = env.ws / "products" / "cluster-1"
    assert (placed / ".git").is_dir()
    assert GitRepo(placed).slug() == "cluster1"

    demat_result = _invoke(env, ["demat", "cluster1"])
    assert demat_result.exit_code == 0, demat_result.output
    assert not placed.exists()
    assert (env.off / "cluster1" / ".git").is_dir()


def _materialize(env, tmp_path: Path, *, slug: str, name: str) -> None:
    origin = tmp_path / f"origin-{slug}"
    _origin(origin, branch="main")
    RepoStore(env.broker).create(
        Repo(
            version=1,
            slug=slug,
            name=name,
            sources={"origin": str(origin)},
            aspects={"product-cluster"},
        )
    )
    assert _invoke(env, ["mat", "moveto", slug]).exit_code == 0


def test_current_defaults_to_name(broker_env, tmp_path):
    env = broker_env
    _materialize(env, tmp_path, slug="cluster1", name="Cluster One")

    result = _invoke(env, ["current"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "Cluster One"


def test_current_slug_and_json(broker_env, tmp_path):
    env = broker_env
    _materialize(env, tmp_path, slug="cluster1", name="Cluster One")

    slug_result = _invoke(env, ["current", "--slug"])
    assert slug_result.exit_code == 0, slug_result.output
    assert slug_result.output.strip() == "cluster1"

    json_result = _invoke(env, ["current", "--json"])
    assert json_result.exit_code == 0, json_result.output
    payload = json.loads(json_result.output)
    assert payload["slug"] == "cluster1"
    assert payload["name"] == "Cluster One"
    assert payload["location"] == "products/cluster-one"


def test_current_rejects_conflicting_forms(broker_env, tmp_path):
    env = broker_env
    _materialize(env, tmp_path, slug="cluster1", name="Cluster One")

    result = _invoke(env, ["current", "--name", "--slug"])
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output


def test_current_errors_when_none_materialized(broker_env):
    env = broker_env
    RepoStore(env.broker).create(
        Repo(version=1, slug="idle", name="Idle", aspects={"product-cluster"})
    )

    result = _invoke(env, ["current"])
    assert result.exit_code != 0
    assert "no materialized product-cluster" in result.output


def test_current_errors_when_many_materialized(broker_env, tmp_path):
    env = broker_env
    _materialize(env, tmp_path, slug="cluster1", name="Cluster One")
    _materialize(env, tmp_path, slug="cluster2", name="Cluster Two")

    result = _invoke(env, ["current"])
    assert result.exit_code != 0
    assert "multiple materialized product-clusters" in result.output


def test_demat_blocks_dirty_cluster(broker_env, tmp_path):
    """A dirty product-cluster blocks demat (its committed state anchors reproducibility)."""
    env = broker_env
    origin = tmp_path / "origin"
    _origin(origin, branch="main")
    RepoStore(env.broker).create(
        Repo(
            version=1,
            slug="dc",
            name="dc",
            sources={"origin": str(origin)},
            aspects={"product-cluster"},
        )
    )
    assert _invoke(env, ["mat", "moveto", "dc"]).exit_code == 0
    placed = env.ws / "products" / "dc"
    (placed / "README.md").write_text("uncommitted\n")

    res = _invoke(env, ["demat", "dc"])
    assert res.exit_code != 0
    assert "uncommitted changes" in res.output
    assert (placed / ".git").is_dir()  # not retired


def test_mat_moveto_refuses_unmarked_repo(broker_env):
    env = broker_env
    RepoStore(env.broker).create(Repo(version=1, slug="plain", name="Plain"))
    result = _invoke(env, ["mat", "moveto", "plain"])
    assert result.exit_code != 0
    assert "does not declare" in result.output


def test_mat_moveto_with_subdir_override(broker_env, tmp_path):
    env = broker_env
    origin = tmp_path / "origin"
    _origin(origin, branch="main")
    RepoStore(env.broker).create(
        Repo(
            version=1,
            slug="cluster2",
            name="Cluster 2",
            sources={"origin": str(origin)},
            aspects={"product-cluster"},
        )
    )

    result = _invoke(env, ["mat", "moveto", "cluster2", "friendly"])
    assert result.exit_code == 0, result.output
    assert (env.ws / "products" / "friendly" / ".git").is_dir()


def test_mat_branchat_blocks_on_unplaced_cluster(broker_env, tmp_path):
    env = broker_env
    origin = tmp_path / "origin"
    _origin(origin, branch="main")
    RepoStore(env.broker).create(
        Repo(
            version=1,
            slug="cluster3",
            name="Cluster Three",
            sources={"origin": str(origin)},
            aspects={"product-cluster"},
        )
    )
    result = _invoke(env, ["mat", "branchat", "cluster3", "main"])
    assert result.exit_code != 0
    assert "moveto" in result.output


def test_mat_layout_target_declarative(broker_env, tmp_path):
    env = broker_env
    origin = tmp_path / "origin"
    _origin(origin, branch="main")
    RepoStore(env.broker).create(
        Repo(
            version=1,
            slug="cluster4",
            name="Cluster Four",
            sources={"origin": str(origin)},
            aspects={"product-cluster"},
        )
    )
    result = _invoke(env, ["mat", "layout-target", "cluster4", "--branch", "main"])
    assert result.exit_code == 0, result.output
    assert (env.ws / "products" / "cluster-four" / ".git").is_dir()


def test_mat_branchat_rejects_unknown_sub_intent(broker_env):
    env = broker_env
    RepoStore(env.broker).create(
        Repo(version=1, slug="c5", name="c5", aspects={"product-cluster"})
    )
    result = _invoke(env, ["mat", "branchat", "c5", "main", "tip"])
    assert result.exit_code != 0
    assert "unsupported sub-intent" in result.output


def test_aspect_is_registered_top_level():
    """`mproj control product-cluster …` works via attach_aspect_commands."""
    from mono_control.aspects import REGISTERED_ASPECTS

    names = {a.name for a in REGISTERED_ASPECTS}
    assert "product-cluster" in names


def test_manage_command_registered():
    """`product-cluster manage` is wired — the interactive peer of `repo manage`."""
    result = runner.invoke(cluster_app, ["--help"])
    assert result.exit_code == 0
    assert "manage" in result.output
    from mono_control.aspects.product_cluster import manager_ui

    assert hasattr(manager_ui, "manage")

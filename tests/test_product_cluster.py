from pathlib import Path

import pytest
from typer.testing import CliRunner

from mono_control import paths
from mono_control.aspects.product_cluster.cli import app as cluster_app
from mono_control.config import Repo, RepoStore
from mono_control.git import GitRepo
from mono_control.git.runner import run_git


runner = CliRunner()


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    workspace_root = tmp_path / "ws"
    offline_root = tmp_path / "off"
    workspace_root.mkdir()
    offline_root.mkdir()
    monkeypatch.setattr(paths, "REPOS_DIR", workspace_root)
    monkeypatch.setattr(paths, "OFFLINE_DIR", offline_root)
    # The aspect CLI uses Typer's ctx.obj for the config dir; we pass it via env
    # by invoking with an explicit context object below.
    return config_dir, workspace_root, offline_root


def _invoke(args: list[str], *, config_dir: Path):
    """Invoke the cluster app with config_dir wired into Typer's context."""
    return runner.invoke(cluster_app, args, obj=config_dir)


def _origin(path: Path, branch: str = "main") -> str:
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--initial-branch", branch, str(path)])
    (path / "README.md").write_text("hello\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "initial"], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path)


def test_list_available_empty(workspace):
    config_dir, _, _ = workspace
    RepoStore.from_config_dir(config_dir)  # ensure dir exists
    result = _invoke(["list-available"], config_dir=config_dir)
    assert result.exit_code == 0
    assert "no product-cluster repos declared" in result.output


def test_mark_and_list_available(workspace):
    config_dir, _, _ = workspace
    store = RepoStore.from_config_dir(config_dir)
    store.create(Repo(version=1, slug="alpha", name="Alpha"))

    marked = _invoke(["mark", "alpha"], config_dir=config_dir)
    assert marked.exit_code == 0
    assert "marked" in marked.output

    listed = _invoke(["list-available"], config_dir=config_dir)
    assert listed.exit_code == 0
    assert "alpha" in listed.output


def test_init_creates_offline_repo_with_aspect(workspace):
    config_dir, _, offline_root = workspace
    result = _invoke(["init", "fresh", "--name", "Fresh"], config_dir=config_dir)
    assert result.exit_code == 0

    store = RepoStore.from_config_dir(config_dir)
    repo = store.load("fresh")
    assert "product-cluster" in repo.aspects
    assert repo.name == "Fresh"

    assert (offline_root / "fresh" / ".git").is_dir()
    assert GitRepo(offline_root / "fresh").slug() == "fresh"


def test_init_refuses_existing_slug(workspace):
    config_dir, _, _ = workspace
    store = RepoStore.from_config_dir(config_dir)
    store.create(Repo(version=1, slug="taken", name="Taken"))

    result = _invoke(["init", "taken"], config_dir=config_dir)
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_mat_demat_round_trip(workspace, tmp_path):
    """End-to-end: mat clones into offline, places it; demat retires it back."""
    config_dir, workspace_root, offline_root = workspace
    origin = tmp_path / "origin"
    _origin(origin, branch="main")

    store = RepoStore.from_config_dir(config_dir)
    store.create(
        Repo(
            version=1,
            slug="cluster1",
            name="Cluster 1",
            sources={"origin": str(origin)},
            aspects={"product-cluster"},
        )
    )

    mat_result = _invoke(
        ["mat", "cluster1", "--branch", "main"], config_dir=config_dir
    )
    assert mat_result.exit_code == 0, mat_result.output
    placed = workspace_root / "products" / "cluster1"
    assert (placed / ".git").is_dir()
    assert GitRepo(placed).slug() == "cluster1"

    demat_result = _invoke(["demat", "cluster1"], config_dir=config_dir)
    assert demat_result.exit_code == 0, demat_result.output
    assert not placed.exists()
    assert (offline_root / "cluster1" / ".git").is_dir()


def test_mat_refuses_unmarked_repo(workspace):
    config_dir, _, _ = workspace
    store = RepoStore.from_config_dir(config_dir)
    store.create(Repo(version=1, slug="plain", name="Plain"))
    result = _invoke(["mat", "plain"], config_dir=config_dir)
    assert result.exit_code != 0
    assert "does not declare" in result.output


def test_mat_uses_custom_name_subdir(workspace, tmp_path):
    config_dir, workspace_root, _ = workspace
    origin = tmp_path / "origin"
    _origin(origin, branch="main")
    store = RepoStore.from_config_dir(config_dir)
    store.create(
        Repo(
            version=1,
            slug="cluster2",
            name="Cluster 2",
            sources={"origin": str(origin)},
            aspects={"product-cluster"},
        )
    )

    result = _invoke(
        ["mat", "cluster2", "--name", "friendly", "--branch", "main"],
        config_dir=config_dir,
    )
    assert result.exit_code == 0, result.output
    assert (workspace_root / "products" / "friendly" / ".git").is_dir()


def test_aspect_is_registered_top_level():
    """`mproj control product-cluster …` works via attach_aspect_commands."""
    from mono_control.aspects import REGISTERED_ASPECTS

    names = {a.name for a in REGISTERED_ASPECTS}
    assert "product-cluster" in names

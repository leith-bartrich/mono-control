"""End-to-end tests for the generic `repo init/mat/demat` CLI commands."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mono_control import paths
from mono_control.cli import app
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
    return config_dir, workspace_root, offline_root


def _run(config_dir: Path, *args: str):
    return runner.invoke(app, ["--config-dir", str(config_dir), *args])


def _origin(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--initial-branch", "main", str(path)])
    (path / "README.md").write_text("hello\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "initial"], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path)


def test_repo_init_creates_offline_repo(workspace):
    config_dir, _, offline_root = workspace
    # Pin the slug via --slug so we can assert against a stable name.
    result = _run(config_dir, "repo", "init", "Plain", "--slug", "plain")
    assert result.exit_code == 0, result.output

    store = RepoStore.from_config_dir(config_dir)
    repo = store.load("plain")
    assert repo.name == "Plain"
    assert repo.aspects == set()  # generic init does NOT mark any aspect
    assert (offline_root / "plain" / ".git").is_dir()
    assert GitRepo(offline_root / "plain").slug() == "plain"


def test_repo_init_derives_slug_from_name(workspace):
    config_dir, _, offline_root = workspace
    result = _run(config_dir, "repo", "init", "My Plain Repo")
    assert result.exit_code == 0, result.output
    slugs = RepoStore.from_config_dir(config_dir).list()
    assert len(slugs) == 1
    assert slugs[0].startswith("my-plain-repo-")
    assert (offline_root / slugs[0] / ".git").is_dir()


def test_repo_init_refuses_existing_slug(workspace):
    config_dir, _, _ = workspace
    store = RepoStore.from_config_dir(config_dir)
    store.create(Repo(version=1, slug="taken", name="Taken"))

    result = _run(config_dir, "repo", "init", "Taken Two", "--slug", "taken")
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_repo_mat_moveto_then_branchat_then_demat(workspace, tmp_path):
    """End-to-end intent sequence: place, then check out a branch, then retire."""
    config_dir, workspace_root, offline_root = workspace
    origin = tmp_path / "origin"
    _origin(origin)

    store = RepoStore.from_config_dir(config_dir)
    store.create(
        Repo(
            version=1,
            slug="opaque",
            name="Opaque",
            sources={"origin": str(origin)},
        )
    )

    # 1) moveto — pure placement, no ref opinion. Since the repo is absent
    # locally, source engine clones it into offline first.
    moveto_result = _run(
        config_dir, "repo", "mat", "moveto", "opaque", "apps/web"
    )
    assert moveto_result.exit_code == 0, moveto_result.output
    placed = workspace_root / "apps" / "web"
    assert (placed / ".git").is_dir()
    assert GitRepo(placed).slug() == "opaque"

    # 2) branchat — change the ref at the current location.
    branchat_result = _run(
        config_dir, "repo", "mat", "branchat", "opaque", "main"
    )
    assert branchat_result.exit_code == 0, branchat_result.output

    # 3) demat — retire via name lookup (slugified comparison).
    demat_result = _run(config_dir, "repo", "demat", "Opaque")
    assert demat_result.exit_code == 0, demat_result.output
    assert not placed.exists()
    assert (offline_root / "opaque" / ".git").is_dir()


def test_repo_mat_branchat_blocks_when_not_materialized(workspace):
    """branchat needs an observed location; refuses when the repo isn't placed."""
    config_dir, _, _ = workspace
    store = RepoStore.from_config_dir(config_dir)
    store.create(Repo(version=1, slug="opaque", name="Opaque"))
    # No mat happened, so opaque is absent → branchat should error.
    result = _run(config_dir, "repo", "mat", "branchat", "opaque", "main")
    assert result.exit_code != 0
    assert "moveto" in result.output  # the error hints at the right next step


def test_repo_mat_branchat_rejects_unknown_sub_intent(workspace):
    """The reserved-grammar slot only accepts 'head' today."""
    config_dir, _, _ = workspace
    store = RepoStore.from_config_dir(config_dir)
    store.create(Repo(version=1, slug="opaque", name="Opaque"))
    result = _run(
        config_dir, "repo", "mat", "branchat", "opaque", "main", "tip"
    )
    assert result.exit_code != 0
    assert "unsupported sub-intent" in result.output


def test_repo_mat_commit_rejects_unknown_sub_intent(workspace):
    """commit's reserved-grammar slot only accepts 'detached' today."""
    config_dir, _, _ = workspace
    store = RepoStore.from_config_dir(config_dir)
    store.create(Repo(version=1, slug="opaque", name="Opaque"))
    result = _run(
        config_dir, "repo", "mat", "commit", "opaque", "abc1234", "attached"
    )
    assert result.exit_code != 0
    assert "unsupported sub-intent" in result.output


def test_repo_mat_layout_target_declarative(workspace, tmp_path):
    """The declarative one-liner combines placement + ref intent."""
    config_dir, workspace_root, _ = workspace
    origin = tmp_path / "origin"
    _origin(origin)
    store = RepoStore.from_config_dir(config_dir)
    store.create(
        Repo(
            version=1,
            slug="opaque",
            name="Opaque",
            sources={"origin": str(origin)},
        )
    )
    result = _run(
        config_dir, "repo", "mat", "layout-target", "opaque",
        "--location", "apps/web", "--branch", "main",
    )
    assert result.exit_code == 0, result.output
    assert (workspace_root / "apps" / "web" / ".git").is_dir()


def test_repo_mat_layout_target_rejects_branch_and_commit_together(workspace):
    config_dir, _, _ = workspace
    store = RepoStore.from_config_dir(config_dir)
    store.create(Repo(version=1, slug="opaque", name="Opaque"))
    result = _run(
        config_dir, "repo", "mat", "layout-target", "opaque",
        "--location", "x", "--branch", "main", "--commit", "abc1234",
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output

"""End-to-end tests for the `repo fork add` CLI command."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mono_control import paths
from mono_control.cli import app
from mono_control.config import Repo, RepoStore
from mono_control.git import GitError, GitRepo, clone
from mono_control.git.runner import run_git
from mono_control.host_platform import FsProfile

runner = CliRunner()

PROFILE = FsProfile(filemode=True, symlinks=True, ignorecase=False)
FORK_URL = "https://example.com/fork.git"


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


def _upstream_repo(config_dir: Path) -> RepoStore:
    store = RepoStore.from_config_dir(config_dir)
    store.create(
        Repo(
            version=1,
            slug="dep",
            name="Dep",
            sources={"upstream": "https://example.com/base.git"},
            branches={"dev": "main"},
        )
    )
    return store


def _make_origin(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--initial-branch", "main", str(path)])
    (path / "README.md").write_text("hello\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "initial"], cwd=path)


def test_fork_add_config_and_stamp(workspace, tmp_path):
    config_dir, _, offline_root = workspace
    store = _upstream_repo(config_dir)
    _make_origin(tmp_path / "base")
    clone(tmp_path / "base", offline_root / "dep", profile=PROFILE, slug="dep")

    result = _run(
        config_dir, "repo", "fork", "add", "dep", FORK_URL, "--dev", "patched-main"
    )
    assert result.exit_code == 0, result.output
    assert "stamped" in result.output

    repo = store.load("dep")
    assert list(repo.sources) == ["upstream", "fork-ours"]
    assert repo.branches == {"dev": "patched-main", "dev-upstream": "main"}
    url = run_git(["remote", "get-url", "fork-ours"], cwd=offline_root / "dep")
    assert url == FORK_URL


def test_fork_add_resolves_by_name_config_only(workspace):
    config_dir, _, _ = workspace
    store = _upstream_repo(config_dir)
    result = _run(config_dir, "repo", "fork", "add", "Dep", FORK_URL)
    assert result.exit_code == 0, result.output
    assert "config only" in result.output
    assert store.load("dep").sources["fork-ours"] == FORK_URL


def test_fork_add_no_upstream_fails(workspace):
    config_dir, _, _ = workspace
    RepoStore.from_config_dir(config_dir).create(
        Repo(version=1, slug="dep", name="Dep", sources={"origin": "u"})
    )
    result = _run(config_dir, "repo", "fork", "add", "dep", FORK_URL)
    assert result.exit_code != 0
    assert "no 'upstream' source" in result.output


def test_fork_add_duplicate_fails(workspace):
    config_dir, _, _ = workspace
    _upstream_repo(config_dir)
    assert _run(config_dir, "repo", "fork", "add", "dep", FORK_URL).exit_code == 0
    result = _run(config_dir, "repo", "fork", "add", "dep", FORK_URL)
    assert result.exit_code != 0
    assert "already has source" in result.output


def test_fork_add_stamp_failure_reports_config_saved(workspace, tmp_path, monkeypatch):
    config_dir, _, offline_root = workspace
    store = _upstream_repo(config_dir)
    _make_origin(tmp_path / "base")
    clone(tmp_path / "base", offline_root / "dep", profile=PROFILE, slug="dep")

    def _boom(self, name, url):
        raise GitError("remote stamp exploded")

    monkeypatch.setattr(GitRepo, "set_remote", _boom)
    result = _run(config_dir, "repo", "fork", "add", "dep", FORK_URL)
    assert result.exit_code == 1
    assert "config saved" in result.output
    assert store.load("dep").sources["fork-ours"] == FORK_URL

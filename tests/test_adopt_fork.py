"""Tests for the governed upstream→fork transition (`repo_ops.adopt_fork`)."""

import json
from pathlib import Path

import pytest

from mono_control import repo_ops
from mono_control.config import ConfigError, Repo, RepoStore
from mono_control.git import GitError, GitRepo, clone
from mono_control.git.runner import run_git
from mono_control.host_platform import FsProfile

PROFILE = FsProfile(filemode=True, symlinks=True, ignorecase=False)
FORK_URL = "https://example.com/fork.git"


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")


@pytest.fixture
def roots(tmp_path):
    workspace_root = tmp_path / "ws"
    offline_root = tmp_path / "off"
    workspace_root.mkdir()
    offline_root.mkdir()
    return workspace_root, offline_root


@pytest.fixture
def store(tmp_path):
    return RepoStore.from_config_dir(tmp_path / "config")


def _upstream_repo(store: RepoStore, *, branches: dict[str, str] | None = None) -> Repo:
    repo = Repo(
        version=1,
        slug="dep",
        name="Dep",
        sources={"upstream": "https://example.com/base.git"},
        branches={"dev": "main"} if branches is None else branches,
    )
    store.create(repo)
    return repo


def _adopt(store, roots, **kwargs):
    workspace_root, offline_root = roots
    return repo_ops.adopt_fork(
        "dep",
        FORK_URL,
        repo_store=store,
        workspace_root=workspace_root,
        offline_root=offline_root,
        **kwargs,
    )


def _make_origin(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--initial-branch", "main", str(path)])
    (path / "README.md").write_text("hello\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "initial"], cwd=path)


def test_config_only_repoints_dev_and_keeps_order(store, roots):
    _upstream_repo(store)
    result = _adopt(store, roots, dev_branch="patched-main")

    repo = store.load("dep")
    # fork-ours appended AFTER upstream — first-declared resolution unchanged.
    assert list(repo.sources) == ["upstream", "fork-ours"]
    assert repo.sources["fork-ours"] == FORK_URL
    assert repo.branches == {"dev": "patched-main", "dev-upstream": "main"}
    assert result.dev_repointed is True
    assert (result.old_dev, result.new_dev) == ("main", "patched-main")
    assert result.checkout is None
    assert result.remote_stamped is False
    assert result.remote_error is None
    # The serialized JSON preserves the source order too.
    on_disk = json.loads(store.path_for("dep").read_text())
    assert list(on_disk["sources"]) == ["upstream", "fork-ours"]


def test_stamps_remote_on_offline_checkout(store, roots, tmp_path):
    workspace_root, offline_root = roots
    _upstream_repo(store)
    _make_origin(tmp_path / "base")
    clone(tmp_path / "base", offline_root / "dep", profile=PROFILE, slug="dep")

    result = _adopt(store, roots, dev_branch="patched-main")

    assert result.checkout == offline_root / "dep"
    assert result.remote_stamped is True
    url = run_git(["remote", "get-url", "fork-ours"], cwd=offline_root / "dep")
    assert url == FORK_URL


def test_same_or_absent_dev_branch_does_not_repoint(store, roots):
    _upstream_repo(store)
    for dev_branch in ("main", None):
        result = _adopt(store, roots, dev_branch=dev_branch)
        assert result.dev_repointed is False
        repo = store.load("dep")
        assert repo.branches == {"dev": "main"}
        # Reset for the second pass.
        repo.sources.pop("fork-ours")
        store.save(repo)


def test_no_prior_dev_sets_dev_without_dev_upstream(store, roots):
    _upstream_repo(store, branches={})
    result = _adopt(store, roots, dev_branch="patched-main")
    assert result.dev_repointed is True
    assert result.old_dev is None
    assert store.load("dep").branches == {"dev": "patched-main"}


def test_third_party_fork_is_tracked_reference(store, roots):
    _upstream_repo(store)
    result = _adopt(store, roots, purpose="Bob's Fork")
    assert result.source_key == "fork-bobs-fork"  # purpose is slugified
    repo = store.load("dep")
    assert repo.sources["fork-bobs-fork"] == FORK_URL
    assert repo.branches == {"dev": "main"}  # never repoints dev


def test_third_party_fork_with_dev_branch_errors(store, roots):
    _upstream_repo(store)
    with pytest.raises(ConfigError, match="tracked reference"):
        _adopt(store, roots, purpose="bob", dev_branch="main")


def test_existing_fork_key_errors(store, roots):
    repo = _upstream_repo(store)
    repo.sources["fork-ours"] = "https://example.com/old.git"
    store.save(repo)
    with pytest.raises(ConfigError, match="already has source"):
        _adopt(store, roots)


def test_origin_only_repo_errors(store, roots):
    store.create(
        Repo(version=1, slug="dep", name="Dep", sources={"origin": "u"})
    )
    with pytest.raises(ConfigError, match="no 'upstream' source"):
        _adopt(store, roots)


def test_conflicting_dev_upstream_errors(store, roots):
    _upstream_repo(store, branches={"dev": "main", "dev-upstream": "other"})
    with pytest.raises(ConfigError, match="refusing to overwrite"):
        _adopt(store, roots, dev_branch="patched-main")


def test_stamp_failure_reports_but_config_is_saved(store, roots, tmp_path, monkeypatch):
    workspace_root, offline_root = roots
    _upstream_repo(store)
    _make_origin(tmp_path / "base")
    clone(tmp_path / "base", offline_root / "dep", profile=PROFILE, slug="dep")

    def _boom(self, name, url):
        raise GitError("remote stamp exploded")

    monkeypatch.setattr(GitRepo, "set_remote", _boom)
    result = _adopt(store, roots, dev_branch="patched-main")

    assert result.remote_stamped is False
    assert "exploded" in result.remote_error
    # Config changes were still committed.
    repo = store.load("dep")
    assert repo.sources["fork-ours"] == FORK_URL
    assert repo.branches["dev"] == "patched-main"

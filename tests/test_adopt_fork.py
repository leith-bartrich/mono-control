"""Tests for the governed upstream→fork transition (`repo_ops.adopt_fork`).

Step 2 re-homes the transition onto the broker: ``adopt_fork`` takes a
``broker`` (not workspace/offline roots), finds the checkout via ``broker.scan``
and stamps the fork remote via ``broker.set_remote``. These drive it against the
real-effect :class:`~broker_shim.ShimBroker`, so the stamp really lands (and its
input-validation rejections really fire) on real temp checkouts.
"""

import json
from pathlib import Path

import pytest

from broker_shim import INVALID_PARAMS, PROFILE, ShimBroker, clone, run_git
from mono_control import repo_ops
from mono_control.broker import BrokerError
from mono_control.config import ConfigError, Repo, RepoStore

FORK_URL = "https://example.com/fork.git"


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")


@pytest.fixture
def env(tmp_path):
    config_dir = tmp_path / "config"
    ws = tmp_path / "ws"
    off = tmp_path / "off"
    ws.mkdir()
    off.mkdir()
    return config_dir, ws, off, ShimBroker(config_dir, ws, off)


@pytest.fixture
def store(env):
    return RepoStore(env[3])


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


def _adopt(store, broker, **kwargs):
    return repo_ops.adopt_fork(
        "dep",
        FORK_URL,
        repo_store=store,
        broker=broker,
        **kwargs,
    )


def _make_origin(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--initial-branch", "main", str(path)])
    (path / "README.md").write_text("hello\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "initial"], cwd=path)


def test_config_only_repoints_dev_and_keeps_order(env, store):
    config_dir, _, _, broker = env
    _upstream_repo(store)
    result = _adopt(store, broker, dev_branch="patched-main")

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
    # The serialized JSON (persisted broker-side) preserves the source order too.
    on_disk = json.loads((config_dir / "repos" / "dep.json").read_text())
    assert list(on_disk["sources"]) == ["upstream", "fork-ours"]


def test_stamps_remote_on_offline_checkout(env, store, tmp_path):
    _, _, off, broker = env
    _upstream_repo(store)
    _make_origin(tmp_path / "base")
    clone(tmp_path / "base", off / "dep", profile=PROFILE, slug="dep")

    result = _adopt(store, broker, dev_branch="patched-main")

    # The broker owns absolute paths; the wire location is relative to its root.
    assert result.checkout == Path("dep")
    assert result.remote_stamped is True
    url = run_git(["remote", "get-url", "fork-ours"], cwd=off / "dep")
    assert url == FORK_URL


def test_same_or_absent_dev_branch_does_not_repoint(env, store):
    _, _, _, broker = env
    _upstream_repo(store)
    for dev_branch in ("main", None):
        result = _adopt(store, broker, dev_branch=dev_branch)
        assert result.dev_repointed is False
        repo = store.load("dep")
        assert repo.branches == {"dev": "main"}
        # Reset for the second pass.
        repo.sources.pop("fork-ours")
        store.save(repo)


def test_no_prior_dev_sets_dev_without_dev_upstream(env, store):
    _, _, _, broker = env
    _upstream_repo(store, branches={})
    result = _adopt(store, broker, dev_branch="patched-main")
    assert result.dev_repointed is True
    assert result.old_dev is None
    assert store.load("dep").branches == {"dev": "patched-main"}


def test_third_party_fork_is_tracked_reference(env, store):
    _, _, _, broker = env
    _upstream_repo(store)
    result = _adopt(store, broker, purpose="Bob's Fork")
    assert result.source_key == "fork-bobs-fork"  # purpose is slugified
    repo = store.load("dep")
    assert repo.sources["fork-bobs-fork"] == FORK_URL
    assert repo.branches == {"dev": "main"}  # never repoints dev


def test_third_party_fork_with_dev_branch_errors(env, store):
    _, _, _, broker = env
    _upstream_repo(store)
    with pytest.raises(ConfigError, match="tracked reference"):
        _adopt(store, broker, purpose="bob", dev_branch="main")


def test_existing_fork_key_errors(env, store):
    _, _, _, broker = env
    repo = _upstream_repo(store)
    repo.sources["fork-ours"] = "https://example.com/old.git"
    store.save(repo)
    with pytest.raises(ConfigError, match="already has source"):
        _adopt(store, broker)


def test_origin_only_repo_errors(env, store):
    _, _, _, broker = env
    store.create(Repo(version=1, slug="dep", name="Dep", sources={"origin": "u"}))
    with pytest.raises(ConfigError, match="no 'upstream' source"):
        _adopt(store, broker)


def test_conflicting_dev_upstream_errors(env, store):
    _, _, _, broker = env
    _upstream_repo(store, branches={"dev": "main", "dev-upstream": "other"})
    with pytest.raises(ConfigError, match="refusing to overwrite"):
        _adopt(store, broker, dev_branch="patched-main")


@pytest.mark.parametrize(
    "slug, name, url",
    [
        ("../evil", "fork-ours", FORK_URL),  # slug escapes its bare-name shape
        ("dep", "bad name", FORK_URL),  # remote name has a space
        ("dep", "fork-ours", "git://example.com/x.git"),  # non-https url
    ],
)
def test_set_remote_rejects_hostile_input(env, slug, name, url):
    """The fake mirrors the real shim's boundary validation (slug/name/url)."""
    broker = env[3]
    with pytest.raises(BrokerError) as excinfo:
        broker.set_remote(slug, name, url)
    assert excinfo.value.code == INVALID_PARAMS


def test_stamp_failure_reports_but_config_is_saved(env, store, tmp_path, monkeypatch):
    _, _, off, broker = env
    _upstream_repo(store)
    _make_origin(tmp_path / "base")
    clone(tmp_path / "base", off / "dep", profile=PROFILE, slug="dep")

    def _boom(slug, name, url):
        raise BrokerError(-32000, "remote stamp exploded")

    monkeypatch.setattr(broker, "set_remote", _boom)
    result = _adopt(store, broker, dev_branch="patched-main")

    assert result.remote_stamped is False
    assert "exploded" in result.remote_error
    # Config changes were still committed.
    repo = store.load("dep")
    assert repo.sources["fork-ours"] == FORK_URL
    assert repo.branches["dev"] == "patched-main"

"""End-to-end tests for the `repo fork add` CLI command (shim broker).

The command is driven against the in-process real-effect broker (via ``obj=``
the ``AppContext`` the ``broker_env`` fixture builds), so the eager remote stamp
really lands on a real offline checkout and the config really persists.
"""

from pathlib import Path

from typer.testing import CliRunner

from broker_shim import PROFILE, clone, run_git
from mono_control.broker import BrokerError
from mono_control.cli import app
from mono_control.config import Repo, RepoStore

runner = CliRunner()

FORK_URL = "https://example.com/fork.git"


def _run(env, *args: str):
    return runner.invoke(
        app, ["--config-dir", str(env.config_dir), *args], obj=env.app
    )


def _upstream_repo(env) -> RepoStore:
    store = RepoStore(env.broker)
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


def test_fork_add_config_and_stamp(broker_env, tmp_path):
    env = broker_env
    store = _upstream_repo(env)
    _make_origin(tmp_path / "base")
    clone(tmp_path / "base", env.off / "dep", profile=PROFILE, slug="dep")

    result = _run(
        env, "repo", "fork", "add", "dep", FORK_URL, "--dev", "patched-main"
    )
    assert result.exit_code == 0, result.output
    assert "stamped" in result.output

    repo = store.load("dep")
    assert list(repo.sources) == ["upstream", "fork-ours"]
    assert repo.branches == {"dev": "patched-main", "dev-upstream": "main"}
    url = run_git(["remote", "get-url", "fork-ours"], cwd=env.off / "dep")
    assert url == FORK_URL


def test_fork_add_resolves_by_name_config_only(broker_env):
    env = broker_env
    store = _upstream_repo(env)
    result = _run(env, "repo", "fork", "add", "Dep", FORK_URL)
    assert result.exit_code == 0, result.output
    assert "config only" in result.output
    assert store.load("dep").sources["fork-ours"] == FORK_URL


def test_fork_add_no_upstream_fails(broker_env):
    env = broker_env
    RepoStore(env.broker).create(
        Repo(version=1, slug="dep", name="Dep", sources={"origin": "u"})
    )
    result = _run(env, "repo", "fork", "add", "dep", FORK_URL)
    assert result.exit_code != 0
    assert "no 'upstream' source" in result.output


def test_fork_add_duplicate_fails(broker_env):
    env = broker_env
    _upstream_repo(env)
    assert _run(env, "repo", "fork", "add", "dep", FORK_URL).exit_code == 0
    result = _run(env, "repo", "fork", "add", "dep", FORK_URL)
    assert result.exit_code != 0
    assert "already has source" in result.output


def test_fork_add_stamp_failure_reports_config_saved(broker_env, tmp_path, monkeypatch):
    env = broker_env
    store = _upstream_repo(env)
    _make_origin(tmp_path / "base")
    clone(tmp_path / "base", env.off / "dep", profile=PROFILE, slug="dep")

    def _boom(slug, name, url):
        raise BrokerError(-32000, "remote stamp exploded")

    monkeypatch.setattr(env.broker, "set_remote", _boom)
    result = _run(env, "repo", "fork", "add", "dep", FORK_URL)
    assert result.exit_code == 1
    assert "config saved" in result.output
    assert store.load("dep").sources["fork-ours"] == FORK_URL

from typer.testing import CliRunner

from mono_control.cli import app
from mono_control.config import RepoStore

runner = CliRunner()


def _run(env, *args, **kw):
    return runner.invoke(
        app, ["--config-dir", str(env.config_dir), *args], obj=env.app, **kw
    )


def _store(env):
    return RepoStore(env.broker)


def test_add_and_list(broker_env):
    env = broker_env
    result = _run(
        env, "repo", "add", "Demo", "--slug", "demo",
        "--source", "origin=git@example.com:demo.git", "--branch", "main=main",
    )
    assert result.exit_code == 0, result.output
    assert _store(env).exists("demo")

    listed = _run(env, "repo", "list")
    assert listed.exit_code == 0
    assert "demo" in listed.output


def test_add_derives_slug_from_name(broker_env):
    env = broker_env
    result = _run(env, "repo", "add", "My Util")
    assert result.exit_code == 0, result.output
    slugs = _store(env).list()
    assert len(slugs) == 1
    assert slugs[0].startswith("my-util-")
    assert len(slugs[0]) == len("my-util-") + 4


def test_add_same_name_twice_gets_distinct_slugs(broker_env):
    env = broker_env
    _run(env, "repo", "add", "Util")
    _run(env, "repo", "add", "Util")
    slugs = _store(env).list()
    assert len(slugs) == 2
    assert slugs[0] != slugs[1]
    assert all(s.startswith("util-") for s in slugs)


def test_add_duplicate_slug_conflict(broker_env):
    env = broker_env
    _run(env, "repo", "add", "Demo", "--slug", "demo")
    dup = _run(env, "repo", "add", "Demo Two", "--slug", "demo")
    assert dup.exit_code == 1
    assert "already exists" in dup.output


def test_add_unslugifiable_name_fails(broker_env):
    bad = _run(broker_env, "repo", "add", "!!!")
    assert bad.exit_code != 0


def test_show_by_name(broker_env):
    env = broker_env
    _run(env, "repo", "add", "Demo", "--slug", "demo", "--source", "origin=u")
    out = _run(env, "repo", "show", "demo")
    assert out.exit_code == 0
    assert "origin = u" in out.output


def test_show_missing(broker_env):
    out = _run(broker_env, "repo", "show", "nope")
    assert out.exit_code == 1


def test_show_slug_only_flag(broker_env):
    env = broker_env
    _run(env, "repo", "add", "Demo", "--slug", "my-slug")
    found = _run(env, "repo", "show", "my-slug", "--slug")
    assert found.exit_code == 0
    missed = _run(env, "repo", "show", "Demo", "--slug")
    assert missed.exit_code == 1


def test_rename(broker_env):
    env = broker_env
    _run(env, "repo", "add", "Demo", "--slug", "demo")
    _run(env, "repo", "rename", "demo", "Renamed")
    assert _store(env).load("demo").name == "Renamed"


def test_source_and_branch_edit(broker_env):
    env = broker_env
    _run(env, "repo", "add", "Demo", "--slug", "demo")
    _run(env, "repo", "source", "add", "demo", "origin", "u")
    _run(env, "repo", "branch", "add", "demo", "main", "main")
    repo = _store(env).load("demo")
    assert repo.sources == {"origin": "u"}
    assert repo.branches == {"main": "main"}
    _run(env, "repo", "source", "remove", "demo", "origin")
    assert _store(env).load("demo").sources == {}


def test_retire_restore(broker_env):
    env = broker_env
    _run(env, "repo", "add", "Demo", "--slug", "demo")
    _run(env, "repo", "retire", "demo", "--yes")
    assert _store(env).load("demo").retired is True
    assert "demo" not in _run(env, "repo", "list").output
    _run(env, "repo", "restore", "demo")
    assert _store(env).load("demo").retired is False


def test_purge_requires_yes(broker_env):
    env = broker_env
    _run(env, "repo", "add", "Demo", "--slug", "demo")
    blocked = _run(env, "repo", "purge", "demo")
    assert blocked.exit_code == 1
    assert _store(env).exists("demo")


def test_purge_requires_matching_slug(broker_env):
    env = broker_env
    _run(env, "repo", "add", "Demo", "--slug", "demo")
    wrong = _run(env, "repo", "purge", "demo", "--yes", "--confirm-slug", "nope")
    assert wrong.exit_code == 1
    assert _store(env).exists("demo")


def test_purge_succeeds_when_confirmed(broker_env):
    env = broker_env
    _run(env, "repo", "add", "Demo", "--slug", "demo")
    ok = _run(env, "repo", "purge", "demo", "--yes", "--confirm-slug", "demo")
    assert ok.exit_code == 0
    assert not _store(env).exists("demo")


def test_validate_reports_repo_count(broker_env):
    env = broker_env
    env.broker.save_system({"version": 1})
    _run(env, "repo", "add", "Demo")
    out = _run(env, "validate")
    assert out.exit_code == 0
    assert "1 repo" in out.output


def test_ambiguous_name_lookup_errors_helpfully(broker_env):
    env = broker_env
    _run(env, "repo", "add", "Util")
    _run(env, "repo", "add", "Util")
    out = _run(env, "repo", "show", "Util")
    assert out.exit_code == 1
    assert "matches" in out.output
    assert "--slug" in out.output

from typer.testing import CliRunner

from mono_control.cli import app
from mono_control.config import RepoStore

runner = CliRunner()


def _run(tmp_path, *args, **kw):
    return runner.invoke(app, ["--config-dir", str(tmp_path), *args], **kw)


def test_add_and_list(tmp_path):
    result = _run(
        tmp_path, "repo", "add", "demo", "--name", "Demo",
        "--source", "origin=git@example.com:demo.git", "--branch", "main=main",
    )
    assert result.exit_code == 0, result.output
    assert RepoStore.from_config_dir(tmp_path).exists("demo")

    listed = _run(tmp_path, "repo", "list")
    assert listed.exit_code == 0
    assert "demo" in listed.output


def test_add_defaults_name_to_slug(tmp_path):
    _run(tmp_path, "repo", "add", "demo")
    assert RepoStore.from_config_dir(tmp_path).load("demo").name == "demo"


def test_add_duplicate_conflict(tmp_path):
    _run(tmp_path, "repo", "add", "demo")
    dup = _run(tmp_path, "repo", "add", "demo")
    assert dup.exit_code == 1
    assert "already exists" in dup.output


def test_add_invalid_slug(tmp_path):
    bad = _run(tmp_path, "repo", "add", "Bad Slug")
    assert bad.exit_code == 1


def test_show(tmp_path):
    _run(tmp_path, "repo", "add", "demo", "--source", "origin=u")
    out = _run(tmp_path, "repo", "show", "demo")
    assert out.exit_code == 0
    assert "origin = u" in out.output


def test_show_missing(tmp_path):
    out = _run(tmp_path, "repo", "show", "nope")
    assert out.exit_code == 1


def test_rename(tmp_path):
    _run(tmp_path, "repo", "add", "demo")
    _run(tmp_path, "repo", "rename", "demo", "Renamed")
    assert RepoStore.from_config_dir(tmp_path).load("demo").name == "Renamed"


def test_source_and_branch_edit(tmp_path):
    _run(tmp_path, "repo", "add", "demo")
    _run(tmp_path, "repo", "source", "add", "demo", "origin", "u")
    _run(tmp_path, "repo", "branch", "add", "demo", "main", "main")
    repo = RepoStore.from_config_dir(tmp_path).load("demo")
    assert repo.sources == {"origin": "u"}
    assert repo.branches == {"main": "main"}
    _run(tmp_path, "repo", "source", "remove", "demo", "origin")
    assert RepoStore.from_config_dir(tmp_path).load("demo").sources == {}


def test_retire_restore(tmp_path):
    _run(tmp_path, "repo", "add", "demo")
    _run(tmp_path, "repo", "retire", "demo", "--yes")
    assert RepoStore.from_config_dir(tmp_path).load("demo").retired is True
    assert "demo" not in _run(tmp_path, "repo", "list").output
    _run(tmp_path, "repo", "restore", "demo")
    assert RepoStore.from_config_dir(tmp_path).load("demo").retired is False


def test_purge_requires_yes(tmp_path):
    _run(tmp_path, "repo", "add", "demo")
    blocked = _run(tmp_path, "repo", "purge", "demo")
    assert blocked.exit_code == 1
    assert RepoStore.from_config_dir(tmp_path).exists("demo")


def test_purge_requires_matching_slug(tmp_path):
    _run(tmp_path, "repo", "add", "demo")
    wrong = _run(tmp_path, "repo", "purge", "demo", "--yes", "--confirm-slug", "nope")
    assert wrong.exit_code == 1
    assert RepoStore.from_config_dir(tmp_path).exists("demo")


def test_purge_succeeds_when_confirmed(tmp_path):
    _run(tmp_path, "repo", "add", "demo")
    ok = _run(tmp_path, "repo", "purge", "demo", "--yes", "--confirm-slug", "demo")
    assert ok.exit_code == 0
    assert not RepoStore.from_config_dir(tmp_path).exists("demo")


def test_validate_reports_repo_count(tmp_path):
    (tmp_path / "system.json").write_text('{"version": 1}')
    _run(tmp_path, "repo", "add", "demo")
    out = _run(tmp_path, "validate")
    assert out.exit_code == 0
    assert "1 repo" in out.output

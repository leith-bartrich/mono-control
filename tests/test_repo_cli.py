from typer.testing import CliRunner

from mono_control.cli import app
from mono_control.config import RepoStore

runner = CliRunner()


def _run(tmp_path, *args, **kw):
    return runner.invoke(app, ["--config-dir", str(tmp_path), *args], **kw)


def test_add_and_list(tmp_path):
    # Pin the slug via --slug so we can assert on it.
    result = _run(
        tmp_path, "repo", "add", "Demo", "--slug", "demo",
        "--source", "origin=git@example.com:demo.git", "--branch", "main=main",
    )
    assert result.exit_code == 0, result.output
    assert RepoStore.from_config_dir(tmp_path).exists("demo")

    listed = _run(tmp_path, "repo", "list")
    assert listed.exit_code == 0
    assert "demo" in listed.output


def test_add_derives_slug_from_name(tmp_path):
    result = _run(tmp_path, "repo", "add", "My Util")
    assert result.exit_code == 0, result.output
    slugs = RepoStore.from_config_dir(tmp_path).list()
    assert len(slugs) == 1
    # Auto-derived slug: my-util-<4 hex>
    assert slugs[0].startswith("my-util-")
    assert len(slugs[0]) == len("my-util-") + 4


def test_add_same_name_twice_gets_distinct_slugs(tmp_path):
    _run(tmp_path, "repo", "add", "Util")
    _run(tmp_path, "repo", "add", "Util")
    slugs = RepoStore.from_config_dir(tmp_path).list()
    assert len(slugs) == 2
    assert slugs[0] != slugs[1]
    assert all(s.startswith("util-") for s in slugs)


def test_add_duplicate_slug_conflict(tmp_path):
    _run(tmp_path, "repo", "add", "Demo", "--slug", "demo")
    dup = _run(tmp_path, "repo", "add", "Demo Two", "--slug", "demo")
    assert dup.exit_code == 1
    assert "already exists" in dup.output


def test_add_unslugifiable_name_fails(tmp_path):
    bad = _run(tmp_path, "repo", "add", "!!!")
    assert bad.exit_code != 0


def test_show_by_name(tmp_path):
    _run(tmp_path, "repo", "add", "Demo", "--slug", "demo", "--source", "origin=u")
    # Lookup by name (slugified comparison)
    out = _run(tmp_path, "repo", "show", "demo")
    assert out.exit_code == 0
    assert "origin = u" in out.output


def test_show_missing(tmp_path):
    out = _run(tmp_path, "repo", "show", "nope")
    assert out.exit_code == 1


def test_show_slug_only_flag(tmp_path):
    _run(tmp_path, "repo", "add", "Demo", "--slug", "my-slug")
    # --slug-only: lookup as slug, no name fallback
    found = _run(tmp_path, "repo", "show", "my-slug", "--slug")
    assert found.exit_code == 0
    # Name "Demo" via --slug-only should miss (it's a name, not a slug)
    missed = _run(tmp_path, "repo", "show", "Demo", "--slug")
    assert missed.exit_code == 1


def test_rename(tmp_path):
    _run(tmp_path, "repo", "add", "Demo", "--slug", "demo")
    _run(tmp_path, "repo", "rename", "demo", "Renamed")
    assert RepoStore.from_config_dir(tmp_path).load("demo").name == "Renamed"


def test_source_and_branch_edit(tmp_path):
    _run(tmp_path, "repo", "add", "Demo", "--slug", "demo")
    _run(tmp_path, "repo", "source", "add", "demo", "origin", "u")
    _run(tmp_path, "repo", "branch", "add", "demo", "main", "main")
    repo = RepoStore.from_config_dir(tmp_path).load("demo")
    assert repo.sources == {"origin": "u"}
    assert repo.branches == {"main": "main"}
    _run(tmp_path, "repo", "source", "remove", "demo", "origin")
    assert RepoStore.from_config_dir(tmp_path).load("demo").sources == {}


def test_retire_restore(tmp_path):
    _run(tmp_path, "repo", "add", "Demo", "--slug", "demo")
    _run(tmp_path, "repo", "retire", "demo", "--yes")
    assert RepoStore.from_config_dir(tmp_path).load("demo").retired is True
    assert "demo" not in _run(tmp_path, "repo", "list").output
    _run(tmp_path, "repo", "restore", "demo")
    assert RepoStore.from_config_dir(tmp_path).load("demo").retired is False


def test_purge_requires_yes(tmp_path):
    _run(tmp_path, "repo", "add", "Demo", "--slug", "demo")
    blocked = _run(tmp_path, "repo", "purge", "demo")
    assert blocked.exit_code == 1
    assert RepoStore.from_config_dir(tmp_path).exists("demo")


def test_purge_requires_matching_slug(tmp_path):
    _run(tmp_path, "repo", "add", "Demo", "--slug", "demo")
    wrong = _run(tmp_path, "repo", "purge", "demo", "--yes", "--confirm-slug", "nope")
    assert wrong.exit_code == 1
    assert RepoStore.from_config_dir(tmp_path).exists("demo")


def test_purge_succeeds_when_confirmed(tmp_path):
    _run(tmp_path, "repo", "add", "Demo", "--slug", "demo")
    ok = _run(tmp_path, "repo", "purge", "demo", "--yes", "--confirm-slug", "demo")
    assert ok.exit_code == 0
    assert not RepoStore.from_config_dir(tmp_path).exists("demo")


def test_validate_reports_repo_count(tmp_path):
    (tmp_path / "system.json").write_text('{"version": 1}')
    _run(tmp_path, "repo", "add", "Demo")
    out = _run(tmp_path, "validate")
    assert out.exit_code == 0
    assert "1 repo" in out.output


def test_ambiguous_name_lookup_errors_helpfully(tmp_path):
    # Two repos with the same name (mechanically distinct slugs)
    _run(tmp_path, "repo", "add", "Util")
    _run(tmp_path, "repo", "add", "Util")
    out = _run(tmp_path, "repo", "show", "Util")
    assert out.exit_code == 1
    assert "matches" in out.output
    assert "--slug" in out.output

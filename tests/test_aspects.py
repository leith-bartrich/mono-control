import typer
from typer.testing import CliRunner

from mono_control.aspects import (
    REGISTERED_ASPECTS,
    attach_aspect_commands,
    discover_repos,
    register,
)
from mono_control.config import Repo, RepoStore


def _snapshot_registry() -> list:
    return list(REGISTERED_ASPECTS)


def test_attach_registers_each_aspect_at_top_level():
    snapshot = _snapshot_registry()
    try:
        REGISTERED_ASPECTS.clear()
        stub = typer.Typer(help="Stub aspect for tests.")

        @stub.command("ping")
        def ping():
            typer.echo("pong")

        register("stub-aspect", stub)

        host = typer.Typer(no_args_is_help=True)
        attach_aspect_commands(host)

        help_result = CliRunner().invoke(host, ["--help"])
        assert "stub-aspect" in help_result.output

        invoked = CliRunner().invoke(host, ["stub-aspect", "ping"])
        assert invoked.exit_code == 0
        assert "pong" in invoked.output
    finally:
        REGISTERED_ASPECTS[:] = snapshot


def test_attach_is_a_noop_when_no_aspects_registered():
    snapshot = _snapshot_registry()
    try:
        REGISTERED_ASPECTS.clear()
        host = typer.Typer()
        attach_aspect_commands(host)  # must not raise; no commands added
        assert host.registered_groups == []
    finally:
        REGISTERED_ASPECTS[:] = snapshot


def test_discover_repos_filters_by_aspect(tmp_path):
    store = RepoStore(tmp_path / "repos")
    store.create(Repo(version=1, slug="a", name="A", aspects={"product-cluster"}))
    store.create(Repo(version=1, slug="b", name="B"))  # no aspects
    store.create(
        Repo(version=1, slug="c", name="C", aspects={"product-cluster", "other"})
    )

    matches = discover_repos(store, "product-cluster")
    slugs = {r.slug for r in matches}
    assert slugs == {"a", "c"}


def test_discover_repos_excludes_retired_by_default(tmp_path):
    store = RepoStore(tmp_path / "repos")
    store.create(Repo(version=1, slug="live", name="L", aspects={"x"}))
    store.create(Repo(version=1, slug="gone", name="G", aspects={"x"}))
    store.retire("gone")

    assert [r.slug for r in discover_repos(store, "x")] == ["live"]
    assert {r.slug for r in discover_repos(store, "x", include_retired=True)} == {
        "live",
        "gone",
    }

from pathlib import Path

from typer.testing import CliRunner

from mono_control.app_context import AppContext
from mono_control.broker import FakeBroker, WireInventory, WireRepo, WireUnmanaged
from mono_control.cli import app

runner = CliRunner()

# Absolute inside the container (the only place the suite runs); satisfies the
# root callback's --config-dir check without depending on a real config tree.
_CONFIG_DIR = Path("/workspaces/mono-config")


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "mono-control" in result.stdout


def test_status_reports_broker_inventory():
    # Step 2: the container has no mounts of its own; `status` reports what the
    # broker observes (reachability + managed/unmanaged counts), not dir paths.
    inventory = WireInventory(
        repos=[
            WireRepo(slug="alpha", location="alpha", state="materialized", commit="c0ffee", dirty=False),
            WireRepo(slug="beta", location="beta", state="offline", commit=None, dirty=False),
        ],
        unmanaged=[WireUnmanaged(location="stranger", state="materialized")],
    )
    ctx = AppContext(config_dir=_CONFIG_DIR, broker=FakeBroker(inventory=inventory))
    result = runner.invoke(app, ["status"], obj=ctx)
    assert result.exit_code == 0
    assert "broker reachable" in result.output
    assert "2 managed repo(s)" in result.output
    assert "1 unmanaged" in result.output


def test_status_reports_unreachable_broker():
    class _DownBroker:
        def scan(self):
            raise RuntimeError("connection refused")

        def call(self, method, params=None):
            raise RuntimeError("connection refused")

    ctx = AppContext(config_dir=_CONFIG_DIR, broker=_DownBroker())
    result = runner.invoke(app, ["status"], obj=ctx)
    assert result.exit_code == 0
    assert "unreachable" in result.output.lower()


def test_no_args_shows_help():
    result = runner.invoke(app, [])
    assert result.exit_code == 2  # no command given -> help + conventional usage exit
    assert "Usage" in result.output


def test_relative_config_dir_rejected():
    # A relative --config-dir would silently mkdir a junk tree inside the
    # container's working dir; the root callback must reject it loudly.
    result = runner.invoke(app, ["--config-dir", "relative/cfg", "status"])
    assert result.exit_code != 0
    assert "absolute" in result.output.lower()


def test_version_command():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "mono-control" in result.output


def test_help_command_top_level():
    result = runner.invoke(app, ["help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_help_command_for_subcommand():
    result = runner.invoke(app, ["help", "repo"])
    assert result.exit_code == 0
    assert "repo" in result.output.lower()


def test_help_command_unknown():
    result = runner.invoke(app, ["help", "nope"])
    assert result.exit_code != 0
    assert "unknown command" in result.output


def test_completion_descends_into_subcommands():
    import typer

    from mono_control.cli.app import _completion_candidates

    group = typer.main.get_command(app)
    # top-level prefix
    assert "product-cluster" in _completion_candidates(group, "prod", [])
    # descend into a sub-group's subcommands
    subs = set(_completion_candidates(group, "product-cluster ", []))
    assert {"conform", "layout", "mat", "manage"} <= subs
    # nested one level further
    conf = set(_completion_candidates(group, "product-cluster conform ", []))
    assert {"relayout", "clear", "swap"} <= conf
    # extra (REPL exit) words only offered at the root
    assert "quit" in _completion_candidates(group, "", ["quit"])
    assert "quit" not in _completion_candidates(group, "product-cluster ", ["quit"])

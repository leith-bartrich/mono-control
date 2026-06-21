from typer.testing import CliRunner

from mono_control.cli import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "mono-control" in result.stdout


def test_status_runs():
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0


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

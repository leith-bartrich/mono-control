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

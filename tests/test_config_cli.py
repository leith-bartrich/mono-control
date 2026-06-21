from typer.testing import CliRunner

from mono_control.cli import app
from mono_control.paths import SYSTEM_FILE

runner = CliRunner()


def _run(tmp_path, *args, **kw):
    return runner.invoke(app, ["--config-dir", str(tmp_path), *args], **kw)


def test_init_creates_system_file(tmp_path):
    result = _run(tmp_path, "config", "init")
    assert result.exit_code == 0, result.output
    assert (tmp_path / SYSTEM_FILE).is_file()


def test_init_refuses_overwrite(tmp_path):
    _run(tmp_path, "config", "init")
    again = _run(tmp_path, "config", "init")
    assert again.exit_code == 1
    assert "already exists" in again.output


def test_show_after_init(tmp_path):
    _run(tmp_path, "config", "init")
    result = _run(tmp_path, "config", "show")
    assert result.exit_code == 0
    assert "version 1" in result.output


def test_validate_after_init(tmp_path):
    _run(tmp_path, "config", "init")
    result = _run(tmp_path, "config", "validate")
    assert result.exit_code == 0
    assert "valid" in result.output


def test_show_on_missing_config_errors(tmp_path):
    result = _run(tmp_path, "config", "show")
    assert result.exit_code == 1

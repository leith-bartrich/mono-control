from typer.testing import CliRunner

from mono_control.cli import app
from mono_control.config import system_exists

runner = CliRunner()


def _run(env, *args, **kw):
    return runner.invoke(
        app, ["--config-dir", str(env.config_dir), *args], obj=env.app, **kw
    )


def test_init_creates_system_file(broker_env):
    env = broker_env
    result = _run(env, "config", "init")
    assert result.exit_code == 0, result.output
    assert system_exists(env.broker)


def test_init_refuses_overwrite(broker_env):
    env = broker_env
    _run(env, "config", "init")
    again = _run(env, "config", "init")
    assert again.exit_code == 1
    assert "already exists" in again.output


def test_show_after_init(broker_env):
    env = broker_env
    _run(env, "config", "init")
    result = _run(env, "config", "show")
    assert result.exit_code == 0
    assert "version 1" in result.output


def test_validate_after_init(broker_env):
    env = broker_env
    _run(env, "config", "init")
    result = _run(env, "config", "validate")
    assert result.exit_code == 0
    assert "valid" in result.output


def test_show_on_missing_config_errors(broker_env):
    result = _run(broker_env, "config", "show")
    assert result.exit_code == 1

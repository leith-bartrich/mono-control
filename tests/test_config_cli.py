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


def test_show_on_missing_config_succeeds_with_defaults(broker_env):
    """The bug this replaced: three commands dead-ended on an optional file."""
    result = _run(broker_env, "config", "show")
    assert result.exit_code == 0, result.output
    assert "version 1" in result.output
    assert "no system.json" in result.output


def test_validate_on_missing_config_succeeds_and_says_so(broker_env):
    result = _run(broker_env, "config", "validate")
    assert result.exit_code == 0, result.output
    assert "no system.json" in result.output


def test_missing_config_points_at_config_init(broker_env):
    """Absent is fine, but the reader should learn the file is creatable."""
    result = _run(broker_env, "config", "show")
    assert "config init" in result.output


def test_show_names_the_file_once_it_exists(broker_env):
    env = broker_env
    _run(env, "config", "init")
    result = _run(env, "config", "show")
    assert result.exit_code == 0
    assert "system.json" in result.output
    assert "no system.json" not in result.output


def test_a_malformed_system_json_still_fails(broker_env):
    """Optional is not unvalidated: a broken file must not read as absent."""
    env = broker_env
    env.broker.save_system({"version": 99})
    result = _run(env, "config", "show")
    assert result.exit_code == 1


def test_top_level_validate_passes_without_system_json(broker_env):
    result = _run(broker_env, "validate")
    assert result.exit_code == 0, result.output
    assert "config is valid" in result.output
    assert "no system.json" in result.output

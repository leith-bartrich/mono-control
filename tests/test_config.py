import json

import pytest

from mono_control.config import (
    ConfigNotFoundError,
    ConfigParseError,
    ConfigValidationError,
    ConfigVersionError,
    WorkspaceConfig,
    load_config,
    save_config,
)
from mono_control.paths import SYSTEM_FILE


def _write_system(config_dir, data):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / SYSTEM_FILE).write_text(json.dumps(data))


def test_load_minimal_config(tmp_path):
    _write_system(tmp_path, {"version": 1})
    config = load_config(tmp_path)
    assert config.version == 1


def test_missing_version(tmp_path):
    _write_system(tmp_path, {})
    with pytest.raises(ConfigVersionError):
        load_config(tmp_path)


def test_version_too_new(tmp_path):
    _write_system(tmp_path, {"version": 2})
    with pytest.raises(ConfigVersionError):
        load_config(tmp_path)


def test_missing_directory(tmp_path):
    with pytest.raises(ConfigNotFoundError):
        load_config(tmp_path / "does-not-exist")


def test_missing_system_file(tmp_path):
    tmp_path.joinpath("placeholder").mkdir()  # dir exists, system.json does not
    with pytest.raises(ConfigNotFoundError):
        load_config(tmp_path)


def test_malformed_json(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / SYSTEM_FILE).write_text("{not valid json")
    with pytest.raises(ConfigParseError):
        load_config(tmp_path)


def test_unknown_key_rejected(tmp_path):
    _write_system(tmp_path, {"version": 1, "bogus": 1})
    with pytest.raises(ConfigValidationError):
        load_config(tmp_path)


def test_save_config_roundtrip(tmp_path):
    target = tmp_path / "fresh"  # does not exist yet
    save_config(WorkspaceConfig(version=1), target)
    assert (target / SYSTEM_FILE).is_file()
    assert load_config(target).version == 1

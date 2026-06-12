import json

import pytest

from mono_control.config import (
    ConfigNotFoundError,
    ConfigParseError,
    ConfigValidationError,
    load_config,
)
from mono_control.paths import SYSTEM_FILE


def _write_system(config_dir, data):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / SYSTEM_FILE).write_text(json.dumps(data))


def test_load_empty_config(tmp_path):
    _write_system(tmp_path, {})
    config = load_config(tmp_path)
    assert config is not None


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
    _write_system(tmp_path, {"bogus": 1})
    with pytest.raises(ConfigValidationError):
        load_config(tmp_path)

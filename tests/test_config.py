"""Workspace config (system.json) loaded/saved over the broker's mono_config verbs."""

import pytest

from broker_shim import ShimBroker
from mono_control.config import (
    ConfigNotFoundError,
    ConfigValidationError,
    ConfigVersionError,
    WorkspaceConfig,
    load_config,
    save_config,
    system_exists,
)


@pytest.fixture
def broker(tmp_path):
    return ShimBroker(tmp_path / "config", tmp_path / "ws", tmp_path / "off")


def test_load_minimal_config(broker):
    broker.save_system({"version": 1})
    assert load_config(broker).version == 1


def test_missing_version(broker):
    broker.save_system({})
    with pytest.raises(ConfigVersionError):
        load_config(broker)


def test_version_too_new(broker):
    broker.save_system({"version": 2})
    with pytest.raises(ConfigVersionError):
        load_config(broker)


def test_missing_system(broker):
    assert not system_exists(broker)
    with pytest.raises(ConfigNotFoundError):
        load_config(broker)


def test_unknown_key_rejected(broker):
    broker.save_system({"version": 1, "bogus": 1})
    with pytest.raises(ConfigValidationError):
        load_config(broker)


def test_save_config_roundtrip(broker):
    assert not system_exists(broker)
    save_config(WorkspaceConfig(version=1), broker)
    assert system_exists(broker)
    assert load_config(broker).version == 1

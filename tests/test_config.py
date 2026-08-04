"""Workspace config (system.json) loaded/saved over the broker's mono_config verbs.

``system.json`` is **optional**: absence yields defaults. The tests below hold the
line that makes that safe — a file which *exists* is still validated exactly as
strictly, so "optional" never leaks into "unchecked".
"""

import pytest

from broker_shim import ShimBroker
from mono_control.config import (
    ConfigValidationError,
    ConfigVersionError,
    WorkspaceConfig,
    load_config,
    load_config_status,
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


def test_missing_system_yields_defaults(broker):
    """Absence is not an error. Real workspaces ran for months without the file."""
    assert not system_exists(broker)
    assert load_config(broker) == WorkspaceConfig()


def test_missing_system_reports_that_it_defaulted(broker):
    """Optional must not mean invisible — callers can tell defaults from a file."""
    config, from_disk = load_config_status(broker)
    assert from_disk is False
    assert config.version == 1


def test_present_system_reports_that_it_came_from_disk(broker):
    broker.save_system({"version": 1})
    config, from_disk = load_config_status(broker)
    assert from_disk is True
    assert config.version == 1


def test_defaults_match_what_config_init_would_write(broker):
    """The defaulted config and the materialized one must not drift apart."""
    defaulted = load_config(broker)
    save_config(WorkspaceConfig(version=1), broker)
    assert load_config(broker) == defaulted


def test_unknown_key_rejected(broker):
    """A file that exists is held to the schema exactly as before."""
    broker.save_system({"version": 1, "bogus": 1})
    with pytest.raises(ConfigValidationError):
        load_config(broker)


def test_a_malformed_file_still_raises_rather_than_defaulting(broker):
    """The dangerous failure mode: silently treating a broken file as absent."""
    broker.save_system({"version": 99})
    with pytest.raises(ConfigVersionError):
        load_config(broker)
    with pytest.raises(ConfigVersionError):
        load_config_status(broker)


def test_save_config_roundtrip(broker):
    assert not system_exists(broker)
    save_config(WorkspaceConfig(version=1), broker)
    assert system_exists(broker)
    assert load_config(broker).version == 1

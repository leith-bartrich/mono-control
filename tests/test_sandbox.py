import pytest

from mono_control import sandbox
from mono_control.sandbox import (
    BROKER_ENV,
    in_container,
    require_broker,
    require_container,
)


def _set_marker(monkeypatch, tmp_path, *, present: bool):
    """Point the container marker at a tmp path that does/doesn't exist."""
    marker = tmp_path / "mono-control-container"
    if present:
        marker.write_text("x")
    monkeypatch.setattr(sandbox, "CONTAINER_MARKER", marker)
    return marker


def test_in_container_true_when_marker_present(monkeypatch, tmp_path):
    _set_marker(monkeypatch, tmp_path, present=True)
    assert in_container() is True


def test_in_container_false_when_marker_absent(monkeypatch, tmp_path):
    _set_marker(monkeypatch, tmp_path, present=False)
    assert in_container() is False


def test_env_sentinel_does_not_bypass(monkeypatch, tmp_path):
    """The whole point of the marker: the old env var must NOT fake the container.

    Regression guard against the bypass this replaced — setting
    MONO_CONTROL_IN_CONTAINER while the marker is absent must still refuse.
    """
    _set_marker(monkeypatch, tmp_path, present=False)
    monkeypatch.setenv("MONO_CONTROL_IN_CONTAINER", "1")
    assert in_container() is False
    with pytest.raises(SystemExit):
        require_container()


def test_require_container_passes_when_marker_present(monkeypatch, tmp_path):
    _set_marker(monkeypatch, tmp_path, present=True)
    require_container()  # should not raise


def test_require_container_exits_when_marker_absent(monkeypatch, tmp_path):
    _set_marker(monkeypatch, tmp_path, present=False)
    with pytest.raises(SystemExit):
        require_container()


def test_require_broker_passes_when_all_set(monkeypatch):
    for name in BROKER_ENV:
        monkeypatch.setenv(name, "value")
    require_broker()  # should not raise


@pytest.mark.parametrize("missing", BROKER_ENV)
def test_require_broker_exits_when_any_missing(monkeypatch, missing):
    for name in BROKER_ENV:
        monkeypatch.setenv(name, "value")
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(SystemExit):
        require_broker()

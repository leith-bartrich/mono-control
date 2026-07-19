import pytest

from mono_control.sandbox import (
    BROKER_ENV,
    SENTINEL,
    in_container,
    require_broker,
    require_container,
)


def test_in_container_true_when_sentinel_set(monkeypatch):
    monkeypatch.setenv(SENTINEL, "1")
    assert in_container() is True


def test_in_container_false_when_unset(monkeypatch):
    monkeypatch.delenv(SENTINEL, raising=False)
    assert in_container() is False


def test_in_container_false_for_other_values(monkeypatch):
    monkeypatch.setenv(SENTINEL, "0")
    assert in_container() is False


def test_require_container_passes_when_set(monkeypatch):
    monkeypatch.setenv(SENTINEL, "1")
    require_container()  # should not raise


def test_require_container_exits_when_unset(monkeypatch):
    monkeypatch.delenv(SENTINEL, raising=False)
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

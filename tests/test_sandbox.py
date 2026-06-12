import pytest

from mono_control.sandbox import SENTINEL, in_container, require_container


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

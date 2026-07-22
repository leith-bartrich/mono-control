import pytest

from mono_control.config import source_names as sn


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("origin", ("origin", None)),
        ("upstream", ("upstream", None)),
        ("fork-ours", ("fork", "ours")),
        ("fork-bob", ("fork", "bob")),
        ("mirror-ours", ("mirror", "ours")),
        ("mirror-local-nas", ("mirror", "local-nas")),
        ("backup", ("other", None)),
        ("fork-", ("other", None)),  # empty purpose is not a governed copy
        ("forked-thing", ("other", None)),  # kind must be exactly fork/mirror
    ],
)
def test_split_key(key, expected):
    assert sn.split_key(key) == expected


def test_canonical_prefers_origin():
    assert sn.canonical({"origin": "u", "upstream": "v"}) == "origin"
    assert sn.canonical({"upstream": "v"}) == "upstream"
    assert sn.canonical({"fork-ours": "f"}) is None
    assert sn.canonical({}) is None


def test_writable_remote_origin_else_fork_ours():
    assert sn.writable_remote({"origin": "u", "fork-ours": "f"}) == "origin"
    assert sn.writable_remote({"upstream": "v", "fork-ours": "f"}) == "fork-ours"
    # A peer's fork is a tracked reference, never auto-selected.
    assert sn.writable_remote({"upstream": "v", "fork-bob": "f"}) is None
    assert sn.writable_remote({}) is None


def test_has_fork():
    assert sn.has_fork({"upstream": "v", "fork-ours": "f"}) is True
    assert sn.has_fork({"upstream": "v", "fork-bob": "f"}) is True
    assert sn.has_fork({"upstream": "v", "mirror-ours": "m"}) is False
    assert sn.has_fork({}) is False


def test_fork_key():
    assert sn.fork_key("ours") == "fork-ours"
    assert sn.fork_key("bob") == "fork-bob"

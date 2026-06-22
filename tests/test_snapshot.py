import json

import pytest

from mono_control.snapshot import (
    Snapshot,
    SnapshotEntry,
    SnapshotValidationError,
    SnapshotVersionError,
    load_snapshot,
)


def _snapshot() -> Snapshot:
    return Snapshot(
        entries={
            "alpha": SnapshotEntry(commit="a" * 40, location="alpha"),
            "beta": SnapshotEntry(commit="b" * 40, location="nested/beta"),
        },
        repo_set_id="set-1",
    )


def test_members_projects_entry_slugs():
    assert _snapshot().members() == {"alpha", "beta"}


def test_roundtrip_via_load_snapshot():
    snap = _snapshot()
    data = json.loads(snap.model_dump_json())
    assert load_snapshot(data) == snap


def test_unknown_key_rejected():
    with pytest.raises(SnapshotValidationError):
        load_snapshot({"version": 1, "entries": {}, "bogus": 1})


def test_unknown_entry_key_rejected():
    with pytest.raises(SnapshotValidationError):
        load_snapshot(
            {"version": 1, "entries": {"a": {"commit": "x", "location": "a", "oops": 1}}}
        )


def test_version_too_new():
    with pytest.raises(SnapshotVersionError):
        load_snapshot({"version": 2, "entries": {}})


def test_missing_version():
    with pytest.raises(SnapshotVersionError):
        load_snapshot({"entries": {}})

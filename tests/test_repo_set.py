import json

import pytest

from mono_control.repo_set import (
    RepoSet,
    RepoSetValidationError,
    RepoSetVersionError,
    load_repo_set,
    missing_members,
)
from mono_control.snapshot import Snapshot, SnapshotEntry


def test_members_returns_slugs():
    rs = RepoSet(id="core", slugs={"alpha", "beta"})
    assert rs.members() == {"alpha", "beta"}


def test_kind_defaults_to_repo_set_and_accepts_product():
    assert RepoSet(id="core").kind == "repo_set"
    assert RepoSet(id="thing", kind="product").kind == "product"


def test_roundtrip_via_load_repo_set():
    rs = RepoSet(id="core", kind="product", slugs={"alpha", "beta"})
    data = json.loads(rs.model_dump_json())
    assert load_repo_set(data) == rs


def test_missing_members_existence_gate():
    rs = RepoSet(id="core", slugs={"alpha", "beta", "gamma"})
    known = {"alpha", "beta"}  # gamma was purged (absent from config)
    assert missing_members(rs, known) == {"gamma"}
    assert missing_members(rs, {"alpha", "beta", "gamma"}) == set()


def test_missing_members_accepts_a_snapshot():
    # The protocol unifies them: a Snapshot is a RepoSetLike via members().
    snap = Snapshot(entries={"alpha": SnapshotEntry(commit="a" * 40, location="alpha")})
    assert missing_members(snap, {"alpha"}) == set()
    assert missing_members(snap, set()) == {"alpha"}


def test_unknown_key_rejected():
    with pytest.raises(RepoSetValidationError):
        load_repo_set({"version": 1, "id": "core", "bogus": 1})


def test_version_too_new():
    with pytest.raises(RepoSetVersionError):
        load_repo_set({"version": 2, "id": "core"})

"""RepoStore against the broker's mono_config verbs (served by the shim).

RepoStore keeps the container-side brain (validation, list filtering, the
retire/restore mutations, conflict/not-found rules); the raw ``<slug>.json`` IO
travels over the broker. The shim serves those verbs against a real config dir,
so these tests exercise the full round-trip.
"""

import json

import pytest

from broker_shim import ShimBroker
from mono_control.config import (
    ConfigConflictError,
    ConfigNotFoundError,
    ConfigValidationError,
    Repo,
    RepoStore,
)


@pytest.fixture
def store(tmp_path):
    broker = ShimBroker(tmp_path / "config", tmp_path / "ws", tmp_path / "off")
    return RepoStore(broker)


def _repo(slug="demo", **kw):
    return Repo(version=1, slug=slug, name=kw.pop("name", "Demo"), **kw)


def test_create_save_load_round_trip(store):
    repo = _repo(sources={"origin": "u"})
    store.create(repo)
    assert store.exists("demo")
    assert store.load("demo") == repo


def test_create_conflict(store):
    store.create(_repo())
    with pytest.raises(ConfigConflictError):
        store.create(_repo())


def test_save_overwrites(store):
    store.create(_repo(name="One"))
    store.save(_repo(name="Two"))
    assert store.load("demo").name == "Two"


def test_load_missing(store):
    with pytest.raises(ConfigNotFoundError):
        store.load("nope")


def test_filename_slug_mismatch(store):
    store.create(_repo(slug="demo"))
    # Rewrite the on-disk file to claim a different slug than its filename.
    path = store.broker.repos_dir / "demo.json"
    data = json.loads(path.read_text())
    data["slug"] = "other"
    path.write_text(json.dumps(data))
    with pytest.raises(ConfigValidationError):
        store.load("demo")


def test_list_filters_retired(store):
    store.create(_repo(slug="active"))
    store.create(_repo(slug="gone"))
    store.retire("gone")
    assert store.list() == ["active"]
    assert store.list(include_retired=True) == ["active", "gone"]


def test_retire_restore(store):
    store.create(_repo())
    assert store.retire("demo").retired is True
    assert store.load("demo").retired is True
    assert store.restore("demo").retired is False


def test_purge(store):
    store.create(_repo())
    store.purge("demo")
    assert not store.exists("demo")
    with pytest.raises(ConfigNotFoundError):
        store.purge("demo")


def test_list_empty(store):
    assert store.list() == []

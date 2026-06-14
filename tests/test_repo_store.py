import json

import pytest

from mono_control.config import (
    ConfigConflictError,
    ConfigNotFoundError,
    ConfigValidationError,
    Repo,
    RepoStore,
)
from mono_control.paths import REPOS_SUBDIR


@pytest.fixture
def store(tmp_path):
    return RepoStore(tmp_path / "repos")


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
    # Rewrite the file's content to claim a different slug than its filename.
    data = json.loads(store.path_for("demo").read_text())
    data["slug"] = "other"
    store.path_for("demo").write_text(json.dumps(data))
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


def test_from_config_dir(tmp_path):
    store = RepoStore.from_config_dir(tmp_path)
    assert store.directory == tmp_path / REPOS_SUBDIR


def test_list_empty_dir(store):
    assert store.list() == []

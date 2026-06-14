import json

import pytest

from mono_control.config import Repo


def test_minimal_repo():
    repo = Repo(version=1, slug="demo", name="Demo")
    assert repo.slug == "demo"
    assert repo.sources == {}
    assert repo.branches == {}
    assert repo.retired is False


def test_named_maps():
    repo = Repo(
        version=1,
        slug="app",
        name="App",
        sources={"origin": "git@example.com:app.git"},
        branches={"main": "main", "dev": "develop"},
    )
    assert repo.sources["origin"].endswith("app.git")
    assert repo.branches["dev"] == "develop"


@pytest.mark.parametrize("bad", ["Demo", "-leading", "has space", "UPPER", ""])
def test_invalid_slug_rejected(bad):
    with pytest.raises(ValueError):
        Repo(version=1, slug=bad, name="x")


def test_unknown_key_rejected():
    with pytest.raises(ValueError):
        Repo(version=1, slug="demo", name="Demo", bogus=1)


def test_json_round_trip():
    repo = Repo(version=1, slug="app", name="App", sources={"origin": "u"})
    text = repo.model_dump_json()
    restored = Repo.load(json.loads(text))
    assert restored == repo

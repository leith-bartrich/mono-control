import pytest

from broker_shim import ShimBroker
from mono_control.config import (
    AmbiguousNameError,
    ConfigNotFoundError,
    Repo,
    RepoStore,
    resolve_repo,
)


@pytest.fixture
def store(tmp_path) -> RepoStore:
    broker = ShimBroker(tmp_path / "config", tmp_path / "ws", tmp_path / "off")
    return RepoStore(broker)


def test_slug_only_loads_by_slug(store):
    store.create(Repo(version=1, slug="alpha", name="Alpha"))
    repo = resolve_repo(store, "alpha", slug_only=True)
    assert repo.slug == "alpha"


def test_slug_only_misses_raise(store):
    with pytest.raises(ConfigNotFoundError):
        resolve_repo(store, "nope", slug_only=True)


def test_slug_only_does_not_fall_back_to_name(store):
    store.create(Repo(version=1, slug="actual-slug-a1b2", name="alpha"))
    # Slug-only mode must ignore the name fallback even if the name matches.
    with pytest.raises(ConfigNotFoundError):
        resolve_repo(store, "alpha", slug_only=True)


def test_name_fallback_via_slugified_comparison(store):
    store.create(Repo(version=1, slug="my-util-a1b2", name="My Util"))
    repo = resolve_repo(store, "My Util")
    assert repo.slug == "my-util-a1b2"


def test_name_lookup_is_case_insensitive(store):
    store.create(Repo(version=1, slug="alpha-a1b2", name="Alpha"))
    assert resolve_repo(store, "alpha").slug == "alpha-a1b2"
    assert resolve_repo(store, "ALPHA").slug == "alpha-a1b2"


def test_slug_wins_when_both_could_match(store):
    # Repo A: slug "demo" (explicit/legacy, not slug-shaped); name "Different"
    # Repo B: slug "x-a1b2"; name "demo"
    # Looking up "demo" should hit slug A (slug wins).
    store.create(Repo(version=1, slug="demo", name="Different"))
    store.create(Repo(version=1, slug="x-a1b2", name="demo"))
    repo = resolve_repo(store, "demo")
    assert repo.slug == "demo"


def test_ambiguous_name_raises(store):
    store.create(Repo(version=1, slug="util-a1b2", name="Util"))
    store.create(Repo(version=1, slug="util-c3d4", name="util"))  # case-insensitive
    with pytest.raises(AmbiguousNameError) as exc:
        resolve_repo(store, "util")
    assert set(exc.value.candidate_slugs) == {"util-a1b2", "util-c3d4"}


def test_not_found_raises(store):
    with pytest.raises(ConfigNotFoundError):
        resolve_repo(store, "ghost")


def test_resolves_retired_repos_too(store):
    store.create(Repo(version=1, slug="gone-a1b2", name="Gone"))
    store.retire("gone-a1b2")
    repo = resolve_repo(store, "Gone")
    assert repo.slug == "gone-a1b2"
    assert repo.retired is True

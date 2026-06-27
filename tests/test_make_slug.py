import re

import pytest

from mono_control.config import is_slug_shaped, make_slug


def _never(_slug: str) -> bool:
    return False


def test_shape_is_stem_dash_four_hex():
    slug = make_slug("My Util", exists=_never)
    assert re.match(r"^my-util-[0-9a-f]{4}$", slug)


def test_uses_slugified_stem():
    slug = make_slug("Hello World!", exists=_never)
    assert slug.startswith("hello-world-")


def test_is_slug_shaped_returns_true_for_output():
    slug = make_slug("anything", exists=_never)
    assert is_slug_shaped(slug)


def test_rehash_on_collision():
    call_count = {"n": 0}

    def exists(_slug: str) -> bool:
        call_count["n"] += 1
        return call_count["n"] < 3  # collide twice, then accept

    slug = make_slug("util", exists=exists)
    assert slug.startswith("util-")
    assert call_count["n"] == 3  # took two rehashes


def test_raises_after_max_retries():
    def always_exists(_slug: str) -> bool:
        return True

    with pytest.raises(RuntimeError, match="could not produce a unique slug"):
        make_slug("util", exists=always_exists)


def test_consecutive_calls_produce_different_slugs():
    a = make_slug("util", exists=_never)
    b = make_slug("util", exists=_never)
    assert a != b  # randomness ensures distinct hashes
    assert a.split("-")[:-1] == b.split("-")[:-1]  # same stem


def test_unslugifiable_name_raises():
    with pytest.raises(ValueError):
        make_slug("!!!", exists=_never)


def test_is_slug_shaped_false_for_bare_stem():
    assert not is_slug_shaped("my-util")  # no hash suffix


def test_is_slug_shaped_false_for_wrong_hash_length():
    assert not is_slug_shaped("my-util-abc")  # 3 chars, not 4
    assert not is_slug_shaped("my-util-abcde")  # 5 chars, not 4


def test_is_slug_shaped_false_for_non_hex_suffix():
    assert not is_slug_shaped("my-util-zzzz")  # z is not hex

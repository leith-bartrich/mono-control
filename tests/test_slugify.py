import pytest

from mono_control.config import slugify


def test_lowercases():
    assert slugify("Hello") == "hello"


def test_whitespace_runs_become_single_dash():
    assert slugify("hello   world") == "hello-world"


def test_tabs_and_newlines_count_as_whitespace():
    assert slugify("hello\tworld\ngoodbye") == "hello-world-goodbye"


def test_drops_punctuation_and_unicode():
    assert slugify("café! v2 (final)") == "caf-v2-final"


def test_collapses_repeated_dashes_from_input():
    assert slugify("a----b") == "a-b"


def test_strips_leading_dashes():
    assert slugify("---hello") == "hello"


def test_existing_clean_slug_is_idempotent():
    assert slugify("my-cool-app") == "my-cool-app"


def test_empty_input_raises():
    with pytest.raises(ValueError):
        slugify("")


def test_whitespace_only_raises():
    with pytest.raises(ValueError):
        slugify("   ")


def test_only_punctuation_raises():
    with pytest.raises(ValueError):
        slugify("!!!???")


def test_strips_dots_and_underscores():
    # Dots and underscores are explicitly NOT in the slug character class
    # (slug pattern is [a-z0-9-]). slugify drops them.
    assert slugify("my.cool_app") == "mycoolapp"

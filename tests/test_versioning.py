"""Exercise VersionedModel's migrate-up-then-validate machinery with a toy model.

The documents under test are written as **actual JSON text** (as they would
exist on disk) and parsed with ``json.loads`` before loading — dogfooding the
real path: serialized JSON in, current model out. Crucially there is **no v1
model in code**; a v1 document exists only as the JSON text below, and the
migration upgrades the parsed dict.
"""

import json
from typing import Literal

import pytest

from mono_control.config import ConfigVersionError, VersionedModel


def _v1_to_v2(data: dict) -> dict:
    # v1 stored the field as `name`; v2 renames it to `title` and bumps version.
    # This is the ONLY code that knows the v1 shape — there is no ThingV1 model.
    return {"version": 2, "title": data["name"]}


class Thing(VersionedModel):
    """Current shape is v2; a v1 document migrates up to it."""

    CURRENT_VERSION = 2
    MIGRATIONS = {1: _v1_to_v2}

    version: Literal[2] = 2
    title: str


# Documents exactly as they would sit in a JSON file on disk.
THING_V1_JSON = '{"version": 1, "name": "hello"}'
THING_V2_JSON = '{"version": 2, "title": "hello"}'


def test_v1_json_migrates_to_current_without_a_v1_model():
    # The v1 document is only this serialized text — no ThingV1 class exists.
    thing = Thing.load(json.loads(THING_V1_JSON))
    assert thing.version == 2
    assert thing.title == "hello"


def test_current_version_json_passes_through():
    thing = Thing.load(json.loads(THING_V2_JSON))
    assert thing.title == "hello"


def test_missing_version():
    with pytest.raises(ConfigVersionError):
        Thing.load(json.loads('{"title": "hello"}'))


def test_version_too_new():
    with pytest.raises(ConfigVersionError):
        Thing.load(json.loads('{"version": 3, "title": "hello"}'))


def test_unmigratable_version():
    class Gapped(VersionedModel):
        CURRENT_VERSION = 3
        MIGRATIONS = {1: _v1_to_v2}  # no migration registered from 2 -> 3
        version: Literal[3] = 3
        title: str

    with pytest.raises(ConfigVersionError):
        Gapped.load(json.loads(THING_V1_JSON))


def test_migration_must_advance():
    class Stuck(VersionedModel):
        CURRENT_VERSION = 2
        MIGRATIONS = {1: lambda data: {"version": 1, "title": "x"}}  # forgets to bump
        version: Literal[2] = 2
        title: str

    with pytest.raises(ConfigVersionError):
        Stuck.load(json.loads(THING_V1_JSON))

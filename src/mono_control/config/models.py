"""Pydantic models for the mono-config manifest.

Each persisted document is a versioned pydantic model (see ``VersionedModel`` in
``mono_control.base_models``): it carries a ``version`` discriminator and is
migrated up to the current shape at load time. PROVISIONAL: ``WorkspaceConfig``
has no real fields yet — the actual schema (repos, named states, ref pinning, and
how the config directory's named files map onto models) is still being designed.
Strict by default so unknown keys surface as validation errors as the schema
grows.
"""

import re
from typing import Literal

from pydantic import field_validator

from ..base_models import VersionedModel

# Filename-safe immutable slug: starts alphanumeric, then alphanumerics plus
# `.`, `_`, `-`. Used as a repo's identity and as its `<slug>.json` filename.
SLUG_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"


class WorkspaceConfig(VersionedModel):
    """Assembled view of the whole mono-config directory.

    PROVISIONAL: no fields beyond ``version`` yet. Populated from ``system.json``
    (plus future named files) once the directory layout is designed.
    """

    CURRENT_VERSION = 1
    version: Literal[1] = 1
    # TODO(design): repos, named states, ref pinning, per-file structure.


class Repo(VersionedModel):
    """A managed repository definition.

    Stored as ``mono-config/repos/<slug>.json``. The ``slug`` is the immutable
    identity (and filename key); ``name`` is a free, mutable display label.
    ``sources`` and ``branches`` are named maps — conventions for what individual
    source/branch names *mean* (which source is "origin", which branch is "main"
    or "dev") are deferred. ``retired`` is the soft-delete tombstone flag.
    """

    CURRENT_VERSION = 1
    version: Literal[1] = 1
    slug: str
    name: str
    sources: dict[str, str] = {}  # name -> url (named remotes)
    branches: dict[str, str] = {}  # name -> branch (named important branches)
    retired: bool = False

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, value: str) -> str:
        if not re.match(SLUG_PATTERN, value):
            raise ValueError(
                f"invalid slug {value!r}: must match {SLUG_PATTERN}"
            )
        return value

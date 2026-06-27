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
import secrets
from typing import Callable, Literal

from pydantic import field_serializer, field_validator

from ..base_models import VersionedModel

# Filename-safe immutable slug: starts alphanumeric, then alphanumerics plus
# `-`. Used as a repo's identity and as its `<slug>.json` filename. Matches
# what `slugify()` produces (lowercase + digits + dashes only); dots are
# reserved for a future ``name.slug`` disk-stamping convention.
SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]*$"

# A slug shaped like ``<name-part>-<4 hex digits>`` — i.e. one that looks like
# ``make_slug()`` produced it. Useful UX heuristic (e.g. for help text); not
# load-bearing in the lookup, which always tries slug first regardless.
_HASH_LEN = 4
SLUG_SHAPED_PATTERN = rf"^[a-z0-9][a-z0-9-]*-[0-9a-f]{{{_HASH_LEN}}}$"


def slugify(text: str) -> str:
    """Derive a filesystem-safe slug fragment from free-form ``text``.

    Lowercase → whitespace runs to ``-`` → drop everything not in
    ``[a-z0-9-]`` → collapse repeated ``-`` → strip leading ``-``. Raises
    ``ValueError`` if the result is empty (no usable characters).
    """
    s = text.lower().strip()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)
    s = re.sub(r"-{2,}", "-", s)
    s = s.lstrip("-")
    if not s:
        raise ValueError(f"cannot derive a slug from {text!r}")
    return s


def make_slug(
    name: str,
    *,
    exists: Callable[[str], bool],
    max_retries: int = 5,
) -> str:
    """Build a unique slug for ``name``: ``slugify(name)-<4 hex chars>``.

    Rehash up to ``max_retries`` times if ``exists(slug)`` is True; raise
    ``RuntimeError`` after exhausting retries (astronomically unlikely with
    a 65k hash space, but cap to keep this bounded).
    """
    stem = slugify(name)
    for _ in range(max_retries):
        slug = f"{stem}-{secrets.token_hex(_HASH_LEN // 2)}"
        if not exists(slug):
            return slug
    raise RuntimeError(
        f"could not produce a unique slug for {name!r} after {max_retries} attempts"
    )


def is_slug_shaped(s: str) -> bool:
    """True iff ``s`` looks like a ``make_slug``-produced slug."""
    return bool(re.match(SLUG_SHAPED_PATTERN, s))


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
    ``aspects`` is the set of declared repo-aspect names (e.g. ``"product-cluster"``)
    — enough for discovery from config alone, without checking the repo out.
    """

    CURRENT_VERSION = 1
    version: Literal[1] = 1
    slug: str
    name: str
    sources: dict[str, str] = {}  # name -> url (named remotes)
    branches: dict[str, str] = {}  # name -> branch (named important branches)
    retired: bool = False
    aspects: set[str] = set()  # declared repo-aspect names (e.g. "product-cluster")

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, value: str) -> str:
        if not re.match(SLUG_PATTERN, value):
            raise ValueError(
                f"invalid slug {value!r}: must match {SLUG_PATTERN}"
            )
        return value

    @field_serializer("aspects")
    def _sort_aspects(self, value: set[str]) -> list[str]:
        # Stable JSON output so committed repo defs don't churn between writes.
        return sorted(value)

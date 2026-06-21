"""Reusable pydantic base classes for versioned config documents.

This is the generic model machinery shared by every config abstraction
(``Repo``, and the upcoming repo-set / target / snapshot models): a strict base
that rejects unknown keys, and ``VersionedModel``'s migrate-up-then-validate
engine. The concrete domain models live in ``config/models.py``.

Note: ``VersionedModel`` raises ``ConfigVersionError`` from ``config.errors`` —
an intentional upward import into the ``config`` subpackage. ``config/errors.py``
is a dependency-free leaf, so there is no import cycle.
"""

from typing import Callable, ClassVar, Self

from pydantic import BaseModel, ConfigDict

from mono_control.config.errors import ConfigVersionError


class StrictModel(BaseModel):
    """Base model that rejects unknown keys (catches manifest typos)."""

    model_config = ConfigDict(extra="forbid")


class VersionedModel(StrictModel):
    """Base for versioned config documents loaded from JSON.

    A document carries an integer ``version``. Subclasses set ``CURRENT_VERSION``
    and (as needed) ``MIGRATIONS`` — an ordered chain of pure ``dict -> dict``
    functions, each mapping version ``v`` to a ``v + 1`` shaped dict — and narrow
    ``version`` to a ``Literal`` so a botched migration can't silently pass.

    Loading is migrate-up-then-validate: ``load`` walks the raw dict from its own
    version to ``CURRENT_VERSION`` and then validates. Migration is in-memory
    only; nothing is written back.
    """

    CURRENT_VERSION: ClassVar[int]
    MIGRATIONS: ClassVar[dict[int, Callable[[dict], dict]]] = {}

    version: int  # subclasses override, e.g. ``version: Literal[1] = 1``

    @classmethod
    def load(cls, data: dict) -> Self:
        """Migrate ``data`` up to the current version, then validate it."""
        return cls.model_validate(cls._migrate(dict(data)))

    @classmethod
    def _migrate(cls, data: dict) -> dict:
        v = data.get("version")
        if not isinstance(v, int):
            raise ConfigVersionError("missing or invalid 'version'")
        if v > cls.CURRENT_VERSION:
            raise ConfigVersionError(
                f"version {v} is newer than supported {cls.CURRENT_VERSION}"
            )
        while v < cls.CURRENT_VERSION:
            migrate = cls.MIGRATIONS.get(v)
            if migrate is None:
                raise ConfigVersionError(f"no migration from version {v}")
            data = migrate(data)
            nv = data.get("version")
            if not isinstance(nv, int) or nv <= v:
                raise ConfigVersionError(
                    f"migration from version {v} did not advance the version"
                )
            v = nv
        return data

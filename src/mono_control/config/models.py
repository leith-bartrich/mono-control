"""Pydantic models for the mono-config manifest.

Each persisted document is a versioned pydantic model (see ``VersionedModel``):
it carries a ``version`` discriminator and is migrated up to the current shape at
load time. PROVISIONAL: ``WorkspaceConfig`` has no real fields yet — the actual
schema (repos, named states, ref pinning, and how the config directory's named
files map onto models) is still being designed. Strict by default so unknown
keys surface as validation errors as the schema grows.
"""

from typing import Callable, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict

from .errors import ConfigVersionError


class _Strict(BaseModel):
    """Base model that rejects unknown keys (catches manifest typos)."""

    model_config = ConfigDict(extra="forbid")


class VersionedModel(_Strict):
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


class WorkspaceConfig(VersionedModel):
    """Assembled view of the whole mono-config directory.

    PROVISIONAL: no fields beyond ``version`` yet. Populated from ``system.json``
    (plus future named files) once the directory layout is designed.
    """

    CURRENT_VERSION = 1
    version: Literal[1] = 1
    # TODO(design): repos, named states, ref pinning, per-file structure.

"""Pydantic models for the mono-config manifest.

PROVISIONAL placeholder. The schema is intentionally empty for now — the actual
fields (repos, named states, ref pinning, and how the config directory's named
files map onto models) are still being designed. Strict by default so unknown
keys surface as validation errors as the schema grows.
"""

from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    """Base model that rejects unknown keys (catches manifest typos)."""

    model_config = ConfigDict(extra="forbid")


class WorkspaceConfig(_Strict):
    """Assembled view of the whole mono-config directory.

    PROVISIONAL: no fields yet. Populated from ``system.json`` (plus future
    named files) once the directory layout is designed.
    """

    # TODO(design): repos, named states, ref pinning, per-file structure.

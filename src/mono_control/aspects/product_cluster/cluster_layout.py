"""The cluster layout: a product cluster's authored repo arrangement.

A product cluster holds a single layout document —
``product-cluster/default-layout.json`` inside the materialized cluster checkout —
mapping member repo slugs to a location under ``mono-repos/`` and a role
(``dev`` | ``dep``). See
``docs/design/layers/repo-aspects/product-cluster/layout.md``.

The layout is a versioned document (reuses ``base_models``) read/written through
``ClusterLayoutStore``, mirroring ``config.RepoStore``. Member identity is the
workspace [slug]; the key set of ``members`` *is* the cluster's membership.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from mono_control.base_models import StrictModel, VersionedModel, VersionError
from mono_control.on_disk import scan

# The aspect's content subdir inside a cluster checkout, and the layout filename.
# ``default-`` leaves room for snapshot-derived / archived layouts later.
ASPECT_SUBDIR = "product-cluster"
LAYOUT_FILENAME = "default-layout.json"


# --------------------------------------------------------------------------- #
# Typed errors (mirror ``config.errors``; translated at the load boundary)
# --------------------------------------------------------------------------- #
class ClusterLayoutError(Exception):
    """Base class for cluster-layout load/validation failures."""


class ClusterLayoutNotFoundError(ClusterLayoutError):
    """The layout file — or the materialized cluster that holds it — is missing."""


class ClusterLayoutParseError(ClusterLayoutError):
    """The layout file exists but is not valid JSON."""


class ClusterLayoutValidationError(ClusterLayoutError):
    """The layout file parsed but did not match the schema."""


class ClusterLayoutVersionError(ClusterLayoutError):
    """The layout's version is missing, unknown, too new, or un-migratable."""


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #
class LayoutMember(StrictModel):
    """One member repo's placement + role within a cluster layout."""

    location: str  # subdir under mono-repos/ where the member materializes
    role: Literal["dev", "dep"]


class ClusterLayout(VersionedModel):
    """A product cluster's single authored arrangement of member repos.

    ``members`` is keyed by workspace [slug]; the key set is the cluster's
    membership. See
    ``docs/design/layers/repo-aspects/product-cluster/layout.md``.
    """

    CURRENT_VERSION = 1
    version: Literal[1] = 1
    members: dict[str, LayoutMember] = {}  # slug -> member


def load_cluster_layout(data: dict) -> ClusterLayout:
    """Deserialize-and-validate a layout dict, surfacing layout-typed errors.

    The deserialize boundary (counterpart to ``config.load_config`` /
    ``snapshot.load_snapshot``): translates the neutral ``VersionError`` and
    pydantic ``ValidationError`` into layout-typed errors.
    """
    try:
        return ClusterLayout.load(data)
    except VersionError as e:
        raise ClusterLayoutVersionError(str(e)) from e
    except ValidationError as e:
        raise ClusterLayoutValidationError(str(e)) from e


# --------------------------------------------------------------------------- #
# Store — reads/writes default-layout.json inside a cluster checkout
# --------------------------------------------------------------------------- #
def _read_json(path: Path) -> dict:
    """Read and parse the layout JSON, wrapping failures as ClusterLayoutError."""
    try:
        raw = path.read_text()
    except FileNotFoundError as e:
        raise ClusterLayoutNotFoundError(f"layout file not found: {path}") from e
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ClusterLayoutParseError(f"{path} is not valid JSON: {e}") from e


class ClusterLayoutStore:
    """Reads and writes a cluster's ``default-layout.json`` inside its checkout."""

    def __init__(self, checkout: Path) -> None:
        self.checkout = checkout
        self.directory = checkout / ASPECT_SUBDIR

    def path(self) -> Path:
        return self.directory / LAYOUT_FILENAME

    def exists(self) -> bool:
        return self.path().is_file()

    def load(self) -> ClusterLayout:
        """Load and validate the layout file (raises ClusterLayoutError)."""
        return load_cluster_layout(_read_json(self.path()))

    def load_or_empty(self) -> ClusterLayout:
        """Load the layout, or a fresh empty one if no file exists yet."""
        if self.exists():
            return self.load()
        return ClusterLayout(version=1)

    def save(self, layout: ClusterLayout) -> None:
        """Write the layout with the standard JSON conventions (indent + newline)."""
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path().write_text(layout.model_dump_json(indent=2) + "\n")


def resolve_cluster_checkout(
    slug: str,
    *,
    workspace_root: Path,
    offline_root: Path,
    require_materialized: bool = True,
) -> Path:
    """Return the absolute checkout path of a cluster, or raise.

    The layout lives *inside* the cluster, so the cluster must be on disk to read
    or write it. By default it must be **materialized** (the case for authoring
    via the ``layout`` verbs). ``require_materialized=False`` also accepts an
    **offline** checkout — used when a swap reads a freshly-acquired cluster's
    layout *before* placing it.
    """
    observed = scan(workspace_root, offline_root).repos.get(slug)
    if observed is None:
        raise ClusterLayoutNotFoundError(f"{slug!r} is not present locally")
    if require_materialized and observed.state != "materialized":
        raise ClusterLayoutNotFoundError(
            f"{slug!r} is not materialized; place it first "
            f"(`mat moveto` or `conform swap`)"
        )
    return observed.location

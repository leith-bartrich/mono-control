"""The cluster layout: a product cluster's authored repo arrangement.

A product cluster holds a single layout document —
``product-cluster/default-layout.json`` inside the materialized cluster worktree —
mapping member repo slugs to a location under ``mono-work/`` and a role
(``dev`` | ``dep``). See
``docs/design/layers/repo-aspects/product-cluster/layout.md``.

The layout is a versioned document (reuses ``base_models``) read/written through
``ClusterLayoutStore``, mirroring ``config.RepoStore``. Member identity is the
workspace [slug]; the key set of ``members`` *is* the cluster's membership.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from mono_control.base_models import StrictModel, VersionedModel, VersionError
from mono_control.broker import BrokerProtocol
from mono_control.on_disk import OnDiskRepo, scan

# The aspect's content subdir inside a cluster checkout, and the layout filename.
# ``default-`` leaves room for snapshot-derived / archived layouts later. These
# are now host-side constants the broker honors; the container names clusters by
# slug and reads/writes their layout over the ``read_layout`` / ``write_layout``
# verbs rather than touching the file.
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

    location: str  # subdir under mono-work/ where the member's worktree materializes
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
# Store — reads/writes default-layout.json inside a cluster checkout, via broker
# --------------------------------------------------------------------------- #
class ClusterLayoutStore:
    """Reads and writes a cluster's ``default-layout.json`` over the broker.

    The document lives inside the (host-side) managed checkout, so the container
    reaches it through the ``read_layout`` / ``write_layout`` verbs keyed by the
    cluster's slug. Presence / materialization must be validated first (see
    :func:`require_cluster_present`).
    """

    def __init__(self, broker: BrokerProtocol, cluster_slug: str) -> None:
        self.broker = broker
        self.cluster_slug = cluster_slug

    def exists(self) -> bool:
        return self.broker.read_layout(self.cluster_slug).exists

    def load(self) -> ClusterLayout:
        """Load and validate the layout document (raises ClusterLayoutError)."""
        result = self.broker.read_layout(self.cluster_slug)
        if not result.exists or result.layout is None:
            raise ClusterLayoutNotFoundError(
                f"no layout authored for {self.cluster_slug!r}"
            )
        return load_cluster_layout(result.layout)

    def load_or_empty(self) -> ClusterLayout:
        """Load the layout, or a fresh empty one if none is authored yet."""
        result = self.broker.read_layout(self.cluster_slug)
        if not result.exists or result.layout is None:
            return ClusterLayout(version=1)
        return load_cluster_layout(result.layout)

    def save(self, layout: ClusterLayout) -> None:
        """Write the layout document over the broker (JSON-native form)."""
        self.broker.write_layout(
            self.cluster_slug, layout.model_dump(mode="json")
        )


def require_cluster_present(
    broker: BrokerProtocol,
    slug: str,
    *,
    work_root: Path,
    bare_root: Path,
    require_materialized: bool = True,
) -> OnDiskRepo:
    """Return the cluster's observed repo, or raise if it can't hold a layout.

    The layout lives *inside* the cluster, so the cluster must be on disk to read
    or write it. By default it must be **materialized** — have a worktree (the case
    for authoring via the ``layout`` verbs). ``require_materialized=False`` also
    accepts an **offline** bare repo (the layout is read from its HEAD blob) — used
    when a swap reads a freshly-acquired cluster's layout *before* placing it.
    """
    observed = scan(broker, work_root, bare_root).repos.get(slug)
    if observed is None:
        raise ClusterLayoutNotFoundError(f"{slug!r} is not present locally")
    if require_materialized and observed.state != "materialized":
        raise ClusterLayoutNotFoundError(
            f"{slug!r} is not materialized; place it first "
            f"(`mat moveto` or `conform swap`)"
        )
    return observed

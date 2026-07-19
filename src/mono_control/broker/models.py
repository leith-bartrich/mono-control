"""Wire models for the host-side broker contract.

The broker relocates git + filesystem *effects* to a host-side JSON-RPC endpoint
the container calls back to. These are the JSON-native shapes that cross that
wire — the serializable mirror of the in-memory ``on_disk`` observation
(``OnDiskRepo`` / ``OnDiskInventory``).

Where the ``on_disk`` models carry *absolute* ``Path`` s (they never leave the
process), the wire models carry *relative* location strings plus the observed
``state``. Absolute paths are reconstructed at the container boundary from the
workspace / offline roots via the free functions below, so the rest of the app
keeps consuming its internal ``OnDiskInventory`` type unchanged.

These run in the container (where pydantic already lives), so they subclass the
repo's ``StrictModel`` and reject unknown keys — a wire-typo guard.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Literal

from ..base_models import StrictModel
from ..on_disk.models import OnDiskInventory, OnDiskRepo

State = Literal["offline", "materialized"]


class BrokerError(Exception):
    """A JSON-RPC error returned by the broker (carries the wire ``code``).

    Raised by the client when the broker answers with an ``error`` envelope, and
    by the in-process fake for unregistered methods. ``code`` is the JSON-RPC
    error code; ``message`` the human-readable text.
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


class WireRepo(StrictModel):
    """One observed checkout in JSON-native form (relative location + state)."""

    slug: str
    location: str  # RELATIVE to the state's root, e.g. "ltx-2" or an offline dir
    state: State
    commit: str | None
    dirty: bool


class WireUnmanaged(StrictModel):
    """An unmanaged (unstamped) checkout found under one of the roots.

    Like ``WireRepo`` it carries a relative ``location`` plus the ``state`` that
    says which root the location is relative to — so a foreign tree found under
    the offline root round-trips back to the offline root, not the workspace one.
    """

    location: str  # RELATIVE to the state's root
    state: State


class WireInventory(StrictModel):
    """The on-disk observation in JSON-native form: managed repos + unmanaged."""

    repos: list[WireRepo] = []
    unmanaged: list[WireUnmanaged] = []


def _root_for(state: State, workspace_root: Path, offline_root: Path) -> Path:
    """The root a ``state``'s relative location is reconstructed against."""
    return workspace_root if state == "materialized" else offline_root


def wire_repo_from_on_disk(
    repo: OnDiskRepo, workspace_root: Path, offline_root: Path
) -> WireRepo:
    """Project an ``OnDiskRepo`` to its wire form (absolute -> relative location)."""
    root = _root_for(repo.state, workspace_root, offline_root)
    relative = repo.location.relative_to(root)
    return WireRepo(
        slug=repo.slug,
        location=relative.as_posix(),
        state=repo.state,
        commit=repo.commit,
        dirty=repo.dirty,
    )


def wire_repo_to_on_disk(
    wire: WireRepo, workspace_root: Path, offline_root: Path
) -> OnDiskRepo:
    """Reconstruct an ``OnDiskRepo`` (absolute location) from its wire form."""
    root = _root_for(wire.state, workspace_root, offline_root)
    location = root / PurePosixPath(wire.location)
    return OnDiskRepo(
        slug=wire.slug,
        location=location,
        state=wire.state,
        commit=wire.commit,
        dirty=wire.dirty,
    )


def wire_unmanaged_from_on_disk(
    path: Path, workspace_root: Path, offline_root: Path
) -> WireUnmanaged:
    """Project an unmanaged absolute path to its wire form.

    The discriminator is which root the path lives under, so an offline foreign
    tree round-trips back to the offline root rather than the workspace one.
    """
    if path.is_relative_to(workspace_root):
        return WireUnmanaged(
            location=path.relative_to(workspace_root).as_posix(), state="materialized"
        )
    if path.is_relative_to(offline_root):
        return WireUnmanaged(
            location=path.relative_to(offline_root).as_posix(), state="offline"
        )
    raise ValueError(f"unmanaged path {path} is under neither root")


def wire_unmanaged_to_on_disk(
    wire: WireUnmanaged, workspace_root: Path, offline_root: Path
) -> Path:
    """Reconstruct an unmanaged absolute path from its wire form."""
    root = _root_for(wire.state, workspace_root, offline_root)
    return root / PurePosixPath(wire.location)


def wire_inventory_from_on_disk(
    inventory: OnDiskInventory, workspace_root: Path, offline_root: Path
) -> WireInventory:
    """Project an ``OnDiskInventory`` to its wire form.

    Repo and unmanaged locations are each made relative to the root implied by
    their ``state``, so both round-trip back to the root they were found under.
    """
    return WireInventory(
        repos=[
            wire_repo_from_on_disk(repo, workspace_root, offline_root)
            for repo in inventory.repos.values()
        ],
        unmanaged=[
            wire_unmanaged_from_on_disk(path, workspace_root, offline_root)
            for path in inventory.unmanaged
        ],
    )


def wire_inventory_to_on_disk(
    wire: WireInventory, workspace_root: Path, offline_root: Path
) -> OnDiskInventory:
    """Reconstruct an ``OnDiskInventory`` (absolute paths) from its wire form.

    The inverse of ``wire_inventory_from_on_disk``: each repo and unmanaged path's
    absolute location is rebuilt from its ``state`` + the matching root. Repos are
    keyed by slug, matching ``scanner.scan``.
    """
    repos = {
        w.slug: wire_repo_to_on_disk(w, workspace_root, offline_root)
        for w in wire.repos
    }
    unmanaged = [
        wire_unmanaged_to_on_disk(u, workspace_root, offline_root)
        for u in wire.unmanaged
    ]
    return OnDiskInventory(repos=repos, unmanaged=unmanaged)


# --------------------------------------------------------------------------- #
# Verb request / response models
#
# One request + response pair per broker verb. ``status`` fields are plain
# ``str`` on the wire (the container re-validates them into the typed
# ``SourceStatus`` / ``LayoutStatus`` literals when it rehydrates the internal
# ``*Outcome`` models) so this module stays a leaf that never imports the
# engines. Requests exist so ``emit_schema`` publishes the full contract and the
# typed client can author calls from a single source of truth.
# --------------------------------------------------------------------------- #


# --- git pack: acquire (source engine's effecting half) --------------------- #
class AcquireRequest(StrictModel):
    """Ask the broker to make ``refs`` locally resolvable for ``slug``.

    The broker resolves the source URL from mono-config (never trusted from the
    container), clones / inits / fetches as needed, verifies each requested ref,
    and returns a ``SourceOutcome``-shaped result. ``initial_branch`` names the
    branch a brand-new (source-less) repo is initialized on.
    """

    slug: str
    refs: list[str] = []
    initial_branch: str | None = None


class AcquireResult(StrictModel):
    """A ``SourceOutcome`` in JSON-native form (plus the ref→commit ``resolved`` map).

    ``resolved`` gives ``plan()`` the concrete commit for a requested ref (e.g. a
    ``PresentBranchHead`` target's ``refs/heads/<branch>``) as plain data, so the
    plan stage needs no git read of its own.
    """

    status: str
    summary: str
    unresolved_refs: list[str] = []
    resolved: dict[str, str] = {}


# --- git pack: layout effects (place / relocate / retire / checkout) -------- #
class LayoutOpRequest(StrictModel):
    """Place / relocate / retire ``slug``. ``location`` is a path relative to the
    workspace root (``None`` for retire, whose destination the broker derives from
    the slug). The broker normalizes it *inside* the workspace root and re-runs the
    race guards (slug re-verify, occupancy)."""

    slug: str
    location: str | None = None


class CheckoutRequest(StrictModel):
    """Check ``commit`` out at ``slug``'s current location (hex commit only)."""

    slug: str
    commit: str


class LayoutOpResult(StrictModel):
    """A ``LayoutOutcome`` in JSON-native form (shared by every layout verb)."""

    status: str
    summary: str


# --- git pack: read/write a cluster's layout document ----------------------- #
class ReadLayoutRequest(StrictModel):
    """Read ``<cluster_slug>``'s ``product-cluster/default-layout.json``.

    The document lives inside the (broker-side) managed checkout; the container
    checks presence/materialization from a prior ``scan`` and asks only for the
    file's contents here.
    """

    cluster_slug: str


class ReadLayoutResult(StrictModel):
    """The layout file's contents, or ``exists=False`` if it isn't authored yet."""

    exists: bool
    layout: dict[str, Any] | None = None


class WriteLayoutRequest(StrictModel):
    """Author ``<cluster_slug>``'s layout document with ``layout`` (a JSON dict).

    Not in the original Step-2 verb table (which listed only ``read_layout``); a
    write path is required because the ``layout add`` / ``remove`` / ``manage``
    authoring commands mutate the file, which is now a broker-side FS effect.
    """

    cluster_slug: str
    layout: dict[str, Any]


# --- mono_config pack: repo definitions + system.json ----------------------- #
class RepoDefsRequest(StrictModel):
    """Read repo definition JSON. ``slugs=None`` returns every definition."""

    slugs: list[str] | None = None


class RepoDefsResult(StrictModel):
    """Raw ``<slug>.json`` repo definitions keyed by slug.

    The container-side ``RepoStore`` keeps ownership of pydantic validation,
    list filtering, and the retire/restore mutations; this verb only serves the
    raw JSON that a workspace mount used to provide.
    """

    repos: dict[str, Any] = {}


class SystemResult(StrictModel):
    """The raw ``system.json`` contents, or ``None`` when it does not exist."""

    system: dict[str, Any] | None = None


class SaveRepoDefRequest(StrictModel):
    """Create or overwrite one repo definition (``repo`` is the raw ``<slug>.json``)."""

    repo: dict[str, Any]


class SaveSystemRequest(StrictModel):
    """Create or overwrite ``system.json`` (``system`` is its raw contents)."""

    system: dict[str, Any]


class SlugRequest(StrictModel):
    """A verb keyed only by ``slug`` (e.g. purge a repo definition)."""

    slug: str


class OkResult(StrictModel):
    """A minimal acknowledgement for write verbs."""

    ok: bool = True


# --- git pack: probe a remote's default branch (guided repo-add) ------------ #
class RemoteDefaultBranchRequest(StrictModel):
    """Ask the broker for the default branch (symbolic ``HEAD``) of a remote.

    Takes a raw ``url`` — not a slug — because guided repo-add probes a remote the
    user is *defining*, so the repo def may not exist in mono-config yet. This is
    the same trust boundary the ``save_repo_def`` write verbs already use: the
    container authors remote URLs, so letting it probe one is consistent.

    SHIM SECURITY (when the real handler is implemented, other repo): the URL is
    attacker-influenced, so the broker MUST sanitize it, run ``git ls-remote
    --symref <url> HEAD`` under ``GIT_ALLOW_PROTOCOL=https`` (no ``file://`` /
    ``ext://`` / ssh side channels), and rely on the github.com-only credential
    helper to scope the token to intended hosts. Never interpolate the URL into a
    shell.
    """

    url: str


class RemoteDefaultBranchResult(StrictModel):
    """The remote's default branch (e.g. ``main``), or ``None`` if it has none."""

    branch: str | None = None

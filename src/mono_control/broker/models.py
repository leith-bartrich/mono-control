"""Wire models for the host-side broker contract.

The broker relocates git + filesystem *effects* to a host-side JSON-RPC endpoint
the container calls back to. These are the JSON-native shapes that cross that
wire — the serializable mirror of the in-memory ``on_disk`` observation
(``OnDiskRepo`` / ``OnDiskInventory``).

Where the ``on_disk`` models carry *absolute* ``Path`` s (they never leave the
process), the wire models carry *relative* location strings plus the observed
``state``. Physical model: **bare repos + worktrees**. A ``materialized`` repo's
location is its worktree path under the work root (``mono-work``); an ``offline``
repo's location is its bare repo path under the bare root (``mono-repos-bare``).
Absolute paths are reconstructed at the container boundary from the work / bare
roots via the free functions below, so the rest of the app keeps consuming its
internal ``OnDiskInventory`` type unchanged.

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
    """One observed repo in JSON-native form (relative location + state).

    ``materialized`` -> ``location`` is the worktree path relative to the work
    root; ``offline`` -> ``location`` is the bare repo's dir (its slug) relative
    to the bare root.
    """

    slug: str
    location: str  # RELATIVE to the state's root (worktree path, or the bare's slug)
    state: State
    commit: str | None
    dirty: bool
    # The branch HEAD is attached to; None when detached or bare. Optional with a
    # default so this is an ADDITIVE wire change (see mono-control-shim#7).
    branch: str | None = None


class WireUnmanaged(StrictModel):
    """An unmanaged (unstamped) bare repo found under one of the roots.

    Like ``WireRepo`` it carries a relative ``location`` plus the ``state`` that
    says which root the location is relative to. An unstamped bare has no worktree
    by definition, so the broker reports it ``offline`` (relative to the bare root).
    """

    location: str  # RELATIVE to the state's root
    state: State


class WireInventory(StrictModel):
    """The on-disk observation in JSON-native form: managed repos + unmanaged."""

    repos: list[WireRepo] = []
    unmanaged: list[WireUnmanaged] = []


def _root_for(state: State, work_root: Path, bare_root: Path) -> Path:
    """The root a ``state``'s relative location is reconstructed against.

    ``materialized`` resolves against the work root (its worktree path);
    ``offline`` resolves against the bare root (its bare repo dir).
    """
    return work_root if state == "materialized" else bare_root


def wire_repo_from_on_disk(
    repo: OnDiskRepo, work_root: Path, bare_root: Path
) -> WireRepo:
    """Project an ``OnDiskRepo`` to its wire form (absolute -> relative location)."""
    root = _root_for(repo.state, work_root, bare_root)
    relative = repo.location.relative_to(root)
    return WireRepo(
        slug=repo.slug,
        location=relative.as_posix(),
        state=repo.state,
        commit=repo.commit,
        dirty=repo.dirty,
        branch=repo.branch,
    )


def wire_repo_to_on_disk(
    wire: WireRepo, work_root: Path, bare_root: Path
) -> OnDiskRepo:
    """Reconstruct an ``OnDiskRepo`` (absolute location) from its wire form."""
    root = _root_for(wire.state, work_root, bare_root)
    location = root / PurePosixPath(wire.location)
    return OnDiskRepo(
        slug=wire.slug,
        location=location,
        state=wire.state,
        commit=wire.commit,
        dirty=wire.dirty,
        branch=wire.branch,
    )


def wire_unmanaged_from_on_disk(
    path: Path, work_root: Path, bare_root: Path
) -> WireUnmanaged:
    """Project an unmanaged absolute path to its wire form.

    The discriminator is which root the path lives under. An unstamped bare under
    the bare root round-trips back to it as ``offline`` (the usual case); the work
    root branch is kept for symmetry.
    """
    if path.is_relative_to(work_root):
        return WireUnmanaged(
            location=path.relative_to(work_root).as_posix(), state="materialized"
        )
    if path.is_relative_to(bare_root):
        return WireUnmanaged(
            location=path.relative_to(bare_root).as_posix(), state="offline"
        )
    raise ValueError(f"unmanaged path {path} is under neither root")


def wire_unmanaged_to_on_disk(
    wire: WireUnmanaged, work_root: Path, bare_root: Path
) -> Path:
    """Reconstruct an unmanaged absolute path from its wire form."""
    root = _root_for(wire.state, work_root, bare_root)
    return root / PurePosixPath(wire.location)


def wire_inventory_from_on_disk(
    inventory: OnDiskInventory, work_root: Path, bare_root: Path
) -> WireInventory:
    """Project an ``OnDiskInventory`` to its wire form.

    Repo and unmanaged locations are each made relative to the root implied by
    their ``state``, so both round-trip back to the root they were found under.
    """
    return WireInventory(
        repos=[
            wire_repo_from_on_disk(repo, work_root, bare_root)
            for repo in inventory.repos.values()
        ],
        unmanaged=[
            wire_unmanaged_from_on_disk(path, work_root, bare_root)
            for path in inventory.unmanaged
        ],
    )


def wire_inventory_to_on_disk(
    wire: WireInventory, work_root: Path, bare_root: Path
) -> OnDiskInventory:
    """Reconstruct an ``OnDiskInventory`` (absolute paths) from its wire form.

    The inverse of ``wire_inventory_from_on_disk``: each repo and unmanaged path's
    absolute location is rebuilt from its ``state`` + the matching root. Repos are
    keyed by slug, matching ``scanner.scan``.
    """
    repos = {
        w.slug: wire_repo_to_on_disk(w, work_root, bare_root)
        for w in wire.repos
    }
    unmanaged = [
        wire_unmanaged_to_on_disk(u, work_root, bare_root)
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
    """Check ``commit`` out at ``slug``'s current location (hex commit only).

    The **pin** purpose: put this worktree at an exact revision. The revision
    comes from the ledger (a snapshot, a dep pin), not from a branch, so a hex
    commit is the right currency and the resulting detached HEAD is correct.
    """

    slug: str
    commit: str


class CheckoutBranchRequest(StrictModel):
    """Attach ``slug``'s worktree to ``branch`` — a line the repo *declares*.

    The **follow-a-line** purpose, and a different currency from
    ``CheckoutRequest`` on purpose. Checking out a hex commit always detaches, so
    the pin verb structurally cannot express "on this branch"; the two were one
    verb, and the second meaning was lost in translation.

    ``branch`` is not trusted. Before it reaches git the host resolves it against
    the lines the repo *expresses* — those its def declares, plus the bare repo's
    own default ``HEAD`` — all read host-side, the same rule sources already
    follow ("never accepted from the container"). So the container's reach is not
    "any ref" but "a line this repo expresses", which is **narrower** than the hex
    form it sits beside: there, any object the container can name is fair game.

    The default counts because ``repo.md`` says the remote's default *is* the line
    unless a def overrides it. Without that, a repo declaring no ``branches`` —
    most of them — could never be put on a branch at all.
    """

    slug: str
    branch: str


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


class SetRemoteRequest(StrictModel):
    """Add or repoint remote ``name`` → ``url`` on ``slug``'s on-disk checkout.

    The eager fork-remote stamp: :func:`repo_ops.adopt_fork` saves config, then
    asks the broker to conform the named remote into the checkout's
    ``.git/config``. Carries a *slug* (the broker resolves its checkout — the
    container never names host paths) plus the remote ``name`` and its https
    ``url``.

    SHIM SECURITY (real handler, other repo): all three params are
    attacker-influenced. The broker MUST reject a non-bare slug, a malformed
    remote name, and any non-https / ``transport::``-helper url before running
    ``git remote add`` / ``set-url`` — never interpolating them into a shell.
    """

    slug: str
    name: str
    url: str


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

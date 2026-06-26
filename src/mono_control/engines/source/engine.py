"""The source engine: per-repo acquisition + ref refresh, never destructive.

For each (slug, requested-refs) in the request, independently:

1. Look up the repo def in the ``RepoStore`` (missing → ``definition-missing``).
2. Resolve a source (the first declared ``sources`` entry — multi-source
   resolution is TBD).
3. If the slug is **absent** locally:
   - has a source → ``clone`` into ``offline_root/<slug>`` with FS profile + slug stamp;
   - has no source → ``init`` a brand-new empty repo with the same stamps;
   - has no source AND refs were requested → ``source-missing`` (no way to
     bring those refs in).
4. If the slug is **present** locally (offline OR materialized) → ``fetch``
   from the resolved source (if it has one).
5. **Verify**: each requested ref must resolve in the local checkout
   (``git rev-parse --verify``). Any that don't → ``ref-missing``.

The engine never **mats / demats** a checkout (that's the
[layout engine](../../../layout_target/)'s domain) and never **pushes** (the
publish engine's). It only ever adds availability.
"""

from __future__ import annotations

from pathlib import Path

from ...config import RepoStore
from ...git import GitError, GitRepo, clone, init
from ...host_platform import FsProfile
from ...on_disk import OnDiskInventory
from .request import SourceRequest
from .result import SourceOutcome, SourceReport


def _resolve_source(sources: dict[str, str]) -> str | None:
    """Pick a remote URL from a repo def's ``sources`` map.

    TBD: full multi-source / default-source resolution. For now, pick the
    *first* declared entry (insertion order) — the smallest defensible choice.
    """
    if not sources:
        return None
    return next(iter(sources.values()))


def _verify(repo: GitRepo, refs: set[str]) -> set[str]:
    """Return the refs that don't resolve locally."""
    return {ref for ref in refs if repo.resolve_ref(ref) is None}


def _process_slug(
    slug: str,
    requested_refs: set[str],
    *,
    repo_store: RepoStore,
    inventory: OnDiskInventory,
    offline_root: Path,
    profile: FsProfile,
) -> SourceOutcome:
    try:
        definition = repo_store.load(slug)
    except Exception as e:  # ConfigNotFoundError / ConfigValidationError / etc.
        return SourceOutcome(
            slug=slug,
            status="definition-missing",
            summary=f"repo def for {slug!r} not loadable: {e}",
        )

    source_url = _resolve_source(definition.sources)
    observed = inventory.repos.get(slug)

    if observed is None:
        # absent → create
        if source_url is None:
            if requested_refs:
                return SourceOutcome(
                    slug=slug,
                    status="source-missing",
                    summary=(
                        f"{slug!r} is absent and declares no sources; cannot "
                        f"satisfy requested refs"
                    ),
                    unresolved_refs=set(requested_refs),
                )
            try:
                init(offline_root / slug, profile=profile, slug=slug)
            except GitError as e:
                return SourceOutcome(
                    slug=slug,
                    status="create-failed",
                    summary=f"init {slug!r} failed: {e}",
                )
            return SourceOutcome(
                slug=slug,
                status="initialized",
                summary=f"initialized brand-new repo at {offline_root / slug}",
            )
        try:
            repo = clone(source_url, offline_root / slug, profile=profile, slug=slug)
        except GitError as e:
            return SourceOutcome(
                slug=slug,
                status="create-failed",
                summary=f"clone {slug!r} from {source_url!r} failed: {e}",
            )
        unresolved = _verify(repo, requested_refs)
        if unresolved:
            return SourceOutcome(
                slug=slug,
                status="ref-missing",
                summary=f"cloned {slug!r}, but {len(unresolved)} ref(s) did not resolve",
                unresolved_refs=unresolved,
            )
        return SourceOutcome(
            slug=slug, status="cloned", summary=f"cloned {slug!r} into offline"
        )

    # present locally (offline or materialized) → fetch (if there's a source)
    repo = GitRepo(observed.location)
    if source_url is not None:
        try:
            repo.fetch(_remote_name_for(source_url))
        except GitError:
            # The clone wired up the URL as remote "origin"; if a non-origin
            # source was used here, fall back to fetching by URL directly.
            try:
                repo.fetch(source_url)
            except GitError as e:
                return SourceOutcome(
                    slug=slug,
                    status="fetch-failed",
                    summary=f"fetch {slug!r} from {source_url!r} failed: {e}",
                )

    unresolved = _verify(repo, requested_refs)
    if unresolved:
        return SourceOutcome(
            slug=slug,
            status="ref-missing",
            summary=f"{slug!r} present, but {len(unresolved)} ref(s) did not resolve",
            unresolved_refs=unresolved,
        )
    if source_url is None:
        return SourceOutcome(
            slug=slug,
            status="ok",
            summary=f"{slug!r} present and has no source to fetch from",
        )
    if not requested_refs:
        return SourceOutcome(
            slug=slug, status="fetched", summary=f"fetched {slug!r} from source"
        )
    return SourceOutcome(
        slug=slug,
        status="fetched",
        summary=f"fetched {slug!r}; {len(requested_refs)} ref(s) verified",
    )


def _remote_name_for(url: str) -> str:
    """The remote name our clone used.

    ``clone`` invokes ``git clone`` with no ``--origin``, so the remote is
    named ``origin`` regardless of the URL. (Multi-source — including
    additional named remotes — is TBD.)
    """
    del url  # unused; reserved for the multi-source future
    return "origin"


def run(
    request: SourceRequest,
    *,
    repo_store: RepoStore,
    inventory: OnDiskInventory,
    offline_root: Path,
    profile: FsProfile,
) -> SourceReport:
    """Execute the source request, per-repo independent.

    A failure on one slug does **not** abort the rest; every requested slug
    yields one outcome record. The on-disk inventory must already reflect what
    was present at the start of the run; the engine does not re-scan.
    """
    offline_root.mkdir(parents=True, exist_ok=True)
    outcomes = [
        _process_slug(
            slug,
            refs,
            repo_store=repo_store,
            inventory=inventory,
            offline_root=offline_root,
            profile=profile,
        )
        for slug, refs in request.refs_by_slug.items()
    ]
    return SourceReport(outcomes=outcomes)

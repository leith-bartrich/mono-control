"""CRUD access to repo definitions, fed by the broker's ``mono_config`` verbs.

The registry *is* a directory of ``<slug>.json`` files on the host — but the
container no longer mounts it. ``RepoStore`` keeps the brain (pydantic validation,
list filtering, the retire/restore mutations, the conflict/not-found rules) and
routes the raw JSON reads/writes through the broker (``get_repo_defs`` /
``save_repo_def`` / ``purge_repo_def``). That split is deliberate: the security
and identity checks stay container-side while the filesystem effect lives on the
host.

Deletion is two-tiered: ``retire`` soft-deletes (a tombstone flag; the slug stays
reserved and the change is reversible via ``restore``), while ``purge`` is the
guarded hard delete that physically removes the file (broker-side).
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..base_models import VersionError
from ..broker import BrokerProtocol
from .errors import (
    AmbiguousNameError,
    ConfigConflictError,
    ConfigNotFoundError,
    ConfigValidationError,
    ConfigVersionError,
)
from .models import Repo, slugify


class RepoStore:
    """Reads and writes repo definitions through the broker's ``mono_config`` pack."""

    def __init__(self, broker: BrokerProtocol) -> None:
        self.broker = broker

    def _all_defs(self) -> dict[str, Any]:
        """Every stored repo definition as raw JSON, keyed by slug."""
        return self.broker.get_repo_defs().repos

    def _def_for(self, slug: str) -> Any | None:
        """One raw repo definition, or ``None`` if the slug is unknown."""
        return self.broker.get_repo_defs([slug]).repos.get(slug)

    def exists(self, slug: str) -> bool:
        return self._def_for(slug) is not None

    def list(self, include_retired: bool = False) -> list[str]:
        """Return the slugs of stored repos, sorted."""
        slugs = sorted(self._all_defs())
        if include_retired:
            return slugs
        return [s for s in slugs if not self.load(s).retired]

    def _validate(self, slug: str, data: Any) -> Repo:
        """Validate one raw definition, mapping failures to config-typed errors."""
        try:
            repo = Repo.load(data)
        except VersionError as e:
            raise ConfigVersionError(str(e)) from e
        except ValidationError as e:
            raise ConfigValidationError(
                f"repo {slug!r} failed validation:\n{e}"
            ) from e
        if repo.slug != slug:
            raise ConfigValidationError(
                f"repo definition filed as {slug!r} declares slug {repo.slug!r}"
            )
        return repo

    def load(self, slug: str) -> Repo:
        data = self._def_for(slug)
        if data is None:
            raise ConfigNotFoundError(f"repo {slug!r} not found")
        return self._validate(slug, data)

    def save(self, repo: Repo) -> None:
        """Write (create or overwrite) a repo definition via the broker."""
        self.broker.save_repo_def(repo.model_dump(mode="json"))

    def create(self, repo: Repo) -> None:
        """Save a new repo, refusing to overwrite an existing slug."""
        if self.exists(repo.slug):
            raise ConfigConflictError(f"repo {repo.slug!r} already exists")
        self.save(repo)

    def retire(self, slug: str) -> Repo:
        """Soft-delete: set the tombstone flag, keeping the slug reserved."""
        repo = self.load(slug)
        repo.retired = True
        self.save(repo)
        return repo

    def restore(self, slug: str) -> Repo:
        """Reverse a retire."""
        repo = self.load(slug)
        repo.retired = False
        self.save(repo)
        return repo

    def purge(self, slug: str) -> None:
        """Hard delete: physically remove the definition file (guarded by callers)."""
        if not self.exists(slug):
            raise ConfigNotFoundError(f"repo {slug!r} not found")
        self.broker.purge_repo_def(slug)


def resolve_repo(store: "RepoStore", query: str, *, slug_only: bool = False) -> Repo:
    """Resolve ``query`` to a single ``Repo``: slug-first, then name fallback.

    - ``slug_only=True`` → load by slug directly; raise ``ConfigNotFoundError``
      on miss. Use this when the caller knows the input is a slug (e.g. when a
      ``--slug`` flag was passed).
    - Otherwise: try ``store.load(query)`` first; if it succeeds the slug
      wins. If not, fall back to name lookup using *slugified comparison*
      (case-insensitive, whitespace-normalized): match every repo whose
      ``slugify(name)`` equals ``slugify(query)``. One match → return it; more
      than one → ``AmbiguousNameError`` listing the candidate slugs; none →
      ``ConfigNotFoundError``.

    Slug-first means an explicit / legacy slug like ``"demo"`` still resolves
    as a slug when stored as one, even though it isn't shaped like a
    ``make_slug`` output.
    """
    if slug_only:
        return store.load(query)
    try:
        return store.load(query)
    except ConfigNotFoundError:
        pass
    needle = slugify(query)
    matches: list[Repo] = []
    for slug in store.list(include_retired=True):
        repo = store.load(slug)
        if slugify(repo.name) == needle:
            matches.append(repo)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise AmbiguousNameError(query, [r.slug for r in matches])
    raise ConfigNotFoundError(f"no repo found for {query!r}")

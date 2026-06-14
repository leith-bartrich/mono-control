"""CRUD access to repo definitions stored as ``<slug>.json`` files.

The directory *is* the registry: each file is one repo, named by its immutable
slug. This is the first part of the data layer that **writes** config — the CLI
and interactive UI author repo definitions through it.

Deletion is two-tiered: ``retire`` soft-deletes (a tombstone flag; the slug stays
reserved and the change is reversible via ``restore``), while ``purge`` is the
guarded hard delete that physically removes the file.
"""

from pathlib import Path

from pydantic import ValidationError

from ..paths import REPOS_SUBDIR
from .errors import (
    ConfigConflictError,
    ConfigNotFoundError,
    ConfigValidationError,
)
from .loader import _read_json
from .models import Repo


class RepoStore:
    """Reads and writes repo definitions in a directory of ``<slug>.json`` files."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @classmethod
    def from_config_dir(cls, config_dir: Path) -> "RepoStore":
        """Build a store rooted at ``<config_dir>/repos``."""
        return cls(config_dir / REPOS_SUBDIR)

    def path_for(self, slug: str) -> Path:
        return self.directory / f"{slug}.json"

    def exists(self, slug: str) -> bool:
        return self.path_for(slug).is_file()

    def list(self, include_retired: bool = False) -> list[str]:
        """Return the slugs of stored repos, sorted."""
        if not self.directory.is_dir():
            return []
        slugs = sorted(p.stem for p in self.directory.glob("*.json"))
        if include_retired:
            return slugs
        return [s for s in slugs if not self.load(s).retired]

    def load(self, slug: str) -> Repo:
        data = _read_json(self.path_for(slug))
        try:
            repo = Repo.load(data)
        except ValidationError as e:
            raise ConfigValidationError(
                f"{self.path_for(slug)} failed validation:\n{e}"
            ) from e
        if repo.slug != slug:
            raise ConfigValidationError(
                f"{self.path_for(slug)} declares slug {repo.slug!r} "
                f"but is filed as {slug!r}"
            )
        return repo

    def save(self, repo: Repo) -> None:
        """Write (create or overwrite) a repo definition."""
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path_for(repo.slug).write_text(repo.model_dump_json(indent=2) + "\n")

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
        try:
            self.path_for(slug).unlink()
        except FileNotFoundError as e:
            raise ConfigNotFoundError(f"repo {slug!r} not found") from e

"""Walk the workspace + offline holding area into an ``OnDiskInventory``.

For each candidate checkout (any directory containing ``.git``), read its
``mono-control.slug`` stamp; unstamped trees are reported as ``unmanaged``,
never operated on. Duplicate slugs across checkouts raise
``DuplicateSlugError`` — the one-materialization rule made enforceable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from ..git import GitRepo, UnmanagedCheckoutError
from .errors import DuplicateSlugError
from .models import OnDiskInventory, OnDiskRepo


def _find_checkouts(root: Path) -> Iterator[Path]:
    """Yield each subtree under ``root`` that contains a ``.git`` entry.

    Descent stops at each checkout (we never look inside an opaque repo).
    """
    if not root.is_dir():
        return
    # Iterative DFS; pruning is just "don't push children of a found checkout".
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        if (current / ".git").exists():
            yield current
            continue
        try:
            children = [p for p in current.iterdir() if p.is_dir()]
        except PermissionError:
            continue
        stack.extend(children)


def _observe(checkout: Path, state: str) -> OnDiskRepo | None:
    """Read one checkout into an ``OnDiskRepo``; ``None`` if it's unmanaged."""
    repo = GitRepo(checkout)
    try:
        slug = repo.slug()
    except UnmanagedCheckoutError:
        return None
    return OnDiskRepo(
        slug=slug,
        location=checkout,
        state=state,  # type: ignore[arg-type]
        commit=repo.current_commit(),
        dirty=repo.is_dirty(),
    )


def scan(workspace_root: Path, offline_root: Path) -> OnDiskInventory:
    """Observe both roots and return an ``OnDiskInventory``."""
    inventory = OnDiskInventory()
    for root, state in ((workspace_root, "materialized"), (offline_root, "offline")):
        for checkout in _find_checkouts(root):
            observed = _observe(checkout, state)
            if observed is None:
                inventory.unmanaged.append(checkout)
                continue
            prior = inventory.repos.get(observed.slug)
            if prior is not None:
                raise DuplicateSlugError(observed.slug, prior.location, checkout)
            inventory.repos[observed.slug] = observed
    return inventory

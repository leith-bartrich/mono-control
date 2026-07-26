"""The product-cluster's default subdir name (mat target).

Per docs/design/layers/repo-aspects/product-cluster/README.md, a cluster materializes
by default at ``mono-work/products/<name>`` where ``<name>`` is a friendly,
**mutable** local alias derived from the repo's ``name`` field — not from its
slug. This is intentional: the slug carries an immutable identity-uniqueness
hash that doesn't belong in path names, and deriving from ``name`` means a
``repo rename`` triggers a relocate at the next mat.
"""

from __future__ import annotations

from mono_control.config import Repo, slugify


def default_subdir(repo: Repo) -> str:
    """Return the default ``<name>`` under ``mono-work/products/`` for ``repo``."""
    return slugify(repo.name)

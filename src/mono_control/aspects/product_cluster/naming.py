"""The product-cluster's default subdir name (mat target).

Per docs/design/layers/repo-aspects/product-cluster.md, a cluster
materializes by default at ``mono-repos/products/<name>`` where ``<name>``
is a friendly local alias derived from the slug. The exact derivation rule
("strip trailing uniqueness/hash segment") and whether slugs carry such a
suffix at all are still TBD — for now the alias is the slug verbatim.
"""

from __future__ import annotations


def default_subdir(slug: str) -> str:
    """Return the default ``<name>`` under ``mono-repos/products/`` for ``slug``.

    TBD: strip a trailing uniqueness/hash segment from the slug once the slug
    convention is firm; for now, identity.
    """
    return slug

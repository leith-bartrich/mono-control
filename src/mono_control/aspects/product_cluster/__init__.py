"""The product-cluster aspect.

A *product cluster* is a data repo holding a layout (and, later, build records
/ snapshots). It is the first repo aspect (see
docs/design/layers/repo-aspects/product-cluster/README.md). This package houses
its models, its CLI verbs + interactive manager, and the registration that
surfaces them as ``mproj control product-cluster <verb>``.
"""

from .cli import app as product_cluster_app
from ..registry import register

# Self-register at import time so `mproj control product-cluster …` works.
register("product-cluster", product_cluster_app)

__all__ = ["product_cluster_app"]

"""The product-cluster aspect.

A *product cluster* is a data repo holding artifact configurations + build
records (snapshots). It is the first repo aspect (see
docs/design/layers/repo-aspects/product-cluster.md). This package houses
its model (TBD), its CLI verbs, and the registration that surfaces them as
``mproj control product-cluster <verb>``.
"""

from .cli import app as product_cluster_app
from ..registry import register

# Self-register at import time so `mproj control product-cluster …` works.
register("product-cluster", product_cluster_app)

__all__ = ["product_cluster_app"]

"""Canonical (nominal) workspace roots.

Step 2 removed the container's bind mounts: git + filesystem effects run
broker-side, and the container never touches these paths directly. They survive
here as the **nominal roots** the wire's *relative* locations are reconstructed
against (``scanner`` rehydration, ``plan`` target-location comparison) — a stable,
process-internal coordinate space that must stay consistent between the scan
converters and the planner, not real mount points. Centralized so the CLI and the
data layer agree on a single source of truth.
"""

from pathlib import Path

WORKSPACES = Path("/workspaces")
CONFIG_DIR = WORKSPACES / "mono-config"  # default for --config-dir (display / gate)
REPOS_DIR = WORKSPACES / "mono-repos"  # nominal materialized root (reconstruction)
OFFLINE_DIR = WORKSPACES / "mono-repos-offline"  # nominal offline holding root

# Provisional top-level file within CONFIG_DIR. The full directory layout (which
# named files exist) is still being designed; the loader reads this for now.
SYSTEM_FILE = "system.json"

# Subdirectory of CONFIG_DIR holding one repo definition per file, named by the
# repo's immutable slug (`<slug>.json`). Distinct from REPOS_DIR, which is where
# the managed repos are actually cloned.
REPOS_SUBDIR = "repos"
REPOS_CONFIG_DIR = CONFIG_DIR / REPOS_SUBDIR

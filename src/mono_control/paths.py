"""Canonical locations of the bind-mounted workspace directories.

These paths are where the dev container mounts the sibling repos (see
.devcontainer/devcontainer.json). Centralized here so the CLI and the data
layer agree on a single source of truth.
"""

from pathlib import Path

WORKSPACES = Path("/workspaces")
CONFIG_DIR = WORKSPACES / "mono-config"  # the config DIRECTORY mono-control reads
REPOS_DIR = WORKSPACES / "mono-repos"  # where managed repos are placed (materialized)
OFFLINE_DIR = WORKSPACES / "mono-repos-offline"  # holding area for unplaced checkouts

# Provisional top-level file within CONFIG_DIR. The full directory layout (which
# named files exist) is still being designed; the loader reads this for now.
SYSTEM_FILE = "system.json"

# Subdirectory of CONFIG_DIR holding one repo definition per file, named by the
# repo's immutable slug (`<slug>.json`). Distinct from REPOS_DIR, which is where
# the managed repos are actually cloned.
REPOS_SUBDIR = "repos"
REPOS_CONFIG_DIR = CONFIG_DIR / REPOS_SUBDIR

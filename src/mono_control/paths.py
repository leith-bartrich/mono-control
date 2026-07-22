"""Canonical (nominal) workspace roots.

Physical model: **bare repos + git worktrees**. Every managed repository is a
*bare* repo under ``BARE_DIR`` (``mono-repos-bare``) that never moves; placing it
into the workspace is an additive ``git worktree add`` under ``WORK_DIR``
(``mono-work``). The ``state`` literal is reinterpreted accordingly: **offline =
a bare repo with no worktree** (located under ``BARE_DIR``), **materialized = a
bare repo with a worktree** (located under ``WORK_DIR``).

Step 2 removed the container's bind mounts: git + filesystem effects run
broker-side, and the container never touches these paths directly. They survive
here as the **nominal roots** the wire's *relative* locations are reconstructed
against (``scanner`` rehydration, ``plan`` target-location comparison) — a stable,
process-internal coordinate space that must stay consistent between the scan
converters and the planner, not real mount points. Centralized so the CLI and the
data layer agree on a single source of truth.

IDE scoping (CURRENT INTENT, not yet solidified): an editor such as VS Code is
meant to be scoped to ``WORK_DIR`` (the worktrees a developer actually edits),
and NOT to index ``BARE_DIR`` (the bare object stores). This keeps an IDE off the
bare repos entirely — which is also what makes worktree add/move/remove safe from
the held-directory move failures the old "clone offline, then rename" model hit.
"""

from pathlib import Path

WORKSPACES = Path("/workspaces")
CONFIG_DIR = WORKSPACES / "mono-config"  # default for --config-dir (display / gate)
WORK_DIR = WORKSPACES / "mono-work"  # nominal materialized/worktree root (reconstruction)
BARE_DIR = WORKSPACES / "mono-repos-bare"  # nominal offline/bare root

# Provisional top-level file within CONFIG_DIR. The full directory layout (which
# named files exist) is still being designed; the loader reads this for now.
SYSTEM_FILE = "system.json"

# Subdirectory of CONFIG_DIR holding one repo definition per file, named by the
# repo's immutable slug (`<slug>.json`). Distinct from BARE_DIR, which is where
# the managed repos' bare object stores actually live.
REPOS_SUBDIR = "repos"
REPOS_CONFIG_DIR = CONFIG_DIR / REPOS_SUBDIR

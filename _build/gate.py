"""In-tree PEP 517 build backend: refuses to build outside the dev container.

This wraps hatchling. Re-exporting its hooks makes this module a drop-in build
backend; the sentinel check below aborts the build on the host *before* any
dependency resolution or install happens, so `uv sync` / `pip install` fail fast
off the sandbox. See README.md > "Runs only in the dev container".
"""

import os

from hatchling.build import *  # noqa: F401,F403 — re-export all PEP 517/660 hooks

if os.environ.get("MONO_CONTROL_IN_CONTAINER") != "1":
    raise RuntimeError(
        "Refusing to build mono-control outside its dev container "
        "(MONO_CONTROL_IN_CONTAINER is not set). See README.md > "
        "'Runs only in the dev container'."
    )

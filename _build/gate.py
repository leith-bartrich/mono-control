"""In-tree PEP 517 build backend: refuses to build outside the dev container.

This wraps hatchling. Re-exporting its hooks makes this module a drop-in build
backend; the marker check below aborts the build on the host *before* any
dependency resolution or install happens, so `uv sync` / `pip install` fail fast
off the sandbox. See README.md > "Runs only in the dev container" and CLAUDE.md.

The check is a MARKER FILE baked into the image by .devcontainer/Dockerfile — NOT
an environment variable. The old gate trusted MONO_CONTROL_IN_CONTAINER, which a
one-line `export` defeated; the marker lives at a system path outside the source
tree, so a host checkout cannot have it and no env var can fake it. Keep the path
in sync with mono_control.sandbox.CONTAINER_MARKER (this module can't import the
package — it isn't built yet).
"""

import os

from hatchling.build import *  # noqa: F401,F403 — re-export all PEP 517/660 hooks

# Must match mono_control.sandbox.CONTAINER_MARKER (duplicated: this backend runs
# before the package exists, so it cannot import it).
_CONTAINER_MARKER = "/etc/mono-control-container"

if not os.path.isfile(_CONTAINER_MARKER):
    raise RuntimeError(
        "\n"
        "mono-control does not build on the host. This refusal is CORRECT and\n"
        "EXPECTED. It is not a bug, and not something to work around.\n"
        "\n"
        "  DO:      build/run it in the container, via `mproj`:\n"
        "             mproj build-control   (build the image)\n"
        "             mproj test-control    (run the suite)\n"
        "             mproj control -- ...  (run the CLI)\n"
        "\n"
        "  DO NOT:  set MONO_CONTROL_IN_CONTAINER or create the container marker to\n"
        "           force a host build. It installs and executes untrusted third-party\n"
        "           dependencies on your machine: the exact risk the container\n"
        "           exists to prevent. See CLAUDE.md and README.md > 'Runs only in\n"
        "           the dev container'.\n"
    )

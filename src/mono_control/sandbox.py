"""Run-time half of the sandbox gate.

Mirrors the install-time gate in _build/gate.py: the CLI refuses to run unless
the dev-container sentinel is present, so even a pre-built environment copied to
the host won't execute.
"""

import os
import sys

SENTINEL = "MONO_CONTROL_IN_CONTAINER"


def in_container() -> bool:
    """True when running inside the mono-control dev container."""
    return os.environ.get(SENTINEL) == "1"


def require_container() -> None:
    """Exit with an error unless running inside the dev container."""
    if not in_container():
        sys.exit(
            f"mono-control must run inside its dev container "
            f"({SENTINEL} not set). Refusing to run on the host."
        )

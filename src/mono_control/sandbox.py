"""Run-time half of the sandbox gate.

Mirrors the install-time gate in _build/gate.py: the CLI refuses to run unless
the dev-container sentinel is present, so even a pre-built environment copied to
the host won't execute.
"""

import os
import sys

SENTINEL = "MONO_CONTROL_IN_CONTAINER"

# Broker connection details the shim injects so the container can call back to
# the host-side broker instead of touching git/filesystem itself.
BROKER_ENV = ("MONO_BROKER_HOST", "MONO_BROKER_PORT", "MONO_BROKER_TOKEN")


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


def require_broker() -> None:
    """Exit with an error unless the broker connection is fully configured.

    Mirrors ``require_container``'s hard-exit posture: the shim injects
    ``MONO_BROKER_HOST`` / ``MONO_BROKER_PORT`` / ``MONO_BROKER_TOKEN`` so the
    container can reach the host-side broker. If any is missing there is no way
    to perform git/filesystem effects, so refuse loudly.

    Not yet wired into the global CLI gate — enforcement is flipped in a later
    slice; for now it is defined and unit-tested only.
    """
    missing = [name for name in BROKER_ENV if not os.environ.get(name)]
    if missing:
        sys.exit(
            f"mono-control broker is not configured "
            f"({', '.join(missing)} not set). The shim must inject the broker "
            f"host, port, and token. Refusing to run."
        )

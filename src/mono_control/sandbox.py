"""Run-time half of the sandbox gate.

mono-control must run ONLY inside its dev container. It imports a large tree of
third-party (PyPI) dependencies whose job is to manage git; the container is what
keeps that untrusted code off the host. Running it on the host executes those
dependencies with the developer's full privileges: the exact supply-chain exposure
this project exists to prevent. **Never run mono-control, or its test suite, on the
host. Use `mproj`, which runs everything in the container.**

The gate keys off a MARKER FILE baked into the image by ``.devcontainer/Dockerfile``
at a system path that is NOT part of the source tree, so a host checkout does not
carry it and it cannot be conjured by setting an environment variable. The previous
gate trusted ``MONO_CONTROL_IN_CONTAINER``, a plain env var that a one-line
``export`` defeated (and it WAS defeated: a developer ran the suite on the host by
spoofing it). A file at ``/etc`` that only the image build creates is a far higher,
and deliberately obvious, bar.

Not bulletproof: a developer who roots the host and forges the marker can still get
through; nothing short of real attestation stops that. The point is to make the
common accidents (``uv run pytest``, ``python -m mono_control`` on the host) fail
loudly, and to turn a deliberate bypass into an unmistakable act rather than an
innocuous-looking env var.
"""

import os
import sys
from pathlib import Path

# Baked into the image by .devcontainer/Dockerfile at build time, at a system path
# that is NOT in the source tree (a host checkout never carries it, and no env var
# can fake it). The build backend (_build/gate.py) hardcodes the same literal path
# (it cannot import this module, since the package is not built yet), so keep them
# in sync.
CONTAINER_MARKER = Path("/etc/mono-control-container")

# Broker connection details the shim injects so the container can call back to the
# host-side broker instead of touching git/filesystem itself.
BROKER_ENV = ("MONO_BROKER_HOST", "MONO_BROKER_PORT", "MONO_BROKER_TOKEN")


def in_container() -> bool:
    """True only inside the mono-control dev container (marker file present).

    Deliberately NOT an env-var check: ``MONO_CONTROL_IN_CONTAINER`` was trivially
    spoofable. The marker is created solely by the image build.
    """
    return CONTAINER_MARKER.is_file()


def require_container() -> None:
    """Exit unless running inside the dev container. No env var can fake this."""
    if not in_container():
        sys.exit(
            "\n"
            "mono-control does not run on the host. This refusal is CORRECT and\n"
            "EXPECTED. It is not a bug, and not something to work around.\n"
            "\n"
            "  DO:      run it inside its container, via `mproj`:\n"
            "             CLI    ->  mproj control -- <args>\n"
            "             tests  ->  mproj test-control\n"
            "             shell  ->  mproj shell-control\n"
            "\n"
            "  DO NOT:  try to get past this gate. Do NOT set MONO_CONTROL_IN_CONTAINER\n"
            "           (it no longer bypasses anything), do NOT create the container\n"
            "           marker file, do NOT run `uv run` / `python -m mono_control`\n"
            "           on the host. Every such bypass executes untrusted third-party\n"
            "           dependencies on your machine: the exact supply-chain risk the\n"
            "           container exists to prevent. See CLAUDE.md.\n"
        )


def require_broker() -> None:
    """Exit with an error unless the broker connection is fully configured.

    Mirrors ``require_container``'s hard-exit posture: the shim injects
    ``MONO_BROKER_HOST`` / ``MONO_BROKER_PORT`` / ``MONO_BROKER_TOKEN`` so the
    container can reach the host-side broker. If any is missing there is no way
    to perform git/filesystem effects, so refuse loudly.

    Enforced in the CLI gate: ``cli/app.py``'s ``main()`` calls this right after
    ``require_container()``, so the console-script entrypoint refuses to run
    without a fully configured broker.
    """
    missing = [name for name in BROKER_ENV if not os.environ.get(name)]
    if missing:
        sys.exit(
            f"mono-control broker is not configured "
            f"({', '.join(missing)} not set). The shim must inject the broker "
            f"host, port, and token. Refusing to run."
        )

"""Host-platform declaration and gate.

mono-control runs in a Linux container but operates on working trees that often
live on a *host* filesystem (Windows/macOS/Linux) via bind mount. Correct git
behavior for those trees depends on the host platform, which the container cannot
reliably infer — so it is *declared* via the ``MONO_CONTROL_HOST_PLATFORM``
environment variable and gated here. See ``docs/design/host-platform.md``.

This is a second sentinel, parallel to ``sandbox.py``'s ``MONO_CONTROL_IN_CONTAINER``
but *dynamic*: the image is multi-platform, so there is nothing static to bake
beyond a safe ``generic`` default. The shim (and the dev container) override it
per invocation with the detected host.

The gate has two tiers:

- **lenient** (``read`` / ``require_valid``) — the value must be a recognized
  token; absent degrades to ``generic``; anything else is rejected. Run at CLI
  startup so a garbage value fails loudly.
- **strict** (``require_specific`` / ``profile``) — used by operations that stamp
  filesystem config (clone/init); these refuse on ``generic`` because they need a
  concrete platform.
"""

import os
import sys
from dataclasses import dataclass

HOST_PLATFORM_ENV = "MONO_CONTROL_HOST_PLATFORM"

WINDOWS = "windows"
DARWIN = "darwin"
LINUX = "linux"
GENERIC = "generic"

# Platforms that name a concrete host filesystem (i.e. have an FS profile).
SPECIFIC = frozenset({WINDOWS, DARWIN, LINUX})
# Everything the gate accepts; anything else is garbage.
KNOWN = SPECIFIC | {GENERIC}


class HostPlatformError(Exception):
    """The declared host platform is unrecognized, or is required but unspecified."""


@dataclass(frozen=True)
class FsProfile:
    """The git filesystem-capability config a platform's working tree needs.

    These are *capability* settings — about faithfully representing the files on
    that filesystem, not about their contents (line endings / ``.gitattributes``
    stay with the managed project). Applied by the git layer when it stamps a
    clone's ``.git/config``.
    """

    filemode: bool
    symlinks: bool
    ignorecase: bool


# Per the table in docs/design/host-platform.md.
PROFILES: dict[str, FsProfile] = {
    WINDOWS: FsProfile(filemode=False, symlinks=False, ignorecase=True),
    DARWIN: FsProfile(filemode=True, symlinks=True, ignorecase=True),
    LINUX: FsProfile(filemode=True, symlinks=True, ignorecase=False),
}


def read() -> str:
    """Return the declared host platform (lenient).

    Absent → ``generic`` (a defensive default, even without the baked ENV). A
    recognized token is returned as-is. Anything else raises ``HostPlatformError``.
    """
    raw = os.environ.get(HOST_PLATFORM_ENV)
    if raw is None:
        return GENERIC
    if raw in KNOWN:
        return raw
    raise HostPlatformError(
        f"unrecognized {HOST_PLATFORM_ENV}={raw!r}; expected one of {sorted(KNOWN)}"
    )


def require_specific() -> str:
    """Return a concrete host platform, raising if it is ``generic`` (strict).

    For operations that must know the real filesystem (e.g. stamping a clone).
    """
    platform = read()
    if platform == GENERIC:
        raise HostPlatformError(
            f"this operation needs a specific host platform, but "
            f"{HOST_PLATFORM_ENV} is '{GENERIC}'. The shim must supply the host "
            f"platform (one of {sorted(SPECIFIC)})."
        )
    return platform


def profile() -> FsProfile:
    """Return the FS-capability profile for the declared (specific) platform."""
    return PROFILES[require_specific()]


def require_valid() -> None:
    """Startup gate: exit if the declared platform is garbage (lenient).

    Mirrors ``sandbox.require_container``'s hard-exit posture — it runs before the
    CLI dispatches, so a misconfigured value fails loudly rather than surfacing as
    a typer error mid-command.
    """
    try:
        read()
    except HostPlatformError as e:
        sys.exit(str(e))

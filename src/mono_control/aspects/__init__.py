"""Repo-aspect plug-in surface (see docs/design/layers/repo-aspects/README.md).

Each aspect lives in its own ``mono_control.aspects.<aspect_name>`` package and
contributes a Typer sub-app. The registry below is what the CLI's ``control``
group iterates: ``mproj control <aspect-name> <verb> …``.

Registration is explicit (a module-level list, populated by importing this
package) rather than discovery-by-walking — small surface, no import-time
magic. Add a new aspect by importing it here and appending its
``(name, app)`` to ``REGISTERED_ASPECTS``.
"""

from .registry import (
    REGISTERED_ASPECTS,
    Aspect,
    attach_aspect_commands,
    discover_repos,
    register,
)

# Importing each aspect package triggers its top-level `register(...)` call.
from . import product_cluster  # noqa: F401 — side-effect import

__all__ = [
    "REGISTERED_ASPECTS",
    "Aspect",
    "attach_aspect_commands",
    "discover_repos",
    "register",
]

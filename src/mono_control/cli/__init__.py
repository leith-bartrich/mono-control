"""Command-line interface for mono-control.

Re-exports ``app`` (the Typer application) and ``main`` (the console-script
entrypoint) so ``mono_control.cli:main`` and ``from mono_control.cli import app``
keep working after the CLI grew from a flat module into this sub-package.
"""

from .app import app, main

__all__ = ["app", "main"]

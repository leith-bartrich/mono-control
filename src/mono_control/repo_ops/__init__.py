"""High-level repo operations: thin orchestrators over the engines.

These compose the source + layout engines (and ``RepoStore``) into the verbs
that most callers actually want — ``init``, ``materialize``, ``dematerialize``,
``mark_aspect``. They are **aspect-agnostic**: aspect-specific CLI commands
delegate here and contribute only their own convention (default subdir,
aspect-name to mark) and their own pre/post logic.

Aspect-agnostic by design — composition, not inheritance: an aspect's `init`
is "call ``init`` here then ``mark_aspect`` here," not "subclass a template."
"""

from .operations import (
    ForkAdoption,
    acquire,
    adopt_fork,
    apply_target,
    init,
    mark_aspect,
)
from .render import render_outcomes, status_color

__all__ = [
    "init",
    "apply_target",
    "acquire",
    "adopt_fork",
    "ForkAdoption",
    "mark_aspect",
    "render_outcomes",
    "status_color",
]

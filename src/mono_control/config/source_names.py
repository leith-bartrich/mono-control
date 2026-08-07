"""The governed sources/branches vocabulary — pure helpers, never load-time validation.

The names of a repo's ``sources`` map are mono-control's reserved vocabulary
(``origin`` XOR ``upstream`` as the canonical, ``fork-<purpose>`` /
``mirror-<purpose>`` as copies — see ``docs/design/layers/data/repo.md``).
The vocabulary is governed by the *authoring flows* (the guided UI and the
fork/source verbs construct only governed keys) and, eventually, by engine
conformance — deliberately **not** by schema validation, so arbitrary extra
names stay legal in the :class:`~mono_control.config.models.Repo` model.
These helpers are what those flows lean on to speak the vocabulary.
"""

ORIGIN = "origin"
UPSTREAM = "upstream"
FORK_OURS = "fork-ours"

DEV = "dev"
DEV_UPSTREAM = "dev-upstream"

_COPY_KINDS = ("fork", "mirror")


def fork_key(purpose: str) -> str:
    """The governed source key for a fork with ``purpose`` (e.g. ``fork-ours``)."""
    return f"fork-{purpose}"


def split_key(key: str) -> tuple[str, str | None]:
    """Classify a source key into ``(kind, purpose)``.

    ``("origin", None)`` / ``("upstream", None)`` for the canonicals,
    ``("fork", <purpose>)`` / ``("mirror", <purpose>)`` for governed copies,
    and ``("other", None)`` for free (ungoverned) names.
    """
    if key in (ORIGIN, UPSTREAM):
        return key, None
    kind, sep, purpose = key.partition("-")
    if sep and purpose and kind in _COPY_KINDS:
        return kind, purpose
    return "other", None


def canonical(sources: dict[str, str]) -> str | None:
    """The canonical source key present — ``origin``, else ``upstream``, else ``None``."""
    if ORIGIN in sources:
        return ORIGIN
    if UPSTREAM in sources:
        return UPSTREAM
    return None


def writable_remote(sources: dict[str, str]) -> str | None:
    """Our writable remote, resolved deterministically: ``origin``, else ``fork-ours``.

    Every other purpose (a peer's fork, a mirror) is a tracked reference and is
    never auto-selected.
    """
    if ORIGIN in sources:
        return ORIGIN
    if FORK_OURS in sources:
        return FORK_OURS
    return None


def has_fork(sources: dict[str, str]) -> bool:
    """True if any governed ``fork-*`` source is declared."""
    return any(split_key(key)[0] == "fork" for key in sources)


# --------------------------------------------------------------------------- #
# Branch lines
# --------------------------------------------------------------------------- #
def resolve_line(branches: dict[str, str], value: str) -> str | None:
    """Resolve *value* to a concrete branch the repo **declares**, or ``None``.

    Accepts either the **line name** (a key — ``dev``, ``dev-upstream``, or any
    declared purpose) or the **concrete branch** it maps to. Both are "a line the
    repo already expresses", which is the only thing mono-control checks out; the
    host re-validates against this same map before git ever sees the value.

    Taking only concrete names is what made ``--branch dev`` fail on a repo whose
    def says ``{"dev": "main"}``, while the docs describe ``branches`` as the
    purpose vocabulary. Taking only keys would have broken the concrete form that
    already worked. Accepting both costs nothing, because neither reading can
    escape the declared set.

    Keys win over values. A repo declaring ``{"dev": "main", "main": "release"}``
    is pathological, and the key reading is the one the vocabulary intends.
    """
    if value in branches:
        return branches[value]
    if value in branches.values():
        return value
    return None


def declared_lines(branches: dict[str, str]) -> str:
    """Render a repo's declared lines for an error message."""
    if not branches:
        return "none declared"
    return ", ".join(f"{name}={branch}" for name, branch in sorted(branches.items()))

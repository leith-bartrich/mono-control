"""Interactive, questionary-driven authoring of a cluster's layout.

Exposed as ``mproj control product-cluster layout manage`` (and reached from the
top-level ``product-cluster manage``). The menu loop needs a TTY; the actual
mutations all go through :class:`ClusterLayoutStore`, which is what the unit tests
exercise (the scriptable ``layout`` verbs share that store). Mirrors
``mono_control.cli.repo_ui``.
"""

import questionary
from rich.console import Console
from rich.table import Table

from mono_control.config import RepoStore

from .cluster_layout import ClusterLayout, ClusterLayoutStore, LayoutMember

console = Console()

_ADD = "[+ add member]"
_EXIT = "[exit layout manager]"
_CANCEL = "[cancel]"


def _member_candidates(repo_store: RepoStore, cluster_slug: str) -> list[str]:
    """Repos eligible to be added as members — everything *but* the cluster itself.

    A product cluster is never a member of its own layout, so it is filtered out
    of the candidate list.
    """
    return [s for s in repo_store.list() if s != cluster_slug]


def manage(store: ClusterLayoutStore, repo_store: RepoStore, cluster_slug: str) -> None:
    """Run the interactive layout-authoring loop until the user exits.

    ``cluster_slug`` is the cluster being edited; it is never offered as one of its
    own members.
    """
    while True:
        layout = store.load_or_empty()
        _show(layout)
        choice = questionary.select(
            "Layout",
            choices=[*(f"remove {s}" for s in sorted(layout.members)), _ADD, _EXIT],
        ).ask()
        if choice in (None, _EXIT):
            return
        if choice == _ADD:
            _add(store, repo_store, cluster_slug)
        elif choice.startswith("remove "):
            _remove(store, choice[len("remove ") :])


def _show(layout: ClusterLayout) -> None:
    if not layout.members:
        console.print("(empty layout)")
        return
    table = Table("slug", "location", "role", box=None)
    for slug, member in sorted(layout.members.items()):
        table.add_row(slug, member.location, member.role)
    console.print(table)


def _add(store: ClusterLayoutStore, repo_store: RepoStore, cluster_slug: str) -> None:
    candidates = _member_candidates(repo_store, cluster_slug)
    if not candidates:
        console.print("[yellow]no other repos to add — define or mark one first[/yellow]")
        return
    layout = store.load_or_empty()
    # Annotate repos already in the layout; selecting one updates it (add is upsert).
    labels = {
        (f"{slug}  (member)" if slug in layout.members else slug): slug
        for slug in candidates
    }
    picked = questionary.select("member repo", choices=[*labels, _CANCEL]).ask()
    if picked in (None, _CANCEL):
        return
    slug = labels[picked]
    existing = layout.members.get(slug)  # pre-fill when editing an existing member
    location = (
        questionary.text(
            "location under mono-work/:",
            default=existing.location if existing else slug,
        ).ask()
        or ""
    ).strip()
    if not location:
        return
    role = questionary.select(
        "role",
        choices=["dev", "dep", _CANCEL],
        default=existing.role if existing else "dev",
    ).ask()
    if role in (None, _CANCEL):
        return
    layout.members[slug] = LayoutMember(location=location, role=role)
    store.save(layout)
    console.print(f"[green]set[/green] {slug} → {location} ({role})")


def _remove(store: ClusterLayoutStore, slug: str) -> None:
    layout = store.load_or_empty()
    if layout.members.pop(slug, None) is not None:
        store.save(layout)
        console.print(f"[green]removed[/green] {slug}")

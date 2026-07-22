"""Top-level interactive manager for product clusters (`product-cluster manage`).

The convention-mirroring peer of `repo manage` (``mono_control.cli.repo_ui``): a menu
over the declared clusters with the cluster-level verbs wired to the shared
:mod:`.actions` logic (and :mod:`mono_control.repo_ops` for create / mark). Interactive
(needs a TTY); every mutation goes through that shared logic — the same paths the unit
tests exercise — so the menu stays a thin presentation layer.
"""

import questionary
from rich.console import Console

from mono_control import paths, repo_ops
from mono_control.config import ConfigError, RepoStore
from mono_control.on_disk import scan

from ..registry import discover_repos
from . import actions
from .cluster_layout import ClusterLayoutError, ClusterLayoutStore, require_cluster_present
from .layout_ui import manage as manage_layout

console = Console()
ASPECT = "product-cluster"

_NEW = "[+ new cluster]"
_MARK = "[mark existing repo]"
_CLEAR = "[clear workspace]"
_EXIT = "[exit product-cluster manager]"
_BACK = "[back]"
_CONFORM = "conform ▸"


def _confirm_dirty(dirty: list[str]) -> bool:
    """`on_dirty` callback for gated actions — prompt to proceed despite dirty clusters."""
    return bool(
        questionary.confirm(
            f"product-cluster(s) {', '.join(dirty)} are dirty — proceed anyway?",
            default=False,
        ).ask()
    )


def manage(store: RepoStore) -> None:
    """Run the interactive product-cluster manager until the user exits."""
    while True:
        inv = scan(store.broker, paths.WORK_DIR, paths.BARE_DIR)
        by_label: dict[str, object] = {}
        choices: list[str] = []
        for repo in discover_repos(store, ASPECT):
            observed = inv.repos.get(repo.slug)
            state = observed.state if observed is not None else "absent"
            label = f"{repo.slug}  ({state})"
            by_label[label] = repo
            choices.append(label)
        choice = questionary.select(
            "Product clusters", choices=[*choices, _NEW, _MARK, _CLEAR, _EXIT]
        ).ask()
        if choice in (None, _EXIT):
            return
        if choice == _NEW:
            _new(store)
        elif choice == _MARK:
            _mark(store)
        elif choice == _CLEAR:
            if questionary.confirm(
                "Clear the whole workspace (retire everything to offline)?", default=False
            ).ask():
                actions.clear(store=store, console=console, on_dirty=_confirm_dirty)
        else:
            _manage_one(store, by_label[choice])


def _new(store: RepoStore) -> None:
    name = (questionary.text("name:").ask() or "").strip()
    if not name:
        return
    try:
        slug, report = repo_ops.init(
            name,
            aspects={ASPECT},
            repo_store=store,
            broker=store.broker,
        )
    except (ConfigError, ValueError, RuntimeError) as e:
        console.print(f"[red]error:[/red] {e}")
        return
    console.print(f"[green]created[/green] {slug}")
    repo_ops.render_outcomes(f"init {slug}", report.outcomes, console=console)


def _mark(store: RepoStore) -> None:
    marked = {r.slug for r in discover_repos(store, ASPECT)}
    candidates = [s for s in store.list() if s not in marked]
    if not candidates:
        console.print("[yellow]no unmarked repos to mark[/yellow]")
        return
    slug = questionary.select(
        "mark which repo as product-cluster", choices=[*candidates, _BACK]
    ).ask()
    if slug in (None, _BACK):
        return
    try:
        newly = repo_ops.mark_aspect(slug, ASPECT, repo_store=store)
    except ConfigError as e:
        console.print(f"[red]error:[/red] {e}")
        return
    console.print(
        f"[green]marked[/green] {slug}" if newly else f"[yellow]already marked[/yellow] {slug}"
    )


def _manage_one(store: RepoStore, repo) -> None:
    while True:
        observed = scan(store.broker, paths.WORK_DIR, paths.BARE_DIR).repos.get(repo.slug)
        state = observed.state if observed is not None else "absent"
        console.print(f"[bold]{repo.slug}[/bold] — {repo.name}  ({state})")
        action = questionary.select(
            "Action", choices=[_CONFORM, "place", "edit layout", "demat", _BACK]
        ).ask()
        if action in (None, _BACK):
            return
        if action == _CONFORM:
            _conform_menu(store, repo)
        elif action == "place":
            subdir = (
                questionary.text("subdir under products/ (blank = default):").ask() or ""
            ).strip() or None
            actions.place(repo, subdir, store=store, console=console)
        elif action == "demat":
            actions.demat(repo, store=store, console=console, on_dirty=_confirm_dirty)
        elif action == "edit layout":
            try:
                require_cluster_present(
                    store.broker,
                    repo.slug,
                    work_root=paths.WORK_DIR,
                    bare_root=paths.BARE_DIR,
                )
            except ClusterLayoutError as e:
                console.print(f"[red]error:[/red] {e}")
                continue
            manage_layout(ClusterLayoutStore(store.broker, repo.slug), store, repo.slug)


def _conform_menu(store: RepoStore, repo) -> None:
    """Workspace-conform actions for this cluster, grouped under their own menu
    (so they don't sit flat beside mat/layout actions — and `relayout` isn't
    confusingly adjacent to `edit layout`)."""
    action = questionary.select(
        "Conform the workspace to", choices=["relayout", "swap to", _BACK]
    ).ask()
    if action in (None, _BACK):
        return
    if action == "relayout":
        actions.relayout(repo, store=store, console=console, on_dirty=_confirm_dirty)
    elif action == "swap to":
        actions.swap(repo, store=store, console=console, on_dirty=_confirm_dirty)

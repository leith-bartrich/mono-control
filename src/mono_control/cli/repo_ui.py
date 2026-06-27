"""Interactive, questionary-driven management of repo definitions.

Exposed as ``mono-control repo manage``. The menu loop needs a TTY; the actual
mutations all go through :class:`~mono_control.config.RepoStore`, which is what
the unit tests exercise.
"""

import questionary
from rich.console import Console

from mono_control.config import ConfigError, Repo, RepoStore, make_slug

console = Console()

_ADD = "[+ add new repo]"
_QUIT = "[quit]"
_BACK = "[back]"


def manage(store: RepoStore) -> None:
    """Run the interactive repo-management loop until the user quits."""
    while True:
        slugs = store.list(include_retired=True)
        choice = questionary.select("Repos", choices=[*slugs, _ADD, _QUIT]).ask()
        if choice in (None, _QUIT):
            return
        if choice == _ADD:
            _add(store)
        else:
            _manage_one(store, choice)


def _add(store: RepoStore) -> None:
    name = (questionary.text("name:").ask() or "").strip()
    if not name:
        return
    slug_override = (
        questionary.text("slug (blank = auto-derive from name):").ask() or ""
    ).strip()
    try:
        slug = slug_override if slug_override else make_slug(name, exists=store.exists)
        store.create(Repo(version=1, slug=slug, name=name))
        console.print(f"[green]created[/green] {slug}")
    except (ConfigError, ValueError, RuntimeError) as e:
        console.print(f"[red]error:[/red] {e}")


def _manage_one(store: RepoStore, slug: str) -> None:
    while True:
        repo = store.load(slug)
        flag = " [red](retired)[/red]" if repo.retired else ""
        console.print(f"[bold]{repo.slug}[/bold] — {repo.name}{flag}")
        toggle = "restore" if repo.retired else "retire"
        action = questionary.select(
            "Action",
            choices=["view", "rename", "sources", "branches", toggle, "purge", _BACK],
        ).ask()
        if action in (None, _BACK):
            return
        if action == "view":
            _view(repo)
        elif action == "rename":
            name = (questionary.text("new name:", default=repo.name).ask() or "").strip()
            if name:
                repo.name = name
                store.save(repo)
        elif action in ("sources", "branches"):
            _edit_map(store, slug, action)
        elif action == "retire":
            store.retire(slug)
        elif action == "restore":
            store.restore(slug)
        elif action == "purge":
            if _confirm_purge(slug):
                store.purge(slug)
                console.print(f"[red]purged[/red] {slug}")
                return


def _view(repo: Repo) -> None:
    for label, mapping in (("sources", repo.sources), ("branches", repo.branches)):
        console.print(f"  {label}:")
        for name, value in mapping.items():
            console.print(f"    {name} = {value}")
        if not mapping:
            console.print("    (none)")


def _edit_map(store: RepoStore, slug: str, field: str) -> None:
    repo = store.load(slug)
    mapping = getattr(repo, field)
    action = questionary.select(
        field, choices=["add", *(f"remove {k}" for k in mapping), _BACK]
    ).ask()
    if action in (None, _BACK):
        return
    if action == "add":
        name = (questionary.text("name:").ask() or "").strip()
        value = (questionary.text("value:").ask() or "").strip()
        if name and value:
            mapping[name] = value
            store.save(repo)
    elif action.startswith("remove "):
        mapping.pop(action[len("remove ") :], None)
        store.save(repo)


def _confirm_purge(slug: str) -> bool:
    typed = questionary.text(
        f"Type '{slug}' to permanently delete it (irreversible):"
    ).ask()
    if typed != slug:
        console.print("[yellow]slug did not match; aborting[/yellow]")
        return False
    return True

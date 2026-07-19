"""Interactive, questionary-driven management of repo definitions.

Exposed as ``mono-control repo manage``. The menu loop needs a TTY; the actual
mutations all go through :class:`~mono_control.config.RepoStore`, which is what
the unit tests exercise.
"""

import questionary
from rich.console import Console

from mono_control import repo_ops
from mono_control.config import ConfigError, Repo, RepoStore, make_slug

console = Console()

_ADD = "[+ add new repo]"
_EXIT = "[exit repo manager]"
_BACK = "[back]"


def manage(store: RepoStore) -> None:
    """Run the interactive repo-management loop until the user exits."""
    while True:
        slugs = store.list(include_retired=True)
        choice = questionary.select("Repos", choices=[*slugs, _ADD, _EXIT]).ask()
        if choice in (None, _EXIT):
            return
        if choice == _ADD:
            _add(store)
        else:
            _manage_one(store, choice)


def _add(store: RepoStore) -> None:
    """Guided repo creation — walks the user into canonical source/branch values.

    Two paths: a **new** repo (init it on a chosen dev branch) or an **existing**
    one (ours=`origin` / someone-else's=`upstream` + optional `fork-ours`, with the
    remote's default branch probed and offered for `dev`). Still permissive — the
    prompts only *suggest* the governed names.
    """
    name = (questionary.text("name:").ask() or "").strip()
    if not name:
        return
    slug_override = (
        questionary.text("slug (blank = auto-derive from name):").ask() or ""
    ).strip()
    kind = questionary.select(
        "Is this a new repo, or does it already exist?", choices=["new", "existing"]
    ).ask()
    if kind is None:
        return
    try:
        slug = slug_override if slug_override else make_slug(name, exists=store.exists)
        if kind == "new":
            _add_new(store, name, slug)
        else:
            _add_existing(store, name, slug)
    except (ConfigError, ValueError, RuntimeError) as e:
        console.print(f"[red]error:[/red] {e}")


def _add_new(store: RepoStore, name: str, slug: str) -> None:
    dev = (questionary.text("dev branch name:", default="main").ask() or "").strip()
    if not dev:
        return
    resolved_slug, report = repo_ops.init(
        name,
        slug=slug,
        branches={"dev": dev},
        initial_branch=dev,
        repo_store=store,
        broker=store.broker,
    )
    console.print(f"[green]created[/green] {resolved_slug} (dev = {dev})")
    repo_ops.render_outcomes(f"init {resolved_slug}", report.outcomes, console=console)


def _add_existing(store: RepoStore, name: str, slug: str) -> None:
    choice = questionary.select(
        "Is this ours, or based on someone else's?",
        choices=["ours", "someone else's (upstream)"],
    ).ask()
    if choice is None:
        return
    sources: dict[str, str] = {}
    if choice == "ours":
        url = (questionary.text("origin URL:").ask() or "").strip()
        if not url:
            return
        sources["origin"] = url
    else:
        url = (questionary.text("upstream URL:").ask() or "").strip()
        if not url:
            return
        sources["upstream"] = url
        if questionary.confirm("Do you maintain your own fork?", default=False).ask():
            fork_url = (questionary.text("fork (ours) URL:").ask() or "").strip()
            if fork_url:
                sources["fork-ours"] = fork_url

    dev = _prompt_dev_from_remote(store, url)
    branches = {"dev": dev} if dev else {}
    store.create(Repo(version=1, slug=slug, name=name, sources=sources, branches=branches))
    console.print(f"[green]created[/green] {slug}")


def _prompt_dev_from_remote(store: RepoStore, url: str) -> str | None:
    """Probe the remote's default branch and offer it for `dev`; else ask (blank skips).

    The probe is a git effect, so it runs broker-side (``remote_default_branch``);
    the container just authors the URL and asks the broker to resolve its symbolic
    HEAD. A broker/transport failure degrades to the plain prompt.
    """
    try:
        default = store.broker.remote_default_branch(url)
    except Exception:
        console.print("[yellow](couldn't read the remote; specify the dev branch)[/yellow]")
        default = None
    if default and questionary.confirm(
        f"The remote's default branch is {default!r} — use it as `dev`?", default=True
    ).ask():
        return default
    return (
        questionary.text("dev branch name (blank to skip):", default=default or "").ask()
        or ""
    ).strip() or None


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

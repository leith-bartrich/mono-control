"""Interactive, questionary-driven management of repo definitions.

Exposed as ``mono-control repo manage``. The menu loop needs a TTY; the actual
mutations all go through :class:`~mono_control.config.RepoStore`, which is what
the unit tests exercise.
"""

import questionary
from rich.console import Console

from mono_control import repo_ops
from mono_control.config import ConfigError, Repo, RepoStore, make_slug, source_names

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
    one, whose three provenance states — theirs / ours / ours-forked-from-theirs —
    decide which sources and branches are even meaningful (see :func:`_add_existing`).
    The remote's default branch is probed and offered for `dev` throughout. Still
    permissive — the prompts only *suggest* the governed names.
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


# The three provenance states the source vocabulary can express, asked directly
# rather than as "ours?" plus a follow-up modifier. The second and third both set
# `upstream`, but they are different intents and they ask for different things next.
_THEIRS = "someone else's — we consume it"
_OURS = "ours — we originated it"
_OURS_FORKED = "ours — a fork of someone else's"


def _add_existing(store: RepoStore, name: str, slug: str) -> None:
    """Author an existing repo's sources + branches from its provenance.

    Which fields get asked for falls out of the answer: ``dev-upstream`` is
    meaningless without an upstream and redundant when we merely consume one, so it
    is reached only on the forked path (see ``docs/design/layers/data/repo.md``).
    """
    choice = questionary.select(
        "Where does this repo come from?", choices=[_THEIRS, _OURS, _OURS_FORKED]
    ).ask()
    if choice is None:
        return

    if choice == _OURS:
        url = (questionary.text("origin URL:").ask() or "").strip()
        if not url:
            return
        _create(store, name, slug, {source_names.ORIGIN: url}, url)
        return

    url = (questionary.text("upstream URL:").ask() or "").strip()
    if not url:
        return
    if choice == _THEIRS:
        # `dev` names the upstream's own line; there is no second line to record.
        _create(store, name, slug, {source_names.UPSTREAM: url}, url)
        return

    fork_url = (questionary.text("fork (ours) URL:").ask() or "").strip()
    if not fork_url:
        return
    # Create upstream-only first, then run the *governed* transition, so this path
    # produces exactly what `manage -> add fork` does: `dev` repointed to the fork's
    # line and the base's line preserved as `dev-upstream`. Hand-writing `fork-ours`
    # here is what let `dev` keep naming the upstream's branch.
    _create(store, name, slug, {source_names.UPSTREAM: url}, url)
    _adopt_fork_for(store, slug, fork_url)


def _create(
    store: RepoStore, name: str, slug: str, sources: dict[str, str], dev_from: str
) -> None:
    """Create the def, probing ``dev_from`` for the dev branch."""
    dev = _prompt_dev_from_remote(store, dev_from)
    branches = {source_names.DEV: dev} if dev else {}
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
        choices = ["view", "rename", "sources", "branches"]
        # The governed upstream→fork transition — offered only where it applies
        # (an upstream-based repo with no fork yet). The scriptable `repo fork
        # add` gates only on the exact key, for power users adding more forks.
        if source_names.UPSTREAM in repo.sources and not source_names.has_fork(
            repo.sources
        ):
            choices.append("add fork")
        choices += [toggle, "purge", _BACK]
        action = questionary.select("Action", choices=choices).ask()
        if action in (None, _BACK):
            return
        if action == "view":
            _view(repo)
        elif action == "add fork":
            _add_fork(store, repo)
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


def _add_fork(store: RepoStore, repo: Repo) -> None:
    """Guided upstream→fork transition — thin shell over :func:`repo_ops.adopt_fork`.

    Asks whose fork it is, the URL, and (ours only) whether the fork's dev
    line differs — probing the fork's default branch like ``_add_existing``.
    """
    whose = questionary.select(
        "Whose fork is this?",
        choices=["ours", "someone else's (tracked reference)"],
    ).ask()
    if whose is None:
        return
    purpose = "ours"
    if whose != "ours":
        purpose = (
            questionary.text("purpose name (e.g. their handle):").ask() or ""
        ).strip()
        if not purpose:
            return
    url = (questionary.text("fork URL:").ask() or "").strip()
    if not url:
        return
    dev_branch = _prompt_fork_dev(store, repo, url) if purpose == "ours" else None
    _adopt_fork(store, repo.slug, url, purpose=purpose, dev_branch=dev_branch)


def _adopt_fork_for(store: RepoStore, slug: str, url: str) -> None:
    """Run the ours-fork transition on a just-created upstream repo.

    Shares :func:`repo_ops.adopt_fork` with ``manage -> add fork`` so creating a
    forked repo and forking an existing one land in the same state.
    """
    try:
        repo = store.load(slug)
    except ConfigError as e:
        console.print(f"[red]error:[/red] {e}")
        return
    _adopt_fork(store, slug, url, purpose="ours", dev_branch=_prompt_fork_dev(store, repo, url))


def _adopt_fork(
    store: RepoStore, slug: str, url: str, *, purpose: str, dev_branch: str | None
) -> None:
    """Apply the governed transition and report what it changed."""
    try:
        result = repo_ops.adopt_fork(
            slug,
            url,
            purpose=purpose,
            dev_branch=dev_branch,
            repo_store=store,
            broker=store.broker,
        )
    except (ConfigError, ValueError, RuntimeError) as e:
        console.print(f"[red]error:[/red] {e}")
        return
    console.print(f"[green]set[/green] source {result.source_key}")
    if result.dev_repointed:
        old = (
            f" (old dev {result.old_dev!r} kept as dev-upstream)"
            if result.old_dev is not None
            else ""
        )
        console.print(f"[green]repointed[/green] dev -> {result.new_dev}{old}")
    if result.remote_stamped:
        console.print(
            f"[green]stamped[/green] remote {result.source_key} in {result.checkout}"
        )
    elif result.remote_error is not None:
        console.print(
            "[yellow]warning:[/yellow] config saved, but remote stamp failed: "
            f"{result.remote_error}"
        )
    else:
        console.print(
            "no on-disk checkout — config only (engines will conform the remote later)"
        )


def _prompt_fork_dev(store: RepoStore, repo: Repo, url: str) -> str | None:
    """Probe the fork's default branch and offer a dev repoint; ``None`` keeps dev.

    The probe is a git effect, so it runs broker-side (``remote_default_branch``);
    a broker/transport failure degrades to the plain prompt.
    """
    current = repo.branches.get(source_names.DEV)
    try:
        default = store.broker.remote_default_branch(url)
    except Exception:
        console.print("[yellow](couldn't read the fork; specify its dev branch)[/yellow]")
        default = None
    if default is not None:
        if default == current:
            return None  # same line — nothing to repoint
        tracked = (
            f"but tracked dev is {current!r}" if current is not None else "and no dev is tracked yet"
        )
        if questionary.confirm(
            f"The fork's default branch is {default!r} {tracked} — repoint dev to "
            "the fork's line (old line kept as 'dev-upstream')?",
            default=True,
        ).ask():
            return default
        return None
    branch = (
        questionary.text("fork's dev branch (blank = keep current dev):").ask() or ""
    ).strip()
    return branch or None


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

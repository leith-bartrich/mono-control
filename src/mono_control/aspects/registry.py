"""Explicit aspect registry + CLI assembly + config-side discovery helper."""

from __future__ import annotations

from typing import NamedTuple

import typer

from ..config import Repo, RepoStore


class Aspect(NamedTuple):
    """One registered aspect: its hyphenated name + Typer sub-app."""

    name: str  # the hyphenated form, e.g. "product-cluster"
    app: typer.Typer


REGISTERED_ASPECTS: list[Aspect] = []


def register(name: str, app: typer.Typer) -> None:
    """Register an aspect's CLI sub-app under ``mproj control <name>``."""
    REGISTERED_ASPECTS.append(Aspect(name=name, app=app))


def attach_aspect_commands(parent: typer.Typer) -> None:
    """Mount every registered aspect's sub-app under ``parent`` at the top level.

    Each aspect becomes a top-level command group on mono-control's CLI — the
    shim's ``mproj control <aspect-name> <verb>`` simply forwards to
    ``mono-control <aspect-name> <verb>`` (the shim's ``control`` subcommand
    is forwarding, not a nested mono-control group).
    """
    for aspect in REGISTERED_ASPECTS:
        parent.add_typer(aspect.app, name=aspect.name)


def discover_repos(
    repo_store: RepoStore,
    aspect_name: str,
    *,
    include_retired: bool = False,
) -> list[Repo]:
    """Return the repo defs whose ``aspects`` set contains ``aspect_name``.

    This is *discovery from config alone* (the cheap half of the aspect
    contract): no checkouts are required to enumerate the available members
    of an aspect.
    """
    matches: list[Repo] = []
    for slug in repo_store.list(include_retired=include_retired):
        repo = repo_store.load(slug)
        if aspect_name in repo.aspects:
            matches.append(repo)
    return matches

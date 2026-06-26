"""Per-repo outcomes the source engine produces (one record per slug)."""

from __future__ import annotations

from typing import Literal

from ...base_models import StrictModel

SourceStatus = Literal[
    "ok",  # already in the requested state; no action needed
    "cloned",  # was absent; clone succeeded; any requested refs verified
    "initialized",  # was absent and had no sources; init succeeded (no refs to verify)
    "fetched",  # was present; fetched; any requested refs verified
    "source-missing",  # absent but the repo def declares no usable source AND refs were requested
    "create-failed",  # clone or init raised
    "fetch-failed",  # fetch raised
    "ref-missing",  # post-action, one or more requested refs don't resolve locally
    "definition-missing",  # the request named a slug the RepoStore doesn't know
]


class SourceOutcome(StrictModel):
    """One repo's source-engine result."""

    slug: str
    status: SourceStatus
    summary: str
    unresolved_refs: set[str] = set()


class SourceReport(StrictModel):
    """All per-repo outcomes; ``ok`` iff every outcome succeeded."""

    outcomes: list[SourceOutcome] = []

    @property
    def ok(self) -> bool:
        good = {"ok", "cloned", "initialized", "fetched"}
        return all(o.status in good for o in self.outcomes)

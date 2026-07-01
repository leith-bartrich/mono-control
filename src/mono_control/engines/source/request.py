"""The source engine's input: a per-repo "make these refs available" map.

A source request is **additive** (no exclusivity, no un-acquire) — its own,
simpler thing than a [layout-target](../../../layout_target/), which is a
*convergent* desired state. A request is typically *derived from* a target;
``from_layout_target`` is that derivation.
"""

from __future__ import annotations

from ...base_models import StrictModel
from ...layout_target import (
    LayoutTarget,
    LayoutTargetPresentAsIs,
    LayoutTargetPresentBranchHead,
    LayoutTargetPresentCommit,
)


class SourceRequest(StrictModel):
    """Per slug, the set of refs that must be locally resolvable after the run.

    An empty set means "just ensure availability" (clone if absent; no specific
    refs to verify). A non-empty set means each ref must resolve locally
    (``git rev-parse``) after fetch.

    ``initial_branch`` names the branch a brand-new repo is ``git init``-ed on
    (only used when a slug is absent *and* declares no source); otherwise git's
    default applies.
    """

    refs_by_slug: dict[str, set[str]] = {}
    initial_branch: str | None = None


def from_layout_target(target: LayoutTarget) -> SourceRequest:
    """Derive the refs each repo needs to satisfy ``target``.

    - ``commit`` desired state → the commit hash as a ref to verify (any fetch
      that brings the commit object in will satisfy it).
    - ``branch-head`` desired state → ``refs/heads/<branch>`` to verify.
    - ``present-as-is`` desired state → empty ref set (acquire if absent;
      no specific refs to verify since we're not checking anything out).
    - ``absent`` desired state → omitted (acquisition is additive).
    """
    refs_by_slug: dict[str, set[str]] = {}
    for slug, desired in target.targets.items():
        if isinstance(desired, LayoutTargetPresentCommit):
            refs_by_slug[slug] = {desired.commit}
        elif isinstance(desired, LayoutTargetPresentBranchHead):
            refs_by_slug[slug] = {f"refs/heads/{desired.branch}"}
        elif isinstance(desired, LayoutTargetPresentAsIs):
            refs_by_slug[slug] = set()
        # absent → not acquired
    return SourceRequest(refs_by_slug=refs_by_slug)

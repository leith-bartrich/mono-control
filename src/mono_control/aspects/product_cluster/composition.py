"""Composition: resolving several co-active clusters into one arrangement.

A cluster's layout may declare ``requires`` — other clusters that must be **active
alongside** it. That is co-activation, not inclusion: the required cluster owns its
own arrangement and the requirer never restates it. See
``docs/design/layers/repo-aspects/product-cluster/composition.md``.

Two pure steps live here, both deliberately free of engine and console concerns so
``actions`` can decide what to *do* with the result:

- :func:`resolve_closure` — the transitive closure of ``requires`` from a root.
  Unordered and cycle-tolerant: ``A -> B -> C -> A`` simply means those three are
  always co-active.
- :func:`merge_members` — fold the active layouts into one member set.

Both are order-independent, which is what makes cycles safe: there is no "first"
cluster to privilege, so nothing depends on which one you happened to name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Literal

from .cluster_layout import ClusterLayout, LayoutMember

Role = Literal["dev", "dep"]


def join_roles(a: Role, b: Role) -> Role:
    """Join two roles for one member: ``dev`` dominates ``dep``.

    The one collision with a principled answer. If any active cluster *develops* a
    member, it materializes as ``dev`` and the co-active consumers get the
    development copy — which is the point of having them co-active at all. Join is
    commutative and associative, so it introduces no ordering.
    """
    return "dev" if "dev" in (a, b) else "dep"


# --------------------------------------------------------------------------- #
# Closure
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Closure:
    """The active cluster set reached from a root, plus what was learned on the way."""

    # Active cluster slugs, sorted — the root and everything transitively required.
    active: tuple[str, ...]
    # Layout per active cluster, for the ones that could be read.
    layouts: dict[str, ClusterLayout]
    # Required clusters whose layout could not be read (unreachable / unacquirable).
    unresolved: tuple[str, ...] = ()
    # Cluster slugs that participate in a `requires` cycle. Harmless under closure
    # semantics — reported as a design smell, never an error.
    cycles: tuple[str, ...] = ()


def resolve_closure(
    root: str,
    read_layout: Callable[[str], ClusterLayout | None],
) -> Closure:
    """Walk ``requires`` from ``root``, returning every co-active cluster.

    ``read_layout`` maps a cluster slug to its layout, or ``None`` when the layout
    cannot be read (the cluster could not be acquired, say). A cluster that cannot be
    read is still *active* — it was required — but contributes no members and is
    reported in ``unresolved``.

    The traversal is a fixpoint over a visited set, so a ``requires`` cycle
    terminates rather than recursing: the members of the cycle are simply all
    co-active. Acquiring each cluster in order to read it is a *fetch* sequence, not
    a precedence one — nothing here depends on the order slugs come back in.
    """
    layouts: dict[str, ClusterLayout] = {}
    unresolved: list[str] = []
    seen: set[str] = set()
    # `requires` edges, kept so cycles can be reported after the walk.
    edges: dict[str, set[str]] = {}

    pending = [root]
    while pending:
        slug = pending.pop()
        if slug in seen:
            continue
        seen.add(slug)
        layout = read_layout(slug)
        if layout is None:
            unresolved.append(slug)
            edges[slug] = set()
            continue
        layouts[slug] = layout
        edges[slug] = set(layout.requires)
        pending.extend(layout.requires)

    return Closure(
        active=tuple(sorted(seen)),
        layouts=layouts,
        unresolved=tuple(sorted(unresolved)),
        cycles=_cycle_members(edges),
    )


def _cycle_members(edges: dict[str, set[str]]) -> tuple[str, ...]:
    """Slugs that lie on a ``requires`` cycle, sorted.

    A node is on a cycle when it can reach itself. The graphs here are tiny (clusters
    in a workspace), so a reachability walk per node is cheaper than the machinery a
    proper SCC pass would need.
    """
    on_cycle: set[str] = set()
    for start in edges:
        stack = list(edges.get(start, ()))
        reached: set[str] = set()
        while stack:
            node = stack.pop()
            if node in reached:
                continue
            reached.add(node)
            stack.extend(edges.get(node, ()))
        if start in reached:
            on_cycle.add(start)
    return tuple(sorted(on_cycle))


# --------------------------------------------------------------------------- #
# Merge
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MemberConflict:
    """Two active clusters disagree about one member, unsatisfiably."""

    slug: str
    field: str  # the field they disagree on, e.g. "location"
    # cluster slug -> the value it declared, for every distinct value
    values: dict[str, str]

    def describe(self) -> str:
        claims = ", ".join(
            f"{cluster} wants {value!r}" for cluster, value in sorted(self.values.items())
        )
        return f"{self.slug}: conflicting {self.field} ({claims})"


@dataclass(frozen=True)
class RoleJoin:
    """A member declared ``dev`` by one cluster and ``dep`` by another.

    Not a conflict — the join resolves it — but the losing cluster's declared intent
    is being set aside, which is exactly the kind of thing that is obvious while you
    are doing it and baffling a week later. Callers report it loudly.
    """

    slug: str
    dev_clusters: tuple[str, ...]
    dep_clusters: tuple[str, ...]

    def describe(self) -> str:
        return (
            f"{self.slug}: developed by {', '.join(self.dev_clusters)} — "
            f"{', '.join(self.dep_clusters)} declared it a dep and will get the "
            f"development copy"
        )


@dataclass(frozen=True)
class Merge:
    """The union of every active cluster's members."""

    members: dict[str, LayoutMember] = field(default_factory=dict)
    conflicts: tuple[MemberConflict, ...] = ()
    joins: tuple[RoleJoin, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.conflicts


def merge_members(layouts: dict[str, ClusterLayout]) -> Merge:
    """Fold every active cluster's members into one arrangement.

    ``location`` must be **equal** across the clusters naming a member — one worktree
    lives in one place, and two candidates have no principled winner, so a
    disagreement is a conflict. ``role`` joins instead (see :func:`join_roles`).

    A shared member is the normal case and produces nothing to report. Every rule is
    commutative, so the result does not depend on the iteration order of ``layouts``.
    """
    merged: dict[str, LayoutMember] = {}
    locations: dict[str, dict[str, str]] = {}  # slug -> {cluster: location}
    roles: dict[str, dict[str, list[str]]] = {}  # slug -> {role: [clusters]}

    for cluster, layout in sorted(layouts.items()):
        for slug, member in layout.members.items():
            locations.setdefault(slug, {})[cluster] = member.location
            roles.setdefault(slug, {}).setdefault(member.role, []).append(cluster)
            if slug not in merged:
                merged[slug] = member
                continue
            merged[slug] = LayoutMember(
                location=merged[slug].location,
                role=join_roles(merged[slug].role, member.role),
            )

    conflicts = tuple(
        MemberConflict(slug=slug, field="location", values=by_cluster)
        for slug, by_cluster in sorted(locations.items())
        if len(set(by_cluster.values())) > 1
    )
    joins = tuple(
        RoleJoin(
            slug=slug,
            dev_clusters=tuple(sorted(by_role["dev"])),
            dep_clusters=tuple(sorted(by_role["dep"])),
        )
        for slug, by_role in sorted(roles.items())
        if "dev" in by_role and "dep" in by_role
    )
    return Merge(members=merged, conflicts=conflicts, joins=joins)


def missing_worktrees(active: Iterable[str], materialized: set[str]) -> tuple[str, ...]:
    """Active clusters that have no worktree yet, sorted.

    Acquiring a required cluster is free and always happens (it makes an unreachable
    remote fail early). *Placing* its worktree is a statement of intent, so the caller
    decides — see ``actions.relayout``.
    """
    return tuple(sorted(slug for slug in active if slug not in materialized))

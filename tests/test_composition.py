"""Tests for the composition closure + merge — the pure half of co-activation.

Both functions are deliberately engine-free, so these need no broker: they pin the
properties the design leans on (order-independence, cycle tolerance, a commutative
merge) rather than any placement behavior. See
``docs/design/layers/repo-aspects/product-cluster/composition.md``.
"""

import pytest

from mono_control.aspects.product_cluster.cluster_layout import ClusterLayout, LayoutMember
from mono_control.aspects.product_cluster.composition import (
    join_roles,
    merge_members,
    missing_worktrees,
    resolve_closure,
)


def _layout(*, members=None, requires=()) -> ClusterLayout:
    return ClusterLayout(
        version=2,
        members={
            slug: LayoutMember(location=loc, role=role)
            for slug, (loc, role) in (members or {}).items()
        },
        requires=set(requires),
    )


def _reader(graph: dict[str, ClusterLayout | None]):
    return lambda slug: graph.get(slug)


# --------------------------------------------------------------------------- #
# Closure
# --------------------------------------------------------------------------- #
def test_closure_of_a_lone_cluster_is_itself():
    closure = resolve_closure("a", _reader({"a": _layout()}))
    assert closure.active == ("a",)
    assert closure.unresolved == ()
    assert closure.cycles == ()


def test_closure_is_transitive():
    closure = resolve_closure(
        "a",
        _reader(
            {
                "a": _layout(requires=["b"]),
                "b": _layout(requires=["c"]),
                "c": _layout(),
            }
        ),
    )
    assert closure.active == ("a", "b", "c")


def test_closure_tolerates_a_cycle_and_reports_it():
    """A -> B -> C -> A just means the three are always co-active."""
    graph = {
        "a": _layout(requires=["b"]),
        "b": _layout(requires=["c"]),
        "c": _layout(requires=["a"]),
    }
    closure = resolve_closure("a", _reader(graph))
    assert closure.active == ("a", "b", "c")
    assert closure.cycles == ("a", "b", "c")


def test_closure_is_independent_of_which_member_of_a_cycle_is_named():
    """The property that makes ordering unnecessary: no cluster is privileged."""
    graph = {
        "a": _layout(requires=["b"]),
        "b": _layout(requires=["a"]),
        "c": _layout(),
    }
    assert resolve_closure("a", _reader(graph)).active == ("a", "b")
    assert resolve_closure("b", _reader(graph)).active == ("a", "b")


def test_closure_reports_unreadable_clusters_but_keeps_them_active():
    closure = resolve_closure(
        "a", _reader({"a": _layout(requires=["gone"]), "gone": None})
    )
    assert closure.active == ("a", "gone")
    assert closure.unresolved == ("gone",)


def test_self_requirement_is_a_cycle_not_a_hang():
    closure = resolve_closure("a", _reader({"a": _layout(requires=["a"])}))
    assert closure.active == ("a",)
    assert closure.cycles == ("a",)


# --------------------------------------------------------------------------- #
# Merge
# --------------------------------------------------------------------------- #
def test_join_roles_is_commutative_and_dev_dominates():
    assert join_roles("dev", "dep") == "dev"
    assert join_roles("dep", "dev") == "dev"
    assert join_roles("dep", "dep") == "dep"
    assert join_roles("dev", "dev") == "dev"


def test_disjoint_members_union():
    merge = merge_members(
        {
            "a": _layout(members={"m1": ("one", "dev")}),
            "b": _layout(members={"m2": ("two", "dep")}),
        }
    )
    assert merge.ok
    assert set(merge.members) == {"m1", "m2"}


def test_shared_member_in_agreement_is_silent():
    """The normal case for a library shared by two clusters — nothing to report."""
    shared = {"lib": ("libs/lib", "dep")}
    merge = merge_members({"a": _layout(members=shared), "b": _layout(members=shared)})
    assert merge.ok
    assert merge.joins == ()
    assert merge.members["lib"].role == "dep"


def test_role_join_resolves_and_is_reported():
    merge = merge_members(
        {
            "app": _layout(members={"lib": ("libs/lib", "dep")}),
            "libdev": _layout(members={"lib": ("libs/lib", "dev")}),
        }
    )
    assert merge.ok  # a join, not a conflict
    assert merge.members["lib"].role == "dev"
    (join,) = merge.joins
    assert join.slug == "lib"
    assert join.dev_clusters == ("libdev",) and join.dep_clusters == ("app",)
    assert "libdev" in join.describe()


def test_location_disagreement_is_a_conflict():
    merge = merge_members(
        {
            "a": _layout(members={"lib": ("libs/lib", "dep")}),
            "b": _layout(members={"lib": ("vendor/lib", "dep")}),
        }
    )
    assert not merge.ok
    (conflict,) = merge.conflicts
    assert conflict.slug == "lib" and conflict.field == "location"
    assert set(conflict.values.values()) == {"libs/lib", "vendor/lib"}


@pytest.mark.parametrize("order", [("a", "b"), ("b", "a")])
def test_merge_is_commutative(order):
    """Same inputs, either iteration order, same answer — what makes cycles safe."""
    layouts = {
        "a": _layout(members={"lib": ("libs/lib", "dep"), "only_a": ("a", "dev")}),
        "b": _layout(members={"lib": ("libs/lib", "dev")}),
    }
    merge = merge_members({k: layouts[k] for k in order})
    assert merge.members["lib"].role == "dev"
    assert merge.members["lib"].location == "libs/lib"
    assert set(merge.members) == {"lib", "only_a"}
    assert len(merge.joins) == 1


# --------------------------------------------------------------------------- #
# Placement intent
# --------------------------------------------------------------------------- #
def test_missing_worktrees_reports_only_unplaced():
    assert missing_worktrees(["a", "b", "c"], {"a", "c"}) == ("b",)
    assert missing_worktrees(["a"], {"a"}) == ()

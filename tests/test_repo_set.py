from mono_control.repo_set import RepoSetLike, missing_members
from mono_control.snapshot import Snapshot, SnapshotEntry


class _Members:
    """A trivial RepoSetLike stand-in: enumerates a fixed set of slugs."""

    def __init__(self, slugs):
        self.slugs = set(slugs)

    def members(self):
        return set(self.slugs)


def test_missing_members_existence_gate():
    rs = _Members({"alpha", "beta", "gamma"})
    # gamma was purged (absent from config)
    assert missing_members(rs, {"alpha", "beta"}) == {"gamma"}
    assert missing_members(rs, {"alpha", "beta", "gamma"}) == set()


def test_missing_members_accepts_a_snapshot():
    # The protocol unifies them: a Snapshot is a RepoSetLike via members().
    snap = Snapshot(entries={"alpha": SnapshotEntry(commit="a" * 40, location="alpha")})
    assert missing_members(snap, {"alpha"}) == set()
    assert missing_members(snap, set()) == {"alpha"}


def test_runtime_checkable_protocol():
    # RepoSetLike is @runtime_checkable; both implementers satisfy it.
    assert isinstance(_Members(set()), RepoSetLike)
    assert isinstance(Snapshot(), RepoSetLike)

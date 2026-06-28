import pytest
from pydantic import ValidationError

from mono_control.layout_target import (
    LayoutTarget,
    LayoutTargetAbsent,
    LayoutTargetPresentAsIs,
    LayoutTargetPresentBranchHead,
    LayoutTargetPresentCommit,
)


def test_empty_target_defaults():
    t = LayoutTarget()
    assert t.pre_clear is False
    assert t.targets == {}


def test_present_commit_state():
    t = LayoutTarget(
        targets={
            "alpha": LayoutTargetPresentCommit(commit="a" * 40, location="alpha"),
        }
    )
    state = t.targets["alpha"]
    assert state.kind == "commit"
    assert state.commit == "a" * 40
    assert state.location == "alpha"


def test_present_branch_head_state():
    t = LayoutTarget(
        targets={
            "beta": LayoutTargetPresentBranchHead(branch="main", location="beta"),
        }
    )
    state = t.targets["beta"]
    assert state.kind == "branch-head"
    assert state.branch == "main"


def test_absent_state():
    t = LayoutTarget(targets={"gamma": LayoutTargetAbsent()})
    assert t.targets["gamma"].kind == "absent"


def test_present_as_is_state():
    t = LayoutTarget(
        targets={
            "delta": LayoutTargetPresentAsIs(location="apps/delta"),
        }
    )
    state = t.targets["delta"]
    assert state.kind == "present-as-is"
    assert state.location == "apps/delta"


def test_discriminator_round_trip_from_dict():
    t = LayoutTarget.model_validate(
        {
            "pre_clear": True,
            "targets": {
                "alpha": {"kind": "commit", "commit": "c" * 40, "location": "alpha"},
                "beta": {"kind": "branch-head", "branch": "dev", "location": "beta"},
                "gamma": {"kind": "absent"},
                "delta": {"kind": "present-as-is", "location": "apps/delta"},
            },
        }
    )
    assert t.pre_clear is True
    assert isinstance(t.targets["alpha"], LayoutTargetPresentCommit)
    assert isinstance(t.targets["beta"], LayoutTargetPresentBranchHead)
    assert isinstance(t.targets["gamma"], LayoutTargetAbsent)
    assert isinstance(t.targets["delta"], LayoutTargetPresentAsIs)


def test_unknown_kind_rejected():
    with pytest.raises(ValidationError):
        LayoutTarget.model_validate(
            {"targets": {"x": {"kind": "bogus", "commit": "c" * 40}}}
        )


def test_unknown_top_level_key_rejected():
    with pytest.raises(ValidationError):
        LayoutTarget.model_validate({"pre_clear": False, "bogus": 1})


def test_unknown_state_key_rejected():
    with pytest.raises(ValidationError):
        LayoutTarget.model_validate(
            {
                "targets": {
                    "x": {
                        "kind": "commit",
                        "commit": "c" * 40,
                        "location": "x",
                        "extra": 1,
                    }
                }
            }
        )

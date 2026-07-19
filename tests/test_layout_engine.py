"""Layout engine: pure plan() classification + broker-dispatch execution.

``plan()`` is pure data (no git), tested by feeding synthetic inventories and the
acquire-resolved ref map. ``run()``/``execute()`` dispatch to the broker's layout
verbs — the happy paths run against the real-effect shim; the composite/edge
outcomes (partial, race-aborted, propagation) run against canned fake responses.
"""

from pathlib import Path

import pytest

from broker_shim import GitRepo, ShimBroker, clone, init, run_git, PROFILE
from mono_control.broker import FakeBroker
from mono_control.engines.layout import plan, run
from mono_control.engines.layout.execute import execute
from mono_control.on_disk import OnDiskInventory, OnDiskRepo, scan
from mono_control.layout_target import (
    LayoutTarget,
    LayoutTargetAbsent,
    LayoutTargetPresentAsIs,
    LayoutTargetPresentBranchHead,
    LayoutTargetPresentCommit,
)

WS = Path("/ws")


def _repo(slug, location, state, commit="c0ffee", dirty=False):
    return OnDiskRepo(slug=slug, location=location, state=state, commit=commit, dirty=dirty)


# --------------------------------------------------------------------------- #
# Pure plan() classification
# --------------------------------------------------------------------------- #
def test_plan_place_from_offline():
    inv = OnDiskInventory(repos={"a": _repo("a", Path("/off/a"), "offline")})
    target = LayoutTarget(targets={"a": LayoutTargetPresentCommit(commit="dead", location="a")})
    (item,) = plan(target, inv, workspace_root=WS)
    assert item.action == "place"
    assert item.classification == "actionable"
    assert item.resolved_commit == "dead"
    assert item.target_location == WS / "a"


def test_plan_satisfied_when_in_place_at_commit():
    inv = OnDiskInventory(repos={"a": _repo("a", WS / "a", "materialized", commit="dead")})
    target = LayoutTarget(targets={"a": LayoutTargetPresentCommit(commit="dead", location="a")})
    (item,) = plan(target, inv, workspace_root=WS)
    assert item.classification == "satisfied"
    assert item.action == "none"


def test_plan_checkout_on_ref_change():
    inv = OnDiskInventory(repos={"a": _repo("a", WS / "a", "materialized", commit="old")})
    target = LayoutTarget(targets={"a": LayoutTargetPresentCommit(commit="new", location="a")})
    (item,) = plan(target, inv, workspace_root=WS)
    assert item.action == "checkout"
    assert item.resolved_commit == "new"


def test_plan_blocks_dirty_ref_change():
    inv = OnDiskInventory(
        repos={"a": _repo("a", WS / "a", "materialized", commit="old", dirty=True)}
    )
    target = LayoutTarget(targets={"a": LayoutTargetPresentCommit(commit="new", location="a")})
    (item,) = plan(target, inv, workspace_root=WS)
    assert item.classification == "blocked"
    assert "dirty" in item.reason


def test_plan_relocate_to_new_location():
    inv = OnDiskInventory(repos={"a": _repo("a", WS / "old", "materialized", commit="dead")})
    target = LayoutTarget(targets={"a": LayoutTargetPresentCommit(commit="dead", location="new")})
    (item,) = plan(target, inv, workspace_root=WS)
    assert item.action == "relocate"
    assert item.target_location == WS / "new"


def test_plan_retire_via_absent():
    inv = OnDiskInventory(repos={"a": _repo("a", WS / "a", "materialized")})
    target = LayoutTarget(targets={"a": LayoutTargetAbsent()})
    (item,) = plan(target, inv, workspace_root=WS)
    assert item.action == "retire"


def test_plan_branch_head_uses_resolved_map():
    inv = OnDiskInventory(repos={"a": _repo("a", Path("/off/a"), "offline")})
    target = LayoutTarget(
        targets={"a": LayoutTargetPresentBranchHead(branch="main", location="a")}
    )
    resolved = {"a": {"refs/heads/main": "beef123"}}
    (item,) = plan(target, inv, workspace_root=WS, resolved_refs=resolved)
    assert item.action == "place"
    assert item.resolved_commit == "beef123"


def test_plan_branch_head_blocked_when_unresolved():
    inv = OnDiskInventory(repos={"a": _repo("a", Path("/off/a"), "offline")})
    target = LayoutTarget(
        targets={"a": LayoutTargetPresentBranchHead(branch="nope", location="a")}
    )
    (item,) = plan(target, inv, workspace_root=WS, resolved_refs={})
    assert item.classification == "blocked"
    assert "branch" in item.reason


def test_plan_present_as_is_blocked_when_absent():
    inv = OnDiskInventory()
    target = LayoutTarget(targets={"a": LayoutTargetPresentAsIs(location="a")})
    (item,) = plan(target, inv, workspace_root=WS)
    assert item.classification == "blocked"
    assert "absent" in item.reason


def test_plan_pre_clear_retires_extras():
    inv = OnDiskInventory(
        repos={
            "a": _repo("a", WS / "a", "materialized", commit="dead"),
            "b": _repo("b", WS / "b", "materialized"),
        }
    )
    target = LayoutTarget(
        pre_clear=True,
        targets={"a": LayoutTargetPresentCommit(commit="dead", location="a")},
    )
    by_slug = {i.slug: i for i in plan(target, inv, workspace_root=WS)}
    assert by_slug["a"].classification == "satisfied"
    assert by_slug["b"].action == "retire"


# --------------------------------------------------------------------------- #
# execute() dispatch — canned fake responses
# --------------------------------------------------------------------------- #
def _placed():
    return {"status": "placed", "summary": "placed"}


def test_execute_place_then_checkout_is_placed():
    inv = OnDiskInventory(repos={"a": _repo("a", Path("/off/a"), "offline")})
    target = LayoutTarget(targets={"a": LayoutTargetPresentCommit(commit="dead", location="a")})
    fake = FakeBroker(
        results={"place": _placed(), "checkout": {"status": "checked-out", "summary": "ok"}}
    )
    report = run(target, broker=fake, inventory=inv, workspace_root=WS)
    assert report.outcomes[0].status == "placed"
    assert [m for m, _ in fake.calls] == ["place", "checkout"]


def test_execute_partial_when_checkout_fails_after_move():
    inv = OnDiskInventory(repos={"a": _repo("a", Path("/off/a"), "offline")})
    target = LayoutTarget(targets={"a": LayoutTargetPresentCommit(commit="deadbeef", location="a")})
    fake = FakeBroker(
        results={"place": _placed(), "checkout": {"status": "failed", "summary": "nope"}}
    )
    report = run(target, broker=fake, inventory=inv, workspace_root=WS)
    outcome = report.outcomes[0]
    assert outcome.status == "partial"
    assert "placed" in outcome.summary and "checkout" in outcome.summary


def test_execute_place_race_aborted_skips_checkout():
    inv = OnDiskInventory(repos={"a": _repo("a", Path("/off/a"), "offline")})
    target = LayoutTarget(targets={"a": LayoutTargetPresentCommit(commit="dead", location="a")})
    fake = FakeBroker(results={"place": {"status": "race-aborted", "summary": "gone"}})
    report = run(target, broker=fake, inventory=inv, workspace_root=WS)
    assert report.outcomes[0].status == "race-aborted"
    # checkout must NOT be attempted after a failed move
    assert [m for m, _ in fake.calls] == ["place"]


def test_execute_present_as_is_place_has_no_checkout():
    inv = OnDiskInventory(repos={"a": _repo("a", Path("/off/a"), "offline")})
    target = LayoutTarget(targets={"a": LayoutTargetPresentAsIs(location="a")})
    fake = FakeBroker(results={"place": _placed()})
    report = run(target, broker=fake, inventory=inv, workspace_root=WS)
    assert report.outcomes[0].status == "placed"
    assert [m for m, _ in fake.calls] == ["place"]  # no checkout


def test_execute_unexpected_exception_propagates():
    class _Boom(FakeBroker):
        def call(self, method, params=None):
            if method == "place":
                raise ZeroDivisionError("simulated broker bug")
            return super().call(method, params)

    inv = OnDiskInventory(repos={"a": _repo("a", Path("/off/a"), "offline")})
    target = LayoutTarget(targets={"a": LayoutTargetPresentAsIs(location="a")})
    with pytest.raises(ZeroDivisionError):
        execute(
            plan(target, inv, workspace_root=WS), broker=_Boom(), workspace_root=WS
        )


# --------------------------------------------------------------------------- #
# Integration through the real-effect shim
# --------------------------------------------------------------------------- #
def _origin(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--initial-branch", "main", str(path)])
    (path / "README.md").write_text("hello\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "initial"], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path)


def _roots(tmp_path):
    ws, off = tmp_path / "ws", tmp_path / "off"
    ws.mkdir()
    off.mkdir()
    return ShimBroker(tmp_path / "config", ws, off), ws, off


def test_integration_place_offline_into_workspace(tmp_path):
    head = _origin(tmp_path / "origin")
    broker, ws, off = _roots(tmp_path)
    clone(tmp_path / "origin", off / "alpha", profile=PROFILE, slug="alpha")
    target = LayoutTarget(targets={"alpha": LayoutTargetPresentCommit(commit=head, location="alpha")})
    report = run(target, broker=broker, inventory=scan(broker, ws, off), workspace_root=ws)
    assert report.outcomes[0].status == "placed"
    assert (ws / "alpha" / ".git").is_dir()
    assert not (off / "alpha").exists()


def test_integration_retire_via_absent(tmp_path):
    _origin(tmp_path / "origin")
    broker, ws, off = _roots(tmp_path)
    clone(tmp_path / "origin", ws / "alpha", profile=PROFILE, slug="alpha")
    target = LayoutTarget(targets={"alpha": LayoutTargetAbsent()})
    report = run(target, broker=broker, inventory=scan(broker, ws, off), workspace_root=ws)
    assert report.outcomes[0].status == "retired"
    assert not (ws / "alpha").exists()
    assert (off / "alpha" / ".git").is_dir()


def test_integration_retire_blocked_when_offline_occupied(tmp_path):
    _origin(tmp_path / "origin")
    broker, ws, off = _roots(tmp_path)
    clone(tmp_path / "origin", ws / "alpha", profile=PROFILE, slug="alpha")
    (off / "alpha").mkdir()  # occupy the offline spot
    target = LayoutTarget(targets={"alpha": LayoutTargetAbsent()})
    report = run(target, broker=broker, inventory=scan(broker, ws, off), workspace_root=ws)
    assert report.outcomes[0].status == "blocked"
    assert (ws / "alpha" / ".git").is_dir()  # untouched


def test_integration_relocate(tmp_path):
    head = _origin(tmp_path / "origin")
    broker, ws, off = _roots(tmp_path)
    clone(tmp_path / "origin", ws / "old", profile=PROFILE, slug="alpha")
    target = LayoutTarget(targets={"alpha": LayoutTargetPresentCommit(commit=head, location="new")})
    report = run(target, broker=broker, inventory=scan(broker, ws, off), workspace_root=ws)
    assert report.outcomes[0].status == "relocated"
    assert not (ws / "old").exists()
    assert (ws / "new" / ".git").is_dir()

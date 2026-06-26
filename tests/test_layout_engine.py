from pathlib import Path

import pytest

from mono_control.engines.layout import run
from mono_control.git import clone
from mono_control.git.runner import run_git
from mono_control.host_platform import FsProfile
from mono_control.layout_target import (
    LayoutTarget,
    LayoutTargetAbsent,
    LayoutTargetPresentBranchHead,
    LayoutTargetPresentCommit,
)
from mono_control.on_disk import scan

PROFILE = FsProfile(filemode=True, symlinks=True, ignorecase=False)


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")


def _origin(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", str(path)])
    (path / "README.md").write_text("hello\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "initial"], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path)


def _commit_more(path: Path, name: str) -> str:
    (path / name).write_text(name + "\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", name], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path)


def _workspace_roots(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "ws"
    offline = tmp_path / "off"
    workspace.mkdir()
    offline.mkdir()
    return workspace, offline


def test_place_offline_into_workspace(tmp_path):
    head = _origin(tmp_path / "origin")
    workspace, offline = _workspace_roots(tmp_path)
    clone(tmp_path / "origin", offline / "alpha", profile=PROFILE, slug="alpha")

    target = LayoutTarget(
        targets={
            "alpha": LayoutTargetPresentCommit(commit=head, location="alpha"),
        }
    )
    report = run(
        target,
        inventory=scan(workspace, offline),
        workspace_root=workspace,
        offline_root=offline,
    )

    assert report.ok
    assert report.outcomes[0].status == "placed"
    assert (workspace / "alpha" / ".git").is_dir()
    assert not (offline / "alpha").exists()


def test_satisfied_when_already_in_place(tmp_path):
    head = _origin(tmp_path / "origin")
    workspace, offline = _workspace_roots(tmp_path)
    clone(tmp_path / "origin", workspace / "alpha", profile=PROFILE, slug="alpha")

    target = LayoutTarget(
        targets={
            "alpha": LayoutTargetPresentCommit(commit=head, location="alpha"),
        }
    )
    report = run(
        target,
        inventory=scan(workspace, offline),
        workspace_root=workspace,
        offline_root=offline,
    )
    assert report.outcomes[0].status == "satisfied"


def test_checkout_changes_ref_in_place(tmp_path):
    origin = tmp_path / "origin"
    first = _origin(origin)
    second = _commit_more(origin, "second.txt")

    workspace, offline = _workspace_roots(tmp_path)
    repo = clone(origin, workspace / "alpha", profile=PROFILE, slug="alpha")
    # Pull `second` into the local object DB so it's resolvable.
    repo.fetch("origin")
    # Reset so observed.commit is `first`.
    run_git(["checkout", first], cwd=repo.path)

    target = LayoutTarget(
        targets={
            "alpha": LayoutTargetPresentCommit(commit=second, location="alpha"),
        }
    )
    report = run(
        target,
        inventory=scan(workspace, offline),
        workspace_root=workspace,
        offline_root=offline,
    )
    assert report.outcomes[0].status == "checked-out"
    assert repo.current_commit() == second


def test_dirty_ref_change_is_blocked(tmp_path):
    origin = tmp_path / "origin"
    first = _origin(origin)
    second = _commit_more(origin, "second.txt")

    workspace, offline = _workspace_roots(tmp_path)
    repo = clone(origin, workspace / "alpha", profile=PROFILE, slug="alpha")
    repo.fetch("origin")
    run_git(["checkout", first], cwd=repo.path)
    (repo.path / "README.md").write_text("local edits\n")  # dirty

    target = LayoutTarget(
        targets={
            "alpha": LayoutTargetPresentCommit(commit=second, location="alpha"),
        }
    )
    report = run(
        target,
        inventory=scan(workspace, offline),
        workspace_root=workspace,
        offline_root=offline,
    )
    assert report.outcomes[0].status == "blocked"
    assert "dirty" in report.outcomes[0].summary


def test_retire_via_absent(tmp_path):
    head = _origin(tmp_path / "origin")
    workspace, offline = _workspace_roots(tmp_path)
    clone(tmp_path / "origin", workspace / "alpha", profile=PROFILE, slug="alpha")

    target = LayoutTarget(targets={"alpha": LayoutTargetAbsent()})
    report = run(
        target,
        inventory=scan(workspace, offline),
        workspace_root=workspace,
        offline_root=offline,
    )
    assert report.outcomes[0].status == "retired"
    assert not (workspace / "alpha").exists()
    assert (offline / "alpha" / ".git").is_dir()
    del head  # not asserted on


def test_retire_blocked_when_offline_occupied(tmp_path):
    _origin(tmp_path / "origin")
    workspace, offline = _workspace_roots(tmp_path)
    clone(tmp_path / "origin", workspace / "alpha", profile=PROFILE, slug="alpha")
    # Block the offline spot with a placeholder.
    (offline / "alpha").mkdir()

    target = LayoutTarget(targets={"alpha": LayoutTargetAbsent()})
    report = run(
        target,
        inventory=scan(workspace, offline),
        workspace_root=workspace,
        offline_root=offline,
    )
    assert report.outcomes[0].status == "blocked"
    assert (workspace / "alpha" / ".git").is_dir()  # untouched


def test_relocate(tmp_path):
    head = _origin(tmp_path / "origin")
    workspace, offline = _workspace_roots(tmp_path)
    clone(tmp_path / "origin", workspace / "old", profile=PROFILE, slug="alpha")

    target = LayoutTarget(
        targets={
            "alpha": LayoutTargetPresentCommit(commit=head, location="new"),
        }
    )
    report = run(
        target,
        inventory=scan(workspace, offline),
        workspace_root=workspace,
        offline_root=offline,
    )
    assert report.outcomes[0].status == "relocated"
    assert not (workspace / "old").exists()
    assert (workspace / "new" / ".git").is_dir()


def test_branch_head_resolved_locally(tmp_path):
    origin = tmp_path / "origin"
    _origin(origin)
    workspace, offline = _workspace_roots(tmp_path)
    repo = clone(origin, offline / "alpha", profile=PROFILE, slug="alpha")
    repo.fetch("origin")  # populate remote-tracking refs

    # Advance origin and fetch so the source branch ref has a new HEAD locally.
    new_head = _commit_more(origin, "second.txt")
    repo.fetch("origin")

    target = LayoutTarget(
        targets={
            "alpha": LayoutTargetPresentBranchHead(branch="master", location="alpha"),
        }
    )
    # Try both default branch names since git's init default varies.
    inv = scan(workspace, offline)
    report = run(
        target,
        inventory=inv,
        workspace_root=workspace,
        offline_root=offline,
    )
    if report.outcomes[0].status == "blocked":
        target = LayoutTarget(
            targets={
                "alpha": LayoutTargetPresentBranchHead(branch="main", location="alpha"),
            }
        )
        report = run(
            target,
            inventory=inv,
            workspace_root=workspace,
            offline_root=offline,
        )
    assert report.outcomes[0].status == "placed"
    from mono_control.git import GitRepo

    assert GitRepo(workspace / "alpha").current_commit() == new_head


def test_branch_head_blocked_when_not_local(tmp_path):
    workspace, offline = _workspace_roots(tmp_path)
    # Create an offline repo with no fetched refs.
    from mono_control.git import init

    init(offline / "alpha", profile=PROFILE, slug="alpha")
    target = LayoutTarget(
        targets={
            "alpha": LayoutTargetPresentBranchHead(branch="nope", location="alpha"),
        }
    )
    report = run(
        target,
        inventory=scan(workspace, offline),
        workspace_root=workspace,
        offline_root=offline,
    )
    assert report.outcomes[0].status == "blocked"
    assert "branch" in report.outcomes[0].summary


def test_pre_clear_retires_extras(tmp_path):
    head = _origin(tmp_path / "origin")
    workspace, offline = _workspace_roots(tmp_path)
    clone(tmp_path / "origin", workspace / "alpha", profile=PROFILE, slug="alpha")
    clone(tmp_path / "origin", workspace / "beta", profile=PROFILE, slug="beta")

    # Target keeps alpha, omits beta with pre_clear=True → beta gets retired.
    target = LayoutTarget(
        pre_clear=True,
        targets={
            "alpha": LayoutTargetPresentCommit(commit=head, location="alpha"),
        },
    )
    report = run(
        target,
        inventory=scan(workspace, offline),
        workspace_root=workspace,
        offline_root=offline,
    )
    by_slug = {o.slug: o for o in report.outcomes}
    assert by_slug["alpha"].status == "satisfied"
    assert by_slug["beta"].status == "retired"
    assert (offline / "beta" / ".git").is_dir()


def test_per_repo_independence_on_failure(tmp_path):
    head = _origin(tmp_path / "origin")
    workspace, offline = _workspace_roots(tmp_path)
    clone(tmp_path / "origin", offline / "alpha", profile=PROFILE, slug="alpha")
    clone(tmp_path / "origin", offline / "beta", profile=PROFILE, slug="beta")
    # Pre-occupy beta's target location so its place will fail.
    (workspace / "beta").mkdir()
    (workspace / "beta" / "stale").write_text("blocker")

    target = LayoutTarget(
        targets={
            "alpha": LayoutTargetPresentCommit(commit=head, location="alpha"),
            "beta": LayoutTargetPresentCommit(commit=head, location="beta"),
        }
    )
    report = run(
        target,
        inventory=scan(workspace, offline),
        workspace_root=workspace,
        offline_root=offline,
    )
    by_slug = {o.slug: o for o in report.outcomes}
    assert by_slug["alpha"].status == "placed"
    assert by_slug["beta"].status == "failed"
    # alpha was placed successfully despite beta failing.
    assert (workspace / "alpha" / ".git").is_dir()

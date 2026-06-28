from pathlib import Path

import pytest

from mono_control.config import Repo, RepoStore
from mono_control.engines.source import (
    SourceRequest,
    from_layout_target,
    run,
)
from mono_control.git import GitRepo
from mono_control.git.runner import run_git
from mono_control.host_platform import FsProfile
from mono_control.layout_target import (
    LayoutTarget,
    LayoutTargetAbsent,
    LayoutTargetPresentBranchHead,
    LayoutTargetPresentCommit,
)
from mono_control.on_disk import OnDiskInventory, scan

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


def _store_with(tmp_path: Path, *repos: Repo) -> RepoStore:
    store = RepoStore(tmp_path / "config" / "repos")
    for r in repos:
        store.create(r)
    return store


def test_clone_absent_with_source(tmp_path):
    origin = tmp_path / "origin"
    head = _origin(origin)
    store = _store_with(
        tmp_path,
        Repo(version=1, slug="alpha", name="Alpha", sources={"origin": str(origin)}),
    )

    offline = tmp_path / "offline"
    report = run(
        SourceRequest(refs_by_slug={"alpha": {"HEAD"}}),
        repo_store=store,
        inventory=OnDiskInventory(),
        offline_root=offline,
        profile=PROFILE,
    )

    assert report.ok
    assert report.outcomes[0].status == "cloned"
    cloned = GitRepo(offline / "alpha")
    assert cloned.slug() == "alpha"
    assert cloned.current_commit() == head


def test_init_absent_without_source(tmp_path):
    store = _store_with(tmp_path, Repo(version=1, slug="fresh", name="Fresh"))
    offline = tmp_path / "offline"

    report = run(
        SourceRequest(refs_by_slug={"fresh": set()}),
        repo_store=store,
        inventory=OnDiskInventory(),
        offline_root=offline,
        profile=PROFILE,
    )

    assert report.ok
    assert report.outcomes[0].status == "initialized"
    assert GitRepo(offline / "fresh").slug() == "fresh"


def test_source_missing_when_refs_requested(tmp_path):
    store = _store_with(tmp_path, Repo(version=1, slug="nope", name="Nope"))
    offline = tmp_path / "offline"

    report = run(
        SourceRequest(refs_by_slug={"nope": {"refs/heads/main"}}),
        repo_store=store,
        inventory=OnDiskInventory(),
        offline_root=offline,
        profile=PROFILE,
    )

    assert not report.ok
    outcome = report.outcomes[0]
    assert outcome.status == "source-missing"
    assert "refs/heads/main" in outcome.unresolved_refs
    assert not (offline / "nope").exists()


def test_fetch_present_brings_new_commit(tmp_path):
    origin = tmp_path / "origin"
    _origin(origin)
    store = _store_with(
        tmp_path,
        Repo(version=1, slug="beta", name="Beta", sources={"origin": str(origin)}),
    )

    offline = tmp_path / "offline"
    # First run: clone.
    run(
        SourceRequest(refs_by_slug={"beta": set()}),
        repo_store=store,
        inventory=OnDiskInventory(),
        offline_root=offline,
        profile=PROFILE,
    )
    # Upstream advances; second run with that ref should bring it in.
    new_commit = _commit_more(origin, "second.txt")
    inv = scan(tmp_path / "ws", offline)
    report = run(
        SourceRequest(refs_by_slug={"beta": {new_commit}}),
        repo_store=store,
        inventory=inv,
        offline_root=offline,
        profile=PROFILE,
    )

    assert report.ok
    assert report.outcomes[0].status == "fetched"
    assert GitRepo(offline / "beta").resolve_ref(new_commit) == new_commit


def test_per_repo_independence_one_failure_others_succeed(tmp_path):
    good_origin = tmp_path / "good"
    _origin(good_origin)
    bad_url = str(tmp_path / "does-not-exist")
    store = _store_with(
        tmp_path,
        Repo(version=1, slug="good", name="Good", sources={"origin": str(good_origin)}),
        Repo(version=1, slug="bad", name="Bad", sources={"origin": bad_url}),
    )

    offline = tmp_path / "offline"
    report = run(
        SourceRequest(refs_by_slug={"good": set(), "bad": set()}),
        repo_store=store,
        inventory=OnDiskInventory(),
        offline_root=offline,
        profile=PROFILE,
    )

    by_slug = {o.slug: o for o in report.outcomes}
    assert by_slug["good"].status == "cloned"
    assert by_slug["bad"].status == "create-failed"
    assert not report.ok


def test_definition_missing(tmp_path):
    store = _store_with(tmp_path)
    report = run(
        SourceRequest(refs_by_slug={"ghost": set()}),
        repo_store=store,
        inventory=OnDiskInventory(),
        offline_root=tmp_path / "offline",
        profile=PROFILE,
    )
    assert report.outcomes[0].status == "definition-missing"


def test_ref_missing_after_clone(tmp_path):
    origin = tmp_path / "origin"
    _origin(origin)
    store = _store_with(
        tmp_path,
        Repo(version=1, slug="alpha", name="Alpha", sources={"origin": str(origin)}),
    )
    report = run(
        SourceRequest(refs_by_slug={"alpha": {"refs/heads/does-not-exist"}}),
        repo_store=store,
        inventory=OnDiskInventory(),
        offline_root=tmp_path / "offline",
        profile=PROFILE,
    )
    outcome = report.outcomes[0]
    assert outcome.status == "ref-missing"
    assert "refs/heads/does-not-exist" in outcome.unresolved_refs


def test_from_layout_target_derives_refs():
    from mono_control.layout_target import LayoutTargetPresentAsIs

    target = LayoutTarget(
        targets={
            "alpha": LayoutTargetPresentCommit(commit="a" * 40, location="alpha"),
            "beta": LayoutTargetPresentBranchHead(branch="main", location="beta"),
            "gamma": LayoutTargetAbsent(),
            "delta": LayoutTargetPresentAsIs(location="apps/delta"),
        }
    )
    req = from_layout_target(target)
    assert req.refs_by_slug == {
        "alpha": {"a" * 40},
        "beta": {"refs/heads/main"},
        "delta": set(),  # present-as-is → empty ref set (acquire if absent, no verify)
    }

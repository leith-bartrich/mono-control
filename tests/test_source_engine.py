"""Source engine as a broker client: derive refs, drive acquire, build outcomes.

Effect-level cases (clone / init / fetch / verify) run against the real-effect
shim; the container-logic cases (per-repo independence, outcome/resolved
construction, the acquire calls made) run against canned fake responses.
"""

from pathlib import Path

from broker_shim import GitRepo, ShimBroker, run_git
from mono_control.broker import FakeBroker
from mono_control.config import Repo, RepoStore
from mono_control.engines.source import SourceRequest, from_layout_target, run
from mono_control.layout_target import (
    LayoutTarget,
    LayoutTargetAbsent,
    LayoutTargetPresentAsIs,
    LayoutTargetPresentBranchHead,
    LayoutTargetPresentCommit,
)


def _origin(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", str(path)])
    (path / "README.md").write_text("hello\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "initial"], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path)


def _env(tmp_path):
    broker = ShimBroker(tmp_path / "config", tmp_path / "ws", tmp_path / "off")
    return broker, RepoStore(broker)


# --------------------------------------------------------------------------- #
# Effect-level (shim)
# --------------------------------------------------------------------------- #
def test_clone_absent_with_source(tmp_path):
    origin = tmp_path / "origin"
    head = _origin(origin)
    broker, store = _env(tmp_path)
    store.create(Repo(version=1, slug="alpha", name="Alpha", sources={"origin": str(origin)}))

    report = run(SourceRequest(refs_by_slug={"alpha": {"HEAD"}}), broker=broker)
    assert report.ok
    assert report.outcomes[0].status == "cloned"
    cloned = GitRepo(tmp_path / "off" / "alpha")
    assert cloned.slug() == "alpha"
    assert cloned.current_commit() == head


def test_acquire_conforms_remotes_and_sets_a_fetch_refspec(tmp_path):
    """Acquisition leaves the repo's git remotes agreeing with its declared sources.

    `origin` aliases the default source — our writable canonical where there is one —
    so a developer working the checkout with plain git has a usable default. And
    `clone --bare` sets no fetch refspec, which is why a fetch previously updated
    nothing under `refs/`.
    """
    base, fork = tmp_path / "base", tmp_path / "fork"
    _origin(base)
    _origin(fork)
    broker, store = _env(tmp_path)
    store.create(
        Repo(
            version=1,
            slug="alpha",
            name="Alpha",
            sources={"upstream": str(base), "fork-ours": str(fork)},
        )
    )

    assert run(SourceRequest(refs_by_slug={"alpha": set()}), broker=broker).ok

    bare = tmp_path / "off" / "alpha"
    url = lambda n: run_git(["remote", "get-url", n], cwd=bare)  # noqa: E731
    assert url("upstream") == str(base)
    assert url("fork-ours") == str(fork)
    assert url("origin") == str(fork)  # the writable canonical, not the base
    assert (
        run_git(["config", "remote.origin.fetch"], cwd=bare)
        == "+refs/heads/*:refs/remotes/origin/*"
    )


def test_init_absent_without_source(tmp_path):
    broker, store = _env(tmp_path)
    store.create(Repo(version=1, slug="fresh", name="Fresh"))
    report = run(SourceRequest(refs_by_slug={"fresh": set()}), broker=broker)
    assert report.ok
    assert report.outcomes[0].status == "initialized"
    assert GitRepo(tmp_path / "off" / "fresh").slug() == "fresh"


def test_init_absent_honors_initial_branch(tmp_path):
    broker, store = _env(tmp_path)
    store.create(Repo(version=1, slug="fresh", name="Fresh"))
    report = run(
        SourceRequest(refs_by_slug={"fresh": set()}, initial_branch="develop"),
        broker=broker,
    )
    assert report.outcomes[0].status == "initialized"
    head = run_git(["symbolic-ref", "HEAD"], cwd=tmp_path / "off" / "fresh").strip()
    assert head == "refs/heads/develop"


def test_source_missing_when_refs_requested(tmp_path):
    broker, store = _env(tmp_path)
    store.create(Repo(version=1, slug="nope", name="Nope"))
    report = run(
        SourceRequest(refs_by_slug={"nope": {"refs/heads/main"}}), broker=broker
    )
    assert not report.ok
    outcome = report.outcomes[0]
    assert outcome.status == "source-missing"
    assert "refs/heads/main" in outcome.unresolved_refs
    assert not (tmp_path / "off" / "nope").exists()


def test_fetch_present_brings_new_commit(tmp_path):
    origin = tmp_path / "origin"
    _origin(origin)
    broker, store = _env(tmp_path)
    store.create(Repo(version=1, slug="beta", name="Beta", sources={"origin": str(origin)}))
    run(SourceRequest(refs_by_slug={"beta": set()}), broker=broker)  # clone

    (origin / "second.txt").write_text("second\n")
    run_git(["add", "."], cwd=origin)
    run_git(["commit", "-m", "second"], cwd=origin)
    new_commit = run_git(["rev-parse", "HEAD"], cwd=origin)

    report = run(SourceRequest(refs_by_slug={"beta": {new_commit}}), broker=broker)
    assert report.ok
    assert report.outcomes[0].status == "fetched"
    assert GitRepo(tmp_path / "off" / "beta").resolve_ref(new_commit) == new_commit


def test_definition_missing(tmp_path):
    broker, _ = _env(tmp_path)
    report = run(SourceRequest(refs_by_slug={"ghost": set()}), broker=broker)
    assert report.outcomes[0].status == "definition-missing"


def test_ref_missing_after_clone(tmp_path):
    origin = tmp_path / "origin"
    _origin(origin)
    broker, store = _env(tmp_path)
    store.create(Repo(version=1, slug="alpha", name="Alpha", sources={"origin": str(origin)}))
    report = run(
        SourceRequest(refs_by_slug={"alpha": {"refs/heads/does-not-exist"}}),
        broker=broker,
    )
    outcome = report.outcomes[0]
    assert outcome.status == "ref-missing"
    assert "refs/heads/does-not-exist" in outcome.unresolved_refs


# --------------------------------------------------------------------------- #
# Container logic (canned fake)
# --------------------------------------------------------------------------- #
def test_per_repo_independence_and_acquire_calls():
    """One slug's failure does not abort the rest; each yields one acquire call."""
    fake = FakeBroker(
        results={
            "acquire": {
                "status": "create-failed",
                "summary": "boom",
                "unresolved_refs": [],
                "resolved": {},
            }
        }
    )
    report = run(
        SourceRequest(refs_by_slug={"good": set(), "bad": set()}), broker=fake
    )
    assert not report.ok
    assert {o.status for o in report.outcomes} == {"create-failed"}
    # one acquire call per requested slug
    assert [m for m, _ in fake.calls] == ["acquire", "acquire"]
    assert {p["slug"] for _, p in fake.calls} == {"good", "bad"}


def test_resolved_map_is_carried_onto_outcome():
    fake = FakeBroker(
        results={
            "acquire": {
                "status": "fetched",
                "summary": "ok",
                "unresolved_refs": [],
                "resolved": {"refs/heads/main": "c0ffee"},
            }
        }
    )
    report = run(SourceRequest(refs_by_slug={"beta": {"refs/heads/main"}}), broker=fake)
    assert report.outcomes[0].resolved == {"refs/heads/main": "c0ffee"}


def test_from_layout_target_derives_refs():
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
        "delta": set(),
    }

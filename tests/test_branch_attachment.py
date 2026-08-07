"""Attaching a materialized worktree to a declared line.

Two reports drove this (mono-control#36, #37). Together they showed there was no
path through the tool to get a materialized worktree onto a branch: every
checkout went through a hex-commit verb (which always detaches), and `branchat`
then reported `satisfied` because the reconciler compared *commit identity* to a
detached HEAD sitting on the branch's tip.

The split is by purpose. A **commit** target pins a revision and detaches, which
is correct — the revision came from the ledger, not a branch. A **branch-head**
target follows a declared line and attaches. The tests below pin both, the
convergence property that makes the reconciler honest, and the host-side rule
that keeps arbitrary refs away from git.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from broker_shim import GitRepo, run_git
from mono_control.broker import BrokerError
from mono_control.cli import app
from mono_control.config import Repo, RepoStore
from mono_control.on_disk import scan

runner = CliRunner()


def _run(env, *args: str):
    return runner.invoke(app, ["--config-dir", str(env.config_dir), *args], obj=env.app)


def _origin(path: Path, branch: str = "main") -> str:
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--initial-branch", branch, str(path)])
    (path / "README.md").write_text("hello\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "initial"], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path)


def _register(env, tmp_path, *, branches=None, slug="proj", branch="main") -> str:
    origin = tmp_path / f"origin-{slug}"
    head = _origin(origin, branch)
    RepoStore(env.broker).create(
        Repo(version=1, slug=slug, name=slug, sources={"origin": str(origin)},
             branches=branches or {})
    )
    return head


def _place_pinned(env, tmp_path, **kw) -> Path:
    """Place at a pinned commit — the detached starting state a dep gets."""
    head = _register(env, tmp_path, **kw)
    slug = kw.get("slug", "proj")
    result = _run(env, "repo", "mat", "layout-target", slug,
                  "--location", "apps/web", "--commit", head)
    assert result.exit_code == 0, result.output
    return env.ws / "apps/web"


def _place_on_line(env, tmp_path, line="main", **kw) -> Path:
    """Place following a declared line."""
    _register(env, tmp_path, **kw)
    slug = kw.get("slug", "proj")
    result = _run(env, "repo", "mat", "layout-target", slug,
                  "--location", "apps/web", "--branch", line)
    assert result.exit_code == 0, result.output
    return env.ws / "apps/web"


class TestPurposeDecidesAttachment:
    def test_a_commit_target_detaches(self, broker_env, tmp_path):
        """Correct, and unchanged: the revision came from a pin, not a branch."""
        wt = _place_pinned(broker_env, tmp_path)
        assert GitRepo(wt).attached_branch() is None

    def test_a_branch_target_attaches_on_placement(self, broker_env, tmp_path):
        """Previously impossible — placement could only ever check out a hex commit."""
        wt = _place_on_line(broker_env, tmp_path)
        assert GitRepo(wt).attached_branch() == "main"


class TestAttachmentIsObserved:
    def _observed(self, env):
        return scan(env.broker, env.ws, env.off).repos["proj"]

    def test_the_scan_reports_the_attached_branch(self, broker_env, tmp_path):
        _place_on_line(broker_env, tmp_path)
        assert self._observed(broker_env).branch == "main"

    def test_the_scan_reports_none_when_detached(self, broker_env, tmp_path):
        """Without this the container cannot tell attached from detached-at-the-tip."""
        _place_pinned(broker_env, tmp_path)
        assert self._observed(broker_env).branch is None


class TestBranchatAttachesAndConverges:
    def test_branchat_attaches_a_detached_worktree(self, broker_env, tmp_path):
        """The reported bug: this said `satisfied` and left HEAD detached."""
        wt = _place_pinned(broker_env, tmp_path)
        assert GitRepo(wt).attached_branch() is None

        result = _run(broker_env, "repo", "mat", "branchat", "proj", "main")

        assert result.exit_code == 0, result.output
        assert GitRepo(wt).attached_branch() == "main"

    def test_a_detached_head_at_the_tip_is_not_satisfied(self, broker_env, tmp_path):
        """Commit identity said yes, attachment says no — that was the whole bug.

        The pinned commit *is* the branch tip here, so the old predicate saw no
        difference at all.
        """
        wt = _place_pinned(broker_env, tmp_path)
        repo = GitRepo(wt)
        before = repo.current_commit()

        _run(broker_env, "repo", "mat", "branchat", "proj", "main")

        assert repo.current_commit() == before, "same commit; only attachment changed"
        assert repo.attached_branch() == "main"

    def test_it_converges(self, broker_env, tmp_path):
        """Attach, then report satisfied. A reconciler that never settles would be
        worse than one that lies, which is why the predicate could not be fixed
        alone."""
        wt = _place_pinned(broker_env, tmp_path)
        first = _run(broker_env, "repo", "mat", "branchat", "proj", "main")
        assert first.exit_code == 0, first.output

        second = _run(broker_env, "repo", "mat", "branchat", "proj", "main")

        assert second.exit_code == 0, second.output
        assert "satisfied" in second.output
        assert GitRepo(wt).attached_branch() == "main"


class TestDeclaredLineVocabulary:
    def test_a_line_name_resolves_to_its_branch(self, broker_env, tmp_path):
        """`--branch dev` on a repo declaring {"dev": "main"} — issue #36."""
        wt = _place_pinned(broker_env, tmp_path, branches={"dev": "main"})

        result = _run(broker_env, "repo", "mat", "branchat", "proj", "dev")

        assert result.exit_code == 0, result.output
        assert GitRepo(wt).attached_branch() == "main"

    def test_the_concrete_branch_still_works(self, broker_env, tmp_path):
        """The form that already worked must keep working."""
        wt = _place_pinned(broker_env, tmp_path, branches={"dev": "main"})

        result = _run(broker_env, "repo", "mat", "branchat", "proj", "main")

        assert result.exit_code == 0, result.output
        assert GitRepo(wt).attached_branch() == "main"

    def test_an_undeclared_line_is_named_not_blamed_on_fetch(self, broker_env, tmp_path):
        """The reported failure blamed fetch state and sent a reader after credentials."""
        _place_pinned(broker_env, tmp_path, branches={"dev": "main"})

        result = _run(broker_env, "repo", "mat", "branchat", "proj", "nope")

        assert result.exit_code == 1
        assert "not a branch line declared" in result.output
        assert "dev=main" in result.output, "say what IS declared"
        assert "fetch" not in result.output.lower(), "must not blame fetch state"

    def test_a_repo_declaring_nothing_still_attaches(self, broker_env, tmp_path):
        """Most repos declare no branches; refusing them would be a worse hole."""
        wt = _place_pinned(broker_env, tmp_path)

        result = _run(broker_env, "repo", "mat", "branchat", "proj", "main")

        assert result.exit_code == 0, result.output
        assert GitRepo(wt).attached_branch() == "main"


class TestOnlyExpressedLinesReachGit:
    def test_an_unexpressed_branch_is_refused_even_though_it_exists(
        self, broker_env, tmp_path
    ):
        """The host's own check, independent of the CLI's. A branch that exists
        locally is still not a line the repo expresses."""
        wt = _place_pinned(broker_env, tmp_path, branches={"dev": "main"})
        run_git(["branch", "sneaky"], cwd=wt)

        with pytest.raises(BrokerError):
            broker_env.broker.call("checkout_branch", {"slug": "proj", "branch": "sneaky"})

        assert GitRepo(wt).attached_branch() != "sneaky"

    def test_a_declared_line_that_does_not_exist_is_not_created(
        self, broker_env, tmp_path
    ):
        """mono-control does not create branches; commits do."""
        wt = _place_pinned(
            broker_env, tmp_path, branches={"dev": "main", "future": "not-yet"}
        )
        before = GitRepo(wt).attached_branch()

        out = broker_env.broker.call("checkout_branch", {"slug": "proj", "branch": "future"})

        assert out["status"] == "failed"
        assert "does not create branches" in out["summary"]
        assert GitRepo(wt).attached_branch() == before, "left as it was"


class TestUpstreamTracking:
    """Attaching without tracking leaves `git pull` with "no tracking information",
    which is most of what a developer wanted the branch for. #30 stage 3."""

    def _tracking(self, wt: Path, branch: str = "main") -> tuple[str | None, str | None]:
        repo = GitRepo(wt)
        def cfg(key):
            try:
                return repo.config_get(key)
            except Exception:  # noqa: BLE001
                return None
        return cfg(f"branch.{branch}.remote"), cfg(f"branch.{branch}.merge")

    def test_attaching_sets_upstream(self, broker_env, tmp_path):
        wt = _place_pinned(broker_env, tmp_path)

        _run(broker_env, "repo", "mat", "branchat", "proj", "main")

        assert self._tracking(wt) == ("origin", "refs/heads/main")

    def test_placing_on_a_line_sets_upstream_too(self, broker_env, tmp_path):
        wt = _place_on_line(broker_env, tmp_path)
        assert self._tracking(wt) == ("origin", "refs/heads/main")

    def test_a_pinned_placement_gets_no_upstream(self, broker_env, tmp_path):
        """A detached pin is not on a line, so there is nothing to track."""
        wt = _place_pinned(broker_env, tmp_path)
        assert GitRepo(wt).attached_branch() is None

    def test_conformance_restores_tracking_after_a_repoint(self, broker_env, tmp_path):
        """`git remote remove` — how a repoint is done — also wipes branch tracking.

        Without conformance re-asserting it, tracking stays silently gone until
        someone notices `git pull` complaining.
        """
        wt = _place_on_line(broker_env, tmp_path)
        assert self._tracking(wt) == ("origin", "refs/heads/main")

        # Simulate what a repoint does to the bare.
        bare = broker_env.off / "proj"
        run_git(["-C", str(bare), "remote", "remove", "origin"])
        assert self._tracking(wt) == (None, None), "precondition: tracking wiped"

        # Any operation conforms; acquire runs on every one.
        _run(broker_env, "repo", "mat", "branchat", "proj", "main")

        assert self._tracking(wt) == ("origin", "refs/heads/main")

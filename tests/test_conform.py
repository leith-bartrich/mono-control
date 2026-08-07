"""Tests for `product-cluster conform clear / swap / relayout` (via the shim broker)."""

import json
from pathlib import Path

from typer.testing import CliRunner

from broker_shim import GitRepo, add_worktree, clone, run_git, PROFILE
from mono_control.aspects.product_cluster.cli import app as cluster_app
from mono_control.config import Repo, RepoStore

runner = CliRunner()


def _invoke(env, args):
    return runner.invoke(cluster_app, args, obj=env.app)


def _origin(path: Path, branch: str = "main") -> str:
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--initial-branch", branch, str(path)])
    (path / "README.md").write_text("hello\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "initial"], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path)


def _cluster_origin(
    path: Path, members: dict, branch: str = "main", requires: list[str] | None = None
) -> str:
    """A cluster origin carrying a committed product-cluster/default-layout.json.

    Writes a **v1** document unless ``requires`` is given, so the common case keeps
    exercising the v1 → v2 migration on the way in.
    """
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--initial-branch", branch, str(path)])
    layout_dir = path / "product-cluster"
    layout_dir.mkdir()
    doc = (
        {"version": 2, "members": members, "requires": requires}
        if requires is not None
        else {"version": 1, "members": members}
    )
    (layout_dir / "default-layout.json").write_text(json.dumps(doc, indent=2) + "\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "layout"], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path)


def _seed(env, slug: str, origin: Path, *, aspects=None, branches=None) -> None:
    RepoStore(env.broker).create(
        Repo(
            version=1,
            slug=slug,
            name=slug,
            sources={"origin": str(origin)},
            aspects=aspects or set(),
            branches=branches or {},
        )
    )


def test_conform_swap_materializes_cluster_and_members(broker_env, tmp_path):
    env = broker_env
    _origin(tmp_path / "m1o")
    _origin(tmp_path / "m2o")
    _cluster_origin(
        tmp_path / "clo",
        {
            "m1": {"location": "src/m1", "role": "dev"},
            "m2": {"location": "libs/m2", "role": "dep"},
        },
    )
    _seed(env, "m1", tmp_path / "m1o")
    _seed(env, "m2", tmp_path / "m2o")
    _seed(env, "cluster1", tmp_path / "clo", aspects={"product-cluster"})

    res = _invoke(env, ["conform", "swap", "cluster1"])
    assert res.exit_code == 0, res.output
    assert (env.ws / "products" / "cluster1" / ".git").exists()
    assert GitRepo(env.ws / "src" / "m1").slug() == "m1"
    assert GitRepo(env.ws / "libs" / "m2").slug() == "m2"


def test_conform_swap_pre_clears_extras(broker_env, tmp_path):
    env = broker_env
    _origin(tmp_path / "extrao")
    # A materialized "extra": a bare repo plus a worktree under the work root.
    clone(tmp_path / "extrao", env.off / "extra", profile=PROFILE, slug="extra")
    add_worktree(env.off / "extra", env.ws / "extra")
    _seed(env, "extra", tmp_path / "extrao")

    _cluster_origin(tmp_path / "clo", {})  # empty layout: just the cluster
    _seed(env, "cluster1", tmp_path / "clo", aspects={"product-cluster"})

    res = _invoke(env, ["conform", "swap", "cluster1"])
    assert res.exit_code == 0, res.output
    assert (env.ws / "products" / "cluster1" / ".git").exists()
    assert not (env.ws / "extra").exists()  # worktree removed
    assert GitRepo(env.off / "extra").is_bare_repository()  # bare survives


def test_conform_clear_retires_all(broker_env, tmp_path):
    env = broker_env
    _origin(tmp_path / "ao")
    clone(tmp_path / "ao", env.off / "alpha", profile=PROFILE, slug="alpha")
    add_worktree(env.off / "alpha", env.ws / "alpha")
    _seed(env, "alpha", tmp_path / "ao")

    res = _invoke(env, ["conform", "clear"])
    assert res.exit_code == 0, res.output
    assert not (env.ws / "alpha").exists()  # worktree removed
    assert GitRepo(env.off / "alpha").is_bare_repository()  # bare survives


def test_conform_clear_blocks_dirty_member(broker_env, tmp_path):
    """A dirty member's worktree isn't silently discarded: the broker's dirty-gated
    retire refuses it, so clear reports failure and leaves the worktree in place."""
    env = broker_env
    _origin(tmp_path / "ao")
    clone(tmp_path / "ao", env.off / "alpha", profile=PROFILE, slug="alpha")
    add_worktree(env.off / "alpha", env.ws / "alpha")
    _seed(env, "alpha", tmp_path / "ao")
    (env.ws / "alpha" / "README.md").write_text("uncommitted change\n")  # dirty

    res = _invoke(env, ["conform", "clear"])
    assert res.exit_code != 0
    assert (env.ws / "alpha" / ".git").exists()  # worktree kept
    assert (env.ws / "alpha" / "README.md").read_text() == "uncommitted change\n"


def test_conform_swap_requires_aspect(broker_env, tmp_path):
    env = broker_env
    RepoStore(env.broker).create(Repo(version=1, slug="plain", name="plain"))
    res = _invoke(env, ["conform", "swap", "plain"])
    assert res.exit_code != 0
    assert "does not declare" in res.output


def test_conform_clear_blocks_dirty_cluster(broker_env, tmp_path):
    """A dirty product-cluster blocks clear (its committed state anchors reproducibility)."""
    env = broker_env
    _origin(tmp_path / "pco")
    _seed(env, "pc1", tmp_path / "pco", aspects={"product-cluster"})
    assert _invoke(env, ["mat", "moveto", "pc1"]).exit_code == 0
    (env.ws / "products" / "pc1" / "README.md").write_text("uncommitted\n")

    res = _invoke(env, ["conform", "clear"])
    assert res.exit_code != 0
    assert "pc1" in res.output
    assert (env.ws / "products" / "pc1" / ".git").exists()  # untouched


def test_conform_swap_blocks_dirty_cluster(broker_env, tmp_path):
    env = broker_env
    _origin(tmp_path / "ao")
    _seed(env, "pca", tmp_path / "ao", aspects={"product-cluster"})
    assert _invoke(env, ["mat", "moveto", "pca"]).exit_code == 0
    (env.ws / "products" / "pca" / "README.md").write_text("dirty\n")

    _cluster_origin(tmp_path / "bo", {})
    _seed(env, "pcb", tmp_path / "bo", aspects={"product-cluster"})

    res = _invoke(env, ["conform", "swap", "pcb"])
    assert res.exit_code != 0
    assert "pca" in res.output
    assert (env.ws / "products" / "pca" / ".git").exists()  # not torn down


def test_conform_swap_unreachable_cluster_leaves_workspace(broker_env, tmp_path):
    """Sourcing the cluster first means an unreachable one fails before any clear."""
    env = broker_env
    _origin(tmp_path / "ao")
    clone(tmp_path / "ao", env.off / "alpha", profile=PROFILE, slug="alpha")
    add_worktree(env.off / "alpha", env.ws / "alpha")
    _seed(env, "alpha", tmp_path / "ao")
    _seed(env, "pcbad", tmp_path / "missing", aspects={"product-cluster"})

    res = _invoke(env, ["conform", "swap", "pcbad"])
    assert res.exit_code != 0
    assert (env.ws / "alpha" / ".git").exists()  # workspace NOT cleared


def test_relayout_applies_layout_delta(broker_env, tmp_path):
    """relayout pulls in missing members, retires extras, leaves the cluster in place."""
    env = broker_env
    _origin(tmp_path / "m1o")
    _origin(tmp_path / "m2o")
    _cluster_origin(
        tmp_path / "clo",
        {
            "m1": {"location": "src/m1", "role": "dev"},
            "m2": {"location": "libs/m2", "role": "dep"},
        },
    )
    _seed(env, "m1", tmp_path / "m1o")
    _seed(env, "m2", tmp_path / "m2o")
    _seed(env, "cluster1", tmp_path / "clo", aspects={"product-cluster"})
    assert _invoke(env, ["mat", "moveto", "cluster1"]).exit_code == 0
    _origin(tmp_path / "extrao")
    clone(tmp_path / "extrao", env.off / "extra", profile=PROFILE, slug="extra")
    add_worktree(env.off / "extra", env.ws / "extra")
    _seed(env, "extra", tmp_path / "extrao")

    res = _invoke(env, ["conform", "relayout", "cluster1"])
    assert res.exit_code == 0, res.output
    assert (env.ws / "products" / "cluster1" / ".git").exists()
    assert GitRepo(env.ws / "src" / "m1").slug() == "m1"
    assert GitRepo(env.ws / "libs" / "m2").slug() == "m2"
    assert not (env.ws / "extra").exists()  # worktree removed
    assert GitRepo(env.off / "extra").is_bare_repository()  # bare survives


def test_relayout_allows_dirty_target_cluster(broker_env, tmp_path):
    """relayout keeps the target cluster, so its dirtiness must NOT gate (unlike clear/swap)."""
    env = broker_env
    _origin(tmp_path / "m1o")
    _cluster_origin(tmp_path / "clo", {"m1": {"location": "src/m1", "role": "dev"}})
    _seed(env, "m1", tmp_path / "m1o")
    _seed(env, "cluster1", tmp_path / "clo", aspects={"product-cluster"})
    assert _invoke(env, ["mat", "moveto", "cluster1"]).exit_code == 0
    (env.ws / "products" / "cluster1" / "README.md").write_text("uncommitted\n")

    res = _invoke(env, ["conform", "relayout", "cluster1"])
    assert res.exit_code == 0, res.output
    assert (env.ws / "products" / "cluster1" / ".git").exists()
    assert GitRepo(env.ws / "src" / "m1").slug() == "m1"


def test_relayout_implied_cluster(broker_env, tmp_path):
    env = broker_env
    _origin(tmp_path / "m1o")
    _cluster_origin(tmp_path / "clo", {"m1": {"location": "m1", "role": "dev"}})
    _seed(env, "m1", tmp_path / "m1o")
    _seed(env, "cluster1", tmp_path / "clo", aspects={"product-cluster"})
    assert _invoke(env, ["mat", "moveto", "cluster1"]).exit_code == 0

    res = _invoke(env, ["conform", "relayout"])  # no arg → sole cluster
    assert res.exit_code == 0, res.output
    assert GitRepo(env.ws / "m1").slug() == "m1"


def test_conform_clear_allow_dirty_still_guards_uncommitted_work(broker_env, tmp_path):
    """``--allow-dirty`` bypasses the container's reproducibility gate, but the
    broker's dirty-gated retire independently refuses to discard uncommitted work —
    so a dirty cluster is kept. Committing makes the worktree clean; clear then
    succeeds and the committed state is safe in the surviving bare repo.
    """
    env = broker_env
    _origin(tmp_path / "pco")
    _seed(env, "pc1", tmp_path / "pco", aspects={"product-cluster"})
    assert _invoke(env, ["mat", "moveto", "pc1"]).exit_code == 0
    placed = env.ws / "products" / "pc1"
    (placed / "README.md").write_text("dirty\n")

    assert _invoke(env, ["conform", "clear"]).exit_code != 0  # gated by container
    # --allow-dirty gets past the gate, but the worktree removal is refused.
    res = _invoke(env, ["conform", "clear", "--allow-dirty"])
    assert res.exit_code != 0
    assert (placed / ".git").exists()  # kept; uncommitted work intact

    # Committing is NOT enough. Placement is detached, so the commit lands on no branch
    # and removing the worktree would orphan it — the second guard refuses. (This case
    # previously asserted the retire *succeeded*, i.e. it encoded the data loss.)
    run_git(["add", "."], cwd=placed)
    run_git(["commit", "-m", "wip"], cwd=placed)
    wip = run_git(["rev-parse", "HEAD"], cwd=placed)
    res2 = _invoke(env, ["conform", "clear"])
    assert res2.exit_code != 0
    assert "unreachable" in res2.output
    assert (placed / ".git").exists()  # still kept

    # Anchoring the work releases it, and the commit survives in the bare repo.
    run_git(["tag", "wip-kept"], cwd=placed)
    res3 = _invoke(env, ["conform", "clear"])
    assert res3.exit_code == 0, res3.output
    assert not placed.exists()
    assert GitRepo(env.off / "pc1").is_bare_repository()
    assert run_git(["rev-parse", "wip-kept^{commit}"], cwd=env.off / "pc1") == wip


# --------------------------------------------------------------------------- #
# Composition — co-activation via `requires`
# --------------------------------------------------------------------------- #
def _members(spec: dict[str, tuple[str, str]]) -> dict:
    return {slug: {"location": loc, "role": role} for slug, (loc, role) in spec.items()}


def _two_cluster_env(env, tmp_path, *, lib_members, app_members, requires=("lib",)):
    """Seed an `app` cluster that requires a `lib` cluster, plus their members."""
    for slug in {*lib_members, *app_members}:
        _origin(tmp_path / f"{slug}o")
        _seed(env, slug, tmp_path / f"{slug}o")
    _cluster_origin(tmp_path / "libo", _members(lib_members), requires=[])
    _cluster_origin(tmp_path / "appo", _members(app_members), requires=list(requires))
    _seed(env, "lib", tmp_path / "libo", aspects={"product-cluster"})
    _seed(env, "app", tmp_path / "appo", aspects={"product-cluster"})


def test_relayout_refuses_to_place_an_unplaced_required_cluster(broker_env, tmp_path):
    """Acquiring is free and automatic; *placing* needs stated intent."""
    env = broker_env
    _two_cluster_env(
        env,
        tmp_path,
        lib_members={"shared": ("libs/shared", "dev")},
        app_members={"a1": ("src/a1", "dev")},
    )
    res = _invoke(env, ["conform", "swap", "app"])
    assert res.exit_code != 0
    assert "lib" in res.output
    # Acquired anyway — the bare repo is there, just not placed.
    assert GitRepo(env.off / "lib").is_bare_repository()
    assert not (env.ws / "products" / "lib").exists()


def test_relayout_activates_required_cluster_when_asked(broker_env, tmp_path):
    env = broker_env
    _two_cluster_env(
        env,
        tmp_path,
        lib_members={"shared": ("libs/shared", "dev")},
        app_members={"a1": ("src/a1", "dev")},
    )
    res = _invoke(env, ["conform", "swap", "app", "--activate-required"])
    assert res.exit_code == 0, res.output
    # Both clusters placed, and the union of their members laid out.
    assert (env.ws / "products" / "app" / ".git").exists()
    assert (env.ws / "products" / "lib" / ".git").exists()
    assert GitRepo(env.ws / "src" / "a1").slug() == "a1"
    assert GitRepo(env.ws / "libs" / "shared").slug() == "shared"


def test_shared_member_in_agreement_is_placed_once(broker_env, tmp_path):
    """The library case: both clusters name the same member, one worktree results."""
    env = broker_env
    _two_cluster_env(
        env,
        tmp_path,
        lib_members={"shared": ("libs/shared", "dev")},
        app_members={"shared": ("libs/shared", "dep")},
    )
    res = _invoke(env, ["conform", "swap", "app", "--activate-required"])
    assert res.exit_code == 0, res.output
    assert GitRepo(env.ws / "libs" / "shared").slug() == "shared"
    # dev ⊔ dep = dev, and the override is surfaced rather than silent.
    assert "dev override" in res.output


def test_location_conflict_between_co_active_clusters_refuses(broker_env, tmp_path):
    env = broker_env
    _two_cluster_env(
        env,
        tmp_path,
        lib_members={"shared": ("libs/shared", "dep")},
        app_members={"shared": ("vendor/shared", "dep")},
    )
    res = _invoke(env, ["conform", "swap", "app", "--activate-required"])
    assert res.exit_code != 0
    assert "conflicting location" in res.output
    # Nothing was laid out on an unsatisfiable merge.
    assert not (env.ws / "libs" / "shared").exists()
    assert not (env.ws / "vendor" / "shared").exists()


def test_requires_an_undeclared_cluster_refuses(broker_env, tmp_path):
    env = broker_env
    _origin(tmp_path / "a1o")
    _seed(env, "a1", tmp_path / "a1o")
    _cluster_origin(tmp_path / "appo", {"a1": {"location": "src/a1", "role": "dev"}},
                    requires=["nope"])
    _seed(env, "app", tmp_path / "appo", aspects={"product-cluster"})
    res = _invoke(env, ["conform", "swap", "app", "--activate-required"])
    assert res.exit_code != 0
    assert "nope" in res.output


def test_dropping_one_claimant_keeps_a_still_claimed_member(broker_env, tmp_path):
    """A shared member survives when one of its two claimants leaves the active set.

    `pre_clear` retires whatever the target doesn't name, and the target names the
    *union* of every active cluster's members — so "still claimed by something active"
    is already the deciding question. Only members nobody active claims are retired.
    """
    env = broker_env
    _two_cluster_env(
        env,
        tmp_path,
        lib_members={"shared": ("libs/shared", "dep"), "l1": ("libs/l1", "dev")},
        app_members={"shared": ("libs/shared", "dev"), "a1": ("src/a1", "dev")},
    )
    assert _invoke(env, ["conform", "swap", "app", "--activate-required"]).exit_code == 0

    # Drop `app` from the active set by conforming to `lib` alone (it requires nothing).
    res = _invoke(env, ["conform", "relayout", "lib"])
    assert res.exit_code == 0, res.output

    # `shared` is still claimed by lib — kept, in the same place.
    assert GitRepo(env.ws / "libs" / "shared").slug() == "shared"
    assert GitRepo(env.ws / "libs" / "l1").slug() == "l1"
    # `a1` was only ever app's, and app itself is gone — both retired, bares survive.
    assert not (env.ws / "src" / "a1").exists()
    assert not (env.ws / "products" / "app").exists()
    assert GitRepo(env.off / "a1").is_bare_repository()


def test_conform_clear_blocks_orphaning_a_detached_commit(broker_env, tmp_path):
    """Committed work on a detached worktree is refused, not silently orphaned.

    Placement checks out a detached HEAD, so a commit made in a placed worktree sits on
    no branch. The tree is then *clean*, so the dirty gate waves the retire through and
    `git worktree remove` leaves the commit unreachable. Committing is exactly what makes
    you vulnerable, which is why this needs its own guard.
    """
    env = broker_env
    _origin(tmp_path / "ao")
    clone(tmp_path / "ao", env.off / "alpha", profile=PROFILE, slug="alpha")
    add_worktree(env.off / "alpha", env.ws / "alpha")
    _seed(env, "alpha", tmp_path / "ao")

    wt = env.ws / "alpha"
    assert run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=wt) == "HEAD"  # detached
    (wt / "work.txt").write_text("committed but on no branch\n")
    run_git(["add", "."], cwd=wt)
    run_git(["commit", "-m", "orphan-to-be"], cwd=wt)
    orphan = run_git(["rev-parse", "HEAD"], cwd=wt)
    assert not run_git(["status", "--porcelain"], cwd=wt)  # clean: dirty gate sees nothing

    res = _invoke(env, ["conform", "clear"])
    assert res.exit_code != 0
    assert "unreachable" in res.output
    assert (wt / ".git").exists()  # worktree kept, commit still reachable from its HEAD
    assert run_git(["rev-parse", "HEAD"], cwd=wt) == orphan


def test_conform_clear_allows_retire_once_the_commit_is_anchored(broker_env, tmp_path):
    """Anchoring the work — here with a tag — clears the block."""
    env = broker_env
    _origin(tmp_path / "ao")
    clone(tmp_path / "ao", env.off / "alpha", profile=PROFILE, slug="alpha")
    add_worktree(env.off / "alpha", env.ws / "alpha")
    _seed(env, "alpha", tmp_path / "ao")

    wt = env.ws / "alpha"
    (wt / "work.txt").write_text("saved\n")
    run_git(["add", "."], cwd=wt)
    run_git(["commit", "-m", "keep me"], cwd=wt)
    orphan = run_git(["rev-parse", "HEAD"], cwd=wt)
    run_git(["tag", "keepme"], cwd=wt)

    res = _invoke(env, ["conform", "clear"])
    assert res.exit_code == 0, res.output
    assert not wt.exists()  # retired
    # The commit survives in the bare repo, anchored by the tag.
    assert run_git(["rev-parse", "keepme^{commit}"], cwd=env.off / "alpha") == orphan


def test_conform_clear_retires_a_clean_detached_worktree(broker_env, tmp_path):
    """The guard is about *unanchored* commits, not about being detached."""
    env = broker_env
    _origin(tmp_path / "ao")
    clone(tmp_path / "ao", env.off / "alpha", profile=PROFILE, slug="alpha")
    add_worktree(env.off / "alpha", env.ws / "alpha")  # detached at the branch tip
    _seed(env, "alpha", tmp_path / "ao")

    res = _invoke(env, ["conform", "clear"])
    assert res.exit_code == 0, res.output
    assert not (env.ws / "alpha").exists()


# --------------------------------------------------------------------------- #
# #30 stage 3: relayout expresses a ref intent on fresh placement
# --------------------------------------------------------------------------- #
def test_relayout_attaches_dev_members_and_the_cluster(broker_env, tmp_path):
    """A dev member's latest IS a living branch head, and `branches.dev` names it.

    Before this, every relayout-placed worktree was detached, so committing from
    one meant leaving the tool — including committing the cluster's own layout
    document, which mono-control itself authors.
    """
    env = broker_env
    _origin(tmp_path / "m1o")
    _origin(tmp_path / "m2o")
    _cluster_origin(
        tmp_path / "clo",
        _members({"m1": ("src/m1", "dev"), "m2": ("libs/m2", "dep")}),
    )
    _seed(env, "m1", tmp_path / "m1o", branches={"dev": "main"})
    _seed(env, "m2", tmp_path / "m2o", branches={"dev": "main"})
    _seed(env, "cluster1", tmp_path / "clo", aspects={"product-cluster"},
          branches={"dev": "main"})

    res = _invoke(env, ["conform", "relayout", "cluster1"])

    assert res.exit_code == 0, res.output
    assert GitRepo(env.ws / "src" / "m1").attached_branch() == "main", "dev member"
    assert GitRepo(env.ws / "products" / "cluster1").attached_branch() == "main", "cluster"


def test_relayout_leaves_deps_detached(broker_env, tmp_path):
    """A dep's revision comes from the snapshot ledger — inputs relayout does not
    read and, by contract, should not. Detached is the honest form of "no policy
    applied yet"."""
    env = broker_env
    _origin(tmp_path / "m1o")
    _origin(tmp_path / "m2o")
    _cluster_origin(
        tmp_path / "clo",
        _members({"m1": ("src/m1", "dev"), "m2": ("libs/m2", "dep")}),
    )
    _seed(env, "m1", tmp_path / "m1o", branches={"dev": "main"})
    _seed(env, "m2", tmp_path / "m2o", branches={"dev": "main"})
    _seed(env, "cluster1", tmp_path / "clo", aspects={"product-cluster"},
          branches={"dev": "main"})

    assert _invoke(env, ["conform", "relayout", "cluster1"]).exit_code == 0

    assert GitRepo(env.ws / "libs" / "m2").attached_branch() is None


def test_relayout_leaves_an_existing_worktrees_ref_alone(broker_env, tmp_path):
    """Relayout means membership and location. A developer sitting on a feature
    branch must not be yanked back because someone re-ran a layout — which also
    means no migration pass for worktrees placed before this change."""
    env = broker_env
    _origin(tmp_path / "m1o")
    _cluster_origin(tmp_path / "clo", _members({"m1": ("src/m1", "dev")}))
    _seed(env, "m1", tmp_path / "m1o", branches={"dev": "main"})
    _seed(env, "cluster1", tmp_path / "clo", aspects={"product-cluster"},
          branches={"dev": "main"})
    assert _invoke(env, ["conform", "relayout", "cluster1"]).exit_code == 0

    wt = env.ws / "src" / "m1"
    run_git(["-C", str(wt), "checkout", "-b", "feature/mine"])

    assert _invoke(env, ["conform", "relayout", "cluster1"]).exit_code == 0

    assert GitRepo(wt).attached_branch() == "feature/mine", "left where the developer put it"


def test_relayout_gives_no_opinion_without_a_declared_dev_line(broker_env, tmp_path):
    """`branches.dev` is what names the line. Falling back to the remote's default
    would be guessing at policy rather than reading it."""
    env = broker_env
    _origin(tmp_path / "m1o")
    _cluster_origin(tmp_path / "clo", _members({"m1": ("src/m1", "dev")}))
    _seed(env, "m1", tmp_path / "m1o")  # declares nothing
    _seed(env, "cluster1", tmp_path / "clo", aspects={"product-cluster"})

    assert _invoke(env, ["conform", "relayout", "cluster1"]).exit_code == 0

    assert GitRepo(env.ws / "src" / "m1").attached_branch() is None

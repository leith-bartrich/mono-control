"""End-to-end tests for the generic `repo init/mat/demat` CLI commands (shim broker)."""

from pathlib import Path

from typer.testing import CliRunner

from broker_shim import GitRepo, run_git
from mono_control.cli import app
from mono_control.config import Repo, RepoStore

runner = CliRunner()


def _run(env, *args: str):
    return runner.invoke(
        app, ["--config-dir", str(env.config_dir), *args], obj=env.app
    )


def _origin(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--initial-branch", "main", str(path)])
    (path / "README.md").write_text("hello\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "initial"], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path)


def test_repo_init_creates_offline_repo(broker_env):
    env = broker_env
    result = _run(env, "repo", "init", "Plain", "--slug", "plain")
    assert result.exit_code == 0, result.output

    repo = RepoStore(env.broker).load("plain")
    assert repo.name == "Plain"
    assert repo.aspects == set()
    assert (env.off / "plain" / ".git").is_dir()
    assert GitRepo(env.off / "plain").slug() == "plain"


def test_repo_init_initial_branch_sets_dev_and_inits_on_it(broker_env):
    env = broker_env
    result = _run(
        env, "repo", "init", "Dev Repo", "--slug", "dev-repo",
        "--initial-branch", "develop",
    )
    assert result.exit_code == 0, result.output

    repo = RepoStore(env.broker).load("dev-repo")
    assert repo.branches == {"dev": "develop"}
    head = run_git(["symbolic-ref", "HEAD"], cwd=env.off / "dev-repo").strip()
    assert head == "refs/heads/develop"


def test_repo_init_derives_slug_from_name(broker_env):
    env = broker_env
    result = _run(env, "repo", "init", "My Plain Repo")
    assert result.exit_code == 0, result.output
    slugs = RepoStore(env.broker).list()
    assert len(slugs) == 1
    assert slugs[0].startswith("my-plain-repo-")
    assert (env.off / slugs[0] / ".git").is_dir()


def test_repo_init_refuses_existing_slug(broker_env):
    env = broker_env
    RepoStore(env.broker).create(Repo(version=1, slug="taken", name="Taken"))
    result = _run(env, "repo", "init", "Taken Two", "--slug", "taken")
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_repo_mat_moveto_then_branchat_then_demat(broker_env, tmp_path):
    """End-to-end intent sequence: place, then check out a branch, then retire."""
    env = broker_env
    origin = tmp_path / "origin"
    _origin(origin)

    RepoStore(env.broker).create(
        Repo(version=1, slug="opaque", name="Opaque", sources={"origin": str(origin)})
    )

    # 1) moveto — pure placement; absent locally, so source engine clones first.
    moveto_result = _run(env, "repo", "mat", "moveto", "opaque", "apps/web")
    assert moveto_result.exit_code == 0, moveto_result.output
    placed = env.ws / "apps" / "web"
    assert (placed / ".git").is_dir()
    assert GitRepo(placed).slug() == "opaque"

    # 2) branchat — change the ref at the current location.
    branchat_result = _run(env, "repo", "mat", "branchat", "opaque", "main")
    assert branchat_result.exit_code == 0, branchat_result.output

    # 3) demat — retire via name lookup (slugified comparison).
    demat_result = _run(env, "repo", "demat", "Opaque")
    assert demat_result.exit_code == 0, demat_result.output
    assert not placed.exists()
    assert (env.off / "opaque" / ".git").is_dir()


def test_repo_mat_branchat_blocks_when_not_materialized(broker_env):
    env = broker_env
    RepoStore(env.broker).create(Repo(version=1, slug="opaque", name="Opaque"))
    result = _run(env, "repo", "mat", "branchat", "opaque", "main")
    assert result.exit_code != 0
    assert "moveto" in result.output


def test_repo_mat_branchat_rejects_unknown_sub_intent(broker_env):
    env = broker_env
    RepoStore(env.broker).create(Repo(version=1, slug="opaque", name="Opaque"))
    result = _run(env, "repo", "mat", "branchat", "opaque", "main", "tip")
    assert result.exit_code != 0
    assert "unsupported sub-intent" in result.output


def test_repo_mat_commit_rejects_unknown_sub_intent(broker_env):
    env = broker_env
    RepoStore(env.broker).create(Repo(version=1, slug="opaque", name="Opaque"))
    result = _run(env, "repo", "mat", "commit", "opaque", "abc1234", "attached")
    assert result.exit_code != 0
    assert "unsupported sub-intent" in result.output


def test_repo_mat_layout_target_declarative(broker_env, tmp_path):
    """The declarative one-liner combines placement + ref intent."""
    env = broker_env
    origin = tmp_path / "origin"
    _origin(origin)
    RepoStore(env.broker).create(
        Repo(version=1, slug="opaque", name="Opaque", sources={"origin": str(origin)})
    )
    result = _run(
        env, "repo", "mat", "layout-target", "opaque",
        "--location", "apps/web", "--branch", "main",
    )
    assert result.exit_code == 0, result.output
    assert (env.ws / "apps" / "web" / ".git").is_dir()


def test_repo_mat_layout_target_rejects_branch_and_commit_together(broker_env):
    env = broker_env
    RepoStore(env.broker).create(Repo(version=1, slug="opaque", name="Opaque"))
    result = _run(
        env, "repo", "mat", "layout-target", "opaque",
        "--location", "x", "--branch", "main", "--commit", "abc1234",
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output

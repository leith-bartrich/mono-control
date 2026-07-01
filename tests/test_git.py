from pathlib import Path

import pytest

from mono_control.git import (
    GitCommandError,
    GitRepo,
    UnmanagedCheckoutError,
    clone,
    init,
    ls_remote,
    remote_default_branch,
)
from mono_control.git.runner import run_git
from mono_control.host_platform import FsProfile

WINDOWSISH = FsProfile(filemode=False, symlinks=False, ignorecase=True)
LINUXISH = FsProfile(filemode=True, symlinks=True, ignorecase=False)


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    # Commits need an identity; set a throwaway one so tests don't depend on the
    # container's ambient git config.
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")


def _make_origin(path: Path) -> str:
    """Create a git repo at *path* with one commit; return its HEAD sha."""
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", str(path)])
    (path / "README.md").write_text("hello\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "initial"], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path)


def _commit_more(path: Path, filename: str, message: str) -> str:
    (path / filename).write_text(filename + "\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", message], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path)


def test_clone_checks_out_and_stamps(tmp_path):
    commit = _make_origin(tmp_path / "origin")
    repo = clone(
        tmp_path / "origin", tmp_path / "dest", profile=WINDOWSISH, slug="demo"
    )

    assert repo.current_commit() == commit
    assert (tmp_path / "dest" / "README.md").is_file()  # working tree populated
    assert repo.config_get("core.filemode") == "false"
    assert repo.config_get("core.symlinks") == "false"
    assert repo.config_get("core.ignorecase") == "true"
    assert repo.slug() == "demo"


def test_init_with_initial_branch(tmp_path):
    init(tmp_path / "fresh", profile=LINUXISH, slug="fresh", initial_branch="trunk")
    assert GitRepo(tmp_path / "fresh").slug() == "fresh"
    head = run_git(["symbolic-ref", "HEAD"], cwd=tmp_path / "fresh").strip()
    assert head == "refs/heads/trunk"


def test_remote_default_branch_reads_symbolic_head(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    run_git(["init", "--initial-branch", "trunk", str(origin)])
    (origin / "README.md").write_text("hi\n")
    run_git(["add", "."], cwd=origin)
    run_git(["commit", "-m", "initial"], cwd=origin)

    assert remote_default_branch(origin) == "trunk"


def test_remote_default_branch_bad_url_raises():
    with pytest.raises(GitCommandError):
        remote_default_branch("/no/such/repo/here")


def test_init_is_empty_and_stamps(tmp_path):
    repo = init(tmp_path / "new", profile=LINUXISH, slug="new-repo")

    assert (tmp_path / "new" / ".git").is_dir()
    assert repo.current_commit() is None  # no commits yet
    assert repo.config_get("core.filemode") == "true"
    assert repo.config_get("core.symlinks") == "true"
    assert repo.config_get("core.ignorecase") == "false"
    assert repo.slug() == "new-repo"


@pytest.mark.parametrize("profile", [WINDOWSISH, LINUXISH])
def test_stamp_roundtrips(tmp_path, profile):
    repo = init(tmp_path / "r", profile=profile, slug="r")
    assert repo.config_get("core.filemode") == ("true" if profile.filemode else "false")
    assert repo.config_get("core.symlinks") == ("true" if profile.symlinks else "false")
    assert repo.config_get("core.ignorecase") == (
        "true" if profile.ignorecase else "false"
    )


def test_run_git_failure_raises():
    with pytest.raises(GitCommandError):
        run_git(["definitely-not-a-git-command"])


def test_slug_on_unstamped_checkout_raises(tmp_path):
    # A plain `git init` produces a checkout without the mono-control.slug stamp.
    raw = tmp_path / "raw"
    raw.mkdir()
    run_git(["init", str(raw)])
    with pytest.raises(UnmanagedCheckoutError):
        GitRepo(raw).slug()


def test_is_dirty(tmp_path):
    _make_origin(tmp_path / "origin")
    repo = clone(
        tmp_path / "origin", tmp_path / "dest", profile=LINUXISH, slug="demo"
    )
    assert repo.is_dirty() is False
    (tmp_path / "dest" / "README.md").write_text("changed\n")
    assert repo.is_dirty() is True


def test_fetch_brings_in_new_refs(tmp_path):
    _make_origin(tmp_path / "origin")
    repo = clone(
        tmp_path / "origin", tmp_path / "dest", profile=LINUXISH, slug="demo"
    )
    new_commit = _commit_more(tmp_path / "origin", "new.txt", "second")
    # Before fetch the new commit isn't local.
    with pytest.raises(GitCommandError):
        run_git(["cat-file", "-e", new_commit], cwd=tmp_path / "dest")
    repo.fetch("origin")
    # After fetch it is.
    run_git(["cat-file", "-e", new_commit], cwd=tmp_path / "dest")


def test_checkout_changes_head(tmp_path):
    first = _make_origin(tmp_path / "origin")
    repo = clone(
        tmp_path / "origin", tmp_path / "dest", profile=LINUXISH, slug="demo"
    )
    assert repo.current_commit() == first
    # Create a second commit upstream, fetch it, then checkout by sha.
    second = _commit_more(tmp_path / "origin", "new.txt", "second")
    repo.fetch("origin")
    repo.checkout(second)
    assert repo.current_commit() == second


def test_ahead_behind(tmp_path):
    _make_origin(tmp_path / "origin")
    repo = clone(
        tmp_path / "origin", tmp_path / "dest", profile=LINUXISH, slug="demo"
    )
    # In-sync: ahead=0, behind=0.
    assert repo.ahead_behind("HEAD") == (0, 0)
    # Add a commit locally → ahead of origin's recorded ref by 1.
    _commit_more(tmp_path / "dest", "local.txt", "local-only")
    ahead, behind = repo.ahead_behind("origin/HEAD")
    assert (ahead, behind) == (1, 0)


def test_ls_remote_known_and_unknown_ref(tmp_path):
    head = _make_origin(tmp_path / "origin")
    assert ls_remote(tmp_path / "origin", "HEAD") == head
    assert ls_remote(tmp_path / "origin", "refs/heads/does-not-exist") is None

from pathlib import Path

import pytest

from mono_control.git import GitCommandError, clone, init
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


def test_clone_checks_out_and_stamps(tmp_path):
    commit = _make_origin(tmp_path / "origin")
    repo = clone(tmp_path / "origin", tmp_path / "dest", profile=WINDOWSISH)

    assert repo.current_commit() == commit
    assert (tmp_path / "dest" / "README.md").is_file()  # working tree populated
    assert repo.config_get("core.filemode") == "false"
    assert repo.config_get("core.symlinks") == "false"
    assert repo.config_get("core.ignorecase") == "true"


def test_init_is_empty_and_stamps(tmp_path):
    repo = init(tmp_path / "new", profile=LINUXISH)

    assert (tmp_path / "new" / ".git").is_dir()
    assert repo.current_commit() is None  # no commits yet
    assert repo.config_get("core.filemode") == "true"
    assert repo.config_get("core.symlinks") == "true"
    assert repo.config_get("core.ignorecase") == "false"


@pytest.mark.parametrize("profile", [WINDOWSISH, LINUXISH])
def test_stamp_roundtrips(tmp_path, profile):
    repo = init(tmp_path / "r", profile=profile)
    assert repo.config_get("core.filemode") == ("true" if profile.filemode else "false")
    assert repo.config_get("core.symlinks") == ("true" if profile.symlinks else "false")
    assert repo.config_get("core.ignorecase") == (
        "true" if profile.ignorecase else "false"
    )


def test_run_git_failure_raises():
    with pytest.raises(GitCommandError):
        run_git(["definitely-not-a-git-command"])

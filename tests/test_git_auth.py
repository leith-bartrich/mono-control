"""Classification of credential failures in the git layer.

None of git's "you have no usable credential" failures actually say *unauthorized*,
and GitHub reports a private repo you cannot see as **not found** rather than
forbidden — so the only thing to go on is stderr, and ``is_auth_failure`` is a
substring classifier over it.

These tests pin the three things that can rot: every declared marker really is
recognized, ordinary git failures are *not* misread as auth failures (the expensive
mistake — it would tell a user to fix their token when their branch name is wrong),
and ``run_git`` picks the error type from the classifier.

``run_git`` is exercised with a stubbed ``subprocess.run``: the stderr strings below
are real, but reproducing them for real would mean a network round-trip to GitHub,
which the suite does not do (see docs/design/layers/git/README.md — real temp repos,
never a real remote).
"""

from __future__ import annotations

import subprocess

import pytest

from mono_control.git import GitAuthError, GitCommandError
from mono_control.git import errors as git_errors
from mono_control.git import runner
from mono_control.git.runner import run_git

# Real stderr, captured from the container. The first is exactly what the missing
# credential produced before any of this existed.
NO_CREDENTIAL = (
    "fatal: could not read Username for 'https://github.com': terminal prompts disabled"
)
PRIVATE_OR_ABSENT = (
    "remote: Repository not found.\n"
    "fatal: repository 'https://github.com/leith-bartrich/fie-ltx2.git/' not found"
)
BAD_CREDENTIAL = (
    "remote: Invalid username or password.\n"
    "fatal: Authentication failed for 'https://github.com/leith-bartrich/fie-ltx2.git/'"
)

# Ordinary failures. These must NOT be mistaken for auth problems.
NOT_A_REPO = "fatal: not a git repository (or any of the parent directories): .git"
BAD_PATHSPEC = "error: pathspec 'nope' did not match any file(s) known to git"
DIRTY_DEST = (
    "fatal: destination path 'x' already exists and is not an empty directory."
)


@pytest.mark.parametrize("marker", git_errors.AUTH_MARKERS)
def test_every_declared_marker_classifies_as_auth(marker: str) -> None:
    assert git_errors.is_auth_failure(marker)


@pytest.mark.parametrize("marker", git_errors.AUTH_MARKERS)
def test_markers_match_case_insensitively(marker: str) -> None:
    # git is inconsistent about case ("could not read Username", "Authentication failed").
    assert git_errors.is_auth_failure(marker.upper())


@pytest.mark.parametrize("stderr", [NO_CREDENTIAL, PRIVATE_OR_ABSENT, BAD_CREDENTIAL])
def test_real_credential_failures_classify_as_auth(stderr: str) -> None:
    assert git_errors.is_auth_failure(stderr)


@pytest.mark.parametrize("stderr", [NOT_A_REPO, BAD_PATHSPEC, DIRTY_DEST, ""])
def test_ordinary_failures_do_not_classify_as_auth(stderr: str) -> None:
    assert not git_errors.is_auth_failure(stderr)


def _stub_git(monkeypatch: pytest.MonkeyPatch, *, returncode: int, stderr: str) -> None:
    """Make the next ``run_git`` see *returncode* / *stderr* without invoking git."""

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN003 - mirrors subprocess.run
        return subprocess.CompletedProcess(
            args=command, returncode=returncode, stdout="", stderr=stderr
        )

    monkeypatch.setattr(runner.subprocess, "run", fake_run)


def test_run_git_raises_auth_error_on_credential_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_git(monkeypatch, returncode=128, stderr=NO_CREDENTIAL)

    with pytest.raises(GitAuthError) as exc:
        run_git(["clone", "https://github.com/leith-bartrich/fie-ltx2.git"])

    message = str(exc.value)
    # The hint must name the way out; that is the entire reason this type exists.
    assert "MONO_CONTROL_GITHUB_TOKEN" in message
    assert "gh auth login" in message
    # ...and must still carry the raw failure it wraps.
    assert "could not read Username" in message


def test_run_git_raises_plain_command_error_otherwise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_git(monkeypatch, returncode=128, stderr=NOT_A_REPO)

    with pytest.raises(GitCommandError) as exc:
        run_git(["status", "--porcelain"])

    assert not isinstance(exc.value, GitAuthError)
    assert "MONO_CONTROL_GITHUB_TOKEN" not in str(exc.value)


def test_auth_error_is_still_a_command_error() -> None:
    """Compatibility invariant: existing ``except GitCommandError`` handlers (e.g.
    ``GitRepo.resolve_ref``, ``GitRepo.slug``) must keep catching auth failures."""
    assert issubclass(GitAuthError, GitCommandError)

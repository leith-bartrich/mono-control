"""The single subprocess chokepoint for invoking git.

Every git call in this package goes through ``run_git`` so behavior and error
handling stay uniform: list-form args (never a shell string), captured output,
and exit codes mapped to the typed ``GitError`` hierarchy.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .errors import GitAuthError, GitCommandError, GitError, is_auth_failure


def run_git(args: list[str], *, cwd: Path | None = None) -> str:
    """Run ``git <args>`` and return its stripped stdout.

    ``cwd`` sets the working directory for the invocation. A non-zero exit raises
    ``GitCommandError`` — or its ``GitAuthError`` subclass when stderr shows the
    failure was really a missing/rejected GitHub credential, since that remedy lies
    outside the container. A missing git binary raises ``GitError``.
    """
    command = ["git", *args]
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as e:
        raise GitError("git executable not found on PATH") from e
    if result.returncode != 0:
        error = GitAuthError if is_auth_failure(result.stderr) else GitCommandError
        raise error(command, result.returncode, result.stderr)
    return result.stdout.strip()

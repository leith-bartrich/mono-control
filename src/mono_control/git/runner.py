"""The single subprocess chokepoint for invoking git.

Every git call in this package goes through ``run_git`` so behavior and error
handling stay uniform: list-form args (never a shell string), captured output,
and exit codes mapped to the typed ``GitError`` hierarchy.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .errors import GitCommandError, GitError


def run_git(args: list[str], *, cwd: Path | None = None) -> str:
    """Run ``git <args>`` and return its stripped stdout.

    ``cwd`` sets the working directory for the invocation. A non-zero exit raises
    ``GitCommandError`` (with the command, code, and stderr); a missing git binary
    raises ``GitError``.
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
        raise GitCommandError(command, result.returncode, result.stderr)
    return result.stdout.strip()

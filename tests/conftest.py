"""Shared test fixtures for the broker-client container.

Step 2 makes mono-control a pure broker client; tests drive it against the
in-process real-effect :class:`~broker_shim.ShimBroker` (standing in for the
host-side broker in the other repo). ``broker_env`` wires one up over real temp
``config`` / ``ws`` (work/worktree root) / ``off`` (bare/offline root) directories,
monkeypatches the nominal path constants (``WORK_DIR`` / ``BARE_DIR``) to match,
and hands back an ``AppContext`` for CLI injection.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from broker_shim import ShimBroker
from mono_control import paths
from mono_control.app_context import AppContext
from mono_control.sandbox import in_container

# The suite runs mono-control's code, which loads untrusted third-party deps, so it
# must run in the container, never on the host. `mproj test-control` does this; a bare
# `uv run pytest` / `python -m pytest` on the host must refuse. Keyed off the baked
# container marker (see sandbox.py), which no env var can fake. Done in a
# pytest_configure hook (not at import) so the refusal reads as a clean, deliberate
# message rather than a conftest ImportError.
def pytest_configure(config):
    if not in_container():
        pytest.exit(
            "\n"
            "mono-control's test suite does not run on the host. This refusal is\n"
            "CORRECT and EXPECTED - not a bug, and not something to work around.\n"
            "\n"
            "  DO:      run the tests inside the container  ->  mproj test-control\n"
            "\n"
            "  DO NOT:  bypass this. No env vars, no forging the container marker, no\n"
            "           `uv run pytest` / `python -m pytest` on the host. pytest imports\n"
            "           and executes the same untrusted dependency tree; running it on\n"
            "           the host is the supply-chain exposure the container prevents.\n"
            "  See CLAUDE.md.\n",
            returncode=1,
        )


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    """A deterministic git identity so the shim's commits/clones succeed."""
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "test@example.com")


@dataclass
class BrokerEnv:
    """A ready-to-use broker + the roots it operates on.

    ``ws`` is the work/worktree root (materialized), ``off`` is the bare/offline
    root — the two roots the bare+worktree model threads everywhere.
    """

    config_dir: Path
    ws: Path
    off: Path
    broker: ShimBroker

    @property
    def app(self) -> AppContext:
        """An ``AppContext`` to pass as ``obj=`` to a ``CliRunner`` invoke."""
        return AppContext(config_dir=self.config_dir, broker=self.broker)


@pytest.fixture
def broker_env(tmp_path, monkeypatch) -> BrokerEnv:
    """A real-effect shim broker over fresh temp roots, with paths patched.

    ``ws`` is the work root (worktrees / materialized); ``off`` is the bare root
    (bare repos / offline).
    """
    config_dir = tmp_path / "config"
    ws = tmp_path / "ws"
    off = tmp_path / "off"
    ws.mkdir()
    off.mkdir()
    monkeypatch.setattr(paths, "WORK_DIR", ws)
    monkeypatch.setattr(paths, "BARE_DIR", off)
    return BrokerEnv(config_dir=config_dir, ws=ws, off=off, broker=ShimBroker(config_dir, ws, off))

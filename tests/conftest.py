"""Shared test fixtures for the broker-client container.

Step 2 makes mono-control a pure broker client; tests drive it against the
in-process real-effect :class:`~broker_shim.ShimBroker` (standing in for the
host-side broker in the other repo). ``broker_env`` wires one up over real temp
``config`` / ``ws`` / ``off`` directories, monkeypatches the nominal path
constants to match, and hands back an ``AppContext`` for CLI injection.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from broker_shim import ShimBroker
from mono_control import paths
from mono_control.app_context import AppContext


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    """A deterministic git identity so the shim's commits/clones succeed."""
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "test@example.com")


@dataclass
class BrokerEnv:
    """A ready-to-use broker + the roots it operates on."""

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
    """A real-effect shim broker over fresh temp roots, with paths patched."""
    config_dir = tmp_path / "config"
    ws = tmp_path / "ws"
    off = tmp_path / "off"
    ws.mkdir()
    off.mkdir()
    monkeypatch.setattr(paths, "REPOS_DIR", ws)
    monkeypatch.setattr(paths, "OFFLINE_DIR", off)
    return BrokerEnv(config_dir=config_dir, ws=ws, off=off, broker=ShimBroker(config_dir, ws, off))

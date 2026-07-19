"""The object the CLI hangs on ``ctx.obj``: the effective config dir + a broker.

Every effect the container performs travels over the host-side broker, so a
single ``BrokerProtocol`` is threaded from the root callback down to the leaf
commands via the Typer context. ``config_dir`` is retained for display / the
``--config-dir`` surface, but repo definitions and system config are now read
through the broker, not that path.

Tests inject a fake broker by constructing an ``AppContext`` and passing it as
``obj=`` to ``CliRunner.invoke``; the root callback preserves an injected broker
rather than building a real HTTP client.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .broker import BrokerProtocol


@dataclass
class AppContext:
    """Shared per-invocation state carried on the Typer ``ctx.obj``."""

    config_dir: Path
    broker: BrokerProtocol

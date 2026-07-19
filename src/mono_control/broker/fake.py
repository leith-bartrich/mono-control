"""In-process fake broker for tests — no sockets.

Implements ``BrokerProtocol`` against canned data so callers depending on the
protocol can be exercised without standing up an HTTP server. Records every
``call`` for assertions, returns the canned inventory for ``scan``, and raises
``BrokerError(-32601, ...)`` (JSON-RPC method-not-found) for anything else.
"""

from __future__ import annotations

from typing import Any

from .models import BrokerError, WireInventory


class FakeBroker:
    """A canned, socket-free ``BrokerProtocol`` implementation for tests."""

    def __init__(
        self,
        inventory: WireInventory | None = None,
        results: dict[str, Any] | None = None,
    ) -> None:
        self.inventory = inventory if inventory is not None else WireInventory()
        self.results: dict[str, Any] = dict(results or {})
        self.results.setdefault("scan", self.inventory)
        self.calls: list[tuple[str, dict | None]] = []

    def call(self, method: str, params: dict | None = None) -> Any:
        """Record the call and return the canned result, or raise method-not-found."""
        self.calls.append((method, params))
        if method not in self.results:
            raise BrokerError(-32601, f"method not found: {method!r}")
        return self.results[method]

    def scan(self) -> WireInventory:
        """Return the canned ``WireInventory`` (also records the call)."""
        result = self.call("scan")
        if isinstance(result, WireInventory):
            return result
        return WireInventory.model_validate(result)

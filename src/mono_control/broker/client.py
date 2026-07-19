"""Stdlib-only JSON-RPC 2.0 client for the host-side broker.

The container holds no token and touches no git/filesystem directly; it calls
back to a host-side broker over JSON-RPC 2.0 (HTTP + bearer auth). The transport
core here is deliberately **stdlib-only** (``urllib`` + ``json``) so it can one
day be mirrored in a leaner runtime; only the typed ``scan`` convenience reaches
for the pydantic wire models.

Connection details are read from the environment the shim injects:
``MONO_BROKER_HOST`` / ``MONO_BROKER_PORT`` / ``MONO_BROKER_TOKEN``. Callers
should depend on ``BrokerProtocol`` (not this concrete class) so tests can
substitute the in-process ``fake``.
"""

from __future__ import annotations

import itertools
import json
import os
import urllib.error
import urllib.request
from typing import Any, Protocol, runtime_checkable

from .models import BrokerError, WireInventory

HOST_ENV = "MONO_BROKER_HOST"
PORT_ENV = "MONO_BROKER_PORT"
TOKEN_ENV = "MONO_BROKER_TOKEN"


class BrokerTransportError(Exception):
    """A broker call failed below the JSON-RPC layer.

    Transport failure (host unreachable), an HTTP error such as ``401
    unauthorized``, or a response body that is not the expected JSON-RPC
    envelope. Distinct from ``BrokerError``, which is a *well-formed* JSON-RPC
    error returned by the broker.
    """


@runtime_checkable
class BrokerProtocol(Protocol):
    """The surface callers depend on — satisfied by ``BrokerClient`` and the fake."""

    def call(self, method: str, params: dict | None = None) -> Any: ...

    def scan(self) -> WireInventory: ...


class BrokerClient:
    """A JSON-RPC 2.0 client that POSTs to the host-side broker over HTTP.

    Reads ``MONO_BROKER_HOST`` / ``PORT`` / ``TOKEN`` from the environment; the
    constructor accepts overrides for tests. ``call`` returns the ``result`` on
    success, raises ``BrokerError`` on a JSON-RPC ``error`` envelope, and raises
    ``BrokerTransportError`` on transport failure / 401 / non-JSON.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | str | None = None,
        token: str | None = None,
        *,
        timeout: float = 30.0,
    ) -> None:
        self.host = host if host is not None else os.environ.get(HOST_ENV)
        raw_port = port if port is not None else os.environ.get(PORT_ENV)
        self.port = str(raw_port) if raw_port is not None else None
        self.token = token if token is not None else os.environ.get(TOKEN_ENV)
        self.timeout = timeout
        self._ids = itertools.count(1)

    @property
    def url(self) -> str:
        """The broker endpoint URL, raising if host/port are unset."""
        if not self.host or not self.port:
            raise BrokerTransportError(
                f"broker connection is not configured "
                f"(need {HOST_ENV} and {PORT_ENV} in the environment)"
            )
        return f"http://{self.host}:{self.port}/"

    def call(self, method: str, params: dict | None = None) -> Any:
        """Invoke a JSON-RPC method; return ``result`` or raise on any failure."""
        request_id = next(self._ids)
        envelope: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            envelope["params"] = params
        body = json.dumps(envelope).encode("utf-8")

        request = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            if exc.code == 401:
                raise BrokerTransportError(
                    f"broker rejected the token (HTTP 401 unauthorized): {detail}"
                ) from exc
            raise BrokerTransportError(
                f"broker returned HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise BrokerTransportError(
                f"could not reach broker at {self.url}: {exc.reason}"
            ) from exc

        try:
            message = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise BrokerTransportError(
                f"broker returned a non-JSON response: {raw!r}"
            ) from exc
        if not isinstance(message, dict):
            raise BrokerTransportError(
                f"broker response was not a JSON-RPC object: {message!r}"
            )

        error = message.get("error")
        if error is not None:
            if isinstance(error, dict):
                code = error.get("code", -32603)
                text = error.get("message", "unknown broker error")
            else:  # malformed error field
                code, text = -32603, str(error)
            raise BrokerError(int(code), str(text))

        if "result" not in message:
            raise BrokerTransportError(
                f"broker response lacked both 'result' and 'error': {message!r}"
            )
        return message["result"]

    def scan(self) -> WireInventory:
        """Call the ``scan`` method and validate its result into ``WireInventory``."""
        result = self.call("scan")
        return WireInventory.model_validate(result)

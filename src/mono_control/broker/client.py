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

from .models import (
    AcquireResult,
    BrokerError,
    CheckoutRequest,
    LayoutOpRequest,
    LayoutOpResult,
    OkResult,
    ReadLayoutResult,
    RemoteDefaultBranchResult,
    RepoDefsResult,
    SystemResult,
    WireInventory,
)

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


class TypedBrokerMixin:
    """Typed convenience verbs, authored once in terms of raw ``call``.

    Every effect the container needs is a thin, typed wrapper over a single
    JSON-RPC ``call`` — the transport chokepoint the concrete client/fake
    provides. These validate the JSON result into the pydantic wire models; the
    transport core itself (``BrokerClient.call``) stays stdlib-only, so this
    convenience layer is the only place pydantic touches the wire.
    """

    def call(self, method: str, params: dict | None = None) -> Any:  # pragma: no cover
        raise NotImplementedError

    def scan(self) -> WireInventory:
        """Observe both roots (``scan``) as a ``WireInventory``."""
        result = self.call("scan")
        # Preserve identity when a fake hands back an already-built model.
        if isinstance(result, WireInventory):
            return result
        return WireInventory.model_validate(result)

    def acquire(
        self, slug: str, refs: list[str], *, initial_branch: str | None = None
    ) -> AcquireResult:
        """Make ``refs`` locally resolvable for ``slug`` (clone / init / fetch)."""
        params: dict[str, Any] = {"slug": slug, "refs": refs}
        if initial_branch is not None:
            params["initial_branch"] = initial_branch
        return AcquireResult.model_validate(self.call("acquire", params))

    def place(self, slug: str, location: str) -> LayoutOpResult:
        """Move ``slug`` offline → ``location`` under the workspace root."""
        return self._layout_op("place", slug, location)

    def relocate(self, slug: str, location: str) -> LayoutOpResult:
        """Move ``slug`` between two materialized locations."""
        return self._layout_op("relocate", slug, location)

    def retire(self, slug: str, location: str | None = None) -> LayoutOpResult:
        """Retire ``slug`` from the workspace back to the offline holding area."""
        return self._layout_op("retire", slug, location)

    def _layout_op(self, method: str, slug: str, location: str | None) -> LayoutOpResult:
        params = LayoutOpRequest(slug=slug, location=location).model_dump()
        return LayoutOpResult.model_validate(self.call(method, params))

    def checkout(self, slug: str, commit: str) -> LayoutOpResult:
        """Check ``commit`` out at ``slug``'s current location (hex only)."""
        params = CheckoutRequest(slug=slug, commit=commit).model_dump()
        return LayoutOpResult.model_validate(self.call("checkout", params))

    def read_layout(self, cluster_slug: str) -> ReadLayoutResult:
        """Read a cluster's ``product-cluster/default-layout.json`` contents."""
        return ReadLayoutResult.model_validate(
            self.call("read_layout", {"cluster_slug": cluster_slug})
        )

    def write_layout(self, cluster_slug: str, layout: dict[str, Any]) -> OkResult:
        """Author a cluster's layout document."""
        return OkResult.model_validate(
            self.call("write_layout", {"cluster_slug": cluster_slug, "layout": layout})
        )

    def get_repo_defs(self, slugs: list[str] | None = None) -> RepoDefsResult:
        """Read raw repo definition JSON (all, or the named ``slugs``)."""
        params = {"slugs": slugs} if slugs is not None else {}
        return RepoDefsResult.model_validate(self.call("get_repo_defs", params))

    def get_system(self) -> SystemResult:
        """Read the raw ``system.json`` contents (``None`` if absent)."""
        return SystemResult.model_validate(self.call("get_system"))

    def save_repo_def(self, repo: dict[str, Any]) -> OkResult:
        """Create or overwrite one repo definition."""
        return OkResult.model_validate(self.call("save_repo_def", {"repo": repo}))

    def purge_repo_def(self, slug: str) -> OkResult:
        """Hard-delete one repo definition (raises ``BrokerError`` if absent)."""
        return OkResult.model_validate(self.call("purge_repo_def", {"slug": slug}))

    def save_system(self, system: dict[str, Any]) -> OkResult:
        """Create or overwrite ``system.json``."""
        return OkResult.model_validate(self.call("save_system", {"system": system}))

    def remote_default_branch(self, url: str) -> str | None:
        """Probe a remote's default branch (its symbolic ``HEAD``), or ``None``.

        Takes a raw URL because guided repo-add probes a remote the user is still
        defining; mirrors the old in-container ``git ls-remote --symref`` helper.
        """
        result = RemoteDefaultBranchResult.model_validate(
            self.call("remote_default_branch", {"url": url})
        )
        return result.branch


@runtime_checkable
class BrokerProtocol(Protocol):
    """The surface callers depend on — satisfied by ``BrokerClient`` and the fakes.

    Callers depend on the typed verbs (``scan`` / ``acquire`` / ``place`` / …),
    all of which route through the single ``call`` chokepoint.
    """

    def call(self, method: str, params: dict | None = None) -> Any: ...

    def scan(self) -> WireInventory: ...

    def acquire(
        self, slug: str, refs: list[str], *, initial_branch: str | None = None
    ) -> AcquireResult: ...

    def place(self, slug: str, location: str) -> LayoutOpResult: ...

    def relocate(self, slug: str, location: str) -> LayoutOpResult: ...

    def retire(self, slug: str, location: str | None = None) -> LayoutOpResult: ...

    def checkout(self, slug: str, commit: str) -> LayoutOpResult: ...

    def read_layout(self, cluster_slug: str) -> ReadLayoutResult: ...

    def write_layout(self, cluster_slug: str, layout: dict[str, Any]) -> OkResult: ...

    def get_repo_defs(self, slugs: list[str] | None = None) -> RepoDefsResult: ...

    def get_system(self) -> SystemResult: ...

    def save_repo_def(self, repo: dict[str, Any]) -> OkResult: ...

    def purge_repo_def(self, slug: str) -> OkResult: ...

    def save_system(self, system: dict[str, Any]) -> OkResult: ...

    def remote_default_branch(self, url: str) -> str | None: ...


class BrokerClient(TypedBrokerMixin):
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

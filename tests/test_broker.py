"""Tests for the additive broker foundation (walking skeleton).

Covers the stdlib JSON-RPC client against a real ephemeral socket, the wire <->
on-disk conversion round-trip, the in-process fake, the schema, and the
``emit-schema`` CLI command.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from typer.testing import CliRunner

from broker_shim import INVALID_PARAMS, ShimBroker
from mono_control.broker import (
    AcquireResult,
    BrokerClient,
    BrokerError,
    BrokerProtocol,
    LayoutOpResult,
    OkResult,
    ReadLayoutResult,
    RepoDefsResult,
    SystemResult,
    WireInventory,
    WireRepo,
    WireUnmanaged,
    emit_schema,
    wire_inventory_from_on_disk,
    wire_inventory_to_on_disk,
)
from mono_control.broker.client import BrokerTransportError
from mono_control.broker.fake import FakeBroker
from mono_control.cli import app
from mono_control.on_disk import OnDiskInventory, OnDiskRepo

TOKEN = "s3cr3t-token"


# --------------------------------------------------------------------------- #
# A tiny stdlib broker over a real ephemeral socket, mirroring the shim's wire.
# --------------------------------------------------------------------------- #


class _BrokerHandler(BaseHTTPRequestHandler):
    # Set per server instance below.
    token: str = TOKEN
    received: list[dict] = []

    # Canned ``result`` payloads for the typed WRITE verbs, keyed by JSON-RPC
    # method. Each is the shape the real shim returns, so the client's typed
    # wrappers must validate it into the matching wire model — catching any
    # client<->shim field-name drift over a real loopback socket.
    CANNED: dict = {
        "acquire": {
            "status": "cloned",
            "summary": "cloned alpha",
            "unresolved_refs": [],
            "resolved": {"refs/heads/main": "c0ffee"},
        },
        "place": {"status": "placed", "summary": "placed alpha at apps/web"},
        "relocate": {"status": "relocated", "summary": "relocated alpha to apps/web"},
        "retire": {"status": "retired", "summary": "retired alpha to offline"},
        "checkout": {"status": "checked-out", "summary": "checked out c0ffee for alpha"},
        "read_layout": {"exists": True, "layout": {"components": ["a", "b"]}},
        "write_layout": {"ok": True},
        "get_repo_defs": {
            "repos": {"alpha": {"version": 1, "slug": "alpha", "name": "Alpha"}}
        },
        "save_repo_def": {"ok": True},
        "purge_repo_def": {"ok": True},
        "get_system": {"system": {"version": 1, "clusters": {}}},
        "save_system": {"ok": True},
        "remote_default_branch": {"branch": "main"},
    }

    def log_message(self, *args):  # silence the default stderr logging
        pass

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        auth = self.headers.get("Authorization")
        if auth != f"Bearer {self.token}":
            self._send(401, {"error": "unauthorized"})
            return
        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length))
        type(self).received.append(request)
        rid = request.get("id")
        method = request.get("method")
        if method == "scan":
            self._send(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "repos": [
                            {
                                "slug": "alpha",
                                "location": "alpha",
                                "state": "materialized",
                                "commit": "abc123",
                                "dirty": False,
                            }
                        ],
                        "unmanaged": [{"location": "stranger", "state": "materialized"}],
                    },
                },
            )
        elif method == "boom":
            self._send(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "error": {"code": -32601, "message": "method not found: 'boom'"},
                },
            )
        elif method == "not-json":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"this is not json")
        elif method == "bad-error":
            # A malformed ``error`` field: a bare string, not a JSON-RPC object.
            self._send(
                200,
                {"jsonrpc": "2.0", "id": rid, "error": "just a string, not an object"},
            )
        elif method == "no-result":
            # Neither ``result`` nor ``error`` — an incomplete envelope.
            self._send(200, {"jsonrpc": "2.0", "id": rid})
        elif method == "server-error":
            # A non-401 HTTP error (distinct from the 401 auth path).
            self._send(500, {"error": "internal broker failure"})
        elif method in self.CANNED:
            self._send(200, {"jsonrpc": "2.0", "id": rid, "result": self.CANNED[method]})
        else:
            self._send(
                200,
                {"jsonrpc": "2.0", "id": rid, "result": {"echo": method}},
            )


@pytest.fixture()
def broker_server():
    """Run the stdlib broker on an ephemeral port; yield (host, port, received)."""
    _BrokerHandler.received = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BrokerHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield host, port, _BrokerHandler.received
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _client(host, port, token=TOKEN) -> BrokerClient:
    return BrokerClient(host=host, port=port, token=token, timeout=5.0)


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #


def test_client_is_a_broker_protocol():
    assert isinstance(BrokerClient(host="h", port=1, token="t"), BrokerProtocol)


def test_call_success_returns_result(broker_server):
    host, port, _ = broker_server
    result = _client(host, port).call("echo-me")
    assert result == {"echo": "echo-me"}


def test_call_sends_bearer_header_and_jsonrpc_envelope(broker_server):
    host, port, received = broker_server
    _client(host, port).call("scan", {"foo": "bar"})
    assert len(received) == 1
    envelope = received[0]
    assert envelope["jsonrpc"] == "2.0"
    assert envelope["method"] == "scan"
    assert envelope["params"] == {"foo": "bar"}
    assert isinstance(envelope["id"], int)


def test_scan_convenience_validates_into_wire_inventory(broker_server):
    host, port, _ = broker_server
    inventory = _client(host, port).scan()
    assert isinstance(inventory, WireInventory)
    assert [r.slug for r in inventory.repos] == ["alpha"]
    assert inventory.repos[0].state == "materialized"
    assert [(u.location, u.state) for u in inventory.unmanaged] == [
        ("stranger", "materialized")
    ]


def test_jsonrpc_error_raises_broker_error(broker_server):
    host, port, _ = broker_server
    with pytest.raises(BrokerError) as excinfo:
        _client(host, port).call("boom")
    assert excinfo.value.code == -32601
    assert "boom" in excinfo.value.message


def test_bad_token_raises_clear_auth_error(broker_server):
    host, port, _ = broker_server
    with pytest.raises(BrokerTransportError) as excinfo:
        _client(host, port, token="wrong").call("scan")
    assert "401" in str(excinfo.value)
    assert "unauthorized" in str(excinfo.value).lower()


def test_non_json_response_raises_transport_error(broker_server):
    host, port, _ = broker_server
    with pytest.raises(BrokerTransportError) as excinfo:
        _client(host, port).call("not-json")
    assert "non-json" in str(excinfo.value).lower()


def test_transport_failure_raises_clear_error():
    # Port 1 on loopback: connection refused -> transport error, not a hang.
    client = BrokerClient(host="127.0.0.1", port=1, token=TOKEN, timeout=2.0)
    with pytest.raises(BrokerTransportError) as excinfo:
        client.call("scan")
    assert "could not reach broker" in str(excinfo.value)


def test_client_reads_env(monkeypatch):
    monkeypatch.setenv("MONO_BROKER_HOST", "example")
    monkeypatch.setenv("MONO_BROKER_PORT", "9999")
    monkeypatch.setenv("MONO_BROKER_TOKEN", "tok")
    client = BrokerClient()
    assert client.url == "http://example:9999/"
    assert client.token == "tok"


def test_client_url_unconfigured_raises(monkeypatch):
    monkeypatch.delenv("MONO_BROKER_HOST", raising=False)
    monkeypatch.delenv("MONO_BROKER_PORT", raising=False)
    with pytest.raises(BrokerTransportError):
        _ = BrokerClient().url


# --------------------------------------------------------------------------- #
# Conversion round-trip
# --------------------------------------------------------------------------- #


def test_wire_inventory_round_trip(tmp_path):
    workspace = tmp_path / "ws"
    offline = tmp_path / "off"
    on_disk = OnDiskInventory(
        repos={
            "alpha": OnDiskRepo(
                slug="alpha",
                location=workspace / "alpha",
                state="materialized",
                commit="deadbeef",
                dirty=False,
            ),
            "beta": OnDiskRepo(
                slug="beta",
                location=offline / "beta",
                state="offline",
                commit=None,
                dirty=True,
            ),
        },
        # One foreign tree under each root, to exercise the state discriminator.
        unmanaged=[workspace / "products" / "stranger", offline / "orphan"],
    )

    wire = wire_inventory_from_on_disk(on_disk, workspace, offline)
    # Wire form carries relative, JSON-native locations.
    assert {r.location for r in wire.repos} == {"alpha", "beta"}
    assert {(u.location, u.state) for u in wire.unmanaged} == {
        ("products/stranger", "materialized"),
        ("orphan", "offline"),
    }

    back = wire_inventory_to_on_disk(wire, workspace, offline)
    assert back == on_disk
    # Absolute paths reconstructed against the right root per state.
    assert back.repos["alpha"].location == workspace / "alpha"
    assert back.repos["beta"].location == offline / "beta"
    assert back.repos["beta"].location.is_absolute()
    # The offline foreign tree round-trips back to the offline root, not workspace.
    assert back.unmanaged == [workspace / "products" / "stranger", offline / "orphan"]


def test_wire_repo_json_native(tmp_path):
    repo = OnDiskRepo(
        slug="alpha",
        location=tmp_path / "ws" / "alpha",
        state="materialized",
        commit="c0ffee",
        dirty=True,
    )
    wire = wire_inventory_from_on_disk(
        OnDiskInventory(repos={"alpha": repo}), tmp_path / "ws", tmp_path / "off"
    )
    # Fully JSON-serializable.
    dumped = json.dumps(wire.model_dump())
    assert '"alpha"' in dumped


# --------------------------------------------------------------------------- #
# Fake
# --------------------------------------------------------------------------- #


def test_fake_is_a_broker_protocol():
    assert isinstance(FakeBroker(), BrokerProtocol)


def test_fake_returns_canned_scan():
    canned = WireInventory(
        repos=[
            WireRepo(
                slug="alpha",
                location="alpha",
                state="materialized",
                commit="abc",
                dirty=False,
            )
        ]
    )
    fake = FakeBroker(inventory=canned)
    assert fake.scan() is canned
    assert fake.calls == [("scan", None)]


def test_fake_refuses_unknown_method():
    fake = FakeBroker()
    with pytest.raises(BrokerError) as excinfo:
        fake.call("nope")
    assert excinfo.value.code == -32601
    assert fake.calls == [("nope", None)]


def test_fake_serves_extra_canned_results():
    fake = FakeBroker(results={"ping": {"pong": True}})
    assert fake.call("ping") == {"pong": True}


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #


def test_emit_schema_has_expected_model_keys():
    schema = emit_schema()
    # The observation shapes plus a request/response pair per verb.
    assert {"WireRepo", "WireUnmanaged", "WireInventory"} <= set(schema)
    assert {"AcquireRequest", "AcquireResult", "LayoutOpRequest", "LayoutOpResult",
            "CheckoutRequest", "CheckoutBranchRequest", "ReadLayoutResult",
            "RepoDefsResult", "RemoteDefaultBranchRequest",
            "RemoteDefaultBranchResult"} <= set(schema)
    props = schema["WireRepo"]["properties"]
    # ``branch`` is what lets the container tell "on the branch" from "detached at
    # its tip" — the distinction the layout engine reconciles on.
    assert set(props) == {"slug", "location", "state", "commit", "dirty", "branch"}
    assert set(schema["WireUnmanaged"]["properties"]) == {"location", "state"}
    assert set(schema["AcquireResult"]["properties"]) == {
        "status", "summary", "unresolved_refs", "resolved"
    }


def test_emit_schema_is_deterministic():
    a = json.dumps(emit_schema(), indent=2, sort_keys=True)
    b = json.dumps(emit_schema(), indent=2, sort_keys=True)
    assert a == b


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_emit_schema_cli_prints_valid_json(tmp_path):
    runner = CliRunner()
    # Pass an absolute --config-dir so the root callback (which validates the
    # default before dispatch) is satisfied on any host platform.
    result = runner.invoke(app, ["--config-dir", str(tmp_path), "emit-schema"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert {"WireRepo", "WireUnmanaged", "WireInventory", "AcquireResult"} <= set(payload)


# --------------------------------------------------------------------------- #
# Typed WRITE verbs over the real loopback socket.
#
# For each write verb the typed client exposes, drive it through the real
# BrokerClient over the ephemeral socket and assert (a) the JSON-RPC method +
# params shape the server recorded, and (b) that the canned response parses into
# the right typed wire model. This catches client<->shim field-name drift that a
# pure in-process fake (which never serializes) would hide.
# --------------------------------------------------------------------------- #


def _last(received: list[dict]) -> dict:
    assert received, "no request reached the broker"
    return received[-1]


def test_acquire_sends_params_and_parses_result(broker_server):
    host, port, received = broker_server
    result = _client(host, port).acquire(
        "alpha", ["refs/heads/main"], initial_branch="main"
    )
    envelope = _last(received)
    assert envelope["method"] == "acquire"
    assert envelope["params"] == {
        "slug": "alpha",
        "refs": ["refs/heads/main"],
        "initial_branch": "main",
    }
    assert isinstance(result, AcquireResult)
    assert result.status == "cloned"
    assert result.resolved == {"refs/heads/main": "c0ffee"}


def test_acquire_omits_initial_branch_when_none(broker_server):
    host, port, received = broker_server
    _client(host, port).acquire("alpha", [])
    assert _last(received)["params"] == {"slug": "alpha", "refs": []}


def test_place_sends_slug_and_location(broker_server):
    host, port, received = broker_server
    result = _client(host, port).place("alpha", "apps/web")
    envelope = _last(received)
    assert envelope["method"] == "place"
    assert envelope["params"] == {"slug": "alpha", "location": "apps/web"}
    assert isinstance(result, LayoutOpResult)
    assert result.status == "placed"


def test_relocate_sends_slug_and_location(broker_server):
    host, port, received = broker_server
    result = _client(host, port).relocate("alpha", "apps/web")
    envelope = _last(received)
    assert envelope["method"] == "relocate"
    assert envelope["params"] == {"slug": "alpha", "location": "apps/web"}
    assert isinstance(result, LayoutOpResult)
    assert result.status == "relocated"


def test_retire_sends_null_location(broker_server):
    host, port, received = broker_server
    result = _client(host, port).retire("alpha")
    envelope = _last(received)
    assert envelope["method"] == "retire"
    assert envelope["params"] == {"slug": "alpha", "location": None}
    assert isinstance(result, LayoutOpResult)
    assert result.status == "retired"


def test_checkout_sends_slug_and_commit(broker_server):
    host, port, received = broker_server
    result = _client(host, port).checkout("alpha", "c0ffee")
    envelope = _last(received)
    assert envelope["method"] == "checkout"
    assert envelope["params"] == {"slug": "alpha", "commit": "c0ffee"}
    assert isinstance(result, LayoutOpResult)
    assert result.status == "checked-out"


def test_read_layout_sends_cluster_slug_and_parses(broker_server):
    host, port, received = broker_server
    result = _client(host, port).read_layout("pc-alpha")
    envelope = _last(received)
    assert envelope["method"] == "read_layout"
    assert envelope["params"] == {"cluster_slug": "pc-alpha"}
    assert isinstance(result, ReadLayoutResult)
    assert result.exists is True
    assert result.layout == {"components": ["a", "b"]}


def test_write_layout_sends_cluster_slug_and_layout(broker_server):
    host, port, received = broker_server
    result = _client(host, port).write_layout("pc-alpha", {"x": 1})
    envelope = _last(received)
    assert envelope["method"] == "write_layout"
    assert envelope["params"] == {"cluster_slug": "pc-alpha", "layout": {"x": 1}}
    assert isinstance(result, OkResult)
    assert result.ok is True


def test_get_repo_defs_all_sends_empty_params(broker_server):
    host, port, received = broker_server
    result = _client(host, port).get_repo_defs()
    envelope = _last(received)
    assert envelope["method"] == "get_repo_defs"
    assert envelope["params"] == {}
    assert isinstance(result, RepoDefsResult)
    assert set(result.repos) == {"alpha"}


def test_get_repo_defs_filtered_sends_slugs(broker_server):
    host, port, received = broker_server
    _client(host, port).get_repo_defs(["alpha", "beta"])
    assert _last(received)["params"] == {"slugs": ["alpha", "beta"]}


def test_save_repo_def_sends_repo(broker_server):
    host, port, received = broker_server
    repo = {"version": 1, "slug": "alpha", "name": "Alpha"}
    result = _client(host, port).save_repo_def(repo)
    envelope = _last(received)
    assert envelope["method"] == "save_repo_def"
    assert envelope["params"] == {"repo": repo}
    assert isinstance(result, OkResult) and result.ok is True


def test_purge_repo_def_sends_slug(broker_server):
    host, port, received = broker_server
    result = _client(host, port).purge_repo_def("alpha")
    envelope = _last(received)
    assert envelope["method"] == "purge_repo_def"
    assert envelope["params"] == {"slug": "alpha"}
    assert isinstance(result, OkResult) and result.ok is True


def test_get_system_sends_no_params_and_parses(broker_server):
    host, port, received = broker_server
    result = _client(host, port).get_system()
    envelope = _last(received)
    assert envelope["method"] == "get_system"
    assert "params" not in envelope  # get_system carries no params
    assert isinstance(result, SystemResult)
    assert result.system == {"version": 1, "clusters": {}}


def test_save_system_sends_system(broker_server):
    host, port, received = broker_server
    system = {"version": 1, "clusters": {}}
    result = _client(host, port).save_system(system)
    envelope = _last(received)
    assert envelope["method"] == "save_system"
    assert envelope["params"] == {"system": system}
    assert isinstance(result, OkResult) and result.ok is True


def test_remote_default_branch_sends_url_and_parses_branch(broker_server):
    host, port, received = broker_server
    branch = _client(host, port).remote_default_branch("https://example.com/x.git")
    envelope = _last(received)
    assert envelope["method"] == "remote_default_branch"
    assert envelope["params"] == {"url": "https://example.com/x.git"}
    assert branch == "main"


# --------------------------------------------------------------------------- #
# Client error branches (below the JSON-RPC layer).
# --------------------------------------------------------------------------- #


def test_malformed_error_field_raises_broker_error(broker_server):
    """A non-dict ``error`` field still surfaces as a BrokerError (generic code)."""
    host, port, _ = broker_server
    with pytest.raises(BrokerError) as excinfo:
        _client(host, port).call("bad-error")
    assert excinfo.value.code == -32603
    assert "just a string" in excinfo.value.message


def test_response_without_result_or_error_raises_transport_error(broker_server):
    host, port, _ = broker_server
    with pytest.raises(BrokerTransportError) as excinfo:
        _client(host, port).call("no-result")
    assert "lacked both" in str(excinfo.value).lower()


def test_non_401_http_error_raises_transport_error(broker_server):
    """A 5xx (unlike 401) surfaces as a generic HTTP transport error."""
    host, port, _ = broker_server
    with pytest.raises(BrokerTransportError) as excinfo:
        _client(host, port).call("server-error")
    assert "http 500" in str(excinfo.value).lower()


# --------------------------------------------------------------------------- #
# ShimBroker security boundary — mirrors the real shim's INVALID_PARAMS rejects.
#
# The real host-side shim validates every container-supplied parameter before it
# touches disk or spawns git; the enriched ShimBroker now models those same
# rejections. These assert mono-control surfaces them as BrokerError(-32602) —
# security-boundary coverage the container suite otherwise lacks (its other tests
# only ever feed valid inputs). Cases mirror the shim's own test_verbs_git.py.
# --------------------------------------------------------------------------- #


def _shim(tmp_path) -> ShimBroker:
    (tmp_path / "ws").mkdir()
    (tmp_path / "off").mkdir()
    return ShimBroker(tmp_path / "config", tmp_path / "ws", tmp_path / "off")


@pytest.mark.parametrize("bad_slug", ["../escape", "a/b", "..", "", ".hidden"])
def test_shim_rejects_invalid_slug(tmp_path, bad_slug):
    with pytest.raises(BrokerError) as excinfo:
        _shim(tmp_path).call("acquire", {"slug": bad_slug})
    assert excinfo.value.code == INVALID_PARAMS


@pytest.mark.parametrize(
    "bad_commit", ["main", "HEAD", "--force", "zzzz", "refs/heads/main"]
)
def test_shim_rejects_non_hex_commit_on_checkout(tmp_path, bad_commit):
    with pytest.raises(BrokerError) as excinfo:
        _shim(tmp_path).call("checkout", {"slug": "alpha", "commit": bad_commit})
    assert excinfo.value.code == INVALID_PARAMS


@pytest.mark.parametrize(
    "bad_url",
    ["file:///etc/passwd", "ext::sh -c id", "ssh://host/x", "http://x/y", "/local/path"],
)
def test_shim_rejects_non_https_remote_url(tmp_path, bad_url):
    with pytest.raises(BrokerError) as excinfo:
        _shim(tmp_path).call("remote_default_branch", {"url": bad_url})
    assert excinfo.value.code == INVALID_PARAMS


@pytest.mark.parametrize("verb", ["place", "relocate"])
@pytest.mark.parametrize("bad_location", ["../out", "/abs/path", "a/../../b"])
def test_shim_rejects_location_escape_on_move(tmp_path, verb, bad_location):
    with pytest.raises(BrokerError) as excinfo:
        _shim(tmp_path).call(verb, {"slug": "alpha", "location": bad_location})
    assert excinfo.value.code == INVALID_PARAMS


def test_shim_rejection_surfaces_through_typed_verb(tmp_path):
    """The rejection reaches callers through the typed convenience verbs too."""
    with pytest.raises(BrokerError) as excinfo:
        _shim(tmp_path).checkout("alpha", "refs/heads/main")
    assert excinfo.value.code == INVALID_PARAMS

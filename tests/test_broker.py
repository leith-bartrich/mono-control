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

from mono_control.broker import (
    BrokerClient,
    BrokerError,
    BrokerProtocol,
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
            "CheckoutRequest", "ReadLayoutResult", "RepoDefsResult",
            "RemoteDefaultBranchRequest", "RemoteDefaultBranchResult"} <= set(schema)
    props = schema["WireRepo"]["properties"]
    assert set(props) == {"slug", "location", "state", "commit", "dirty"}
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

"""Bridge client classification (plan T1 offline expected-failures) and gate.

The live-server stub binds a real loopback socket — no game involved — so the
transport, token handling, and failure classification are exercised exactly
as they will run. The stub answers contract 2 (the live surface); contract 1
is read-only diagnostics and refuses writes client-side (plan v2 §Phase A).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from minecraft_film_agent.bridge_client import (
    BridgeTransportError,
    CinematicBridgeClient,
    CinematicBridgeConfig,
    version_mismatches,
    version_mismatches_v2,
)
from minecraft_film_agent.production_models import (
    ErrorClass,
    OperationRequest,
    PINNED_VERSIONS,
    RuntimeVersions,
)


def _request(method: str) -> OperationRequest:
    return OperationRequest(
        run_id="run-x",
        operation_id="op-1",
        idempotency_key="run-x/op-1",
        method=method,
    )


def test_non_loopback_endpoint_refused_at_construction() -> None:
    with pytest.raises(BridgeTransportError):
        CinematicBridgeClient(
            CinematicBridgeConfig(endpoint="http://192.168.1.5:9000", token="t")
        )


def test_closed_port_read_is_bridge_unavailable() -> None:
    client = CinematicBridgeClient(
        CinematicBridgeConfig(endpoint="http://127.0.0.1:1", token="t", timeout_seconds=1.0)
    )
    with pytest.raises(BridgeTransportError) as error:
        client.call(_request("bridge.get_runtime_versions"))
    assert error.value.kind is ErrorClass.BRIDGE_UNAVAILABLE


def test_contract1_write_refused_client_side() -> None:
    """Live writes NEVER ride the contract-1 wire (plan v2 §Phase A)."""

    client = CinematicBridgeClient(
        CinematicBridgeConfig(endpoint="http://127.0.0.1:1", token="t", timeout_seconds=1.0)
    )
    with pytest.raises(BridgeTransportError) as error:
        client.call(_request("bridge.submit_timeline"))
    assert error.value.kind is ErrorClass.VALIDATION_FAILED


def test_closed_port_v2_write_is_timeout_unknown_never_bridge_down() -> None:
    client = CinematicBridgeClient(
        CinematicBridgeConfig(endpoint="http://127.0.0.1:1", token="t", timeout_seconds=1.0)
    )
    with pytest.raises(BridgeTransportError) as error:
        client.mocap_prepare(_request("mocap.prepare_recording"))
    assert error.value.kind is ErrorClass.OPERATION_TIMEOUT_UNKNOWN


class _StubBridge(BaseHTTPRequestHandler):
    token = "tok123"
    versions = {
        "minecraft": "1.21.1",
        "fabric_loader": "0.19.3",
        "flashback": "0.39.8",
        "mocap": "1.3.10",
        "bridge": "0.2.0",
        "contract": 2,
    }
    capabilities = {
        "contract": 2,
        "minecraft": "1.21.1",
        "fabric_loader": "0.19.3",
        "flashback": "0.39.8",
        "mocap": "1.3.10",
        "bridge": "0.2.0",
        "typed_world_ops": True,
        "world_reads": True,
        "mocap_state_machine": True,
        "tick_scheduler": True,
        "flashback_automation": False,
    }

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length)
        if self.headers.get("Authorization") != f"Bearer {self.token}":
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        envelope = json.loads(payload.decode("utf-8"))
        request = envelope["request"]
        assert request["schema_version"] == 2, "live client must speak contract 2"
        if request["method"] == "bridge.get_runtime_versions":
            result = self.versions
        elif request["method"] == "bridge.capabilities":
            result = self.capabilities
        else:
            result = {"state": "waiting_for_selection"}
        body = json.dumps(
            {
                "schema_version": 2,
                "operation_id": request["operation_id"],
                "idempotency_key": request["idempotency_key"],
                "status": "applied",
                "journal_state": "observed",
                "result": result,
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # silence test output
        return


@pytest.fixture()
def stub_bridge() -> "tuple[CinematicBridgeClient, str]":
    server = HTTPServer(("127.0.0.1", 0), _StubBridge)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    yield endpoint, endpoint
    server.shutdown()
    server.server_close()


def test_live_stub_round_trip_and_version_gate(stub_bridge) -> None:
    endpoint, _ = stub_bridge
    client = CinematicBridgeClient(CinematicBridgeConfig(endpoint=endpoint, token="tok123"))
    versions = client.handshake()
    assert versions.flashback == "0.39.8"
    assert versions.contract == 2
    assert version_mismatches_v2(versions) == []


def test_live_stub_capabilities_and_mocap_round_trip(stub_bridge) -> None:
    endpoint, _ = stub_bridge
    client = CinematicBridgeClient(CinematicBridgeConfig(endpoint=endpoint, token="tok123"))
    capabilities = client.capabilities("run-x")
    assert capabilities.typed_world_ops is True
    assert capabilities.flashback_automation is False
    assert capabilities.missing_for_mocap_only() == []
    state = client.mocap_state("run-x")
    assert state.state.value == "waiting_for_selection"


def test_live_stub_rejects_bad_token_as_authentication_failure(stub_bridge) -> None:
    endpoint, _ = stub_bridge
    client = CinematicBridgeClient(CinematicBridgeConfig(endpoint=endpoint, token="wrong"))
    with pytest.raises(BridgeTransportError) as error:
        client.call(_request("bridge.get_runtime_versions"))
    assert error.value.kind is ErrorClass.AUTHENTICATION_FAILED
    assert "tok123" not in str(error.value)


def test_version_gate_rejects_near_misses() -> None:
    drifted = RuntimeVersions(
        minecraft="1.21.1",
        fabric_loader="0.19.3",
        flashback="0.39.10",
        mocap="1.3.9",
        bridge="0.1.0",
        contract=2,
    )
    issues = version_mismatches_v2(drifted)
    assert any("0.39.10" in issue for issue in issues)
    assert any("1.3.9" in issue for issue in issues)
    assert len(issues) == 2
    assert set(PINNED_VERSIONS) == {"minecraft", "fabric_loader", "flashback", "mocap"}
    # contract 1 is a mismatch for live writes
    assert any("contract" in issue for issue in version_mismatches_v2(
        drifted.model_copy(update={"flashback": "0.39.8", "mocap": "1.3.10", "contract": 1})
    ))

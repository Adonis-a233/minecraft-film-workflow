"""Contract tests for the read-only bridge inspector against a mock bridge.

The mock reproduces the MCPServer mod's REST surface (X-API-Key header,
/health without auth, JSON GET endpoints) and the failure modes the live
adapter must classify: 401, timeout, connection refused, wrong service.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from minecraft_film_agent.adapters import McpServerRestInspector
from minecraft_film_agent.bridge import (
    BridgeAuthFailed,
    BridgeConfigError,
    BridgeUnexpectedResponse,
    BridgeUnreachable,
    check_environment,
    resolve_bridge_config,
    save_environment_snapshot,
)

TOKEN = "secret-token-abcdef123456"

GAME_STATUS = {
    "status": "running",
    "version": "1.21.1",
    "worldName": "Marx Video Test",
    "players": ["Abel"],
    "time": 6000,
}


class FakeBridge:
    """Configurable stand-in for the in-game MCPServer REST endpoints."""

    def __init__(self, *, status_code=200, payload=None, content_type="application/json", delay=0.0, require_key=TOKEN):
        self.requests: list[dict[str, str]] = []
        self.status_code = status_code
        self.payload = payload if payload is not None else {}
        self.content_type = content_type
        self.delay = delay
        self.require_key = require_key
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.endpoint = f"http://127.0.0.1:{self._server.server_address[1]}"

    def _make_handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence test output
                pass

            def do_GET(self):
                outer.requests.append(
                    {
                        "method": "GET",
                        "path": self.path,
                        "api_key": self.headers.get("X-API-Key"),
                    }
                )
                if self.path == "/health" and outer.require_key is None:
                    outer._respond(self)
                    return
                if outer.require_key is not None and self.headers.get("X-API-Key") != outer.require_key:
                    body = json.dumps({"error": "bad key", "echo": outer.require_key}).encode()
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                outer._respond(self)

            def do_POST(self):
                outer.requests.append(
                    {
                        "method": "POST",
                        "path": self.path,
                        "api_key": self.headers.get("X-API-Key"),
                    }
                )
                self.send_error(405)

        return Handler

    def _respond(self, handler):
        if self.delay:
            threading.Event().wait(self.delay)
        body = json.dumps(self.payload).encode() if self.content_type == "application/json" else b"<html>not the bridge</html>"
        handler.send_response(self.status_code)
        handler.send_header("Content-Type", self.content_type)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def stop(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture()
def inspector_factory():
    fixtures: list[FakeBridge] = []

    def make(**kwargs) -> tuple[McpServerRestInspector, FakeBridge]:
        bridge = FakeBridge(**kwargs)
        fixtures.append(bridge)
        config = resolve_bridge_config(endpoint=bridge.endpoint, api_key=TOKEN)
        return McpServerRestInspector(config), bridge

    yield make
    for bridge in fixtures:
        bridge.stop()


def test_inspect_environment_happy_path(inspector_factory):
    inspector, bridge = inspector_factory(payload=GAME_STATUS)
    snapshot = inspector.inspect_environment()
    assert snapshot.game_status["worldName"] == "Marx Video Test"
    paths = [request["path"] for request in bridge.requests]
    assert "/api/status" in paths
    assert "/api/entities" in paths
    assert all(request["method"] == "GET" for request in bridge.requests)
    assert all(request["api_key"] == TOKEN for request in bridge.requests if request["path"] != "/health")


def test_probe_does_not_send_api_key(inspector_factory):
    inspector, bridge = inspector_factory(payload={"status": "ok"}, require_key=None)
    payload = inspector.probe()
    assert payload == {"status": "ok"}
    health = [request for request in bridge.requests if request["path"] == "/health"]
    assert health and health[0]["api_key"] is None


def test_wrong_api_key_raises_auth_failure_without_leaking_token(inspector_factory):
    _inspector, bridge = inspector_factory(payload=GAME_STATUS)
    wrong = McpServerRestInspector(
        resolve_bridge_config(endpoint=bridge.endpoint, api_key="wrong-key")
    )
    with pytest.raises(BridgeAuthFailed) as excinfo:
        wrong.inspect_environment()
    assert "wrong-key" not in str(excinfo.value)
    assert "wrong-key" not in str(excinfo.value.detail)


def test_timeout_is_classified(inspector_factory):
    inspector, _bridge = inspector_factory(payload=GAME_STATUS, delay=1.0)
    slow_config = resolve_bridge_config(
        endpoint=inspector._config.endpoint, api_key=TOKEN, timeout_seconds=0.2
    )
    slow = McpServerRestInspector(slow_config)
    with pytest.raises(BridgeUnreachable) as excinfo:
        slow.inspect_environment()
    assert "timeout" in str(excinfo.value)


def test_game_not_running_is_classified():
    probe_socket = __import__("socket").socket()
    probe_socket.bind(("127.0.0.1", 0))
    free_port = probe_socket.getsockname()[1]
    probe_socket.close()
    config = resolve_bridge_config(endpoint=f"http://127.0.0.1:{free_port}", api_key=TOKEN)
    inspector = McpServerRestInspector(config)
    with pytest.raises(BridgeUnreachable) as excinfo:
        inspector.inspect_environment()
    assert "running" in str(excinfo.value)


def test_wrong_service_is_classified(inspector_factory):
    inspector, _bridge = inspector_factory(payload=GAME_STATUS, content_type="text/html")
    with pytest.raises(BridgeUnexpectedResponse):
        inspector.inspect_environment()


def test_missing_world_and_player_reported_by_check():
    from datetime import UTC, datetime

    from minecraft_film_agent.models import EnvironmentSnapshot

    bare = EnvironmentSnapshot(
        captured_at=datetime.now(UTC),
        endpoint="http://127.0.0.1:8081",
        bridge_probe={},
        game_status={"status": "starting"},
    )
    result = check_environment(bare, expect_world="Marx Video Test", expect_player="Abel")
    assert result["ok"] is False
    assert all(not check["met"] for check in result["checks"])


def test_loopback_only_configuration():
    with pytest.raises(BridgeConfigError):
        resolve_bridge_config(endpoint="http://10.1.2.3:8081", api_key=TOKEN)
    with pytest.raises(BridgeConfigError):
        resolve_bridge_config(endpoint="ftp://localhost:8081", api_key=TOKEN)
    with pytest.raises(BridgeConfigError):
        resolve_bridge_config(endpoint="http://localhost:8081", api_key=None)
    resolved = resolve_bridge_config(endpoint="http://localhost:8081/", api_key=TOKEN)
    assert resolved.endpoint == "http://localhost:8081"


def test_snapshot_file_is_immutable(tmp_path: Path):
    from minecraft_film_agent.models import EnvironmentSnapshot
    from datetime import UTC, datetime

    snapshot = EnvironmentSnapshot(
        captured_at=datetime.now(UTC),
        endpoint="http://127.0.0.1:8081",
        bridge_probe={},
        game_status=GAME_STATUS,
    )
    out = tmp_path / "snap.json"
    save_environment_snapshot(tmp_path, snapshot, out_path=out)
    with pytest.raises(BridgeConfigError):
        save_environment_snapshot(tmp_path, snapshot, out_path=out)
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["game_status"]["worldName"] == "Marx Video Test"

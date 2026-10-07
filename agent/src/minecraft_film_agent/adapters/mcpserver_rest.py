"""Read-only REST inspector for the MCPServer Fabric mod bridge.

The mod (QianKunBoss/Minecraft-MCPServer) exposes GET endpoints such as
`/api/status` and `/api/entities` authenticated by an `X-API-Key` header.
This adapter is read-only by construction: it issues GET requests to a fixed
path whitelist and has no way to execute game commands.

Failure classification (see `bridge.BridgeError` subclasses):

- connection refused / timeout -> `BridgeUnreachable` (game not running);
- 401/403 -> `BridgeAuthFailed`;
- anything else (HTML page, 404, non-JSON, missing payload) ->
  `BridgeUnexpectedResponse`.

Every error message is passed through a redactor so the API key can never
appear in logs, CLI output, or MCP tool results.
"""

from __future__ import annotations

import http.client
import json
import socket
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

from ..bridge import (
    BridgeAuthFailed,
    BridgeConfig,
    BridgeError,
    BridgeUnexpectedResponse,
    BridgeUnreachable,
    redact,
)
from ..models import EnvironmentSnapshot


MAX_ERROR_BODY_BYTES = 64 * 1024


class McpServerRestInspector:
    """GET-only inspector; the API key never appears in raised messages."""

    name = "mcpserver-rest"
    read_only = True

    def __init__(self, config: BridgeConfig):
        self._config = config
        self._redact = lambda text: redact(text, config.api_key)

    # -- public API ---------------------------------------------------------

    def probe(self) -> dict[str, object]:
        """Classified reachability check against the unauthenticated /health."""
        payload = self._get_json("/health", authenticated=False)
        if not isinstance(payload, dict):
            raise BridgeUnexpectedResponse(
                "/health returned non-object JSON",
                detail=repr(payload)[:500],
                redactor=self._redact,
            )
        return payload

    def inspect_environment(
        self, *, include_entities: bool = True
    ) -> EnvironmentSnapshot:
        """Capture a read-only environment snapshot from the bridge."""
        game_status = self._get_json("/api/status")
        if not isinstance(game_status, dict):
            raise BridgeUnexpectedResponse(
                "/api/status returned non-object JSON",
                detail=repr(game_status)[:500],
                redactor=self._redact,
            )

        entity_metrics: dict[str, object] | None = None
        warnings: list[str] = []
        if include_entities:
            try:
                raw_entities = self._get_json("/api/entities")
                if isinstance(raw_entities, dict):
                    entity_metrics = raw_entities
                else:
                    warnings.append("/api/entities returned non-object JSON")
            except BridgeError as error:
                warnings.append(f"/api/entities unavailable: {error.kind}")

        return EnvironmentSnapshot(
            captured_at=datetime.now(UTC),
            endpoint=self._config.endpoint,
            bridge_probe={"adapter": self.name, "read_only": self.read_only},
            game_status=game_status,
            entity_metrics=entity_metrics,
            warnings=warnings,
        )

    # -- HTTP plumbing ------------------------------------------------------

    def _get_json(self, path: str, *, authenticated: bool = True) -> Any:
        body, status = self._request("GET", path, authenticated=authenticated)
        if status != 200:
            raise self._http_error(path, status, body)
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BridgeUnexpectedResponse(
                f"{path} returned non-JSON body",
                detail=f"{error}: {body[:200]!r}",
                redactor=self._redact,
            ) from error

    def _http_error(self, path: str, status: int, body: bytes) -> BridgeError:
        detail = body[:MAX_ERROR_BODY_BYTES].decode("utf-8", errors="replace")
        if status in (401, 403):
            return BridgeAuthFailed(
                f"{path} rejected the API key (HTTP {status})",
                detail=detail,
                redactor=self._redact,
            )
        return BridgeUnexpectedResponse(
            f"{path} returned HTTP {status}",
            detail=detail,
            redactor=self._redact,
        )

    def _request(
        self, method: str, path: str, *, authenticated: bool
    ) -> "tuple[bytes, int]":
        url = f"{self._config.endpoint}{path}"
        headers = {"Accept": "application/json"}
        if authenticated:
            headers["X-API-Key"] = self._config.api_key
        request = urllib.request.Request(url, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout_seconds) as response:
                return response.read(MAX_ERROR_BODY_BYTES), response.status
        except urllib.error.HTTPError as error:  # subclass of URLError; check first
            try:
                error_body = error.read(MAX_ERROR_BODY_BYTES)
            except OSError:
                error_body = b""
            return error_body, error.code
        except urllib.error.URLError as error:
            raise self._unreachable(path, error.reason) from error
        except (TimeoutError, socket.timeout) as error:
            raise self._unreachable(path, error) from error
        except (OSError, http.client.HTTPException) as error:
            raise self._unreachable(path, error) from error
        except Exception as error:
            raise BridgeUnexpectedResponse(
                f"{path} failed in an unexpected way",
                detail=repr(error),
                redactor=self._redact,
            ) from error

    def _unreachable(self, path: str, reason: object) -> BridgeUnreachable:
        text = repr(reason)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            label = "timeout"
        elif isinstance(reason, ConnectionRefusedError):
            label = "connection refused (is the game running with the bridge mod?)"
        else:
            label = "no route to host"
        return BridgeUnreachable(
            f"{path} unreachable: {label}",
            detail=text,
            redactor=self._redact,
        )

"""Configuration, error taxonomy, and evidence helpers for the game bridge.

The bridge is the in-game MCP/REST server exposed by the MCPServer Fabric mod.
This module holds everything about the bridge that is not HTTP mechanics:

- `BridgeConfig`: explicit, loopback-only endpoint configuration;
- `BridgeError` hierarchy: classified failures that never leak the API key;
- `EnvironmentSnapshot` persistence: append-only evidence files;
- `check_environment`: expectation checks for the P1 acceptance flow.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from .models import EnvironmentSnapshot


LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class BridgeConfigError(ValueError):
    pass


class BridgeError(RuntimeError):
    """Base class for bridge failures; messages never contain the API key."""

    kind = "bridge_error"

    def __init__(self, message: str, detail: str | None = None, redactor=None):
        self._redactor = redactor
        self.kind = type(self).kind
        self.detail = redactor(detail) if redactor and detail else detail
        super().__init__(message)


class BridgeUnreachable(BridgeError):
    kind = "unreachable"


class BridgeAuthFailed(BridgeError):
    kind = "auth_failed"


class BridgeUnexpectedResponse(BridgeError):
    kind = "unexpected_response"


class BridgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str
    api_key: str
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


def resolve_bridge_config(
    *,
    endpoint: str | None,
    api_key: str | None,
    api_key_file: Path | None = None,
    timeout_seconds: float = 5.0,
) -> BridgeConfig:
    """Build a bridge config from explicit arguments only.

    The endpoint is never guessed and the API key is never accepted from
    command-line arguments, only from the environment or a private file.
    """
    if not endpoint:
        raise BridgeConfigError(
            "bridge endpoint is required (for example http://127.0.0.1:8081)"
        )
    parts = urlsplit(endpoint)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise BridgeConfigError(f"endpoint must be an http(s) URL, got {endpoint!r}")
    if parts.hostname.lower() not in LOOPBACK_HOSTS:
        raise BridgeConfigError(
            "bridge endpoint must be a loopback address; refusing " f"{parts.hostname!r}"
        )
    normalized = f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"

    if not api_key and api_key_file is not None:
        api_key = api_key_file.read_text(encoding="utf-8").strip()
    if not api_key:
        raise BridgeConfigError(
            "bridge API key is required via environment variable or key file"
        )
    return BridgeConfig(
        endpoint=normalized,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )


def redact(text: str, api_key: str) -> str:
    if not api_key:
        return text
    return text.replace(api_key, "***")


def default_snapshot_path(workspace_root: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return workspace_root / "work" / "snapshots" / f"{stamp}-environment-snapshot.json"


def save_environment_snapshot(
    workspace_root: Path, snapshot: EnvironmentSnapshot, out_path: Path | None = None
) -> Path:
    """Write an environment snapshot as immutable evidence and return its path."""
    root = workspace_root.resolve()
    path = (out_path if out_path is not None else default_snapshot_path(root)).resolve()
    if root not in path.parents:
        raise BridgeConfigError("snapshot output must stay inside the workspace")
    if path.exists():
        raise BridgeConfigError(
            f"snapshot already exists, refusing to overwrite: {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(snapshot.model_dump_json(indent=2))
        stream.write("\n")
    return path


def _iter_strings(node: object) -> list[str]:
    found: list[str] = []
    if isinstance(node, str):
        found.append(node)
    elif isinstance(node, dict):
        for key, value in node.items():
            found.append(str(key))
            found.extend(_iter_strings(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_iter_strings(item))
    return found


def check_environment(
    snapshot: EnvironmentSnapshot,
    *,
    expect_world: str | None = None,
    expect_player: str | None = None,
) -> dict[str, object]:
    """Check P1 expectations against everything the bridge reported.

    The bridge payload schema is not pinned yet, so expectations are checked
    by recursive string search over the raw payloads instead of fixed fields.
    """
    haystack = _iter_strings(snapshot.game_status) + _iter_strings(
        snapshot.entity_metrics
    )
    checks: list[dict[str, object]] = []
    if expect_world:
        met = any(expect_world.lower() in value.lower() for value in haystack)
        checks.append({"expect_world": expect_world, "met": met})
    if expect_player:
        met = any(expect_player.lower() in value.lower() for value in haystack)
        checks.append({"expect_player": expect_player, "met": met})
    return {
        "ok": all(check["met"] for check in checks) if checks else True,
        "checks": checks,
    }

"""Controller→CinematicBridge client: transport, version gate, failure classes.

The bridge contract (contracts/v1 + contracts/v2, Java side in
``cinematic-bridge/``) is JSON over loopback HTTP with a bearer token. This
client never retries on its own and never logs or stores the token; retry
decisions belong to the controller's policy layer, and only after a write's
outcome has been resolved through a status query.

Contract rules (plan v2 §Phase A):
- contract 1 stays read-only here: live WRITES always go through ``call_v2``
  (schema_version 2); a contract-1 write attempt is refused client-side;
- v2 results REQUIRE the idempotency key in every reply (failure F1);
- unknown outcomes are resolved via ``operation_status`` / state reads —
  never by resending.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlparse

from pydantic import ValidationError

from .contracts import validate_against_contract_v2, validate_against_contract_v3
from .production_models import (
    CapabilitiesV2,
    CapabilitiesV3,
    ErrorClass,
    GameStateV2,
    MocapStateV2,
    OperationRequest,
    OperationRequestV2,
    OperationRequestV3,
    OperationResult,
    OperationResultV2,
    OperationResultV3,
    PINNED_VERSIONS,
    RuntimeVersions,
    TimelinePlan,
    CameraTrack,
)


class BridgeTransportError(RuntimeError):
    def __init__(self, kind: ErrorClass, message: str):
        self.kind = kind
        super().__init__(message)


@dataclass(frozen=True)
class CinematicBridgeConfig:
    endpoint: str
    token: str
    timeout_seconds: float = 5.0


def _require_loopback(endpoint: str) -> None:
    host = urlparse(endpoint).hostname
    if not host:
        raise BridgeTransportError(ErrorClass.VALIDATION_FAILED, f"endpoint has no host: {endpoint}")
    if host == "localhost":
        return
    try:
        address = ip_address(host)
    except ValueError as error:
        raise BridgeTransportError(
            ErrorClass.VALIDATION_FAILED, f"endpoint must be loopback, got host: {host}"
        ) from error
    if not address.is_loopback:
        raise BridgeTransportError(
            ErrorClass.VALIDATION_FAILED, "refusing non-loopback bridge endpoint"
        )


# Methods that change game or artifact state. Under contract 1 this client
# refuses them (read-only diagnostics only); contract 2 is the live surface.
CONTRACT1_WRITE_METHODS = frozenset(
    {
        "bridge.submit_timeline",
        "bridge.cancel_timeline",
        "mocap.start_recording",
        "mocap.stop_recording",
        "mocap.save_recording",
        "mocap.start_scene",
        "mocap.stop_scene",
        "flashback.start_recording",
        "flashback.stop_recording",
        "flashback.open_replay",
        "flashback.replace_camera_track",
        "flashback.set_export_range",
        "flashback.start_export",
        "flashback.cancel_export",
    }
)


class CinematicBridgeClient:
    """Thin, classified transport. Loopback-only by construction."""

    READ_ONLY_METHODS = frozenset(
        {
            "bridge.health",
            "bridge.capabilities",
            "bridge.get_runtime_versions",
            "bridge.get_game_state",
            "bridge.get_timeline_status",
            "bridge.get_operation_status",
            "actor.get_take_status",
            "actor.get_state",
            "world.get_block",
            "world.get_time",
            "world.get_weather",
            "world.count_entities",
            "mocap.get_status",
            "flashback.get_editor_state",
            "flashback.get_export_status",
            "replay.get_render_status",
            "replay.get_master_status",
            "replay.await_master_saved",
        }
    )

    def __init__(self, config: CinematicBridgeConfig, *, recording_root=None):
        _require_loopback(config.endpoint)
        self.endpoint = config.endpoint.rstrip("/")
        self.token = config.token
        self.timeout_seconds = config.timeout_seconds
        self.recording_root = recording_root
        self.name = "cinematic-bridge-http"

    # -- transport ------------------------------------------------------------

    def _post(self, payload: bytes) -> dict[str, object]:
        http_request = urllib.request.Request(
            self.endpoint + "/rpc",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise BridgeTransportError(
                    ErrorClass.AUTHENTICATION_FAILED,
                    f"bridge rejected credentials (HTTP {error.code})",
                ) from error
            raise BridgeTransportError(
                ErrorClass.OPERATION_REJECTED,
                f"bridge returned HTTP {error.code}",
            ) from error
        except urllib.error.URLError as error:
            raise BridgeTransportError(
                ErrorClass.BRIDGE_UNAVAILABLE, f"bridge unreachable: {error.reason}"
            ) from error
        except TimeoutError as error:
            raise BridgeTransportError(
                ErrorClass.BRIDGE_UNAVAILABLE, "bridge request timed out"
            ) from error
        except OSError as error:
            raise BridgeTransportError(
                ErrorClass.BRIDGE_UNAVAILABLE, f"bridge connection interrupted: {error}"
            ) from error

    # -- contract 1 (read-only diagnostics only) -------------------------------

    def call(self, request: OperationRequest) -> OperationResult:
        if request.method in CONTRACT1_WRITE_METHODS:
            raise BridgeTransportError(
                ErrorClass.VALIDATION_FAILED,
                f"{request.method} is a write; live writes require contract 2 (call_v2)",
            )
        return self._call_v1(request)

    def _call_v1(self, request: OperationRequest) -> OperationResult:
        payload = json.dumps(
            {"request": request.model_dump(mode="json", exclude_none=True)},
            ensure_ascii=False,
        ).encode("utf-8")
        body = self._post(payload)
        try:
            return OperationResult.model_validate(body)
        except ValidationError as error:
            raise BridgeTransportError(
                ErrorClass.BRIDGE_UNAVAILABLE,
                f"bridge reply failed contract-1 validation: {error}",
            ) from error

    # -- contract 2 (the live surface) ------------------------------------------

    def call_v2(self, request: OperationRequestV2) -> OperationResultV2:
        """Sends a contract-2 envelope; validates the reply against v2.

        A network-level timeout maps to UNKNOWN semantics on the caller side
        (the write may have landed) — the controller resolves it through
        ``operation_status``, never by resending.
        """

        validate_against_contract_v2(
            request.model_dump(mode="json", exclude_none=True), "operation-request"
        )
        payload = json.dumps(
            {"request": request.model_dump(mode="json", exclude_none=True)},
            ensure_ascii=False,
        ).encode("utf-8")
        write = request.method not in self.READ_ONLY_METHODS
        try:
            body = self._post(payload)
        except BridgeTransportError as error:
            if write and error.kind is ErrorClass.BRIDGE_UNAVAILABLE:
                raise BridgeTransportError(
                    ErrorClass.OPERATION_TIMEOUT_UNKNOWN,
                    f"no reply for v2 write {request.method}: {error}",
                ) from error
            raise
        try:
            result = OperationResultV2.model_validate(body)
        except ValidationError as error:
            raise BridgeTransportError(
                ErrorClass.BRIDGE_UNAVAILABLE,
                f"bridge reply failed contract-2 validation: {error}",
            ) from error
        validate_against_contract_v2(
            result.model_dump(mode="json", exclude_none=True), "operation-result"
        )
        if result.idempotency_key != request.idempotency_key:
            raise BridgeTransportError(
                ErrorClass.BRIDGE_UNAVAILABLE,
                "bridge reply idempotency_key does not match the request",
            )
        return result

    # -- convenience surface used by the controller --------------------------

    def handshake(self) -> RuntimeVersions:
        """BridgePort handshake: contract 2 only — the live client never
        downgrades the negotiation."""

        from datetime import UTC, datetime

        return self.handshake_v2("handshake-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))

    def handshake_v1_diagnostic(self) -> RuntimeVersions:
        """Contract-1 read-only diagnostic (migration aid, never for writes)."""

        from datetime import UTC, datetime
        from pathlib import Path as _Path

        request = OperationRequest(
            run_id="handshake-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
            operation_id="handshake",
            idempotency_key="handshake/" + _Path(self.endpoint).name,
            method="bridge.get_runtime_versions",
        )
        result = self._call_v1(request)
        if result.status != "applied":
            raise BridgeTransportError(
                result.error_class or ErrorClass.BRIDGE_UNAVAILABLE,
                result.message or "handshake failed",
            )
        return RuntimeVersions.model_validate(result.result)

    def handshake_v2(self, run_id: str) -> RuntimeVersions:
        request = self._v2_request(
            run_id, "handshake", "bridge.get_runtime_versions"
        )
        result = self._unwrap(self.call_v2(request))
        return RuntimeVersions.model_validate(result)

    def capabilities(self, run_id: str) -> CapabilitiesV2:
        request = self._v2_request(run_id, "capabilities", "bridge.capabilities")
        result = self._unwrap(self.call_v2(request))
        return CapabilitiesV2.model_validate(result)

    def game_state(self, run_id: str) -> GameStateV2:
        request = self._v2_request(run_id, "state", "bridge.get_game_state")
        result = self._unwrap(self.call_v2(request))
        return GameStateV2.model_validate(result)

    def mocap_status(self, run_id: str) -> MocapStateV2:
        request = self._v2_request(run_id, "mocap-status", "mocap.get_status")
        result = self._unwrap(self.call_v2(request))
        return MocapStateV2.model_validate(result)

    def mocap_transition(
        self, run_id: str, action: str, *, name: str | None = None
    ) -> OperationResultV2:
        method = f"mocap.{action}"
        params: dict[str, object] = {} if name is None else {"name": name}
        request = self._v2_request(run_id, f"mocap-{action}", method, params)
        return self.call_v2(request)

    def world_op(
        self,
        run_id: str,
        operation: str,
        label: str,
        params: dict[str, object],
        idempotency_key: str | None = None,
    ) -> OperationResultV2:
        request = self._v2_request(
            run_id, label, f"world.{operation}", params, idempotency_key=idempotency_key
        )
        return self.call_v2(request)

    def world_read(self, run_id: str, operation: str, label: str, params: dict[str, object]) -> dict[str, object]:
        request = self._v2_request(run_id, label, f"world.{operation}", params)
        return self._unwrap(self.call_v2(request))

    def operation_status(self, run_id: str, label: str, idempotency_key: str) -> OperationResultV2:
        request = self._v2_request(
            run_id, label, "bridge.get_operation_status",
            {"idempotency_key": idempotency_key},
            idempotency_key=idempotency_key,
        )
        return self.call_v2(request)

    # -- contract 3 (async world writes, persistent ledger) ----------------------

    def call_v3(self, request: OperationRequestV3) -> OperationResultV3:
        """Sends a contract-3 envelope; validates the reply against v3.

        A network-level timeout on a write maps to UNKNOWN semantics (the
        write may still be queued or executed later) — the controller resolves
        it through ``operation_status_v3``, never by resending.
        """

        validate_against_contract_v3(
            request.model_dump(mode="json", exclude_none=True), "operation-request"
        )
        payload = json.dumps(
            {"request": request.model_dump(mode="json", exclude_none=True)},
            ensure_ascii=False,
        ).encode("utf-8")
        write = request.method not in self.READ_ONLY_METHODS
        try:
            body = self._post(payload)
        except BridgeTransportError as error:
            if write and error.kind is ErrorClass.BRIDGE_UNAVAILABLE:
                raise BridgeTransportError(
                    ErrorClass.OPERATION_TIMEOUT_UNKNOWN,
                    f"no reply for v3 write {request.method}: {error}",
                ) from error
            raise
        try:
            result = OperationResultV3.model_validate(body)
        except ValidationError as error:
            raise BridgeTransportError(
                ErrorClass.BRIDGE_UNAVAILABLE,
                f"bridge reply failed contract-3 validation: {error}",
            ) from error
        validate_against_contract_v3(
            result.model_dump(mode="json", exclude_none=True), "operation-result"
        )
        if result.idempotency_key != request.idempotency_key:
            raise BridgeTransportError(
                ErrorClass.BRIDGE_UNAVAILABLE,
                "bridge reply idempotency_key does not match the request",
            )
        return result

    def capabilities_v3(self, run_id: str) -> CapabilitiesV3:
        result = self.call_v3(OperationRequestV3(run_id=run_id, operation_id="capabilities-v3",
            idempotency_key=f"{run_id}/capabilities-v3", method="bridge.capabilities", params={}))
        if result.status != "applied":
            raise BridgeTransportError(ErrorClass.ENVIRONMENT_MISMATCH, "v3 capabilities unavailable")
        return CapabilitiesV3.model_validate(result.result)

    @staticmethod
    def _operation_id_from_key(key: str) -> str:
        """operation_id has a narrower charset than idempotency_key."""
        import re

        return re.sub(r"[^A-Za-z0-9_.-]", "-", key)[:80] or "op"

    def submit_world_op_v3(
        self,
        run_id: str,
        operation: str,
        params: dict[str, object],
        *,
        idempotency_key: str,
        plan_hash: str | None = None,
    ) -> OperationResultV3:
        """Submits a world write under contract 3 and returns immediately.

        The caller's key travels unchanged: same key + same params replays the
        journaled outcome; same key + different params is a conflict.
        """

        request = OperationRequestV3(
            run_id=run_id,
            operation_id=self._operation_id_from_key(idempotency_key),
            idempotency_key=idempotency_key,
            plan_hash=plan_hash,
            method=f"world.{operation}",
            params=params,
        )
        return self.call_v3(request)

    def operation_status_v3(
        self, run_id: str, idempotency_key: str
    ) -> OperationResultV3:
        """Faithful status from the persistent ledger for one operation."""

        request = OperationRequestV3(
            run_id=run_id,
            operation_id=self._operation_id_from_key(idempotency_key + "-status"),
            idempotency_key=(idempotency_key + "-status")[:160],
            method="bridge.get_operation_status",
            params={"idempotency_key": idempotency_key},
        )
        return self.call_v3(request)

    def await_world_op_v3(
        self,
        run_id: str,
        idempotency_key: str,
        submitted: OperationResultV3,
        *,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.4,
        poll=...,  # type: ignore[assignment]
    ) -> OperationResultV3:
        """Polls a contract-3 write to a terminal answer.

        accepted/pending are intermediate; succeeded/failed/rejected/unknown
        are terminal for the caller (unknown is resolved further by the
        adapter through a typed state read, never by resending). ``poll`` is
        injectable for offline tests; production uses time.sleep.
        """

        import time as _time

        sleeper = _time.sleep if poll is ... or poll is None else poll
        deadline = _time.monotonic() + timeout_seconds
        result = submitted
        while result.status in ("accepted", "pending"):
            if _time.monotonic() >= deadline:
                return result  # caller decides; the bridge still finishes the job
            sleeper(poll_interval_seconds)
            result = self.operation_status_v3(run_id, idempotency_key)
        return result

    # -- BridgePort surface (Phase E) ------------------------------------------
    #
    # The controller hands these v1-shaped OperationRequests; the client
    # upgrades them to contract-2 envelopes itself — live writes NEVER ride
    # the contract-1 wire.

    def _as_v2(
        self, request: OperationRequest, method: str, params: dict[str, object] | None = None
    ) -> OperationRequestV2:
        return OperationRequestV2(
            run_id=request.run_id,
            operation_id=request.operation_id,
            idempotency_key=request.idempotency_key,
            plan_hash=request.plan_hash,
            method=method,
            params=params or {},
        )

    def submit_timeline(self, request: OperationRequest, timeline: TimelinePlan) -> OperationResultV2:
        return self.call_v2(self._as_v2(
            request, "bridge.submit_timeline",
            {"timeline": timeline.model_dump(mode="json", exclude_none=True)},
        ))

    def timeline_status(self, request: OperationRequest) -> OperationResultV2:
        return self.call_v2(self._as_v2(request, "bridge.get_timeline_status"))

    def await_replay_saved(self, request: OperationRequest, timeline_id: str) -> OperationResultV2:
        return self.call_v2(self._as_v2(
            request, "flashback.await_replay_saved", {"timeline_id": timeline_id}
        ))

    def replace_camera_track(
        self, request: OperationRequest, timeline_id: str, camera: CameraTrack
    ) -> OperationResultV2:
        return self.call_v2(self._as_v2(
            request,
            "flashback.replace_camera_track",
            {
                "timeline_id": timeline_id,
                "keyframes": [frame.model_dump(mode="json") for frame in camera.keyframes],
                "interpolation": camera.interpolation,
            },
        ))

    def start_export(
        self,
        request: OperationRequest,
        *,
        timeline_id: str,
        range_ticks: "tuple[int, int]",
        output_relative: str,
        width: int,
        height: int,
        fps: int,
    ) -> OperationResultV2:
        return self.call_v2(self._as_v2(
            request,
            "flashback.start_export",
            {
                "timeline_id": timeline_id,
                "range": {"start_tick": range_ticks[0], "end_tick": range_ticks[1]},
                "output_path": output_relative,
                "width": width,
                "height": height,
                "fps": fps,
            },
        ))

    def export_status(self, request: OperationRequest) -> OperationResultV2:
        return self.call_v2(self._as_v2(request, "flashback.get_export_status"))

    def mocap_prepare(self, request: OperationRequest) -> OperationResultV2:
        return self.call_v2(self._as_v2(request, "mocap.prepare_recording"))

    def mocap_confirm(self, request: OperationRequest) -> OperationResultV2:
        return self.call_v2(self._as_v2(request, "mocap.confirm_recording_start"))

    def mocap_stop(self, request: OperationRequest) -> OperationResultV2:
        return self.call_v2(self._as_v2(request, "mocap.stop_recording"))

    def mocap_save(self, request: OperationRequest, name: str) -> OperationResultV2:
        return self.call_v2(self._as_v2(request, "mocap.save_recording", {"name": name}))

    def mocap_status(self, request: OperationRequest | None = None) -> OperationResultV2:
        if request is None:
            return self.call_v2(self._v2_request("diagnostic", "mocap-status", "mocap.get_status"))
        return self.call_v2(self._as_v2(request, "mocap.get_status"))

    def mocap_state(self, run_id: str) -> MocapStateV2:
        """Typed recorder-state read (diagnostics and the live adapter)."""

        result = self.call_v2(self._v2_request(run_id, "mocap-status", "mocap.get_status"))
        return MocapStateV2.model_validate(self._unwrap(result))

    def recording_path(self, name: str):
        """Artifact path for save proof; None when no instance root was given
        (the controller then fails the save stage instead of skipping proof)."""

        if self.recording_root is None:
            return None
        from pathlib import Path

        return Path(self.recording_root) / f"{name}.mcmocap_rec"

    # -- helpers ----------------------------------------------------------------

    def _v2_request(
        self,
        run_id: str,
        label: str,
        method: str,
        params: dict[str, object] | None = None,
        idempotency_key: str | None = None,
    ) -> OperationRequestV2:
        # Key passthrough (v3 §2): when the caller supplies a key it travels
        # unchanged end to end; only label-based convenience calls get a
        # generated one. A generated key here must never silently replace a
        # submitted operation's identity.
        return OperationRequestV2(
            run_id=run_id,
            operation_id=f"{run_id}-{label}"[:80],
            idempotency_key=idempotency_key if idempotency_key is not None else f"{run_id}/{label}",
            method=method,
            params=params or {},
        )

    @staticmethod
    def _unwrap(result: OperationResultV2) -> dict[str, object]:
        if result.status not in ("applied", "observed"):
            raise BridgeTransportError(
                result.error_class or ErrorClass.BRIDGE_UNAVAILABLE,
                result.message or f"bridge returned {result.status}",
            )
        return result.result


def version_mismatches(versions: RuntimeVersions) -> list[str]:
    """Exact-pin gate (architecture spec §6): near-misses are mismatches."""

    issues: list[str] = []
    actual = versions.model_dump()
    for field, expected in PINNED_VERSIONS.items():
        if actual.get(field) != expected:
            issues.append(f"{field}: expected {expected!r}, bridge reports {actual.get(field)!r}")
    if versions.contract != 1:
        issues.append(f"contract: expected 1, bridge reports {versions.contract}")
    return issues


def version_mismatches_v2(versions: RuntimeVersions) -> list[str]:
    """Live gate: same exact pins, but contract must be 2."""

    issues: list[str] = []
    actual = versions.model_dump()
    for field, expected in PINNED_VERSIONS.items():
        if actual.get(field) != expected:
            issues.append(f"{field}: expected {expected!r}, bridge reports {actual.get(field)!r}")
    if versions.contract != 2:
        issues.append(f"contract: expected 2 for live writes, bridge reports {versions.contract}")
    return issues


def runtime_check(client: CinematicBridgeClient) -> dict[str, object]:
    """Live read-only gate check (plan P6 gates 1–3): handshake, versions,
    capabilities, game state. Writes nothing; any version drift is reported,
    never 'worked around'. Prefers contract 2; falls back to contract-1
    diagnostics if the bridge does not answer v2 yet."""

    try:
        versions = client.handshake_v2("bridge-check")
        contract = 2
    except BridgeTransportError:
        versions = client.handshake_v1_diagnostic()
        contract = 1
    mismatches = (
        version_mismatches_v2(versions) if contract == 2 else version_mismatches(versions)
    )
    capabilities: dict[str, object] | None = None
    game_state: dict[str, object] | None = None
    if not mismatches:
        if contract == 2:
            capabilities = client.capabilities("bridge-check").model_dump(mode="json")
            game_state = client.game_state("bridge-check").model_dump(mode="json")
        else:
            capabilities_result = client.call(
                OperationRequest(
                    run_id="bridge-check",
                    operation_id="bridge-check-capabilities",
                    idempotency_key="bridge-check/capabilities",
                    method="bridge.capabilities",
                )
            )
            capabilities = capabilities_result.result
            state_result = client.call(
                OperationRequest(
                    run_id="bridge-check",
                    operation_id="bridge-check-state",
                    idempotency_key="bridge-check/state",
                    method="bridge.get_game_state",
                )
            )
            game_state = state_result.result
    return {
        "ok": not mismatches,
        "contract": contract,
        "versions": versions.model_dump(),
        "mismatches": mismatches,
        "capabilities": capabilities,
        "game_state": game_state,
    }

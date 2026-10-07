"""Live-mode controller behavior (plan v2 §Phases C/E): capability preflight
before ANY write, flashback stages skipped with a truthful scope label, and
the Mocap checkpoints running against a contract-v2-style bridge surface.

No game process is involved: the fake bridge implements the same BridgePort
surface as ``CinematicBridgeClient`` with v2-shaped results.
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from minecraft_film_agent.adapters.mock import MockMinecraftAdapter
from minecraft_film_agent.production import ProductionController, StageFailure
from minecraft_film_agent.production_models import (
    CapabilitiesV2,
    ErrorClass,
    GameStateV2,
    MocapPhase,
    OperationRequest,
    ProductionPlan,
    RuntimeVersions,
    SessionPhase,
    StageName,
    StageStatus,
    TimelinePlan,
)
from minecraft_film_agent.store import ProductionStore


class FakeLiveMinecraft(MockMinecraftAdapter):
    """Status surface shaped like the real LiveMinecraftAdapter's."""

    name = "cinematic-bridge-live-fake"
    dry_run = False

    def get_status(self) -> dict[str, object]:
        return GameStateV2(
            session_phase=SessionPhase.IN_WORLD,
            save_name="Marx Video Test",
            dimension="minecraft:overworld",
            player_name="CineProbe",
            paused=False,
            client_tick=1000,
            blocking_screen=False,
        ).model_dump(mode="json")


class FakeLiveBridge:
    """BridgePort-shaped fake for live mode (flashback license-gated off)."""

    name = "cinematic-bridge-live-fake"

    def __init__(self, workspace_root: Path):
        self.recordings_dir = workspace_root / "work" / "live-sim" / "recordings"
        self.versions = RuntimeVersions(
            minecraft="1.21.1", fabric_loader="0.19.3", flashback="0.39.8",
            mocap="1.3.10", bridge="0.2.0", contract=2,
        )
        self.phase = MocapPhase.IDLE
        self.executed: list[str] = []
        self.calls: list[str] = []

    def handshake(self):
        return self.versions.model_copy()

    def capabilities(self, run_id: str):
        return CapabilitiesV2(
            contract=2, minecraft="1.21.1", fabric_loader="0.19.3",
            flashback="0.39.8", mocap="1.3.10", bridge="0.2.0",
            typed_world_ops=True, world_reads=True, mocap_state_machine=True,
            tick_scheduler=True, flashback_automation=False,
            flashback_disabled_reason="license review pending",
        )

    def submit_timeline(self, request: OperationRequest, timeline: TimelinePlan):
        self.calls.append(request.idempotency_key)
        return _v2_result(request, "applied", {"timeline_id": timeline.timeline_id})

    def timeline_status(self, request: OperationRequest):
        return _v2_result(request, "applied", {"state": "COMPLETED"})

    def await_replay_saved(self, request: OperationRequest, timeline_id: str):
        return _v2_result(request, "failed", {}, error_class=ErrorClass.REPLAY_NOT_CREATED,
                          message="flashback automation is disabled")

    def replace_camera_track(self, request, timeline_id, camera):
        return _v2_result(request, "rejected", {}, error_class=ErrorClass.MANUAL_INTERVENTION_REQUIRED)

    def start_export(self, request, **kwargs):
        return _v2_result(request, "rejected", {}, error_class=ErrorClass.MANUAL_INTERVENTION_REQUIRED)

    def export_status(self, request):
        return _v2_result(request, "applied", {})

    # -- mocap two-step machine ------------------------------------------------

    def mocap_prepare(self, request: OperationRequest):
        if self.phase is MocapPhase.IDLE:
            self.phase = MocapPhase.WAITING_FOR_SELECTION
            return _v2_result(request, "applied", {"state": MocapPhase.WAITING_FOR_SELECTION.value})
        return _v2_result(request, "rejected", {},
                          error_class=ErrorClass.OPERATION_REJECTED,
                          message=f"recorder is {self.phase.value}")

    def mocap_confirm(self, request: OperationRequest):
        if self.phase is MocapPhase.WAITING_FOR_SELECTION:
            self.phase = MocapPhase.RECORDING
            return _v2_result(request, "applied", {"state": MocapPhase.RECORDING.value})
        return _v2_result(request, "rejected", {},
                          error_class=ErrorClass.OPERATION_REJECTED,
                          message="confirm requires waiting_for_selection")

    def mocap_stop(self, request: OperationRequest):
        if self.phase is MocapPhase.RECORDING:
            self.phase = MocapPhase.RECORDED_UNSAVED
            return _v2_result(request, "applied", {"state": MocapPhase.RECORDED_UNSAVED.value})
        return _v2_result(request, "rejected", {}, error_class=ErrorClass.OPERATION_REJECTED)

    def mocap_save(self, request: OperationRequest, name: str):
        if self.phase is not MocapPhase.RECORDED_UNSAVED:
            return _v2_result(request, "rejected", {},
                              error_class=ErrorClass.OPERATION_REJECTED,
                              message="save requires recorded_unsaved")
        target = self.recording_path(name)
        if target.exists():
            return _v2_result(request, "rejected", {},
                              error_class=ErrorClass.OPERATION_REJECTED,
                              message="recording exists; never overwrite")
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"LIVE-SIM-MOCAP")
        self.phase = MocapPhase.SAVED
        return _v2_result(request, "applied", {"state": MocapPhase.SAVED.value,
                                               "recording_name": name})

    def mocap_status(self, request: OperationRequest):
        return _v2_result(request, "applied", {"state": self.phase.value})

    def recording_path(self, name: str):
        return self.recordings_dir / f"{name}.mcmocap_rec"


def _v2_result(request, status, result, error_class=None, message=None):
    from minecraft_film_agent.production_models import OperationResultV2

    return OperationResultV2(
        operation_id=request.operation_id,
        idempotency_key=request.idempotency_key,
        status=status,
        journal_state="observed" if status in ("applied", "failed") else "rejected",
        error_class=error_class,
        message=message,
        result=result,
    )


LIVE_CAPABILITIES = dict(
    contract=2, minecraft="1.21.1", fabric_loader="0.19.3",
    flashback="0.39.8", mocap="1.3.10", bridge="0.2.0",
    typed_world_ops=True, world_reads=True, mocap_state_machine=True,
    tick_scheduler=True, flashback_automation=False,
    flashback_disabled_reason="license review pending",
)


def mocap_only_plan() -> dict:
    return {
        "schema_version": 1,
        "production_id": "live-mocap-001",
        "minecraft_version": "1.21.1",
        "fabric_loader": "0.19.3",
        "target": {"width": 1280, "height": 720, "fps": 30, "codec": "h264"},
        "scenes": [
            {
                "scene_id": "take",
                "world_ref": "Marx Video Test",
                "shots": [
                    {
                        "shot_id": "S01",
                        "scene_id": "take",
                        "duration_ticks": 60,
                        "recording": {"pre_roll_ticks": 10, "post_roll_ticks": 10},
                    }
                ],
            }
        ],
    }


def build_live_controller(tmp_path: Path, production_payload: dict, **capability_overrides):
    capabilities = CapabilitiesV2.model_validate({**LIVE_CAPABILITIES, **capability_overrides})
    minecraft = FakeLiveMinecraft()
    bridge = FakeLiveBridge(tmp_path)
    controller = ProductionController(
        tmp_path,
        ProductionStore(tmp_path),
        minecraft=minecraft,
        bridge=bridge,
        mode="live",
        capabilities=capabilities,
        expected_world="Marx Video Test",
        expected_player="CineProbe",
        instance_root=tmp_path,
    )
    preview = controller.preview(ProductionPlan.model_validate(production_payload))
    return controller, bridge, minecraft, preview


def test_interrupted_live_stage_is_not_replayed(tmp_path):
    controller, bridge, minecraft, preview = build_live_controller(tmp_path, mocap_only_plan())
    run_id = controller.commit(preview, "alice", "interrupted-live")
    original = controller._run_stage
    calls = []
    def crash(run_id, stage, production):
        calls.append(stage)
        raise KeyboardInterrupt("process interrupted after write submission")
    controller._run_stage = crash
    with pytest.raises(KeyboardInterrupt):
        controller.execute(run_id)
    from minecraft_film_agent.locking import RunLease
    with RunLease(controller._run_dir(run_id) / "execution.lock"):
        pass  # A persistent lease file is harmless; the OS lock was released.
    controller._run_stage = original
    result = controller.execute(run_id)
    assert not result["ok"]
    assert result["error_class"] == ErrorClass.OPERATION_TIMEOUT_UNKNOWN.value
    assert calls == [StageName.VALIDATE_PLAN]
    assert bridge.calls == []


def test_live_mocap_only_chain_skips_flashback_stages(tmp_path: Path) -> None:
    controller, bridge, minecraft, preview = build_live_controller(tmp_path, mocap_only_plan())
    assert preview.ready, preview.issues
    run_id = controller.commit(preview, "alice", "live-mocap-run")
    result = controller.execute(run_id)
    assert result["ok"], result
    assert result["scope"] == "live-mocap"

    records = {r.stage.value: r for r in controller.store.stages(run_id)}
    for stage in ("prepare_recording", "start_recording", "run_timeline",
                  "stop_recording", "save_mocap"):
        assert records[stage].status is StageStatus.SUCCEEDED, stage
    for stage in ("await_replay", "apply_camera", "export_shot", "inspect_media"):
        assert records[stage].status is StageStatus.SKIPPED, stage

    # artifact proof: the take landed as a file with its hash recorded
    evidence = records["save_mocap"].evidence
    assert evidence["S01"]["sha256"].startswith("sha256:")
    assert evidence["S01"]["bytes"] == len(b"LIVE-SIM-MOCAP")

    # the timeline never asks the disabled flashback port for anything
    assert not any(key.startswith("live-mocap-run/replay-") for key in bridge.calls)


def test_live_flashback_required_plan_rejected_before_writes(tmp_path: Path) -> None:
    payload = mocap_only_plan()
    payload["scenes"][0]["shots"][0]["camera_ref"] = "S01C01-v1"
    camera_dir = tmp_path / "assets" / "cameras"
    camera_dir.mkdir(parents=True)
    (camera_dir / "S01C01-v1.json").write_text(json.dumps({
        "schema_version": 1,
        "camera_track_id": "S01C01-v1",
        "shot_id": "S01",
        "coordinate_space": "world",
        "interpolation": "smooth",
        "keyframes": [
            {"tick": 10, "position": [1.0, 65.0, 1.0], "yaw": 0.0, "pitch": 0.0, "roll": 0.0, "fov": 60.0},
            {"tick": 70, "position": [2.0, 65.0, 2.0], "yaw": 10.0, "pitch": 0.0, "roll": 0.0, "fov": 60.0},
        ],
    }), encoding="utf-8")

    controller, bridge, minecraft, preview = build_live_controller(tmp_path, payload)
    run_id = controller.commit(preview, "alice", "live-flashback-plan")
    result = controller.execute(run_id)
    assert not result["ok"]
    assert result["stage"] == "prepare_scene"
    assert result["error_class"] == "manual_intervention_required"
    # NO world write happened: the refusal precedes the first write
    assert minecraft.executed == []


def test_live_missing_capability_blocks_mocap_only_plan(tmp_path: Path) -> None:
    controller, _, _, preview = build_live_controller(
        tmp_path, mocap_only_plan(), mocap_state_machine=False
    )
    run_id = controller.commit(preview, "alice", "live-missing-cap")
    result = controller.execute(run_id)
    assert not result["ok"]
    assert result["error_class"] == "environment_mismatch"
    assert "mocap_state_machine" in result["message"]


def test_live_version_drift_fails_closed_at_first_bridge_stage(tmp_path: Path) -> None:
    controller, bridge, _, preview = build_live_controller(tmp_path, mocap_only_plan())
    bridge.versions = bridge.versions.model_copy(update={"mocap": "1.3.9"})
    run_id = controller.commit(preview, "alice", "live-drift")
    result = controller.execute(run_id)
    assert not result["ok"]
    assert result["stage"] == "prepare_recording"
    assert result["error_class"] == "environment_mismatch"
    assert "1.3.9" in result["message"]


def test_simulation_chain_still_runs_full_flashback_path(tmp_path: Path) -> None:
    """The split must not silently degrade the offline simulation chain."""

    from minecraft_film_agent.adapters.cinema_mock import MockCinemaBridge
    from minecraft_film_agent.actions import ActionRegistry

    payload = mocap_only_plan()
    minecraft = MockMinecraftAdapter()
    bridge = MockCinemaBridge(tmp_path)
    controller = ProductionController(
        tmp_path,
        ProductionStore(tmp_path),
        minecraft=minecraft,
        bridge=bridge,
        registry=ActionRegistry(tmp_path),
    )
    preview = controller.preview(ProductionPlan.model_validate(payload))
    run_id = controller.commit(preview, "alice", "sim-mocap-run")
    result = controller.execute(run_id)
    assert result["ok"], result
    assert result["scope"] == "simulation"
    records = {r.stage.value: r for r in controller.store.stages(run_id)}
    for stage in ("prepare_recording", "start_recording", "run_timeline",
                  "stop_recording", "save_mocap", "await_replay"):
        assert records[stage].status is StageStatus.SUCCEEDED, stage

"""Whole-film production chain, simulated end to end (plan P1 acceptance).

Covers: full success chain, idempotent resubmission, export-only retry,
media-failure re-export on a new version, restart recovery without duplicate
world writes, the fail-closed Flashback version gate, world mismatch,
unknown-outcome resolution through a status read, and asset blocking with a
human checklist.
"""

from __future__ import annotations

import json
from pathlib import Path

from minecraft_film_agent.actions import ActionRegistry
from minecraft_film_agent.adapters.cinema_mock import MockCinemaBridge
from minecraft_film_agent.adapters.mock import MockMinecraftAdapter
from minecraft_film_agent.production import PlanPreview, ProductionController, StageFailure
from minecraft_film_agent.production_models import (
    ErrorClass,
    ProductionPlan,
    RuntimeVersions,
    StageName,
    StageStatus,
)
from minecraft_film_agent.store import ProductionStore
from minecraft_film_agent.video import probe_video


def build_workspace(tmp_path: Path) -> dict:
    action_dir = tmp_path / "assets" / "actions" / "worker-look-up-v1"
    action_dir.mkdir(parents=True)
    (action_dir / "source.mcmocap_rec").write_bytes(b"SIM-RECORDING")
    (action_dir / "action.json").write_text(
        json.dumps(
            {
                "recording_id": "worker-look-up-v1",
                "title": "worker looks up",
                "source_file": "assets/actions/worker-look-up-v1/source.mcmocap_rec",
                "duration_ticks": 60,
                "start_pose": "standing",
                "end_pose": "standing",
                "translation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "source": "human_recorded",
                "verified": True,
            }
        ),
        encoding="utf-8",
    )

    blueprint = {
        "schema_version": 1,
        "plan_id": "site-v1",
        "title": "Construction site platform",
        "world_name": "Marx Video Test",
        "objective": "Build the incident platform for scene 1",
        "build_region": {
            "start": {"x": 0, "y": 60, "z": 0},
            "end": {"x": 16, "y": 72, "z": 16},
        },
        "actions": [
            {"type": "set_time", "value": 6000},
            {
                "type": "fill",
                "start": {"x": 0, "y": 60, "z": 0},
                "end": {"x": 8, "y": 60, "z": 8},
                "block": "minecraft:stone",
                "placement": "keep",
            },
        ],
    }
    (tmp_path / "assets" / "blueprints").mkdir(parents=True)
    (tmp_path / "assets" / "blueprints" / "site-v1.json").write_text(
        json.dumps(blueprint), encoding="utf-8"
    )

    camera = {
        "schema_version": 1,
        "camera_track_id": "S01C01-v1",
        "shot_id": "S01C01",
        "coordinate_space": "world",
        "interpolation": "smooth",
        "keyframes": [
            {
                "tick": 10,
                "position": [110.0, 69.0, 118.0],
                "yaw": 142.0,
                "pitch": -14.0,
                "roll": 0.0,
                "fov": 55.0,
            },
            {
                "tick": 150,
                "position": [108.0, 68.5, 116.0],
                "yaw": 150.0,
                "pitch": -12.0,
                "roll": 0.0,
                "fov": 48.0,
            },
        ],
    }
    (tmp_path / "assets" / "cameras").mkdir(parents=True)
    (tmp_path / "assets" / "cameras" / "S01C01-v1.json").write_text(
        json.dumps(camera), encoding="utf-8"
    )

    return {
        "schema_version": 1,
        "production_id": "chain-test-001",
        "minecraft_version": "1.21.1",
        "fabric_loader": "0.19.3",
        "target": {"width": 1280, "height": 720, "fps": 30, "codec": "h264"},
        "scenes": [
            {
                "scene_id": "site",
                "world_ref": "Marx Video Test",
                "blueprint_ref": "assets/blueprints/site-v1.json",
                "shots": [
                    {
                        "shot_id": "S01C01",
                        "scene_id": "site",
                        "duration_ticks": 100,
                        "actors": [
                            {
                                "actor_id": "worker",
                                "action_ref": "worker-look-up-v1",
                                "start_tick": 10,
                                "position": [2, 0, -1],
                                "yaw": 90.0,
                            }
                        ],
                        "camera_ref": "S01C01-v1",
                        "recording": {"pre_roll_ticks": 20, "post_roll_ticks": 20},
                    }
                ],
            }
        ],
    }


def make_controller(
    tmp_path: Path,
    *,
    bridge: MockCinemaBridge | None = None,
    with_registry: bool = True,
    production_payload: dict | None = None,
) -> "tuple[ProductionController, MockCinemaBridge, MockMinecraftAdapter]":
    minecraft = MockMinecraftAdapter()
    bridge = bridge or MockCinemaBridge(tmp_path)
    registry = ActionRegistry(tmp_path) if with_registry else None
    controller = ProductionController(
        tmp_path,
        ProductionStore(tmp_path),
        minecraft=minecraft,
        bridge=bridge,
        registry=registry,
    )
    return controller, bridge, minecraft


def committed_run(tmp_path: Path, **kwargs) -> "tuple[ProductionController, str, dict]":
    payload = kwargs.get("production_payload") or build_workspace(tmp_path)
    controller, bridge, minecraft = make_controller(tmp_path, **{
        key: value for key, value in kwargs.items() if key != "production_payload"
    })
    preview = controller.preview(ProductionPlan.model_validate(payload))
    run_id = controller.commit(preview, "alice", "run-chain-001")
    return controller, run_id, payload


def stage_records(controller: ProductionController, run_id: str) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for record in controller.store.stages(run_id):
        grouped.setdefault(record.stage.value, []).append(record)
    return grouped


# -- the happy chain ---------------------------------------------------------

def test_full_success_chain(tmp_path: Path) -> None:
    controller, run_id, _ = committed_run(tmp_path)
    result = controller.execute(run_id)
    assert result["ok"], result

    output = tmp_path / "assets" / "renders" / "S01C01-v1.mp4"
    assert output.is_file() and output.stat().st_size > 0
    probe = probe_video(output)
    assert any(track.fourcc == "avc1" for track in probe.tracks)
    assert (probe.tracks[0].width, probe.tracks[0].height) == (1280, 720)

    records = stage_records(controller, run_id)
    assert set(records) == {stage.value for stage in StageName}
    for stage, entries in records.items():
        assert entries[-1].status is StageStatus.SUCCEEDED, stage


def test_camera_track_reached_bridge(tmp_path: Path) -> None:
    payload = build_workspace(tmp_path)
    controller, bridge, _ = make_controller(tmp_path)
    preview = controller.preview(ProductionPlan.model_validate(payload))
    run_id = controller.commit(preview, "alice", "run-camera-001")
    assert controller.execute(run_id)["ok"]
    camera = bridge.camera_for("S01C01-take-001")
    assert camera is not None and len(camera.keyframes) == 2


def test_duplicate_plan_submission_is_idempotent(tmp_path: Path) -> None:
    controller, run_id, payload = committed_run(tmp_path)
    assert controller.execute(run_id)["ok"]
    minecraft = controller.minecraft
    world_writes_after_first = len(minecraft.executed)

    preview_again = controller.preview(ProductionPlan.model_validate(payload))
    same_run = controller.commit(preview_again, "bob", "run-chain-002")
    assert same_run == run_id

    result = controller.execute(run_id)
    assert result["ok"]
    assert all(entry["status"] == "skipped" for entry in result["stages"].values())
    assert len(minecraft.executed) == world_writes_after_first


# -- failure and recovery ----------------------------------------------------

def test_export_failure_retries_only_the_export_node(tmp_path: Path) -> None:
    bridge = MockCinemaBridge(tmp_path, fail_export=True)
    controller, run_id, _ = committed_run(tmp_path, bridge=bridge)
    minecraft = controller.minecraft

    result = controller.execute(run_id)
    assert not result["ok"]
    assert result["stage"] == "export_shot"
    assert result["error_class"] == "export_failed"
    writes_after_failure = len(minecraft.executed)

    bridge.fail_export = False
    retry = controller.execute(run_id)
    assert retry["ok"], retry

    exports = stage_records(controller, run_id)["export_shot"]
    records = stage_records(controller, run_id)
    assert [r.status for r in exports] == [StageStatus.FAILED, StageStatus.SUCCEEDED]
    # replay/recording was never re-recorded: each checkpoint ran exactly once
    assert len(records["save_mocap"]) == 1
    assert len(records["run_timeline"]) == 1
    assert len(minecraft.executed) == writes_after_failure  # world untouched

    output = tmp_path / "assets" / "renders" / "S01C01-v1.mp4"
    assert output.is_file()  # failed attempt never wrote; v1 is still free


def test_media_failure_reexports_to_a_new_version(tmp_path: Path) -> None:
    class CorruptExportBridge(MockCinemaBridge):
        corrupt = True

        def start_export(self, request, **kwargs):
            result = super().start_export(request, **kwargs)
            if result.status == "applied" and self.corrupt:
                self.render_path(kwargs["output_relative"]).write_bytes(b"JUNK-NOT-AN-MP4")
            return result

    bridge = CorruptExportBridge(tmp_path)
    controller, run_id, _ = committed_run(tmp_path, bridge=bridge)
    first = controller.execute(run_id)
    assert not first["ok"]
    assert first["stage"] == "inspect_media"
    assert first["error_class"] == "media_validation_failed"
    assert (tmp_path / "assets" / "renders" / "S01C01-v1.mp4").read_bytes() == b"JUNK-NOT-AN-MP4"

    bridge.corrupt = False
    second = controller.execute(run_id)
    assert second["ok"], second

    output = tmp_path / "assets" / "renders" / "S01C01-v2.mp4"
    assert output.is_file(), "re-export must land on a fresh version, never overwrite v1"
    assert (tmp_path / "assets" / "renders" / "S01C01-v1.mp4").read_bytes() == b"JUNK-NOT-AN-MP4"
    records = stage_records(controller, run_id)
    assert len(records["save_mocap"]) == 1
    assert [r.status for r in records["export_shot"]] == [StageStatus.SUCCEEDED, StageStatus.SUCCEEDED]


def test_restart_recovery_replays_nothing(tmp_path: Path) -> None:
    controller, run_id, _ = committed_run(tmp_path)
    assert controller.execute(run_id)["ok"]
    writes_before = len(controller.minecraft.executed)

    # A fresh controller over the same workspace: the process "restarted".
    restarted = ProductionController(
        tmp_path,
        ProductionStore(tmp_path),
        minecraft=controller.minecraft,
        bridge=controller.bridge,
        registry=ActionRegistry(tmp_path),
    )
    result = restarted.execute(run_id)
    assert result["ok"]
    assert all(entry["status"] == "skipped" for entry in result["stages"].values())
    assert len(controller.minecraft.executed) == writes_before


def test_version_gate_fails_closed(tmp_path: Path) -> None:
    drifting = RuntimeVersions(
        minecraft="1.21.1",
        fabric_loader="0.19.3",
        flashback="0.39.9",
        mocap="1.3.10",
        bridge="0.1.0-sim",
        contract=1,
    )
    bridge = MockCinemaBridge(tmp_path, versions=drifting)
    controller, run_id, _ = committed_run(tmp_path, bridge=bridge)

    result = controller.execute(run_id)
    assert not result["ok"]
    assert result["stage"] == "prepare_recording"
    assert result["error_class"] == "environment_mismatch"
    assert "0.39.9" in result["message"]

    before = len(controller.store.stages(run_id))
    again = controller.execute(run_id)
    assert again["error_class"] == "environment_mismatch"
    assert len(controller.store.stages(run_id)) == before  # no attempts burned


def test_world_mismatch_halts_recording(tmp_path: Path) -> None:
    bridge = MockCinemaBridge(tmp_path, expected_world="Some Other World")
    controller, run_id, _ = committed_run(tmp_path, bridge=bridge)
    result = controller.execute(run_id)
    assert not result["ok"]
    assert result["error_class"] == "world_mismatch"
    assert result["stage"] == "run_timeline"


def test_unknown_outcome_resolved_by_status_read(tmp_path: Path) -> None:
    bridge = MockCinemaBridge(tmp_path, lose_first_response={"run-chain-001/record-S01C01"})
    controller, run_id, _ = committed_run(tmp_path, bridge=bridge)
    result = controller.execute(run_id)
    assert result["ok"], result  # unknown → status read → applied, no resend
    assert (tmp_path / "work" / "cinema-sim" / "replays" / "S01C01-take-001.flashback_replay").is_file()


# -- preview-level rejections --------------------------------------------------

def test_missing_asset_blocks_commit_with_checklist(tmp_path: Path) -> None:
    payload = build_workspace(tmp_path)
    # The registry is live but the catalog entry is gone: improvising is forbidden.
    (tmp_path / "assets" / "actions" / "worker-look-up-v1" / "action.json").unlink()
    controller, _, _ = make_controller(tmp_path)
    preview = controller.preview(ProductionPlan.model_validate(payload))
    assert not preview.ready
    assert preview.asset_missing == ["worker-look-up-v1"]
    try:
        controller.commit(preview, "alice", "run-missing-001")
        raise AssertionError("commit must fail on missing assets")
    except StageFailure as failure:
        assert failure.error_class is ErrorClass.ASSET_MISSING


def test_invalid_timeline_blocks_preview(tmp_path: Path) -> None:
    payload = build_workspace(tmp_path)
    payload["scenes"][0]["shots"][0]["duration_ticks"] = 23900
    payload["scenes"][0]["shots"][0]["recording"] = {"pre_roll_ticks": 600, "post_roll_ticks": 600}
    controller, _, _ = make_controller(tmp_path)
    preview = controller.preview(ProductionPlan.model_validate(payload))
    assert not preview.ready
    assert preview.issues


def test_camera_outside_recording_window_blocks_preview(tmp_path: Path) -> None:
    payload = build_workspace(tmp_path)
    camera_path = tmp_path / "assets" / "cameras" / "S01C01-v1.json"
    camera = json.loads(camera_path.read_text(encoding="utf-8"))
    camera["keyframes"][0]["tick"] = 30  # after the 20-tick pre-roll opens
    camera_path.write_text(json.dumps(camera), encoding="utf-8")
    controller, _, _ = make_controller(tmp_path)
    preview = controller.preview(ProductionPlan.model_validate(payload))
    assert not preview.ready
    assert any("camera" in issue for issue in preview.issues)


def test_blueprint_outside_region_blocks_preview(tmp_path: Path) -> None:
    payload = build_workspace(tmp_path)
    blueprint_path = tmp_path / "assets" / "blueprints" / "site-v1.json"
    blueprint = json.loads(blueprint_path.read_text(encoding="utf-8"))
    blueprint["actions"][1]["end"] = {"x": 8, "y": 60, "z": 40}  # outside build_region
    blueprint_path.write_text(json.dumps(blueprint), encoding="utf-8")
    controller, _, _ = make_controller(tmp_path)
    preview = controller.preview(ProductionPlan.model_validate(payload))
    assert not preview.ready
    assert any("build_region" in issue for issue in preview.issues)

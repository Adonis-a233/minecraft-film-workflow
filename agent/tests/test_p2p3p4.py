"""P2/P3/P4 offline surfaces: schematics, asset registry, dual-view masters,
deterministic edit plans (workflow v3 §6/§7).

Everything here runs without a game and (mostly) without ffmpeg: the edit
plan is DATA — command generation is asserted exactly; only real renders
need the game, only real muxing needs ffmpeg.
"""

from __future__ import annotations

import gzip
import json
import struct
from pathlib import Path

import pytest

from minecraft_film_agent.assets import AssetRegistryError, load_registry, register_asset, verify_asset
from minecraft_film_agent.contracts import ContractError, load_schema, validate_against_contract_v3
from minecraft_film_agent.edit import EditPlanError, build_ffmpeg_plan, load_edit_list
from minecraft_film_agent.master_view import (
    MasterViewError,
    event_tick,
    load_master_view,
    render_requests,
)
from minecraft_film_agent.schematic import (
    SchematicError,
    TAG_BYTE_ARRAY,
    TAG_COMPOUND,
    TAG_INT,
    TAG_INT_ARRAY,
    TAG_SHORT,
    TAG_STRING,
    inspect_schematic,
    write_nbt_compound,
)


# -- P2: schematic pre-flight ------------------------------------------------------

def _write_schematic(path: Path, *, width: int, height: int, length: int,
                     palette: dict, blocks: list[int], data_version: int = 3953) -> None:
    """Builds a minimal Sponge-v2 .schem with the tags the inspector reads."""

    packed = bytearray()
    for index in blocks:
        while index >= 128:
            packed.append((index & 127) | 128)
            index >>= 7
        packed.append(index)
    palette_compound = {
        name: (TAG_INT, index) for name, index in palette.items()
    }
    payload = {
        "Version": (TAG_INT, 2),
        "DataVersion": (TAG_INT, data_version),
        "Width": (TAG_SHORT, width),
        "Height": (TAG_SHORT, height),
        "Length": (TAG_SHORT, length),
        "Palette": (TAG_COMPOUND, palette_compound),
        "BlockData": (TAG_BYTE_ARRAY, bytes(packed)),
    }
    nbt = write_nbt_compound("Schematic", payload)
    path.write_bytes(gzip.compress(nbt))


def test_valid_schematic_inspects(tmp_path: Path) -> None:
    target = tmp_path / "classroom.schem"
    palette = {"minecraft:air": 0, "minecraft:stone": 1, "minecraft:oak_planks": 2}
    # 2x1x2 volume: stone, air, planks, stone
    _write_schematic(target, width=2, height=1, length=2, palette=palette,
                     blocks=[1, 0, 2, 1])
    summary = inspect_schematic(target)
    assert (summary.width, summary.height, summary.length) == (2, 1, 2)
    assert summary.volume == 4
    assert summary.block_count == 3
    assert summary.air_count == 1
    assert summary.palette_size == 3
    assert summary.data_version == 3953
    assert "minecraft:oak_planks" in summary.palette


def test_blockdata_volume_mismatch_fails(tmp_path: Path) -> None:
    target = tmp_path / "bad.schem"
    palette = {"minecraft:air": 0, "minecraft:stone": 1}
    # volume 8 (2x2x2) but ZERO data bytes → genuinely short, not just padding
    _write_schematic(target, width=2, height=2, length=2, palette=palette,
                     blocks=[])
    with pytest.raises(SchematicError, match="decodes to only 0 entries"):
        inspect_schematic(target)


def test_non_schematic_root_fails(tmp_path: Path) -> None:
    target = tmp_path / "not-a-schem.schem"
    nbt = write_nbt_compound("SomethingElse", {"Version": (TAG_INT, 2)})
    target.write_bytes(gzip.compress(nbt))
    with pytest.raises(SchematicError, match="SomethingElse"):
        inspect_schematic(target)


def test_garbage_file_fails(tmp_path: Path) -> None:
    target = tmp_path / "garbage.schem"
    target.write_bytes(b"\x1f\x8b" + b"junk")
    with pytest.raises(SchematicError):
        inspect_schematic(target)


def test_missing_schematic_fails(tmp_path: Path) -> None:
    with pytest.raises(SchematicError, match="missing"):
        inspect_schematic(tmp_path / "absent.schem")


# -- P2: asset registry ------------------------------------------------------------


def _asset_record(tmp_path: Path, original: Path) -> dict:
    import hashlib

    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    return {
        "schema_version": 3,
        "asset_id": "classroom-v1",
        "kind": "schematic",
        "author": "some-builder",
        "source_url": "https://example.org/classroom",
        "license": {"id": "CC-BY-4.0", "attribution": "© some-builder, CC BY 4.0"},
        "source": {
            "path": str(original),
            "sha256": f"sha256:{digest}",
            "size_bytes": original.stat().st_size,
        },
        "data_version": 3953,
        "minecraft_versions": ["1.21.1"],
        "dependencies": [],
        "bbox": {"start": {"x": 0, "y": 0, "z": 0}, "end": {"x": 8, "y": 5, "z": 10}},
        "origin": {"x": 0, "y": -60, "z": 0},
        "landmarks": [{"name": "front-door", "position": {"x": 4, "y": -60, "z": 10}}],
        "import_method": "worldedit-schem",
        "notes": "test fixture",
    }


def test_register_verify_roundtrip(tmp_path: Path) -> None:
    original = tmp_path / "upload" / "classroom.schem"
    original.parent.mkdir(parents=True)
    _write_schematic(original, width=2, height=1, length=2,
                     palette={"minecraft:air": 0, "minecraft:stone": 1},
                     blocks=[0, 1, 1, 0])
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    stored = register_asset(workspace, _asset_record(tmp_path, original), original)
    assert stored["target"]["sha256"].startswith("sha256:")
    stored_path = workspace / stored["target"]["path"]
    assert stored_path.is_file()
    # the original copy is read-only
    assert not (stored_path.stat().st_mode & 0o222)

    assert verify_asset(workspace, "classroom-v1")["asset_id"] == "classroom-v1"
    # re-registration without overwrite refuses; originals are never replaced
    with pytest.raises(AssetRegistryError, match="already registered"):
        register_asset(workspace, _asset_record(tmp_path, original), original)
    assert len(load_registry(workspace)) == 1


def test_register_rejects_hash_mismatch(tmp_path: Path) -> None:
    original = tmp_path / "classroom.schem"
    _write_schematic(original, width=1, height=1, length=1,
                     palette={"minecraft:air": 0}, blocks=[0])
    record = _asset_record(tmp_path, original)
    record["source"]["sha256"] = "sha256:" + "0" * 64
    workspace = tmp_path / "workspace"
    with pytest.raises(AssetRegistryError, match="sha256 mismatch"):
        register_asset(workspace, record, original)
    # nothing was left behind
    assert load_registry(workspace) == {}


def test_register_validates_against_contract(tmp_path: Path) -> None:
    original = tmp_path / "x.schem"
    original.write_bytes(b"x")
    record = _asset_record(tmp_path, original)
    record["asset_id"] = "BAD ID"  # contract requires [a-z0-9_-]
    with pytest.raises(AssetRegistryError, match="rejected"):
        register_asset(tmp_path / "workspace", record, original)


# -- P3: dual-view masters ----------------------------------------------------------


def _master_plan() -> dict:
    keyframes_c1 = [
        {"tick": 0, "position": [12.5, -60.0, 8.5], "rotation": [45.0, 10.0, 0.0]},
        {"tick": 200, "position": [10.5, -60.0, 6.5], "rotation": [60.0, 5.0, 0.0]},
    ]
    keyframes_c2 = [
        {"tick": 0, "position": [0.5, -58.0, 0.5], "rotation": [0.0, 0.0, 0.0]},
        {"tick": 200, "position": [0.5, -58.0, 0.5], "rotation": [90.0, 0.0, 0.0]},
    ]
    return {
        "schema_version": 3,
        "master_id": "KJDS-EV01-master-01",
        "master_hash": "sha256:" + "a" * 64,
        "source_recording": "2026-09-29_10-30-00.mcpr",
        "event_ticks": [
            {"event_id": "hazard_point", "tick": 40, "note": "worker reaches P"},
            {"event_id": "push", "tick": 60},
            {"event_id": "board_fall", "tick": 120},
        ],
        "views": [
            {"view_id": "C1", "role": "bystander_phone", "camera_ref": "cam-c1",
             "keyframes": keyframes_c1, "interpolation": "smooth",
             "range": {"start_tick": 0, "end_tick": 200},
             "output": "work/run/exports/c1-v1.mp4"},
            {"view_id": "C2", "role": "cctv_continuous", "camera_ref": "cam-c2",
             "keyframes": keyframes_c2, "interpolation": "linear",
             "range": {"start_tick": 0, "end_tick": 200},
             "output": "work/run/exports/c2-v1.mp4"},
        ],
    }


def test_master_view_schema_and_invariants() -> None:
    plan = load_master_view(_master_plan())
    assert len(plan["views"]) == 2
    schema = load_schema("master-view", version=3)
    assert schema["properties"]["schema_version"]["const"] == 3


def test_master_view_rejects_duplicate_and_escaping_views() -> None:
    plan = _master_plan()
    plan["views"][1]["view_id"] = "C1"
    with pytest.raises(MasterViewError, match="duplicate view_id"):
        load_master_view(plan)
    plan = _master_plan()
    plan["views"][0]["keyframes"][1]["tick"] = 500  # escapes the 0..200 range
    with pytest.raises(MasterViewError, match="escapes the render range"):
        load_master_view(plan)
    plan = _master_plan()
    plan["views"][0]["range"] = {"start_tick": 100, "end_tick": 50}
    with pytest.raises(MasterViewError, match="end > start"):
        load_master_view(plan)


def test_master_view_schema_rejects_reenactment_fields() -> None:
    schema = load_schema("master-view", version=3)
    view_props = schema["properties"]["views"]["items"]["properties"]
    # a view carries camera + range + output ONLY: no world-write, no replay
    # field that could fork the event per view
    assert set(view_props) == {
        "view_id", "role", "camera_ref", "keyframes", "interpolation",
        "range", "output", "width", "height", "fps",
    }


def test_render_requests_carry_same_master() -> None:
    plan = _master_plan()
    requests = [render_requests(plan, view_id) for view_id in ("C1", "C2")]
    for request in requests:
        assert request["camera"]["params"]["timeline_id"] == plan["master_id"]
        assert request["render"]["params"]["timeline_id"] == plan["master_id"]
        assert request["render"]["params"]["range"] == {"start_tick": 0, "end_tick": 200}
    assert requests[0]["render"]["params"]["output_path"].endswith("c1-v1.mp4")
    assert requests[1]["camera"]["params"]["interpolation"] == "linear"
    with pytest.raises(MasterViewError, match="no view"):
        render_requests(plan, "C3")
    # event ticks are stamped once and shared
    assert event_tick(plan, "push") == 60
    with pytest.raises(MasterViewError, match="no event tick"):
        event_tick(plan, "nonexistent")


# -- P4: deterministic edit plans ----------------------------------------------------


def _edit_list(tmp_path: Path) -> dict:
    return {
        "schema_version": 3,
        "edit_id": "ev01-cut",
        "output": {"path": str(tmp_path / "final.mp4"),
                   "width": 1280, "height": 720, "fps": 30, "container": "mp4"},
        "video_clips": [
            {"source": str(tmp_path / "c1-v1.mp4"), "take_from_seconds": 0.0,
             "duration_seconds": 5.0, "timeline_start_seconds": 0.0, "note": "路人视角"},
            {"source": str(tmp_path / "c2-v1.mp4"), "take_from_seconds": 1.0,
             "duration_seconds": 5.0, "timeline_start_seconds": 5.0, "note": "监控视角"},
        ],
        "audio_clips": [
            {"source": str(tmp_path / "amb.wav"), "take_from_seconds": 0.0,
             "duration_seconds": 10.0, "timeline_start_seconds": 0.0,
             "gain_db": -6.0, "fade_in_seconds": 1.0},
        ],
        "subtitles": [
            {"start_seconds": 1.0, "end_seconds": 3.5, "text": "小心头顶"},
        ],
    }


def test_edit_plan_generates_fixed_command_sequence(tmp_path: Path) -> None:
    plan = build_ffmpeg_plan(_edit_list(tmp_path))
    kinds = [command[0] for command in plan]
    assert kinds == ["ffmpeg", "ffmpeg", "write-file", "ffmpeg",
                     "write-file", "ffmpeg", "ffmpeg", "accept-media"]
    # stage 1: one trim per clip, deterministic args
    trim = plan[0]
    assert trim[:8] == ["ffmpeg", "-y", "-v", "error", "-ss", "0.000", "-t", "5.000"]
    assert trim[8] == "-i" and trim[10] == "-vf" and "scale=1280:720" in trim[11]
    # stage 2 concats the segments
    assert plan[3][4:7] == ["-f", "concat", "-safe"]
    # subtitles burn in with an escaped filter path
    assert plan[4][0] == "write-file" and plan[4][1].endswith("subs.srt")
    burn = plan[5]
    assert "subtitles=" in burn[burn.index("-vf") + 1]
    # final stage is the audio mix into the accepted artifact
    final = plan[-2]
    assert "amix=inputs=1" in final[final.index("-filter_complex") + 1]
    assert plan[-1] == ["accept-media", str(tmp_path / "ev01-cut.final.mp4")]


def test_edit_plan_without_audio_or_subs_still_terminates_in_accept(tmp_path: Path) -> None:
    edit = _edit_list(tmp_path)
    del edit["audio_clips"], edit["subtitles"]
    plan = build_ffmpeg_plan(edit)
    assert plan[-1] == ["accept-media", str(tmp_path / "ev01-cut.final.mp4")]
    assert not any("filter_complex" in command for command in plan)


def test_timed_image_and_video_overlays_have_bounded_filters(tmp_path: Path) -> None:
    edit = _edit_list(tmp_path)
    edit["visual_overlays"] = [
        {"source": "card.png", "kind": "image", "start_seconds": 1,
         "end_seconds": 2, "x": 0, "y": 0, "width": 1280, "height": 720},
        {"source": "phone.mp4", "kind": "video", "start_seconds": 5,
         "end_seconds": 7, "x": 900, "y": 100, "width": 210, "height": 375,
         "speed": 0.5},
    ]
    plan = build_ffmpeg_plan(edit)
    overlays = [cmd for cmd in plan if "-filter_complex" in cmd and "overlay=" in cmd[cmd.index("-filter_complex") + 1]]
    assert len(overlays) == 2
    assert "-loop" in overlays[0] and "lt(t,2)" in overlays[0][overlays[0].index("-filter_complex") + 1]
    assert "-stream_loop" in overlays[1] and "lt(t,7)" in overlays[1][overlays[1].index("-filter_complex") + 1]
    assert plan[-1][0] == "accept-media"


def test_edit_plan_rejects_overlapping_clips(tmp_path: Path) -> None:
    edit = _edit_list(tmp_path)
    edit["video_clips"][1]["timeline_start_seconds"] = 3.0  # overlaps 0..5
    with pytest.raises(EditPlanError, match="overlap"):
        build_ffmpeg_plan(edit)


def test_edit_list_validates_against_contract(tmp_path: Path) -> None:
    edit = _edit_list(tmp_path)
    validate_against_contract_v3(edit, "edit-list")
    schema = load_schema("edit-list", version=3)
    assert schema["properties"]["schema_version"]["const"] == 3
    broken = dict(edit)
    broken["video_clips"] = []
    with pytest.raises(ContractError):
        validate_against_contract_v3(broken, "edit-list")

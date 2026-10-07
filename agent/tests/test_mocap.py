"""Mocap library manifest and conflict checks against a fixture save layout.

The fixture reproduces the verified on-disk layout:
`<save>/mocap_files/recordings/<name>.mcmocap_rec` and `<save>/mocap_files/scenes/`.
"""

from pathlib import Path

import pytest

from minecraft_film_agent.mocap import MocapLibrary, MocapLibraryUnavailable
from minecraft_film_agent.models import ScenePlan


def make_save(tmp_path: Path) -> Path:
    save = tmp_path / "Marx Video Test"
    recordings = save / "mocap_files" / "recordings"
    recordings.mkdir(parents=True)
    (save / "mocap_files" / "scenes").mkdir()
    (recordings / "test_take.mcmocap_rec").write_bytes(b"\x00")
    (recordings / "worker_walk.mcmocap_rec").write_bytes(b"\x00")
    (save / "mocap_files" / "scenes" / "factory_scene.mcmocap_scene").write_text(
        "{}", encoding="utf-8"
    )
    return save


def make_plan(actions: list[dict]) -> ScenePlan:
    return ScenePlan.model_validate(
        {
            "plan_id": "mocap-test",
            "title": "Mocap test",
            "world_name": "Marx Video Test",
            "objective": "Mocap conflict checks",
            "build_region": {
                "start": {"x": 0, "y": 60, "z": 0},
                "end": {"x": 8, "y": 70, "z": 8},
            },
            "actions": actions,
        }
    )


def save(name: str) -> dict:
    return {"type": "mocap_recording_save", "name": name}


def play(name: str) -> dict:
    return {"type": "mocap_playback_start", "name": name}


def scene_create(name: str) -> dict:
    return {"type": "mocap_scene_create", "scene": name}


def scene_add(scene: str, recording: str) -> dict:
    return {
        "type": "mocap_scene_add",
        "scene": scene,
        "recording": recording,
        "player_name": "WorkerA",
    }


def test_scan_lists_recordings_and_scenes(tmp_path: Path) -> None:
    manifest = MocapLibrary(make_save(tmp_path)).scan()
    assert manifest.recordings == ["test_take", "worker_walk"]
    assert manifest.scenes == ["factory_scene"]
    assert manifest.warnings == []


def test_scan_of_save_without_mocap_warns(tmp_path: Path) -> None:
    save = tmp_path / "Fresh World"
    save.mkdir()
    manifest = MocapLibrary(save).scan()
    assert manifest.recordings == []
    assert any("no mocap_files" in warning for warning in manifest.warnings)


def test_scan_is_read_only(tmp_path: Path) -> None:
    save = make_save(tmp_path)
    before = sorted(str(p) for p in save.rglob("*"))
    MocapLibrary(save).scan()
    after = sorted(str(p) for p in save.rglob("*"))
    assert before == after


def test_missing_save_root_is_unavailable(tmp_path: Path) -> None:
    with pytest.raises(MocapLibraryUnavailable):
        MocapLibrary(tmp_path / "does-not-exist").scan()


def test_conflict_on_saving_existing_recording(tmp_path: Path) -> None:
    issues = MocapLibrary(make_save(tmp_path)).conflicts(make_plan([save("test_take")]))
    assert len(issues) == 1
    assert "already exists" in issues[0]


def test_conflict_on_creating_existing_scene(tmp_path: Path) -> None:
    issues = MocapLibrary(make_save(tmp_path)).conflicts(
        make_plan([scene_create("factory_scene")])
    )
    assert len(issues) == 1


def test_playback_of_existing_recording_is_clean(tmp_path: Path) -> None:
    issues = MocapLibrary(make_save(tmp_path)).conflicts(make_plan([play("test_take")]))
    assert issues == []


def test_dangling_playback_is_reported(tmp_path: Path) -> None:
    issues = MocapLibrary(make_save(tmp_path)).conflicts(make_plan([play("ghost_take")]))
    assert len(issues) == 1
    assert "ghost_take" in issues[0]


def test_reference_must_come_after_save(tmp_path: Path) -> None:
    library = MocapLibrary(make_save(tmp_path))
    ok = library.conflicts(
        make_plan([save("new_take"), scene_add("factory_scene", "new_take")])
    )
    assert ok == []
    inverted = library.conflicts(
        make_plan([scene_add("factory_scene", "new_take"), save("new_take")])
    )
    assert len(inverted) == 1
    assert "earlier action" in inverted[0]


def test_scene_add_may_reference_library_recording(tmp_path: Path) -> None:
    issues = MocapLibrary(make_save(tmp_path)).conflicts(
        make_plan([scene_create("chase_scene"), scene_add("chase_scene", "worker_walk")])
    )
    assert issues == []

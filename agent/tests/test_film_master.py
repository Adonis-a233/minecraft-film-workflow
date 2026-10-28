"""Declarative master pipeline (film_master) — offline tests.

Everything runs without a game. Real muxing tests use the repository ffmpeg
when available and skip otherwise. The staleness matrix is pure hashing and
always runs.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from minecraft_film_agent.contracts import ContractError, validate_against_contract_v3
from minecraft_film_agent.film_master import (
    FilmMasterError,
    _shot_spec_digest,
    build_report,
    chapter_inputs_digest,
    chapter_status,
    compile_chapter_edits,
    load_chapter,
    load_shots_manifest,
    run_master,
)
from minecraft_film_agent.edit import execute_edit

ROOT = Path(__file__).resolve().parents[2]
FFMPEG = ROOT / "tools/ffmpeg/bin/ffmpeg.exe"
FFPROBE = ROOT / "tools/ffmpeg/bin/ffprobe.exe"
HAS_FFMPEG = FFMPEG.is_file() or shutil.which("ffmpeg") is not None


def media_tools(tmp_path: Path) -> tuple[Path, Path]:
    if FFMPEG.is_file():
        return FFMPEG, FFPROBE
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg/ffprobe not available")
    return Path(ffmpeg), Path(ffprobe)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


MINIMAL_ASS = "[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\n\n" \
    "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, Bold, Outline, Alignment, MarginV\n" \
    "Format: Text, Arial, 40, &H00FFFFFF, 0, 2, 2, 40\n" \
    "Style: Default,Arial,40,&H00FFFFFF,0,2,2,40\n\n" \
    "[Events]\nFormat: Layer, Start, End, Style, Text\n" \
    "Dialogue: 0,0:00:00.00,0:00:10.00,Default,test overlay\n"


# -- tiny synthetic workspace -------------------------------------------------

def make_clip(tmp_path: Path, ffmpeg: Path, name: str, seconds: float = 3.0) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(ffmpeg), "-y", "-v", "error",
                    "-f", "lavfi", "-i", f"mandelbrot=size=1280x720:rate=30",
                    "-t", f"{seconds}", "-c:v", "libx264", "-preset", "ultrafast",
                    "-crf", "30", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def make_wav(tmp_path: Path, ffmpeg: Path, name: str, seconds: float, freq: int) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(ffmpeg), "-y", "-v", "error",
                    "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}",
                    "-ac", "2", "-c:a", "pcm_s16le", str(path)], check=True)
    return path


def decoded_pcm_sha(path: Path, ffmpeg: Path) -> str:
    raw = subprocess.run([str(ffmpeg), "-v", "error", "-i", str(path), "-f", "s16le",
                          "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "2", "-"],
                         capture_output=True, check=True).stdout
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture()
def workspace(tmp_path: Path):
    """A tiny but fully pinned production: two chapters built from three
    shots plus one imported clip each, ready for a two-chapter film."""

    root = tmp_path
    ffmpeg = media_tools(root)[0]
    (root / "game/instances/t/replays").mkdir(parents=True)
    (root / "game/instances/t/replays/m1.mcpr").write_bytes(b"replay-master-1")
    (root / "game/instances/t/replays/m2.mcpr").write_bytes(b"replay-master-2")
    (root / "assets/resourcepacks").mkdir(parents=True)
    (root / "assets/resourcepacks/pack.zip").write_bytes(b"resourcepack-v1")
    (root / "assets/renders").mkdir(parents=True)

    pack_manifest = {"resourcepacks": {"pack": {
        "profile_id": "file/pack.zip", "sha256": sha(root / "assets/resourcepacks/pack.zip")}}}
    shots = []
    for index, master in enumerate(("m1", "m1", "m2"), start=1):
        clip = make_clip(root, ffmpeg, f"game/instances/t/bridge-renders/shot-{index}.mp4")
        span = 60 * index  # native ticks; (end-start)*30 fps % 20 == 0
        shots.append({
            "shot_id": f"{index:02d}",
            "master_id": master,
            "master_sha256": sha(root / f"game/instances/t/replays/{master}.mcpr"),
            "camera_track": {"interpolation": "linear", "keyframes": [
                {"tick": span - 60, "position": [0.0, 4.0, 0.0], "rotation": [0.0, 0.0, 0.0], "fov": 70},
                {"tick": span, "position": [0.0, 4.0, 0.0], "rotation": [0.0, 0.0, 0.0], "fov": 70}]},
            "tick_range": {"start_tick": span - 60, "end_tick": span},
            "resourcepack_sha256": sha(root / "assets/resourcepacks/pack.zip"),
            "enabled_file_profiles": ["file/pack.zip"],
            "width": 1280, "height": 720, "fps": 30,
            "output": f"game/instances/t/bridge-renders/shot-{index}.mp4",
            "output_sha256": sha(clip),
        })
        shots[-1]["accepted_spec_digest"] = _shot_spec_digest(shots[-1], pack_manifest)
    manifest = write_json(root / "assets/productions/t/shots-manifest.json", {
        "schema_version": 3,
        "manifest_id": "t-shots",
        "video": {"width": 1280, "height": 720, "fps": 30},
        "resourcepacks": {"pack": {"path": "assets/resourcepacks/pack.zip",
                                   "sha256": sha(root / "assets/resourcepacks/pack.zip"),
                                   "profile_id": "file/pack.zip"}},
        "masters": {"m1": {"file": "game/instances/t/replays/m1.mcpr",
                           "sha256": sha(root / "game/instances/t/replays/m1.mcpr")},
                    "m2": {"file": "game/instances/t/replays/m2.mcpr",
                           "sha256": sha(root / "game/instances/t/replays/m2.mcpr")}},
        "shots": shots,
    })

    ass = root / "assets/productions/t/overlay.ass"
    ass.write_text(MINIMAL_ASS, encoding="utf-8")
    chapters = []
    # Whole-film assembly follows the v10 preset: the last chapter is "credits".
    for number, (chapter_id, shot_a, shot_b, seconds) in enumerate(
            (("C1", "01", "02", 6), ("credits", "03", None, 3)), start=1):
        timeline = []
        if shot_b:
            timeline.append({"shot": shot_b, "take_from_seconds": 0.0, "duration_seconds": 3.0,
                             "timeline_start_seconds": 3.0})
        timeline.insert(0, {"shot": shot_a, "take_from_seconds": 0.0, "duration_seconds": 3.0,
                            "timeline_start_seconds": 0.0})
        wav = make_wav(root, ffmpeg, f"assets/audio/{chapter_id}.wav", float(seconds), 330 * number)
        chapter = {
            "schema_version": 3,
            "chapter_id": chapter_id,
            "seconds": seconds,
            "video": {"width": 1280, "height": 720, "fps": 30},
            "shots_manifest": "assets/productions/t/shots-manifest.json",
            "timeline": timeline,
            "audio_clips": [{"source": f"assets/audio/{chapter_id}.wav",
                             "sha256": sha(wav),
                             "take_from_seconds": 0.0, "duration_seconds": float(seconds),
                             "timeline_start_seconds": 0.0}],
            "variants": {"clean": {"ass_overlays": [
                            {"path": "assets/productions/t/overlay.ass", "sha256": sha(ass)}]},
                         "subtitles": {"ass_overlays": [
                            {"path": "assets/productions/t/overlay.ass", "sha256": sha(ass)}]}},
            "outputs": {
                "clean": f"assets/renders/t-{chapter_id}-clean-v1.mp4",
                "subtitles": f"assets/renders/t-{chapter_id}-subtitles-v1.mp4",
                "manifest": f"assets/productions/t/{chapter_id}/review-manifest.json"},
        }
        path = write_json(root / f"assets/productions/t/{chapter_id}-recipe.json", chapter)
        chapters.append(path)

    film_wav = make_wav(root, ffmpeg, "assets/audio/film.wav", 9.0, 550)
    plan = {
        "schema_version": 3,
        "plan_id": "t-master-plan",
        "video": {"width": 1280, "height": 720, "fps": 30},
        "shots_manifest": {"path": "assets/productions/t/shots-manifest.json", "sha256": sha(manifest)},
        "chapters": [{"path": str(path.relative_to(root)).replace("\\", "/"),
                      "sha256": sha(path)} for path in chapters],
        "film": {"audio": {"path": "assets/audio/film.wav", "sha256": sha(film_wav),
                           "sample_rate": 48000, "channels": 2,
                           "decoded_pcm_sha256": decoded_pcm_sha(film_wav, ffmpeg)},
                 "outputs": {"clean": "work/film-out/{film_id}-clean.mp4",
                             "subtitles": "work/film-out/{film_id}-subtitles.mp4"}},
    }
    plan_path = write_json(root / "assets/productions/t/master-plan.json", plan)
    from minecraft_film_agent.film_review import record_review
    for info in build_report(root, plan_path)["shots"].values():
        record_review(root, plan_path, synthetic_review(info["review"]))
    return {"root": root, "plan": plan_path, "ffmpeg": media_tools(root)[0],
            "ffprobe": media_tools(root)[1]}


def synthetic_review(binding):
    return {**{key: binding[key] for key in ("target", "spec_digest", "output_hashes")},
            "reviewer": "test reviewer", "reviewed_at": "2026-10-27T12:00:00+08:00",
            "decision": "approved", "normal_speed_watched": True,
            "checks": {key: "pass" for key in ("geometry", "performance", "composition", "continuity", "sound")},
            "notes": "Synthetic fixture only."}


def run_reviewed(root, plan, **kwargs):
    from minecraft_film_agent.film_review import record_review
    for _ in range(20):
        report = run_master(root, plan, **kwargs)
        if not report["actions"]:
            return report
        for action in report["actions"]:
            if action["kind"].startswith("review_"):
                record_review(root, plan, synthetic_review(action["review"]))
    pytest.fail("reviewed executor did not finish")


def _report(workspace) -> dict:
    return build_report(workspace["root"], workspace["plan"])


# -- contracts ----------------------------------------------------------------

def test_film_shots_contract_rejects_missing_master_hash(workspace):
    manifest = json.loads((workspace["root"] / "assets/productions/t/shots-manifest.json")
                          .read_text(encoding="utf-8"))
    del manifest["shots"][0]["master_sha256"]
    with pytest.raises(ContractError):
        validate_against_contract_v3(manifest, "film-shots")


def test_chapter_timeline_gap_rejected(workspace):
    chapter = json.loads((workspace["root"] / "assets/productions/t/C1-recipe.json")
                         .read_text(encoding="utf-8"))
    chapter["timeline"][1]["timeline_start_seconds"] = 4.0
    path = workspace["root"] / "assets/productions/t/gap.json"
    write_json(path, chapter)
    with pytest.raises(FilmMasterError, match="gap or overlap"):
        load_chapter(workspace["root"], str(path.relative_to(workspace["root"])).replace("\\", "/"))


def test_chapter_seconds_mismatch_rejected(workspace):
    chapter = json.loads((workspace["root"] / "assets/productions/t/C1-recipe.json")
                         .read_text(encoding="utf-8"))
    chapter["seconds"] = 7
    path = workspace["root"] / "assets/productions/t/bad.json"
    write_json(path, chapter)
    with pytest.raises(FilmMasterError, match="seconds declares"):
        load_chapter(workspace["root"], str(path.relative_to(workspace["root"])).replace("\\", "/"))


def test_camera_keyframes_must_stay_in_tick_range(workspace):
    root = workspace["root"]
    manifest = json.loads((root / "assets/productions/t/shots-manifest.json")
                          .read_text(encoding="utf-8"))
    manifest["shots"][0]["camera_track"]["keyframes"][0]["tick"] = 999
    write_json(root / "assets/productions/t/bad-shots.json", manifest)
    with pytest.raises(FilmMasterError, match="leave the tick range"):
        load_shots_manifest(root, "assets/productions/t/bad-shots.json")


# -- staleness matrix ---------------------------------------------------------

def test_all_fresh_plan_has_no_actions(workspace):
    report = _report(workspace)
    assert report["ok"]
    assert all(shot["status"] == "fresh" for shot in report["shots"].values())
    assert all(info["status"] == "rebuild" for info in report["chapters"].values())
    assert report["film"]["status"] == "waiting_for_chapters"
    assert [action["kind"] for action in report["actions"]] == \
        ["rebuild_chapter", "rebuild_chapter"]
    assert not report["requires_live_bridge"]


def test_missing_shot_output_requires_live_bridge_and_blocks_chapters(workspace):
    (workspace["root"] / "game/instances/t/bridge-renders/shot-3.mp4").unlink()
    report = _report(workspace)
    assert report["shots"]["03"]["reasons"] == ["output_missing"]
    assert report["requires_live_bridge"]
    assert report["chapters"]["credits"]["status"] == "waiting_for_shots"
    assert report["film"]["status"] == "waiting_for_chapters"
    with pytest.raises(FilmMasterError, match="fail-closed|live bridge"):
        run_master(workspace["root"], workspace["plan"],
                   ffmpeg=workspace["ffmpeg"], ffprobe=workspace["ffprobe"], bridge=None)
    # The refusal is journaled, but no render or chapter output appeared.
    assert not (workspace["root"] / "assets/renders/t-credits-clean-v1.mp4").exists()
    journal = json.loads((workspace["root"] / "work/film-master/t-master-plan/master-journal.json")
                         .read_text(encoding="utf-8"))
    assert journal["status"] == "failed" and "live bridge" in journal["error"]


def test_resourcepack_change_stales_every_shot(workspace):
    pack = workspace["root"] / "assets/resourcepacks/pack.zip"
    pack.write_bytes(b"resourcepack-v2-changed")
    report = _report(workspace)
    assert all(info["reasons"] == ["resourcepack_changed:file/pack.zip"] for info in report["shots"].values())
    assert report["requires_live_bridge"]


def test_imported_clip_hash_drift_blocks_chapter(workspace):
    """A pinned imported clip whose file drifted must block, never rebuild."""

    root = workspace["root"]
    wav = make_wav(root, workspace["ffmpeg"], "assets/audio/insert.wav", 1.0, 660)
    chapter = json.loads((root / "assets/productions/t/C1-recipe.json").read_text(encoding="utf-8"))
    chapter["chapter_id"] = "CX"
    chapter["seconds"] = 7
    chapter["timeline"].append({"clip": {"path": "assets/audio/insert.wav", "sha256": "0" * 64},
                                "take_from_seconds": 0.0, "duration_seconds": 1.0,
                                "timeline_start_seconds": 6.0})
    chapter["outputs"] = {**chapter["outputs"],
                          "manifest": "assets/productions/t/cx/review-manifest.json"}
    write_json(root / "assets/productions/t/cx-recipe.json", chapter)
    loaded = load_chapter(root, "assets/productions/t/cx-recipe.json")
    plan_report = _report(workspace)
    shot_infos = {shot_id: {"status": info["status"]} for shot_id, info in plan_report["shots"].items()}
    manifest = load_shots_manifest(root, "assets/productions/t/shots-manifest.json")
    status = chapter_status(root, loaded, manifest, {}, shot_infos)
    assert status["status"] == "blocked"
    assert status["reasons"] == ["imported clip_changed: assets/audio/insert.wav"]


def test_shot_receipt_supersedes_declaration_and_detects_spec_drift(workspace):
    root = workspace["root"]
    receipts = {"plan_id": "t-master-plan", "shots": {"01": {
        "output": "game/instances/t/bridge-renders/shot-1.mp4",
        "output_sha256": sha(root / "game/instances/t/bridge-renders/shot-1.mp4"),
        "spec_digest": "stale-spec"}}}
    write_json(root / "work/film-master/t-master-plan/shot-receipts.json", receipts)
    report = _report(workspace)
    assert report["shots"]["01"]["status"] == "stale"
    assert "render_spec_changed_since_receipt" in report["shots"]["01"]["reasons"]


def test_preview_writes_nothing(workspace):
    before = sorted(str(p.relative_to(workspace["root"])) for p in workspace["root"].rglob("*"))
    _report(workspace)
    after = sorted(str(p.relative_to(workspace["root"])) for p in workspace["root"].rglob("*"))
    assert before == after


# -- compile determinism ------------------------------------------------------

def test_compile_chapter_edits_is_deterministic_and_lowercase(workspace):
    root = workspace["root"]
    manifest = load_shots_manifest(root, "assets/productions/t/shots-manifest.json")
    chapter = load_chapter(root, "assets/productions/t/C1-recipe.json")
    first = compile_chapter_edits(chapter, manifest, {}, edit_id_prefix="t-plan-c1")
    second = compile_chapter_edits(chapter, manifest, {}, edit_id_prefix="t-plan-c1")
    assert first == second
    assert set(first) == {"clean", "subtitles"}
    for edit in first.values():
        assert edit["edit_id"].startswith("t-plan-c1-")
        assert edit["ass_overlays"] == [{"path": "assets/productions/t/overlay.ass"}]
        assert len(edit["video_clips"]) == 2
        assert edit["output"]["path"] == chapter["outputs"]["clean"] \
            or edit["output"]["path"] == chapter["outputs"]["subtitles"]


def test_inputs_digest_tracks_receipt_output(workspace):
    root = workspace["root"]
    manifest = load_shots_manifest(root, "assets/productions/t/shots-manifest.json")
    chapter = load_chapter(root, "assets/productions/t/C1-recipe.json")
    base = chapter_inputs_digest(chapter, manifest, {})
    receipt = {"output": "game/instances/t/bridge-renders/shot-1.mp4",
               "output_sha256": "f" * 64, "spec_digest": "x"}
    changed = chapter_inputs_digest(chapter, manifest, {"01": receipt})
    assert base != changed


def test_chapter_timing_change_invalidates_inputs_digest(workspace):
    root = workspace["root"]
    manifest = load_shots_manifest(root, "assets/productions/t/shots-manifest.json")
    chapter = load_chapter(root, "assets/productions/t/C1-recipe.json")
    original = chapter_inputs_digest(chapter, manifest, {})
    chapter["timeline"][0]["take_from_seconds"] = 0.5
    assert chapter_inputs_digest(chapter, manifest, {}) != original


def test_visual_overlay_shot_uses_current_render_receipt(workspace):
    root = workspace["root"]
    manifest = load_shots_manifest(root, "assets/productions/t/shots-manifest.json")
    chapter = load_chapter(root, "assets/productions/t/C1-recipe.json")
    chapter["visual_overlays"] = [{"shot": "03", "kind": "video",
                                   "start_seconds": 0, "end_seconds": 1,
                                   "x": 0, "y": 0, "width": 1280, "height": 720}]
    base = chapter_inputs_digest(chapter, manifest, {})
    receipt = {"output": "game/instances/t/bridge-renders/new-shot-3.mp4",
               "output_sha256": "f" * 64, "spec_digest": "x"}
    changed = chapter_inputs_digest(chapter, manifest, {"03": receipt})
    assert base != changed
    compiled = compile_chapter_edits(chapter, manifest, {"03": receipt},
                                     edit_id_prefix="t-plan-c1")
    assert compiled["clean"]["visual_overlays"][0]["source"] == receipt["output"]


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not available")
def test_image_timeline_and_video_overlay_render(tmp_path):
    ffmpeg, ffprobe = media_tools(tmp_path)
    image_path = tmp_path / "assets/graphics/card.png"
    image_path.parent.mkdir(parents=True)
    subprocess.run([str(ffmpeg), "-y", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=blue:s=1280x720:r=30", "-frames:v", "1", "-update", "1",
                    str(image_path)], check=True)
    movie = make_clip(tmp_path, ffmpeg, "assets/footage/actor.mp4", 1)
    edit = {"schema_version": 3, "edit_id": "overlay-smoke",
            "output": {"path": "assets/renders/overlay-smoke.mp4", "width": 1280,
                       "height": 720, "fps": 30, "container": "mp4"},
            "video_clips": [
                {"source": "assets/graphics/card.png", "kind": "image",
                 "take_from_seconds": 0, "duration_seconds": 1,
                 "timeline_start_seconds": 0},
                {"source": "assets/footage/actor.mp4", "kind": "video",
                 "take_from_seconds": 0, "duration_seconds": 1,
                 "timeline_start_seconds": 1}],
            "visual_overlays": [{"source": "assets/footage/actor.mp4", "kind": "video",
                                 "start_seconds": 0, "end_seconds": 1,
                                 "x": 800, "y": 100, "width": 320, "height": 180}]}
    report = execute_edit(edit, workspace=tmp_path, evidence_dir=tmp_path / "work/overlay-smoke",
                          ffmpeg=ffmpeg, ffprobe=ffprobe)
    assert report["status"] == "succeeded"
    assert report["media"]["streams"][0]["frames"] == 60


# -- end-to-end run (real muxing, no game) ------------------------------------

@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not available")
def test_run_builds_chapters_and_film_then_is_idempotent(workspace):
    root, plan = workspace["root"], workspace["plan"]
    ffmpeg, ffprobe = workspace["ffmpeg"], workspace["ffprobe"]
    report = run_reviewed(root, plan, ffmpeg=ffmpeg, ffprobe=ffprobe, bridge=None)
    assert report["actions"] == []
    assert report["film"]["status"] == "fresh"
    for chapter_id in ("C1", "credits"):
        for variant in ("clean", "subtitles"):
            assert (root / f"assets/renders/t-{chapter_id}-{variant}-v1.mp4").is_file()
    outputs = list((root / "work/film-out").glob("*.mp4"))
    assert len(outputs) == 2
    manifest = json.loads((root / "assets/productions/t/C1/review-manifest.json")
                          .read_text(encoding="utf-8"))
    assert manifest["chapter_id"] == "C1" and len(manifest["outputs"]) == 2
    receipt_path = root / "work/film-master/t-master-plan/film-receipt.json"
    first_receipt = receipt_path.read_text(encoding="utf-8")
    journal = json.loads((root / "work/film-master/t-master-plan/master-journal.json")
                         .read_text(encoding="utf-8"))
    assert journal["status"] == "succeeded"
    # Second run: everything fresh, nothing rebuilt or reassembled.
    second = run_master(root, plan, ffmpeg=ffmpeg, ffprobe=ffprobe, bridge=None)
    assert second["actions"] == [] and second["film"]["status"] == "fresh"
    assert receipt_path.read_text(encoding="utf-8") == first_receipt
    assert len(list((root / "work/film-out").glob("*.mp4"))) == 2


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not available")
def test_rebuilt_shot_output_cascades_into_chapters_and_film(workspace):
    """A re-exported shot (new declared output path) must stale its chapter
    and film; the author bumps chapter output versions and the run rebuilds
    them into fresh files plus a second whole-film assembly."""

    root, plan = workspace["root"], workspace["plan"]
    ffmpeg, ffprobe = workspace["ffmpeg"], workspace["ffprobe"]
    assert run_reviewed(root, plan, ffmpeg=ffmpeg, ffprobe=ffprobe, bridge=None)["actions"] == []
    new_clip = make_clip(root, ffmpeg, "game/instances/t/bridge-renders/shot-3-v2.mp4")
    manifest_payload = json.loads((root / "assets/productions/t/shots-manifest.json")
                                  .read_text(encoding="utf-8"))
    shot = next(s for s in manifest_payload["shots"] if s["shot_id"] == "03")
    shot["output"] = "game/instances/t/bridge-renders/shot-3-v2.mp4"
    shot["output_sha256"] = sha(new_clip)
    shot["camera_track"]["keyframes"][0]["fov"] = 65
    # A changed camera must wait for re-export even when an MP4 exists.
    manifest_path = write_json(root / "assets/productions/t/shots-manifest.json", manifest_payload)
    plan_payload = json.loads(plan.read_text(encoding="utf-8"))
    plan_payload["shots_manifest"]["sha256"] = sha(manifest_path)
    write_json(plan, plan_payload)
    waiting = build_report(root, plan)
    assert waiting["shots"]["03"]["status"] == "stale"
    assert waiting["chapters"]["credits"]["status"] == "waiting_for_shots"
    # This synthetic MP4 stands in for an accepted re-export in the offline test.
    shot["accepted_spec_digest"] = _shot_spec_digest(shot, manifest_payload)
    manifest_path = write_json(root / "assets/productions/t/shots-manifest.json", manifest_payload)
    plan_payload = json.loads(plan.read_text(encoding="utf-8"))
    plan_payload["shots_manifest"]["sha256"] = sha(manifest_path)
    # Version-bump C2's declared outputs; nothing is ever overwritten.
    chapter_path = root / "assets/productions/t/credits-recipe.json"
    chapter_payload = json.loads(chapter_path.read_text(encoding="utf-8"))
    chapter_payload["outputs"] = {
        "clean": "assets/renders/t-credits-clean-v2.mp4",
        "subtitles": "assets/renders/t-credits-subtitles-v2.mp4",
        "manifest": "assets/productions/t/credits/review-manifest-v2.json"}
    write_json(chapter_path, chapter_payload)
    plan_payload["chapters"] = [{**pin, "sha256": sha(chapter_path)}
                                if pin["path"].endswith("credits-recipe.json") else pin
                                for pin in plan_payload["chapters"]]
    write_json(plan, plan_payload)
    from minecraft_film_agent.film_review import record_review
    record_review(root, plan, synthetic_review(build_report(root, plan)["shots"]["03"]["review"]))
    report = build_report(root, plan)
    assert report["chapters"]["credits"]["status"] == "rebuild"
    # The bumped recipe points at v2 outputs that do not exist yet.
    assert report["chapters"]["credits"]["reasons"] == ["review_manifest_missing"]
    assert report["film"]["status"] == "waiting_for_chapters"
    final = run_reviewed(root, plan, ffmpeg=ffmpeg, ffprobe=ffprobe, bridge=None)
    assert final["actions"] == [] and final["film"]["status"] == "fresh"
    assert (root / "assets/renders/t-credits-clean-v2.mp4").is_file()
    assert len(list((root / "work/film-out").glob("*.mp4"))) == 4  # first film + rebuilt film

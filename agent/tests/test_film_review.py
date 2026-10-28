"""Hash and review regressions run offline, without FFmpeg or a game."""
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from minecraft_film_agent import film_master as master
from minecraft_film_agent.film_review import FilmReview, record_review


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))
    return path


def approval(binding, decision="approved"):
    return {**{key: binding[key] for key in ("target", "spec_digest", "output_hashes")},
            "reviewer": "Test reviewer", "reviewed_at": "2026-10-27T12:00:00+08:00",
            "decision": decision, "normal_speed_watched": True,
            "checks": {key: "pass" for key in ("geometry", "performance", "composition", "continuity", "sound")},
            "notes": "Synthetic test review; not a production approval."}


@pytest.fixture
def offline(tmp_path):
    packs = {}
    for name in ("main", "school", "unused"):
        path = tmp_path / f"assets/resourcepacks/{name}.zip"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
        packs[name] = {"path": str(path.relative_to(tmp_path)), "profile_id": f"file/{name}.zip", "sha256": sha(path)}
    replay = tmp_path / "assets/replays/m.mcpr"
    replay.parent.mkdir(parents=True)
    replay.write_bytes(b"master")
    manifest = {"schema_version": 3, "manifest_id": "test-shots",
                "video": {"width": 1280, "height": 720, "fps": 30},
                "resourcepacks": packs, "masters": {"m": {"file": "assets/replays/m.mcpr", "sha256": sha(replay)}}, "shots": []}
    for name in ("one", "two"):
        output = tmp_path / f"assets/footage/{name}.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(name.encode())
        shot = {"shot_id": name, "master_id": "m", "master_sha256": sha(replay),
                "camera_track": {"interpolation": "linear", "keyframes": [
                    {"tick": 0, "position": [0, 2, 0], "rotation": [0, 0, 0], "fov": 70}]},
                "tick_range": {"start_tick": 0, "end_tick": 60},
                "resourcepack_sha256": packs["main"]["sha256"],
                "enabled_file_profiles": ["file/main.zip", "file/school.zip"],
                "width": 1280, "height": 720, "fps": 30,
                "output": str(output.relative_to(tmp_path)), "output_sha256": sha(output)}
        shot["accepted_spec_digest"] = master._shot_spec_digest(shot, manifest)
        manifest["shots"].append(shot)
    manifest_path = write(tmp_path / "assets/shots.json", manifest)
    overlay = tmp_path / "assets/overlay.ass"
    overlay.write_text("test overlay")
    chapter = {"schema_version": 3, "chapter_id": "C1", "seconds": 6,
               "video": manifest["video"], "shots_manifest": "assets/shots.json",
               "timeline": [{"shot": name, "take_from_seconds": 0, "duration_seconds": 3, "timeline_start_seconds": n * 3} for n, name in enumerate(("one", "two"))],
               "variants": {name: {"ass_overlays": [{"path": "assets/overlay.ass", "sha256": sha(overlay)}]} for name in ("clean", "subtitles")},
               "outputs": {"clean": "assets/renders/clean.mp4", "subtitles": "assets/renders/subtitles.mp4", "manifest": "assets/review.json"}}
    chapter_path = write(tmp_path / "assets/chapter.json", chapter)
    plan = {"schema_version": 3, "plan_id": "test-plan", "video": manifest["video"],
            "shots_manifest": {"path": "assets/shots.json", "sha256": sha(manifest_path)},
            "chapters": [{"path": "assets/chapter.json", "sha256": sha(chapter_path)}]}
    plan_path = write(tmp_path / "assets/plan.json", plan)
    return tmp_path, plan_path, manifest


def test_secondary_pin_change_and_stack_order_invalidate(offline):
    root, _, manifest = offline
    shot = manifest["shots"][0]
    baseline = master._shot_spec_digest(shot, manifest)
    manifest["resourcepacks"]["school"]["sha256"] = "a" * 64
    assert master._shot_spec_digest(shot, manifest) != baseline
    # Even if the actual file now matches the NEW pin, the old picture is stale.
    (root / manifest["resourcepacks"]["school"]["path"]).write_bytes(b"new-school")
    manifest["resourcepacks"]["school"]["sha256"] = sha(root / manifest["resourcepacks"]["school"]["path"])
    assert "accepted_render_spec_changed" in master.shot_status(root, manifest, shot, None)["reasons"]
    manifest["resourcepacks"]["unused"]["sha256"] = "b" * 64
    current = master._shot_spec_digest(shot, manifest)
    shot["enabled_file_profiles"].reverse()
    assert master._shot_spec_digest(shot, manifest) != current


def test_unused_pack_and_path_do_not_change_content_key(offline):
    root, _, manifest = offline
    shot = manifest["shots"][0]
    receipt = {"output": shot["output"], "output_sha256": shot["output_sha256"],
               "spec_digest": master._shot_spec_digest(shot, manifest)}
    manifest["resourcepacks"]["unused"]["sha256"] = "c" * 64
    old = root / shot["output"]
    shot["output"] = "assets/footage/moved.mp4"
    (root / shot["output"]).write_bytes(old.read_bytes())
    assert master.shot_status(root, manifest, shot, receipt)["status"] == "fresh"
    (root / shot["output"]).write_bytes(b"wrong file")
    assert master.shot_status(root, manifest, shot, receipt)["status"] == "stale"


def test_legacy_spec_is_never_silently_approved(offline):
    root, _, manifest = offline
    shot = manifest["shots"][0]
    shot["accepted_spec_digest"] = "0" * 64
    assert master.shot_status(root, manifest, shot, None)["status"] == "stale"


def test_preview_pure_and_run_pauses_without_media_tools(offline):
    root, plan, _ = offline
    before = sorted(root.rglob("*"))
    report = master.build_report(root, plan)
    assert sorted(root.rglob("*")) == before
    assert report["chapters"]["C1"]["status"] == "waiting_for_review"
    report = master.run_master(root, plan, ffmpeg=Path("missing"), ffprobe=Path("missing"))
    assert [action["kind"] for action in report["actions"]] == ["review_shot", "review_shot"]
    journal = json.loads((root / "work/film-master/test-plan/master-journal.json").read_text())
    assert journal["status"] == "needs_review" and journal["stages"] == []


def test_rejection_and_explicit_resume(offline):
    root, plan, _ = offline
    report = master.build_report(root, plan)
    first = report["shots"]["one"]["review"]
    record_review(root, plan, approval(first, "rejected"))
    assert master.build_report(root, plan)["shots"]["one"]["review"]["status"] == "rejected"
    for info in report["shots"].values():
        record_review(root, plan, approval(info["review"]))
    resumed = master.build_report(root, plan)
    assert resumed["chapters"]["C1"]["status"] == "rebuild"
    assert [action["kind"] for action in resumed["actions"]] == ["rebuild_chapter"]
    history = json.loads((root / "work/film-master/test-plan/human-reviews.json").read_text())
    assert len(history["reviews"]) == 3


def test_old_review_cannot_approve_modified_output(offline):
    root, plan, manifest = offline
    review = approval(master.build_report(root, plan)["shots"]["one"]["review"])
    record_review(root, plan, review)
    (root / manifest["shots"][0]["output"]).write_bytes(b"tampered")
    assert master.build_report(root, plan)["shots"]["one"]["review"]["status"] == "unavailable"
    with pytest.raises(master.FilmMasterError, match="not technically ready"):
        record_review(root, plan, review)


@pytest.mark.parametrize("change", [
    {"reviewer": " "}, {"normal_speed_watched": False}, {"reviewed_at": "2026-10-27"},
    {"checks": {"geometry": "pass"}}, {"output_hashes": {"output": "wrong"}},
])
def test_incomplete_approval_rejected(offline, change):
    root, plan, _ = offline
    review = approval(master.build_report(root, plan)["shots"]["one"]["review"])
    with pytest.raises(ValidationError):
        record_review(root, plan, {**review, **change})


def test_review_wrong_binding_rejected(offline):
    root, plan, _ = offline
    review = approval(master.build_report(root, plan)["shots"]["one"]["review"])
    with pytest.raises(master.FilmMasterError, match="changed content"):
        record_review(root, plan, {**review, "spec_digest": "f" * 64})


def approve_shots(root, plan):
    for info in master.build_report(root, plan)["shots"].values():
        record_review(root, plan, approval(info["review"]))


def fake_chapter(root, chapter, manifest, receipts, **kwargs):
    outputs = []
    for name in ("clean", "subtitles"):
        output = root / chapter["outputs"][name]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(name.encode())
        outputs.append({"output": chapter["outputs"][name], "sha256": sha(output)})
    write(root / chapter["outputs"]["manifest"], {
        "inputs_digest": master.chapter_inputs_digest(chapter, manifest, receipts), "outputs": outputs})
    return {"chapter_id": chapter["chapter_id"]}


def test_chapter_pause_review_and_idempotent_resume(offline, monkeypatch):
    root, plan, _ = offline
    approve_shots(root, plan)
    monkeypatch.setattr(master, "build_chapter", fake_chapter)
    report = master.run_master(root, plan, ffmpeg=Path("unused"), ffprobe=Path("unused"))
    assert [action["kind"] for action in report["actions"]] == ["review_chapter"]
    review = approval(report["chapters"]["C1"]["review"])
    record_review(root, plan, review)
    monkeypatch.setattr(master, "build_chapter", lambda *a, **k: pytest.fail("chapter rebuilt"))
    assert master.run_master(root, plan, ffmpeg=Path("unused"), ffprobe=Path("unused"))["actions"] == []


def test_only_one_stale_shot_exported_before_review(offline, monkeypatch):
    root, plan, manifest = offline
    for shot in manifest["shots"]:
        (root / shot["output"]).unlink()
    calls = []

    def export(root, manifest, shot, *args, **kwargs):
        calls.append(shot["shot_id"])
        (root / shot["output"]).write_bytes(b"new take")
        return {"output": shot["output"], "output_sha256": sha(root / shot["output"]),
                "spec_digest": master._shot_spec_digest(shot, manifest)}

    monkeypatch.setattr(master, "export_shot", export)
    options = dict(ffmpeg=Path("unused"), ffprobe=Path("unused"), bridge=object())
    report = master.run_master(root, plan, **options)
    assert calls == ["one"]
    assert report["shots"]["one"]["review"]["status"] == "needs_review"
    master.run_master(root, plan, **options)
    assert calls == ["one"]  # An unchanged pending review does not export the next take.
    record_review(root, plan, approval(report["shots"]["one"]["review"]))
    master.run_master(root, plan, **options)
    assert calls == ["one", "two"]


def test_film_requires_chapter_and_final_sound_review(offline, monkeypatch):
    root, plan_path, _ = offline
    plan = json.loads(plan_path.read_text())
    soundtrack = root / "assets/sound.wav"
    soundtrack.write_bytes(b"sound")
    plan["film"] = {"audio": {"path": "assets/sound.wav", "sha256": sha(soundtrack),
        "sample_rate": 48000, "channels": 2, "decoded_pcm_sha256": "a" * 64},
        "outputs": {"clean": "work/{film_id}-clean.mp4", "subtitles": "work/{film_id}-subtitles.mp4"}}
    write(plan_path, plan)
    approve_shots(root, plan_path)
    monkeypatch.setattr(master, "build_chapter", fake_chapter)
    calls = []

    def assemble(recipe, **kwargs):
        calls.append(recipe)
        hashes = {}
        for name, relative in recipe["outputs"].items():
            path = root / relative
            path.write_bytes(name.encode())
            hashes[name] = sha(path)
        return {"output_hashes": hashes}

    monkeypatch.setattr(master, "assemble_whole_film", assemble)
    options = dict(ffmpeg=Path("unused"), ffprobe=Path("unused"))
    report = master.run_master(root, plan_path, **options)
    assert calls == [] and report["film"]["status"] == "waiting_for_review"
    record_review(root, plan_path, approval(report["chapters"]["C1"]["review"]))
    report = master.run_master(root, plan_path, **options)
    assert len(calls) == 1
    assert [a["kind"] for a in report["actions"]] == ["review_film"]
    review = approval(report["film"]["review"])
    review["checks"]["sound"] = "not_applicable"
    with pytest.raises(ValidationError, match="sound review"):
        record_review(root, plan_path, review)
    record_review(root, plan_path, approval(report["film"]["review"]))
    assert master.run_master(root, plan_path, **options)["actions"] == []
    assert len(calls) == 1


def test_render_dependencies_invalidate_and_missing_blocks(offline):
    root, _, manifest = offline
    shot = manifest["shots"][0]
    lock = write(root / "assets/environment.json", {"shader": "baseline", "renderer": "v1"})
    shot["render_dependencies"] = [{"path": "assets/environment.json", "sha256": sha(lock)}]
    shot["accepted_spec_digest"] = master._shot_spec_digest(shot, manifest)
    assert master.shot_status(root, manifest, shot, None)["status"] == "fresh"
    lock.unlink()
    assert "render_dependency_missing:assets/environment.json" in master.shot_status(root, manifest, shot, None)["reasons"]


def test_upstream_spec_change_revokes_chapter_review_even_if_bytes_identical(offline, monkeypatch):
    root, plan_path, manifest = offline
    approve_shots(root, plan_path)
    monkeypatch.setattr(master, "build_chapter", fake_chapter)
    report = master.run_master(root, plan_path, ffmpeg=Path("unused"), ffprobe=Path("unused"))
    previous = report["chapters"]["C1"]["review"]
    record_review(root, plan_path, approval(previous))
    manifest["shots"][0]["camera_track"]["keyframes"][0]["fov"] = 65
    # Synthetic render receipt: different camera specification, identical bytes.
    shot = manifest["shots"][0]
    write(root / "work/film-master/test-plan/shot-receipts.json", {"plan_id": "test-plan", "shots": {
        "one": {"output": shot["output"], "output_sha256": shot["output_sha256"],
                "spec_digest": master._shot_spec_digest(shot, manifest)}}})
    write(root / "assets/shots.json", manifest)
    plan = json.loads(plan_path.read_text())
    plan["shots_manifest"]["sha256"] = sha(root / "assets/shots.json")
    write(plan_path, plan)
    report = master.build_report(root, plan_path)
    assert report["shots"]["one"]["review"]["status"] == "needs_review"
    record_review(root, plan_path, approval(report["shots"]["one"]["review"]))
    report = master.build_report(root, plan_path)
    assert report["chapters"]["C1"]["status"] == "fresh"  # No unnecessary encoding.
    assert report["chapters"]["C1"]["review"]["status"] == "needs_review"
    assert report["chapters"]["C1"]["review"]["spec_digest"] != previous["spec_digest"]


@pytest.mark.parametrize("returncode, stderr, message", [
    (1, "filter failed", "inspection failed"),
    (0, "black_start:0 black_end:1", "rendered black"),
])
def test_failed_black_frame_inspection_never_publishes(offline, monkeypatch, returncode, stderr, message):
    from types import SimpleNamespace
    root, _, manifest = offline
    shot = manifest["shots"][0]
    (root / shot["output"]).unlink()
    instance = root / "game/instances/test"
    for pack in manifest["resourcepacks"].values():
        installed = instance / "resourcepacks" / pack["profile_id"].removeprefix("file/")
        installed.parent.mkdir(parents=True, exist_ok=True)
        installed.write_bytes((root / pack["path"]).read_bytes())
    replay = instance / "replays/m.mcpr"
    replay.parent.mkdir(parents=True)
    replay.write_bytes((root / "assets/replays/m.mcpr").read_bytes())

    class Photo:
        def __init__(self, *args, **kwargs):
            pass

        def require(self, name, *args):
            result = {
                "capabilities": {key: "replaymod" for key in ("replay_backend", "camera_backend", "render_backend")},
                "state": {"paused": False, "blocking_screen": False},
                "resourcepacks": {"enabled_profile_ids": shot["enabled_file_profiles"]},
            }[name]
            return SimpleNamespace(result=result)

        def open_master(self, *args):
            pass

        def render(self, master_id, master_hash, run_id, track, scratch, *args):
            scratch.write_bytes(b"rendered")

    monkeypatch.setattr(master, "ReplayPhotography", Photo)
    monkeypatch.setattr(master, "verify_render", lambda *a, **k: SimpleNamespace(model_dump=lambda **k: {}))
    monkeypatch.setattr(master.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=returncode, stderr=stderr))
    bridge = master.BridgeOptions(instance, "http://127.0.0.1:25575/rpc", "test-token")
    with pytest.raises(master.FilmMasterError, match=message):
        master.export_shot(root, manifest, shot, bridge, plan_id="test-plan", ffmpeg=Path("unused"), ffprobe=Path("unused"))
    assert not (root / shot["output"]).exists()

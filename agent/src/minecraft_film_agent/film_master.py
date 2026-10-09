"""Declarative master pipeline: replay shots -> chapters -> whole film.

This closes the workflow-gap-audit (2026-10-08): shot exports and chapter
edits become DATA (contracts/v3/film-shots / film-chapter / film-plan), and
one deterministic executor decides from hashes which shots must be re-exported
through the live bridge, which chapters must be rebuilt through edit-execute,
and whether the whole film must be reassembled through film-assembly.

Nothing is ever overwritten: re-exports publish to the declared output only
when it does not exist, chapters are rebuilt into freshly named outputs, and
each film assembly gets a fresh film_id. Preview is pure and writes nothing;
run leaves receipts and a journal under work/film-master/<plan_id>/.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .contracts import canonical_json, validate_against_contract_v3
from .edit import execute_edit
from .film_assembly import assemble as assemble_whole_film
from .locking import RunLease, write_json
from .media import verify_render
from .photography import ReplayPhotography, publish_file


class FilmMasterError(ValueError):
    pass


@dataclass
class BridgeOptions:
    """Live connection needed only when stale shots must be re-exported."""

    instance_dir: Path
    endpoint: str
    token: str
    timeout_seconds: float = 900.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise FilmMasterError(f"path leaves workspace: {name}")
    return path


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FilmMasterError(f"unreadable JSON {path}: {error}") from error


def load_plan(root: Path, plan_ref: Path) -> dict:
    plan = _read_json(plan_ref)
    validate_against_contract_v3(plan, "film-plan")
    root = root.resolve()
    for pin in [plan["shots_manifest"], *plan["chapters"]]:
        path = _resolve(root, pin["path"])
        if not path.is_file() or _hash_file(path) != pin["sha256"]:
            raise FilmMasterError(
                f"pinned file missing or changed; update the plan pin deliberately: {pin['path']}")
    return plan


def load_shots_manifest(root: Path, ref: str) -> dict:
    manifest = _read_json(_resolve(root, ref))
    validate_against_contract_v3(manifest, "film-shots")
    masters = manifest["masters"]
    pack_hashes = {entry["sha256"] for entry in manifest["resourcepacks"].values()}
    declared_profiles = [entry["profile_id"] for entry in manifest["resourcepacks"].values()]
    if len(set(declared_profiles)) != len(declared_profiles):
        raise FilmMasterError("resourcepack profile ids must be unique")
    seen: set[str] = set()
    for shot in manifest["shots"]:
        if shot["shot_id"] in seen:
            raise FilmMasterError(f"duplicate shot id: {shot['shot_id']}")
        seen.add(shot["shot_id"])
        master = masters.get(shot["master_id"])
        if master is None:
            raise FilmMasterError(f"shot {shot['shot_id']}: unknown master {shot['master_id']}")
        if master["sha256"] != shot["master_sha256"]:
            raise FilmMasterError(f"shot {shot['shot_id']}: master hash differs from masters table")
        if shot["resourcepack_sha256"] not in pack_hashes:
            raise FilmMasterError(f"shot {shot['shot_id']}: resourcepack hash is undeclared")
        active_packs = [entry for entry in manifest["resourcepacks"].values()
                        if entry["profile_id"] in shot["enabled_file_profiles"]]
        if len(active_packs) != len(shot["enabled_file_profiles"]) or not any(
                entry["sha256"] == shot["resourcepack_sha256"] for entry in active_packs):
            raise FilmMasterError(f"shot {shot['shot_id']}: enabled resourcepack stack is unpinned")
        start, end = shot["tick_range"]["start_tick"], shot["tick_range"]["end_tick"]
        if start >= end or (end - start) * shot["fps"] % 20:
            raise FilmMasterError(f"shot {shot['shot_id']}: tick range is not integral frames")
        ticks = [keyframe["tick"] for keyframe in shot["camera_track"]["keyframes"]]
        if min(ticks) < start or max(ticks) > end:
            raise FilmMasterError(f"shot {shot['shot_id']}: camera keyframes leave the tick range")
    return manifest


def load_chapter(root: Path, ref: str) -> dict:
    chapter = _read_json(_resolve(root, ref))
    validate_against_contract_v3(chapter, "film-chapter")
    items = sorted(chapter["timeline"], key=lambda item: item["timeline_start_seconds"])
    cursor = 0.0
    fps = chapter["video"]["fps"]
    for item in items:
        if abs(item["timeline_start_seconds"] - cursor) > 1e-9:
            raise FilmMasterError(f"chapter {chapter['chapter_id']}: timeline gap or overlap")
        if abs(item["duration_seconds"] * fps - round(item["duration_seconds"] * fps)) > 1e-6:
            raise FilmMasterError(f"chapter {chapter['chapter_id']}: clip is not integral frames")
        cursor += item["duration_seconds"]
    if abs(cursor - chapter["seconds"]) > 1e-6:
        raise FilmMasterError(
            f"chapter {chapter['chapter_id']}: timeline is {cursor}s but seconds declares {chapter['seconds']}s")
    for overlay in chapter.get("visual_overlays", []):
        if overlay["start_seconds"] >= overlay["end_seconds"] or overlay["end_seconds"] > cursor:
            raise FilmMasterError(f"chapter {chapter['chapter_id']}: visual overlay leaves timeline")
    return chapter


def _shot_spec_digest(shot: dict) -> str:
    spec = {key: shot[key] for key in ("master_id", "master_sha256", "camera_track", "tick_range",
                                       "resourcepack_sha256", "enabled_file_profiles", "width", "height", "fps", "output")}
    return hashlib.sha256(canonical_json(spec).encode("utf-8")).hexdigest()


def _master_dir(root: Path, plan_id: str) -> Path:
    return root / "work" / "film-master" / plan_id


def _load_receipts(root: Path, plan_id: str) -> dict:
    path = _master_dir(root, plan_id) / "shot-receipts.json"
    if not path.is_file():
        return {}
    receipts = _read_json(path)
    if receipts.get("plan_id") != plan_id:
        raise FilmMasterError(f"receipt journal belongs to another plan: {path}")
    return receipts.get("shots", {})


def _effective_output(shot: dict, receipt: dict | None) -> tuple[str, str]:
    """The output a shot currently stands for: the latest accepted re-export
    receipt when present, otherwise the manifest's original declaration."""

    if receipt:
        return receipt["output"], receipt["output_sha256"]
    return shot["output"], shot["output_sha256"]


def shot_status(root: Path, manifest: dict, shot: dict, receipt: dict | None) -> dict:
    reasons: list[str] = []
    output_name, output_sha = _effective_output(shot, receipt)
    if receipt and receipt.get("spec_digest") != _shot_spec_digest(shot):
        reasons.append("render_spec_changed_since_receipt")
    if receipt is None and shot["accepted_spec_digest"] != _shot_spec_digest(shot):
        reasons.append("accepted_render_spec_changed")
    output = _resolve(root, output_name)
    if not output.is_file():
        reasons.append("output_missing")
    elif _hash_file(output) != output_sha:
        reasons.append("output_hash_mismatch")
    master_file = _resolve(root, manifest["masters"][shot["master_id"]]["file"])
    if master_file.is_file() and _hash_file(master_file) != manifest["masters"][shot["master_id"]]["sha256"]:
        reasons.append("master_file_hash_mismatch")
    for pack in (entry for entry in manifest["resourcepacks"].values()
                 if entry["profile_id"] in shot["enabled_file_profiles"]):
        pinned = _resolve(root, pack["path"])
        if pinned.is_file() and _hash_file(pinned) != pack["sha256"]:
            reasons.append(f"resourcepack_changed:{pack['profile_id']}")
    info = {"status": "stale" if reasons else "fresh", "reasons": reasons,
            "output": output_name, "output_sha256": output_sha,
            "render_receipt": bool(receipt)}
    if receipt is None:
        info["notes"] = ["accepted_without_render_receipt"]
    return info


def chapter_shot_refs(chapter: dict) -> list[str]:
    return ([item["shot"] for item in chapter["timeline"] if "shot" in item]
            + [item["shot"] for item in chapter.get("visual_overlays", []) if "shot" in item])


def _verify_pinned_file(root: Path, pinned: dict, kind: str) -> str | None:
    """Returns a blocking reason when a hash-pinned material diverged."""

    path = _resolve(root, pinned["path"])
    if not path.is_file():
        return f"{kind}_missing"
    if _hash_file(path) != pinned["sha256"]:
        return f"{kind}_changed"
    return None


def chapter_inputs_digest(chapter: dict, manifest: dict, receipts: dict) -> str:
    shots = {shot["shot_id"]: shot for shot in manifest["shots"]}
    inputs: list[dict] = []
    for item in sorted(chapter["timeline"], key=lambda item: item["timeline_start_seconds"]):
        if "shot" in item:
            shot = shots.get(item["shot"])
            if shot is None:
                raise FilmMasterError(f"chapter {chapter['chapter_id']}: unknown shot {item['shot']}")
            _, sha = _effective_output(shot, receipts.get(item["shot"]))
            inputs.append({"shot": item["shot"], "sha256": sha,
                           "take_from_seconds": item["take_from_seconds"],
                           "duration_seconds": item["duration_seconds"],
                           "timeline_start_seconds": item["timeline_start_seconds"]})
        else:
            inputs.append({"clip": item["clip"]["path"], "sha256": item["clip"]["sha256"],
                           "kind": item["clip"].get("kind", "video"),
                           "take_from_seconds": item["take_from_seconds"],
                           "duration_seconds": item["duration_seconds"],
                           "timeline_start_seconds": item["timeline_start_seconds"]})
    payload = {
        "chapter_id": chapter["chapter_id"],
        "seconds": chapter["seconds"],
        "video": chapter["video"],
        "timeline": inputs,
        "audio": [{"source": clip["source"], "sha256": clip.get("sha256"),
                   "take_from_seconds": clip["take_from_seconds"],
                   "duration_seconds": clip["duration_seconds"],
                   "timeline_start_seconds": clip["timeline_start_seconds"],
                   "gain_db": clip.get("gain_db", 0.0),
                   "fade_in_seconds": clip.get("fade_in_seconds", 0.0),
                   "fade_out_seconds": clip.get("fade_out_seconds", 0.0)}
                  for clip in chapter.get("audio_clips", [])],
        "visual_overlays": [
            {**overlay, "source_sha256": _effective_output(shots[overlay["shot"]], receipts.get(overlay["shot"]))[1]}
            if "shot" in overlay else overlay
            for overlay in chapter.get("visual_overlays", [])],
        "variants": chapter["variants"],
        "outputs": chapter["outputs"],
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def chapter_status(root: Path, chapter: dict, manifest: dict, receipts: dict,
                   shot_infos: dict[str, dict]) -> dict:
    stale_shots = [shot_id for shot_id in chapter_shot_refs(chapter)
                   if shot_infos[shot_id]["status"] != "fresh"]
    if stale_shots:
        return {"status": "waiting_for_shots",
                "reasons": [f"shot {shot_id} is {shot_infos[shot_id]['status']}: "
                            f"{', '.join(shot_infos[shot_id]['reasons'])}" for shot_id in stale_shots]}
    for item in chapter["timeline"]:
        if "clip" in item:
            reason = _verify_pinned_file(root, item["clip"], "clip")
            if reason:
                return {"status": "blocked", "reasons": [f"imported {reason}: {item['clip']['path']}"]}
    for variant in ("clean", "subtitles"):
        for overlay in chapter["variants"][variant]["ass_overlays"]:
            reason = _verify_pinned_file(root, overlay, "ass_overlay")
            if reason:
                return {"status": "blocked", "reasons": [f"{reason}: {overlay['path']}"]}
    for clip in chapter.get("audio_clips", []):
        if "sha256" in clip:
            reason = _verify_pinned_file(root, {"path": clip["source"], "sha256": clip["sha256"]},
                                         "audio")
            if reason:
                return {"status": "blocked", "reasons": [f"{reason}: {clip['source']}"]}
    for overlay in chapter.get("visual_overlays", []):
        if "shot" in overlay:
            continue
        reason = _verify_pinned_file(root, {"path": overlay["source"], "sha256": overlay["sha256"]}, "visual_overlay")
        if reason:
            return {"status": "blocked", "reasons": [f"{reason}: {overlay['source']}"]}
    digest = chapter_inputs_digest(chapter, manifest, receipts)
    manifest_path = _resolve(root, chapter["outputs"]["manifest"])
    if not manifest_path.is_file():
        return {"status": "rebuild", "reasons": ["review_manifest_missing"], "inputs_digest": digest}
    proof = _read_json(manifest_path)
    if proof.get("inputs_digest") != digest:
        return {"status": "rebuild", "reasons": ["declared_inputs_changed"], "inputs_digest": digest}
    for variant in ("clean", "subtitles"):
        declared = chapter["outputs"][variant]
        output = _resolve(root, declared)
        if not output.is_file():
            return {"status": "rebuild", "reasons": [f"{variant}_output_missing"],
                    "inputs_digest": digest}
        entries = [entry for entry in proof.get("outputs", []) if entry.get("output") == declared]
        if not entries or entries[0].get("sha256") != _hash_file(output):
            return {"status": "blocked",
                    "reasons": [f"{variant}_output is not proven by its review manifest"],
                    "inputs_digest": digest}
    return {"status": "fresh", "reasons": [], "inputs_digest": digest,
            "seconds": chapter["seconds"],
            "outputs": {variant: {"path": chapter["outputs"][variant],
                                  "sha256": _hash_file(_resolve(root, chapter["outputs"][variant]))}
                        for variant in ("clean", "subtitles")},
            "manifest": chapter["outputs"]["manifest"],
            "manifest_sha256": _hash_file(manifest_path)}


def _film_receipt(root: Path, plan_id: str) -> dict | None:
    path = _master_dir(root, plan_id) / "film-receipt.json"
    return _read_json(path) if path.is_file() else None


def _film_chapters_digest(chapter_infos: dict[str, dict]) -> str:
    payload = [{"chapter_id": chapter_id,
                "manifest": info.get("manifest"), "manifest_sha256": info.get("manifest_sha256"),
                "outputs": info.get("outputs")}
               for chapter_id, info in chapter_infos.items()]
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _film_spec_digest(plan: dict) -> str:
    return hashlib.sha256(canonical_json(plan["film"]).encode("utf-8")).hexdigest()


def film_state(root: Path, plan: dict, chapter_infos: dict[str, dict]) -> dict:
    if "film" not in plan:
        return {"status": "skipped", "reasons": ["plan has no film section"]}
    pending = [chapter_id for chapter_id, info in chapter_infos.items()
               if info["status"] != "fresh"]
    if pending:
        return {"status": "waiting_for_chapters",
                "reasons": [f"chapter {chapter_id} is {chapter_infos[chapter_id]['status']}"
                            for chapter_id in pending]}
    reason = _verify_pinned_file(root, plan["film"]["audio"], "soundtrack")
    if reason:
        return {"status": "blocked", "reasons": [reason]}
    receipt = _film_receipt(root, plan["plan_id"])
    digest = _film_chapters_digest(chapter_infos)
    if receipt and receipt.get("chapters_digest") == digest and receipt.get("film_spec_digest") == _film_spec_digest(plan):
        broken = [name for name in ("clean", "subtitles")
                  if not (_resolve(root, receipt["outputs"][name]["path"]).is_file()
                          and _hash_file(_resolve(root, receipt["outputs"][name]["path"]))
                          == receipt["outputs"][name]["sha256"])]
        if not broken:
            return {"status": "fresh", "reasons": [], "film_id": receipt["film_id"]}
        return {"status": "blocked",
                "reasons": [f"assembled film {name} is missing or changed" for name in broken]}
    return {"status": "assemble", "reasons": ["no matching whole-film assembly receipt"]}


def build_report(root: Path, plan_ref: Path) -> dict:
    """Pure offline staleness report over the whole plan. Writes nothing."""

    root = root.resolve()
    plan = load_plan(root, plan_ref)
    manifest = load_shots_manifest(root, plan["shots_manifest"]["path"])
    receipts = _load_receipts(root, plan["plan_id"])
    shots = {shot["shot_id"]: shot for shot in manifest["shots"]}
    shot_infos = {shot_id: shot_status(root, manifest, shot, receipts.get(shot_id))
                  for shot_id, shot in shots.items()}
    chapters: dict[str, dict] = {}
    chapter_infos: dict[str, dict] = {}
    for pin in plan["chapters"]:
        chapter = load_chapter(root, pin["path"])
        if chapter["chapter_id"] in chapters:
            raise FilmMasterError(f"duplicate chapter id: {chapter['chapter_id']}")
        chapters[chapter["chapter_id"]] = chapter
        chapter_infos[chapter["chapter_id"]] = {"recipe": pin["path"]}
    for chapter_id, chapter in chapters.items():
        unknown = set(chapter_shot_refs(chapter)) - set(shots)
        if unknown:
            raise FilmMasterError(f"chapter {chapter_id}: unknown shots {sorted(unknown)}")
        chapter_infos[chapter_id].update(
            chapter_status(root, chapter, manifest, receipts, shot_infos))
    film_info = film_state(root, plan, chapter_infos)
    actions: list[dict] = []
    for shot_id, info in shot_infos.items():
        if info["status"] == "stale":
            actions.append({"kind": "export_shot", "shot_id": shot_id, "reasons": info["reasons"]})
    for chapter_id, info in chapter_infos.items():
        if info["status"] == "rebuild":
            actions.append({"kind": "rebuild_chapter", "chapter_id": chapter_id,
                            "reasons": info["reasons"]})
        elif info["status"] == "blocked":
            actions.append({"kind": "inspect_chapter", "chapter_id": chapter_id,
                            "reasons": info["reasons"]})
    if film_info["status"] in ("assemble", "blocked"):
        actions.append({"kind": "film_" + film_info["status"], "reasons": film_info["reasons"]})
    return {"ok": True, "plan_id": plan["plan_id"], "generated_utc": _utc_now(),
            "shots": shot_infos, "chapters": chapter_infos, "film": film_info,
            "actions": actions,
            "requires_live_bridge": any(action["kind"] == "export_shot" for action in actions)}


def export_shot(root: Path, manifest: dict, shot: dict, options: BridgeOptions,
                *, plan_id: str, ffmpeg: Path, ffprobe: Path) -> dict:
    """Re-export one shot through the live ReplayMod bridge. Fail-closed:
    the scratch render and the published output must both be absent."""

    root = root.resolve()
    instance = options.instance_dir.resolve()
    if not instance.is_dir():
        raise FilmMasterError(f"instance dir is missing: {instance}")
    master = manifest["masters"][shot["master_id"]]
    source_master = _resolve(root, master["file"])
    if not source_master.is_file() or _hash_file(source_master) != master["sha256"]:
        raise FilmMasterError(f"pinned replay master is missing or changed: {master['file']}")
    for pack in (entry for entry in manifest["resourcepacks"].values()
                 if entry["profile_id"] in shot["enabled_file_profiles"]):
        pinned = _resolve(root, pack["path"])
        if not pinned.is_file() or _hash_file(pinned) != pack["sha256"]:
            raise FilmMasterError(f"pinned resourcepack is missing or changed: {pack['path']}")
    run_id = re.sub(r"[^A-Za-z0-9_.-]", "-",
                    f"reexport-{plan_id[:24]}-{shot['shot_id'][:20]}-{_shot_spec_digest(shot)[:12]}")[:80]
    output = _resolve(root, shot["output"])
    if output.exists():
        raise FilmMasterError(
            f"shot {shot['shot_id']} output already exists; declare a new output path: {shot['output']}")
    from .bridge_client import CinematicBridgeClient, CinematicBridgeConfig
    client = CinematicBridgeClient(
        CinematicBridgeConfig(options.endpoint, options.token, min(options.timeout_seconds, 30.0)))
    photo = ReplayPhotography(client, run_id, timeout=options.timeout_seconds)
    capabilities = photo.require("capabilities", "bridge.capabilities", {}).result
    if any(capabilities.get(name) != "replaymod"
           for name in ("replay_backend", "camera_backend", "render_backend")):
        raise FilmMasterError("pinned ReplayMod photography unavailable")
    state = photo.require("state", "bridge.get_game_state", {}).result
    if state.get("paused") or state.get("blocking_screen"):
        raise FilmMasterError("game is paused or a blocking screen is active")
    active = photo.require("resourcepacks", "bridge.get_resourcepacks", {}).result
    enabled = active.get("enabled_profile_ids")
    if not isinstance(enabled, list):
        raise FilmMasterError("bridge did not prove the enabled resourcepack stack")
    enabled_files = [item for item in enabled if isinstance(item, str) and item.startswith("file/")]
    if enabled_files != shot["enabled_file_profiles"]:
        raise FilmMasterError(
            f"active file resourcepacks differ from plan: {enabled_files} != {shot['enabled_file_profiles']}")
    for pack in (entry for entry in manifest["resourcepacks"].values()
                 if entry["profile_id"] in shot["enabled_file_profiles"]):
        installed = (instance / "resourcepacks" / pack["profile_id"].removeprefix("file/")).resolve()
        if not installed.is_relative_to(instance / "resourcepacks") or not installed.is_file():
            raise FilmMasterError(f"enabled resourcepack file is missing: {pack['profile_id']}")
        if _hash_file(installed) != pack["sha256"]:
            raise FilmMasterError(f"enabled resourcepack hash differs from plan: {pack['profile_id']}")
    installed_master = (instance / "replays" / f"{shot['master_id']}.mcpr").resolve()
    if not installed_master.is_relative_to(instance / "replays") or not installed_master.is_file():
        raise FilmMasterError(f"replay master is not installed in the game instance: {shot['master_id']}")
    if _hash_file(installed_master) != shot["master_sha256"]:
        raise FilmMasterError(f"installed replay master hash differs from plan: {shot['master_id']}")
    photo.open_master(shot["master_id"], "sha256:" + shot["master_sha256"])
    scratch = instance / "bridge-renders" / run_id / f"{run_id}.mp4"
    if scratch.exists():
        raise FilmMasterError(f"scratch render already exists: {scratch}")
    scratch.parent.mkdir(parents=True, exist_ok=True)
    photo.render(shot["master_id"], "sha256:" + shot["master_sha256"], run_id,
                 shot["camera_track"], scratch,
                 shot["tick_range"]["start_tick"], shot["tick_range"]["end_tick"],
                 shot["width"], shot["height"], shot["fps"])
    accepted = verify_render(scratch, expected_width=shot["width"], expected_height=shot["height"],
                             expected_fps=shot["fps"],
                             expected_min_duration_seconds=(shot["tick_range"]["end_tick"]
                                                            - shot["tick_range"]["start_tick"]) / 20,
                             expected_duration_seconds=(shot["tick_range"]["end_tick"]
                                                        - shot["tick_range"]["start_tick"]) / 20,
                             expected_frames=(shot["tick_range"]["end_tick"]
                                              - shot["tick_range"]["start_tick"]) * shot["fps"] // 20,
                             require_decode=True, ffmpeg_path=ffmpeg, ffprobe_path=ffprobe)
    black = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-i", str(scratch),
         "-vf", "blackdetect=d=0.1:pix_th=0.02:pic_th=0.98", "-an", "-f", "null", "-"],
        capture_output=True, text=True, timeout=900, check=False)
    if "black_start:" in black.stderr:
        raise FilmMasterError(
            f"shot {shot['shot_id']} rendered black; inspect {scratch} and delete it after review")
    publish_file(scratch, output)
    return {"output": shot["output"], "output_sha256": _hash_file(output),
            "spec_digest": _shot_spec_digest(shot),
            "exported_utc": _utc_now(),
            "media": accepted.model_dump(mode="json")}


def compile_chapter_edits(chapter: dict, manifest: dict, receipts: dict,
                          *, edit_id_prefix: str) -> dict[str, dict]:
    """Deterministically compile one chapter recipe into two edit lists
    (clean/subtitles) that execute_edit accepts."""

    shots = {shot["shot_id"]: shot for shot in manifest["shots"]}
    clips: list[dict] = []
    for item in sorted(chapter["timeline"], key=lambda item: item["timeline_start_seconds"]):
        if "shot" in item:
            source, sha = _effective_output(shots[item["shot"]], receipts.get(item["shot"]))
        else:
            source, sha = item["clip"]["path"], item["clip"]["sha256"]
        clips.append({"source": source, "sha256": sha,
                      "kind": item.get("clip", {}).get("kind", "video"),
                      "take_from_seconds": item["take_from_seconds"],
                      "duration_seconds": item["duration_seconds"],
                      "timeline_start_seconds": item["timeline_start_seconds"],
                      "note": item.get("note", "")})
    edits: dict[str, dict] = {}
    for variant in ("clean", "subtitles"):
        edit_id = f"{edit_id_prefix}-{variant}"
        if not re.fullmatch(r"[a-z0-9_-]{2,64}", edit_id):
            raise FilmMasterError(f"compiled edit id is invalid: {edit_id}")
        edits[variant] = {
            "schema_version": 3,
            "edit_id": edit_id,
            "output": {"path": chapter["outputs"][variant], "width": chapter["video"]["width"],
                       "height": chapter["video"]["height"], "fps": chapter["video"]["fps"],
                       "container": "mp4"},
            "video_clips": [{key: clip[key] for key in
                             ("source", "kind", "take_from_seconds", "duration_seconds",
                              "timeline_start_seconds", "note")} for clip in clips],
            "audio_clips": [{key: clip[key] for key in
                             ("source", "take_from_seconds", "duration_seconds",
                              "timeline_start_seconds", "gain_db", "fade_in_seconds",
                              "fade_out_seconds", "note") if key in clip}
                            for clip in chapter.get("audio_clips", [])],
            "ass_overlays": [{"path": overlay["path"]}
                             for overlay in chapter["variants"][variant]["ass_overlays"]],
            "visual_overlays": [
                {**{key: value for key, value in overlay.items() if key not in ("sha256", "shot")},
                 "source": _effective_output(shots[overlay["shot"]], receipts.get(overlay["shot"]))[0]}
                if "shot" in overlay else {key: value for key, value in overlay.items() if key != "sha256"}
                for overlay in chapter.get("visual_overlays", [])],
        }
    return edits


def build_chapter(root: Path, chapter: dict, manifest: dict, receipts: dict, *,
                  plan_id: str, ffmpeg: Path, ffprobe: Path) -> dict:
    """Rebuild one chapter into its declared (absent) outputs and write the
    review manifest that later staleness decisions are derived from."""

    root = root.resolve()
    chapter_id = chapter["chapter_id"]
    for item in chapter["timeline"]:
        if "clip" in item:
            path = _resolve(root, item["clip"]["path"])
            if not path.is_file() or _hash_file(path) != item["clip"]["sha256"]:
                raise FilmMasterError(f"imported clip changed: {item['clip']['path']}")
    for variant in ("clean", "subtitles"):
        for overlay in chapter["variants"][variant]["ass_overlays"]:
            path = _resolve(root, overlay["path"])
            if not path.is_file() or _hash_file(path) != overlay["sha256"]:
                raise FilmMasterError(f"ass overlay changed: {overlay['path']}")
    for clip in chapter.get("audio_clips", []):
        if "sha256" in clip:
            path = _resolve(root, clip["source"])
            if not path.is_file() or _hash_file(path) != clip["sha256"]:
                raise FilmMasterError(f"audio material changed: {clip['source']}")
    for overlay in chapter.get("visual_overlays", []):
        if "shot" in overlay:
            continue
        path = _resolve(root, overlay["source"])
        if not path.is_file() or _hash_file(path) != overlay["sha256"]:
            raise FilmMasterError(f"visual overlay changed: {overlay['source']}")
    for variant in ("clean", "subtitles"):
        if _resolve(root, chapter["outputs"][variant]).exists():
            raise FilmMasterError(
                f"chapter {chapter_id} {variant} output already exists; declare new versioned paths")
    manifest_path = _resolve(root, chapter["outputs"]["manifest"])
    if manifest_path.exists():
        raise FilmMasterError(
            f"chapter {chapter_id} review manifest already exists: {chapter['outputs']['manifest']}")
    edits = compile_chapter_edits(chapter, manifest, receipts,
                                  edit_id_prefix=f"{plan_id}-{chapter_id.lower()}")
    digest = chapter_inputs_digest(chapter, manifest, receipts)
    outputs: list[dict] = []
    verification: dict[str, dict] = {}
    for variant in ("clean", "subtitles"):
        # Evidence is keyed by the declared output stem: rebuilds always use
        # freshly named outputs, so the evidence dirs can never collide.
        stem = Path(chapter["outputs"][variant]).stem
        evidence = _master_dir(root, plan_id) / "chapters" / chapter_id / f"{stem}-{variant}"
        if evidence.exists():
            raise FilmMasterError(
                f"evidence dir already exists for {chapter_id}/{variant}; use a new plan_id: {evidence}")
        report = execute_edit(edits[variant], workspace=root, evidence_dir=evidence,
                              ffmpeg=ffmpeg, ffprobe=ffprobe)
        output = _resolve(root, chapter["outputs"][variant])
        outputs.append({"output": chapter["outputs"][variant], "sha256": _hash_file(output)})
        verification[variant] = report["media"]
    proof = {"chapter_id": chapter_id, "seconds": chapter["seconds"], "video": chapter["video"],
             "inputs_digest": digest,
             "shots_manifest": {"path": chapter["shots_manifest"],
                                "sha256": _hash_file(_resolve(root, chapter["shots_manifest"]))},
             "outputs": outputs, "verification": verification,
             "inputs": {entry["output"]: entry["sha256"] for entry in outputs},
             "built_utc": _utc_now()}
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(manifest_path, proof)
    return {"chapter_id": chapter_id, "inputs_digest": digest, "outputs": outputs,
            "manifest": chapter["outputs"]["manifest"],
            "manifest_sha256": _hash_file(manifest_path)}


def _generate_film_recipe(plan: dict, chapter_infos: dict[str, dict], film_id: str) -> dict:
    chapters = []
    for chapter_id, info in chapter_infos.items():
        chapters.append({"scene": chapter_id, "seconds": info["seconds"],
                         "manifest": info["manifest"], "manifest_sha256": info["manifest_sha256"],
                         "clean": info["outputs"]["clean"], "subtitles": info["outputs"]["subtitles"]})
    return {"schema_version": 1, "film_id": film_id, "video": plan["video"],
            "chapters": chapters, "audio": plan["film"]["audio"],
            "outputs": {variant: plan["film"]["outputs"][variant].format(film_id=film_id)
                        for variant in ("clean", "subtitles")}}


def run_master(root: Path, plan_ref: Path, *, ffmpeg: Path, ffprobe: Path,
               bridge: BridgeOptions | None = None) -> dict:
    """Execute the plan: stale shots -> stale chapters -> whole film.

    Every stage appends to the plan journal; a stage is skipped when the
    report already considers its output fresh. Shot re-export requires the
    live bridge and fails closed when it was not provided.
    """

    root = root.resolve()
    report = build_report(root, plan_ref)
    plan = load_plan(root, plan_ref)
    plan_id = plan["plan_id"]
    journal_path = _master_dir(root, plan_id) / "master-journal.json"
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with RunLease(journal_path.with_name("master-journal.lock")):
        journal = {"plan_id": plan_id, "plan": plan_ref.name,
                   "started_utc": _utc_now(), "stages": [], "status": "running"}
        if journal_path.exists():
            previous = _read_json(journal_path)
            if previous.get("status") == "running":
                raise FilmMasterError(
                    f"journal shows an unresolved run; inspect {journal_path} and use a new plan_id")
            journal["previous_runs"] = int(previous.get("previous_runs", 0)) + 1
        write_json(journal_path, journal)
        try:
            if report["requires_live_bridge"]:
                if bridge is None:
                    raise FilmMasterError(
                        "stale shots require the live bridge; pass --instance-dir and --endpoint "
                        "(fail-closed: no shot was re-exported and nothing was written)")
                manifest = load_shots_manifest(root, plan["shots_manifest"]["path"])
                shots = {shot["shot_id"]: shot for shot in manifest["shots"]}
                receipts = _load_receipts(root, plan_id)
                for action in report["actions"]:
                    if action["kind"] != "export_shot":
                        continue
                    shot = shots[action["shot_id"]]
                    if shot_status(root, manifest, shot, receipts.get(shot["shot_id"]))["status"] == "fresh":
                        continue
                    receipt = export_shot(root, manifest, shot, bridge, plan_id=plan_id,
                                          ffmpeg=ffmpeg, ffprobe=ffprobe)
                    receipts[shot["shot_id"]] = receipt
                    write_json(_master_dir(root, plan_id) / "shot-receipts.json",
                               {"plan_id": plan_id, "shots": receipts})
                    journal["stages"].append({"kind": "export_shot", "shot_id": shot["shot_id"],
                                              "receipt": receipt, "utc": _utc_now()})
                    write_json(journal_path, journal)
                report = build_report(root, plan_ref)
            chapters_by_id = {load_chapter(root, pin["path"])["chapter_id"]: pin["path"]
                              for pin in plan["chapters"]}
            for action in report["actions"]:
                if action["kind"] != "rebuild_chapter":
                    continue
                chapter = load_chapter(root, chapters_by_id[action["chapter_id"]])
                manifest = load_shots_manifest(root, plan["shots_manifest"]["path"])
                receipt = build_chapter(root, chapter, manifest, _load_receipts(root, plan_id),
                                        plan_id=plan_id, ffmpeg=ffmpeg, ffprobe=ffprobe)
                journal["stages"].append({"kind": "rebuild_chapter", "receipt": receipt,
                                          "utc": _utc_now()})
                write_json(journal_path, journal)
            report = build_report(root, plan_ref)
            if report["film"]["status"] == "assemble":
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                film_id = f"{plan_id[:31]}-{stamp}"
                recipe = _generate_film_recipe(plan, report["chapters"], film_id)
                (_master_dir(root, plan_id) / "film-recipe.json").write_text(
                    json.dumps(recipe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                assembled = assemble_whole_film(recipe, root=root, ffmpeg=ffmpeg, ffprobe=ffprobe)
                receipt = {"film_id": film_id,
                           "chapters_digest": _film_chapters_digest(report["chapters"]),
                           "film_spec_digest": _film_spec_digest(plan),
                           "outputs": {variant: {"path": recipe["outputs"][variant],
                                                 "sha256": assembled["output_hashes"][variant]}
                                       for variant in ("clean", "subtitles")},
                           "assembled_utc": _utc_now()}
                write_json(_master_dir(root, plan_id) / "film-receipt.json", receipt)
                journal["stages"].append({"kind": "assemble_film", "film_id": film_id,
                                          "receipt": receipt, "utc": _utc_now()})
                write_json(journal_path, journal)
                report = build_report(root, plan_ref)
            outstanding = [action for action in report["actions"]
                           if action["kind"] in ("inspect_chapter", "film_blocked")]
            if outstanding:
                journal["status"] = "blocked"
                journal["blocked"] = outstanding
                journal["finished_utc"] = _utc_now()
                write_json(journal_path, journal)
                raise FilmMasterError(f"plan has blocked items needing human inspection: {outstanding}")
            if report["actions"]:
                raise FilmMasterError(
                    "run finished but actions remain; this is an executor bug, inspect the journal")
            journal["status"] = "succeeded"
            journal["finished_utc"] = _utc_now()
            journal["final_report"] = {key: report[key] for key in
                                       ("shots", "chapters", "film", "actions")}
            write_json(journal_path, journal)
            return report
        except BaseException as error:
            journal["status"] = "failed"
            journal["error"] = str(error)
            journal["finished_utc"] = _utc_now()
            write_json(journal_path, journal)
            raise

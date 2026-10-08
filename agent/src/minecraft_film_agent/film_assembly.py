"""Assemble accepted chapter renders with one continuous soundtrack.

This is a fixed command plan driven by contracts/v3/film-assembly.schema.json.
It does not record actors or reuse old pictures after an appearance change.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from .contracts import validate_against_contract_v3
from .media import verify_render


class FilmAssemblyError(ValueError):
    pass


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise FilmAssemblyError(f"path leaves workspace: {name}")
    return path


def _run(argv: list[str], *, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout, check=False)
    if result.returncode:
        raise FilmAssemblyError(f"command failed ({result.returncode}): {result.stderr[-2000:]}")
    return result


def _decoded_audio_hash(path: Path, ffmpeg: Path) -> str:
    process = subprocess.Popen([str(ffmpeg), "-v", "error", "-i", str(path),
                                "-f", "s16le", "-acodec", "pcm_s16le", "-ar", "48000",
                                "-ac", "2", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    digest = hashlib.sha256()
    assert process.stdout is not None
    for block in iter(lambda: process.stdout.read(1024 * 1024), b""):
        digest.update(block)
    process.stdout.close()
    assert process.stderr is not None
    error = process.stderr.read().decode("utf-8", errors="replace")
    if process.wait(timeout=120) or error.strip():
        raise FilmAssemblyError(f"continuous audio decode failed: {error[-1000:]}")
    return digest.hexdigest()


def preflight(recipe: dict, *, root: Path, ffmpeg: Path, ffprobe: Path) -> dict:
    validate_against_contract_v3(recipe, "film-assembly")
    root = root.resolve()
    if not ffmpeg.is_file() or not ffprobe.is_file():
        raise FilmAssemblyError("explicit FFmpeg and ffprobe executables are required")
    if recipe["video"]["width"] * 9 != recipe["video"]["height"] * 16:
        raise FilmAssemblyError("this whole-film preset requires 16:9 video")
    ids = [chapter["scene"] for chapter in recipe["chapters"]]
    if len(ids) != len(set(ids)) or ids[-1] != "credits":
        raise FilmAssemblyError("chapter IDs must be unique and end with credits")
    total_seconds = sum(chapter["seconds"] for chapter in recipe["chapters"])
    if total_seconds > 3600:
        raise FilmAssemblyError("film exceeds 3600-second limit")
    source_hashes: dict[str, str] = {}
    for chapter in recipe["chapters"]:
        manifest = _resolve(root, chapter["manifest"])
        if not manifest.is_file() or _hash_file(manifest) != chapter["manifest_sha256"]:
            raise FilmAssemblyError(f"chapter manifest missing or changed: {chapter['scene']}")
        evidence = json.loads(manifest.read_text(encoding="utf-8"))
        declared = evidence.get("outputs") or [evidence]
        source_hashes[chapter["manifest"]] = chapter["manifest_sha256"]
        for variant in ("clean", "subtitles"):
            source = chapter[variant]
            path = _resolve(root, source["path"])
            if not path.is_file() or _hash_file(path) != source["sha256"]:
                raise FilmAssemblyError(f"chapter source missing or changed: {chapter['scene']} {variant}")
            if not any((Path(item.get("output", "")) if Path(item.get("output", "")).is_absolute()
                        else root / item.get("output", "")).resolve() == path
                       and item.get("sha256") == source["sha256"] for item in declared):
                raise FilmAssemblyError(f"chapter source lacks matching manifest proof: {chapter['scene']} {variant}")
            source_hashes[source["path"]] = source["sha256"]
            probe = json.loads(_run([str(ffprobe), "-v", "error", "-show_streams", "-show_format",
                                     "-of", "json", str(path)], timeout=60).stdout)
            videos = [s for s in probe["streams"] if s.get("codec_type") == "video"]
            if len(videos) != 1:
                raise FilmAssemblyError(f"expected one video stream: {source['path']}")
            video = videos[0]
            if (video.get("codec_name") != "h264" or video.get("width") != recipe["video"]["width"]
                    or video.get("height") != recipe["video"]["height"]
                    or int(video.get("nb_frames", 0)) != chapter["seconds"] * recipe["video"]["fps"]):
                raise FilmAssemblyError(f"chapter video spec mismatch: {source['path']}")
            if abs(float(video.get("duration", probe["format"]["duration"])) - chapter["seconds"]) > 1 / recipe["video"]["fps"]:
                raise FilmAssemblyError(f"chapter duration mismatch: {source['path']}")
    audio = recipe["audio"]
    audio_path = _resolve(root, audio["path"])
    if not audio_path.is_file() or _hash_file(audio_path) != audio["sha256"]:
        raise FilmAssemblyError("continuous soundtrack missing or changed")
    audio_probe = json.loads(_run([str(ffprobe), "-v", "error", "-show_streams", "-of", "json",
                                   str(audio_path)], timeout=60).stdout)
    audio_streams = [stream for stream in audio_probe["streams"] if stream.get("codec_type") == "audio"]
    if len(audio_streams) != 1 or int(audio_streams[0].get("sample_rate", 0)) != audio["sample_rate"] or audio_streams[0].get("channels") != audio["channels"]:
        raise FilmAssemblyError("continuous soundtrack format mismatch")
    if _decoded_audio_hash(audio_path, ffmpeg) != audio["decoded_pcm_sha256"]:
        raise FilmAssemblyError("decoded soundtrack differs from pinned PCM")
    source_hashes[audio["path"]] = audio["sha256"]
    for variant in ("clean", "subtitles"):
        output = _resolve(root, recipe["outputs"][variant])
        if not (output.is_relative_to(root / "work") or output.is_relative_to(root / "assets" / "renders")):
            raise FilmAssemblyError("output must be under work/ or assets/renders/")
        if output.exists():
            raise FilmAssemblyError(f"output already exists: {recipe['outputs'][variant]}")
    return {"ok": True, "film_id": recipe["film_id"], "chapters": ids,
            "duration_seconds": total_seconds, "frames": total_seconds * recipe["video"]["fps"],
            "input_hashes": source_hashes, "outputs": recipe["outputs"]}


def assemble(recipe: dict, *, root: Path, ffmpeg: Path, ffprobe: Path) -> dict:
    root = root.resolve()
    report = preflight(recipe, root=root, ffmpeg=ffmpeg, ffprobe=ffprobe)
    evidence = root / "work" / "film-assembly" / recipe["film_id"]
    evidence.mkdir(parents=True, exist_ok=False)
    staged: dict[str, Path] = {}
    commands: list[list[str]] = []
    diagnostics: dict[str, dict] = {}
    try:
        for variant in ("clean", "subtitles"):
            playlist = evidence / f"{variant}.concat.txt"
            playlist.write_text("".join("file '" + _resolve(root, chapter[variant]["path"]).as_posix().replace("'", "'\\''") + "'\n"
                                        for chapter in recipe["chapters"]), encoding="utf-8")
            temporary = evidence / f"{variant}.mp4"
            command = [str(ffmpeg), "-v", "warning", "-n", "-f", "concat", "-safe", "0",
                       "-i", str(playlist), "-i", str(_resolve(root, recipe["audio"]["path"])),
                       "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
                       "-b:a", "192k", "-t", str(report["duration_seconds"]),
                       "-movflags", "+faststart", str(temporary)]
            commands.append(command)
            result = _run(command)
            (evidence / f"{variant}.ffmpeg.log").write_text(result.stderr, encoding="utf-8")
            if "Non-monotonic" in result.stderr:
                raise FilmAssemblyError(f"non-monotonic timestamps: {variant}")
            accepted = verify_render(temporary, expected_width=recipe["video"]["width"],
                                     expected_height=recipe["video"]["height"],
                                     expected_fps=recipe["video"]["fps"],
                                     expected_min_duration_seconds=report["duration_seconds"],
                                     expected_duration_seconds=report["duration_seconds"],
                                     expected_frames=report["frames"], require_decode=True,
                                     ffmpeg_path=ffmpeg, ffprobe_path=ffprobe)
            if not accepted.full_decode_passed or not accepted.cfr_passed or not any(s.kind == "audio" for s in accepted.streams):
                raise FilmAssemblyError(f"whole-film media validation failed: {variant}")
            black = _run([str(ffmpeg), "-hide_banner", "-i", str(temporary),
                          "-vf", "blackdetect=d=0.1:pix_th=0.02:pic_th=0.98",
                          "-an", "-f", "null", "-"], timeout=900)
            (evidence / f"{variant}.blackdetect.log").write_text(black.stderr, encoding="utf-8")
            if "black_start:" in black.stderr:
                raise FilmAssemblyError(f"black interval found: {variant}")
            packet_data = json.loads(_run([str(ffprobe), "-v", "error", "-select_streams", "a:0",
                                           "-show_packets", "-show_entries", "packet=dts_time",
                                           "-of", "json", str(temporary)], timeout=120).stdout)
            stamps = [float(packet["dts_time"]) for packet in packet_data["packets"]]
            gaps = [right-left for left, right in zip(stamps, stamps[1:])]
            if not gaps or min(gaps) <= 0 or max(gaps) >= .025:
                raise FilmAssemblyError(f"audio packet timestamps are not continuous: {variant}")
            diagnostics[variant] = {"full_decode_passed": True, "cfr_passed": True,
                                    "blackdetect_passed": True, "audio_packets": len(stamps),
                                    "audio_packet_min_gap_seconds": min(gaps),
                                    "audio_packet_max_gap_seconds": max(gaps)}
            staged[variant] = temporary
        # Both editions must carry exactly the same encoded continuous audio.
        audio_hashes = []
        for variant in ("clean", "subtitles"):
            raw = subprocess.run([str(ffmpeg), "-v", "error", "-i", str(staged[variant]),
                                  "-map", "0:a:0", "-c", "copy", "-f", "adts", "-"],
                                 capture_output=True, timeout=120, check=True).stdout
            audio_hashes.append(hashlib.sha256(raw).hexdigest())
        if audio_hashes[0] != audio_hashes[1]:
            raise FilmAssemblyError("clean and subtitles audio bitstreams differ")
        # A source mutation during encoding invalidates publication.
        for name, digest in report["input_hashes"].items():
            if _hash_file(_resolve(root, name)) != digest:
                raise FilmAssemblyError(f"input changed during assembly: {name}")
        published = []
        try:
            for variant in ("clean", "subtitles"):
                destination = _resolve(root, recipe["outputs"][variant])
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as target, staged[variant].open("rb") as source:
                    published.append(destination)
                    shutil.copyfileobj(source, target)
            report.update(status="succeeded", audio_adts_sha256=audio_hashes[0],
                          output_hashes={variant: _hash_file(_resolve(root, recipe["outputs"][variant]))
                                         for variant in ("clean", "subtitles")},
                          diagnostics=diagnostics, commands=commands)
            (evidence / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return report
        except Exception:
            for destination in published:
                destination.unlink(missing_ok=True)
            raise
    except Exception as exc:
        (evidence / "failure.json").write_text(json.dumps({"status": "failed", "error": str(exc),
                                                          "commands": commands}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise

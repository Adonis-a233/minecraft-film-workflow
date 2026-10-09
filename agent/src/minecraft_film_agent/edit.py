"""Deterministic edit assembly (workflow v3 §7-P4).

The edit is DATA (contracts/v3/edit-list.schema.json); this module turns it
into a FIXED argv sequence — trims → concat → subtitles → audio mix → final
mux — with all timestamps in absolute seconds on the output timeline. No
interactive editing, no hand-timed cuts; the same EditList always produces
the same commands, and the result is only "done" when media.py accepts the
file.
"""

from __future__ import annotations

from pathlib import Path
import math

from .contracts import ContractError, validate_against_contract_v3


class EditPlanError(ValueError):
    pass


def load_edit_list(edit: dict) -> dict:
    try:
        validate_against_contract_v3(edit, "edit-list")
    except ContractError as error:
        raise EditPlanError(f"edit list rejected: {error}") from error
    if any(edit["output"][axis] % 2 for axis in ("width","height")):
        raise EditPlanError("yuv420p output dimensions must be even")
    # Overlap and coverage invariants beyond the schema.
    clips = sorted(edit["video_clips"], key=lambda clip: clip["timeline_start_seconds"])
    cursor = 0.0
    fps = edit["output"]["fps"]
    for clip in clips:
        for key in ("take_from_seconds", "duration_seconds", "timeline_start_seconds"):
            if not math.isfinite(clip[key]): raise EditPlanError("clip times must be finite")
        if abs(clip["timeline_start_seconds"] - cursor) > 1e-9:
            raise EditPlanError("video timeline has a gap or overlap; explicit gap clips are required")
        if abs(clip["duration_seconds"] * fps - round(clip["duration_seconds"] * fps)) > 1e-6:
            raise EditPlanError("clip duration must produce integral frames")
        cursor += clip["duration_seconds"]
    for earlier, later in zip(clips, clips[1:]):
        earlier_end = earlier["timeline_start_seconds"] + earlier["duration_seconds"]
        if later["timeline_start_seconds"] + 1e-9 < earlier_end:
            raise EditPlanError(
                f"video clips overlap on the timeline at {later['timeline_start_seconds']}s "
                f"(previous clip runs until {earlier_end}s)")
    for subtitle in edit.get("subtitles", []):
        if subtitle["end_seconds"] <= subtitle["start_seconds"]:
            raise EditPlanError("subtitle end must be after start")
    for clip in edit.get("audio_clips", []):
        for key in ("take_from_seconds", "duration_seconds", "timeline_start_seconds", "gain_db", "fade_in_seconds", "fade_out_seconds"):
            if not math.isfinite(clip.get(key, 0)): raise EditPlanError("audio values must be finite")
        if clip["timeline_start_seconds"] + clip["duration_seconds"] > cursor + 1e-9:
            raise EditPlanError("audio extends beyond the video timeline")
        if max(clip.get("fade_in_seconds",0), clip.get("fade_out_seconds",0)) > clip["duration_seconds"]:
            raise EditPlanError("audio fade exceeds clip duration")
    if any(not math.isfinite(s[k]) for s in edit.get("subtitles", []) for k in ("start_seconds","end_seconds")):
        raise EditPlanError("subtitle times must be finite")
    if any(s["end_seconds"] > cursor for s in edit.get("subtitles", [])):
        raise EditPlanError("subtitle extends beyond the video timeline")
    for overlay in edit.get("visual_overlays", []):
        start, end = overlay["start_seconds"], overlay["end_seconds"]
        if not all(math.isfinite(value) for value in (start, end, overlay.get("speed", 1))):
            raise EditPlanError("visual overlay times and speed must be finite")
        if start >= end or end > cursor + 1e-9:
            raise EditPlanError("visual overlay leaves the video timeline")
        if overlay["x"] + overlay["width"] > edit["output"]["width"] or overlay["y"] + overlay["height"] > edit["output"]["height"]:
            raise EditPlanError("visual overlay leaves the output frame")
        if overlay["kind"] == "image" and (overlay.get("take_from_seconds", 0) or overlay.get("speed", 1) != 1):
            raise EditPlanError("still image overlays cannot have video timing")
    return {**edit, "video_clips": clips}


def _quote_filter_path(path: Path) -> str:
    """ffmpeg filter args need their own escaping: ' and : and \\."""

    return "'" + str(path).replace("\\", "/").replace(":", "\\:").replace("'", "'\\\\\\''") + "'"


def build_ffmpeg_plan(edit: dict) -> list[list[str]]:
    """The deterministic argv sequence for one EditList.

    Stage 1 trims every clip to an intermediate segment; stage 2 concats the
    segments; stage 3 burns subtitles (if any); stage 4 mixes audio (if any)
    into the final mux. Segments land beside the output under ``<edit_id>.``.
    """

    edit = load_edit_list(edit)
    output = Path(edit["output"]["path"])
    width = edit["output"]["width"]
    height = edit["output"]["height"]
    fps = edit["output"]["fps"]
    container = edit["output"].get("container", "mp4")
    edit_id = edit["edit_id"]
    plan: list[list[str]] = []

    scale = f"setpts=PTS-STARTPTS,scale={width}:{height}:force_original_aspect_ratio=decrease," \
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}"
    segments: list[Path] = []
    for index, clip in enumerate(edit["video_clips"]):
        segment = output.parent / f"{edit_id}.segment-{index:03d}.mp4"
        segments.append(segment)
        image_input = ["-loop", "1", "-framerate", str(fps)] if clip.get("kind") == "image" else ["-ss", f"{clip['take_from_seconds']:.3f}"]
        plan.append([
            "ffmpeg", "-y", "-v", "error",
            *image_input,
            "-t", f"{clip['duration_seconds']:.3f}",
            "-i", clip["source"],
            "-vf", scale,
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-video_track_timescale", str(fps*1000),
            str(segment),
        ])

    concat_list = output.parent / f"{edit_id}.concat.txt"
    concat_payload = "".join("file '" + str(segment).replace("\\", "/").replace("'", "'\\''") + "'\n" for segment in segments)
    base_video = output.parent / f"{edit_id}.base.{container}"
    plan.append(["write-file", str(concat_list), concat_payload])
    plan.append([
        "ffmpeg", "-y", "-v", "error",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c", "copy", str(base_video),
    ])

    current = base_video
    for index, overlay in enumerate(edit.get("visual_overlays", [])):
        overlaid = output.parent / f"{edit_id}.visual-{index:02d}.{container}"
        start, end = overlay["start_seconds"], overlay["end_seconds"]
        if overlay["kind"] == "image":
            source_input = ["-loop", "1", "-framerate", str(fps), "-i", overlay["source"]]
            timing = "setpts=PTS-STARTPTS"
        else:
            source_input = ["-stream_loop", "-1", "-ss", f"{overlay.get('take_from_seconds', 0):.3f}",
                            "-i", overlay["source"]]
            timing = f"setpts=(PTS-STARTPTS)/{overlay.get('speed', 1)}+{start}/TB"
        width, height = overlay["width"], overlay["height"]
        if overlay.get("fit", "stretch") == "contain_black":
            size = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
        else:
            size = f"scale={width}:{height}"
        filter_graph = (f"[1:v]{timing},{size},setsar=1[fg];"
                        f"[0:v][fg]overlay={overlay['x']}:{overlay['y']}:"
                        f"enable='gte(t,{start})*lt(t,{end})':eof_action=pass[v]")
        plan.append(["ffmpeg", "-y", "-v", "error", "-i", str(current), *source_input,
                     "-filter_complex", filter_graph, "-map", "[v]", "-an", "-t",
                     f"{sum(clip['duration_seconds'] for clip in edit['video_clips']):.6f}",
                     "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                     "-pix_fmt", "yuv420p", str(overlaid)])
        current = overlaid

    subtitles = edit.get("subtitles", [])
    if subtitles:
        srt_path = output.parent / f"{edit_id}.subs.srt"
        lines: list[str] = []
        for number, subtitle in enumerate(sorted(
                subtitles, key=lambda item: item["start_seconds"]), start=1):
            lines.append(str(number))
            lines.append(f"{_srt_time(subtitle['start_seconds'])} --> "
                         f"{_srt_time(subtitle['end_seconds'])}")
            lines.append(subtitle["text"])
            lines.append("")
        plan.append(["write-file", str(srt_path), "\n".join(lines)])
        captioned = output.parent / f"{edit_id}.subbed.{container}"
        plan.append([
            "ffmpeg", "-y", "-v", "error",
            "-i", str(current),
            "-vf", f"subtitles={_quote_filter_path(srt_path)}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            str(captioned),
        ])
        current = captioned

    ass_overlays = edit.get("ass_overlays", [])
    if ass_overlays:
        chain = ",".join(f"ass={_quote_filter_path(Path(overlay['path']))}"
                         for overlay in ass_overlays)
        overlaid = output.parent / f"{edit_id}.ass.{container}"
        plan.append([
            "ffmpeg", "-y", "-v", "error",
            "-i", str(current),
            "-vf", chain,
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            str(overlaid),
        ])
        current = overlaid

    audio_clips = edit.get("audio_clips", [])
    total_seconds = sum(clip["duration_seconds"] for clip in edit["video_clips"])
    if audio_clips:
        inputs: list[str] = []
        filters: list[str] = []
        delay_groups: list[str] = []
        for index, clip in enumerate(audio_clips):
            inputs.extend(["-ss", f"{clip['take_from_seconds']:.3f}",
                           "-t", f"{clip['duration_seconds']:.3f}",
                           "-i", clip["source"]])
            gain = clip.get("gain_db", 0.0)
            chain = f"volume={gain}dB"
            if clip.get("fade_in_seconds"):
                chain += f",afade=t=in:st=0:d={clip['fade_in_seconds']}"
            if clip.get("fade_out_seconds"):
                chain += f",afade=t=out:st={clip['duration_seconds']-clip['fade_out_seconds']}:d={clip['fade_out_seconds']}"
            filters.append(
                f"[{index+1}:a]asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates=48000:"
                f"channel_layouts=stereo,{chain},"
                f"adelay={int(clip['timeline_start_seconds'] * 1000)}|"
                f"{int(clip['timeline_start_seconds'] * 1000)}[a{index}]")
            delay_groups.append(f"[a{index}]")
        filters.append(
            f"{''.join(delay_groups)}amix=inputs={len(audio_clips)}:"
            f"duration=longest:normalize=0[mixed]")
        filters.append(
            f"[mixed]apad=whole_dur={total_seconds:.3f}[audio]")
        mixed = output.parent / f"{edit_id}.final.{container}"
        plan.append([
            "ffmpeg", "-y", "-v", "error",
            "-i", str(current), *inputs,
            "-filter_complex", ";".join(filters),
            "-map", "0:v", "-map", "[audio]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{total_seconds:.6f}",
            str(mixed),
        ])
        current = mixed
    else:
        final = output.parent / f"{edit_id}.final.{container}"
        plan.append([
            "ffmpeg", "-y", "-v", "error",
            "-i", str(current),
            "-c", "copy", str(final),
        ])
        current = final

    plan.append(["accept-media", str(current)])
    return plan


def _srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


__all__ = ["EditPlanError", "build_ffmpeg_plan", "load_edit_list", "execute_edit"]


def execute_edit(edit: dict, *, workspace: Path, evidence_dir: Path,
                 ffmpeg: Path, ffprobe: Path, timeout_seconds: float = 600) -> dict:
    """Execute validated local edits; verify complete media before publication."""
    import json
    import subprocess
    from .locking import write_json, RunLease
    from .photography import file_hash, publish_file
    from .media import verify_render
    edit = load_edit_list(edit)
    workspace = workspace.resolve()
    output = Path(edit["output"]["path"])
    output = (workspace/output).resolve() if not output.is_absolute() else output.resolve()
    if not any(output.is_relative_to(root) for root in (workspace/"work",workspace/"assets/renders")):
        raise EditPlanError("output must be inside workspace work/ or assets/renders/")
    if output.exists(): raise EditPlanError("output already exists; never overwrite")
    ffmpeg, ffprobe = ffmpeg.resolve(), ffprobe.resolve()
    if not ffmpeg.is_file() or not ffprobe.is_file(): raise EditPlanError("explicit media tools missing")
    sources = {}
    normalized = {**edit, "video_clips": [], "audio_clips": [], "visual_overlays": []}
    for group in ("video_clips","audio_clips"):
        for clip in edit.get(group,[]):
            source = Path(clip["source"])
            source = (workspace/source).resolve() if not source.is_absolute() else source.resolve()
            if not source.is_file(): raise EditPlanError(f"missing source: {source}")
            # Read source streams and durations before starting any output writes.
            result = subprocess.run([str(ffprobe),"-v","error","-show_streams","-show_format","-of","json",str(source)],capture_output=True,text=True,timeout=30,check=True)
            metadata = json.loads(result.stdout)
            required = "video" if group == "video_clips" else "audio"
            if not any(s.get("codec_type")==required for s in metadata.get("streams",[])):
                raise EditPlanError(f"source has no {required} stream: {source}")
            if clip.get("kind") == "image" and (clip["take_from_seconds"] != 0 or source.suffix.lower() != ".png"):
                raise EditPlanError("image timeline clip must be a PNG with take_from_seconds=0")
            if clip.get("kind") != "image" and float(metadata["format"]["duration"]) + .001 < clip["take_from_seconds"]+clip["duration_seconds"]:
                raise EditPlanError(f"clip exceeds source duration: {source}")
            sources[str(source)] = file_hash(source)
            normalized[group].append({**clip,"source":str(source)})
    normalized_ass = []
    for overlay in edit.get("ass_overlays", []):
        path = Path(overlay["path"])
        path = (workspace/path).resolve() if not path.is_absolute() else path.resolve()
        if not path.is_file(): raise EditPlanError(f"missing ass overlay: {path}")
        sources[str(path)] = file_hash(path)
        normalized_ass.append({"path": str(path)})
    normalized["ass_overlays"] = normalized_ass
    for overlay in edit.get("visual_overlays", []):
        path = Path(overlay["source"])
        path = (workspace/path).resolve() if not path.is_absolute() else path.resolve()
        if not path.is_file(): raise EditPlanError(f"missing visual overlay: {path}")
        if overlay["kind"] == "image" and path.suffix.lower() != ".png":
            raise EditPlanError("image overlay must be a PNG")
        if overlay["kind"] == "video" and path.suffix.lower() not in (".mp4", ".mov", ".mkv"):
            raise EditPlanError("video overlay has an unsupported extension")
        sources[str(path)] = file_hash(path)
        normalized["visual_overlays"].append({**overlay, "source": str(path)})
    evidence_dir = evidence_dir.resolve()
    if not evidence_dir.is_relative_to(workspace/"work"):
        raise EditPlanError("edit evidence must stay inside workspace work/")
    evidence_dir.mkdir(parents=True,exist_ok=False)
    normalized["output"] = {**edit["output"],"path":str(evidence_dir/"assembled.mp4")}
    plan = build_ffmpeg_plan(normalized)
    report = {"status":"running","inputs":sources,"commands":plan,"steps":[],"output":str(output)}
    manifest = evidence_dir/"edit.json"
    with RunLease(output.with_name(output.name+".lease")):
        write_json(manifest,report)
        try:
            for index,argv in enumerate(plan):
                if argv[0]=="write-file":
                    with Path(argv[1]).open("x",encoding="utf-8") as stream: stream.write(argv[2])
                elif argv[0]=="accept-media":
                    spec=edit["output"];duration=sum(c["duration_seconds"] for c in edit["video_clips"])
                    accepted=verify_render(Path(argv[1]),expected_width=spec["width"],expected_height=spec["height"],expected_fps=spec["fps"],expected_min_duration_seconds=duration,expected_duration_seconds=duration,expected_frames=round(duration*spec["fps"]),require_decode=True,ffmpeg_path=ffmpeg,ffprobe_path=ffprobe)
                    if edit.get("audio_clips") and not any(s.kind=="audio" for s in accepted.streams):
                        raise EditPlanError("final audio stream is absent")
                    if edit.get("audio_clips"):
                        audio=next(s for s in accepted.streams if s.kind=="audio")
                        if audio.duration_seconds is None or abs(audio.duration_seconds-duration)>1/spec["fps"]:
                            raise EditPlanError("final audio duration differs from the timeline")
                        decoded=subprocess.run([str(ffmpeg),"-v","error","-xerror","-i",argv[1],"-map","0:v:0","-map","0:a:0","-f","null","-"],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=timeout_seconds)
                        if decoded.returncode or decoded.stderr.strip(): raise EditPlanError("complete audio/video decode failed")
                        report["audio_decode_passed"]=True
                    if any(file_hash(Path(name))!=digest for name,digest in sources.items()):
                        raise EditPlanError("source changed during edit")
                    publish_file(Path(argv[1]),output)
                    report["media"]=accepted.model_dump(mode="json")
                    report["output_hash"]=file_hash(output)
                else:
                    argv=[str(ffmpeg),*("-n" if a=="-y" else a for a in argv[1:])]
                    result=subprocess.run(argv,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=timeout_seconds)
                    (evidence_dir/f"step-{index:02d}.log").write_text(result.stdout+result.stderr,encoding="utf-8")
                    if result.returncode or result.stderr.strip(): raise EditPlanError(f"edit step {index} failed; inspect its log")
                report["steps"].append(index);write_json(manifest,report)
            report["status"]="succeeded"
        except BaseException as error:
            report["status"]="failed";report["error"]=str(error);write_json(manifest,report);raise
        write_json(manifest,report)
    return report

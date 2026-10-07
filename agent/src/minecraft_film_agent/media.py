"""Media acceptance for rendered exports (workflow v3 §7: 成功条件要求真实产物).

A completed render dialog — or a bridge job that claims succeeded — is not
evidence. This module validates the FILE that was actually produced:
ffprobe reports container/streams/decodability when available; without
ffprobe it falls back to the pure-Python MP4 box walker (video.py) and says
so in ``decoder``. Structural claims (duration, dimensions, codec) are
checked against the render spec before an export stage may succeed.
"""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .video import VideoProbeError, probe_video


class MediaStream(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    frames: int | None = None
    fps: float | None = None
    nominal_fps: float | None = None
    duration_seconds: float | None = None


class MediaReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    size_bytes: int
    container: str
    duration_seconds: float | None = None
    streams: list[MediaStream] = Field(default_factory=list)
    decoder: str  # "ffprobe" | "mp4-box-walk"
    raw_notes: list[str] = Field(default_factory=list)
    full_decode_passed: bool = False
    cfr_passed: bool = False


class MediaValidationError(ValueError):
    def __init__(self, message: str, report: MediaReport):
        self.report = report
        super().__init__(message)


def ffprobe_available() -> bool:
    from shutil import which

    return which("ffprobe") is not None


def _probe_with_ffprobe(path: Path, executable: str = "ffprobe", *, count_frames: bool = False) -> MediaReport:
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            executable, "-v", "error", *(["-count_frames", "-show_frames", "-show_entries",
                "frame=media_type,best_effort_timestamp_time:stream:format"] if count_frames else []), "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        capture_output=True, text=True, timeout=120, check=True,
    )
    if completed.stderr.strip():
        raise ValueError("ffprobe reported errors: " + completed.stderr[:2000])
    payload = json.loads(completed.stdout)
    streams = []
    for raw in payload.get("streams", []):
        duration = raw.get("duration")
        frames = raw.get("nb_read_frames" if count_frames else "nb_frames")
        streams.append(MediaStream(
            kind=str(raw.get("codec_type", "unknown")),
            codec=raw.get("codec_name"),
            width=int(width) if (width := raw.get("width")) is not None else None,
            height=int(height) if (height := raw.get("height")) is not None else None,
            frames=int(frames) if frames is not None and str(frames).isdigit() else None,
            fps=_rate(raw.get("avg_frame_rate")),
            nominal_fps=_rate(raw.get("r_frame_rate")),
            duration_seconds=float(duration) if duration is not None else None,
        ))
    fmt = payload.get("format", {})
    duration = fmt.get("duration")
    cfr = False
    if count_frames:
        stamps = [frame.get("best_effort_timestamp_time") for frame in payload.get("frames", [])
                  if frame.get("media_type") == "video"]
        video = next((s for s in streams if s.kind == "video"), None)
        if video and video.fps and len(stamps) == video.frames and len(stamps) >= 2 and None not in stamps:
            times = [float(stamp) for stamp in stamps]
            step = 1.0 / video.fps
            cfr = all(abs((b-a) - step) < 0.0001 for a,b in zip(times, times[1:]))
    return MediaReport(
        path=str(path),
        size_bytes=path.stat().st_size,
        container=str(fmt.get("format_name", "unknown")),
        duration_seconds=float(duration) if duration is not None else None,
        streams=streams,
        decoder="ffprobe",
        cfr_passed=cfr,
    )


def _rate(value: str | None) -> float | None:
    try:
        return float(Fraction(value)) if value else None
    except (ValueError, ZeroDivisionError):
        return None


def _probe_with_box_walker(path: Path) -> MediaReport:
    try:
        probe = probe_video(path)
    except VideoProbeError as error:
        raise MediaValidationError(
            f"file does not parse as MP4: {error}",
            MediaReport(path=str(path), size_bytes=path.stat().st_size,
                        container="unparsed", decoder="mp4-box-walk",
                        raw_notes=[str(error)]),
        ) from error
    return MediaReport(
        path=str(probe.path),
        size_bytes=probe.size_bytes,
        container="mp4",
        duration_seconds=probe.duration_seconds,
        streams=[
            MediaStream(kind="video", codec=track.fourcc,
                        width=track.width, height=track.height)
            for track in probe.tracks
        ],
        decoder="mp4-box-walk",
        raw_notes=["ffprobe not available; structural MP4 walk only — install "
                   "ffmpeg for full decode acceptance before shipping a cut"],
    )


def probe_media(path: Path) -> MediaReport:
    """Validates that the file exists and parses; no spec comparison."""

    if not path.is_file():
        raise MediaValidationError(f"media file missing: {path}",
                                   MediaReport(path=str(path), size_bytes=0,
                                               container="missing", decoder="none"))
    if ffprobe_available():
        try:
            return _probe_with_ffprobe(path)
        except (subprocess.SubprocessError, ValueError) as error:
            raise MediaValidationError("ffprobe failed; refusing structural downgrade: " + str(error),
                MediaReport(path=str(path), size_bytes=path.stat().st_size,
                            container="unparsed", decoder="ffprobe")) from error
    return _probe_with_box_walker(path)


def verify_render(
    path: Path,
    *,
    expected_width: int,
    expected_height: int,
    expected_fps: float,
    expected_min_duration_seconds: float,
    expected_duration_seconds: float | None = None,
    expected_frames: int | None = None,
    require_decode: bool = False,
    ffprobe_path: Path | None = None,
    ffmpeg_path: Path | None = None,
    structural_only: bool = False,
) -> MediaReport:
    """Acceptance gate for one exported shot: real, decodable, matching.

    Raises MediaValidationError (carrying the report as evidence) when the
    artifact is missing, undecodable, or does not meet the render spec. A
    video stream must exist; an audio stream is optional.
    """

    if not path.is_file():
        return probe_media(path)  # produces the missing-file error with evidence
    if require_decode:
        try:
            report = _probe_with_ffprobe(path, str(ffprobe_path or "ffprobe"), count_frames=True)
            decoded = subprocess.run(
                [str(ffmpeg_path or "ffmpeg"), "-v", "error", "-xerror", "-i", str(path),
                 "-map", "0:v:0", "-f", "null", "-"],
                capture_output=True, text=True, timeout=900, check=True,
            )
            if decoded.stderr.strip():
                raise ValueError(decoded.stderr[:2000])
            report.full_decode_passed = True
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            raise MediaValidationError("full media acceptance failed: " + str(error),
                MediaReport(path=str(path), size_bytes=path.stat().st_size,
                            container="unverified", decoder="ffprobe")) from error
    else:
        report = _probe_with_box_walker(path) if structural_only else probe_media(path)
    problems: list[str] = []
    video_streams = [stream for stream in report.streams if stream.kind == "video"]
    if not video_streams:
        problems.append("no video stream found")
        video_streams = [MediaStream(kind="video")]
    stream = video_streams[0]
    if stream.width != expected_width:
        problems.append(f"width {stream.width} != expected {expected_width}")
    if stream.height != expected_height:
        problems.append(f"height {stream.height} != expected {expected_height}")
    if report.duration_seconds is None:
        problems.append("duration unreadable")
    elif report.duration_seconds + 1e-6 < expected_min_duration_seconds:
        problems.append(
            f"duration {report.duration_seconds:.3f}s < required "
            f"{expected_min_duration_seconds:.3f}s"
        )
    if expected_duration_seconds is not None:
        tolerance = 1.0 / expected_fps + 1e-6
        if report.duration_seconds is None or abs(report.duration_seconds - expected_duration_seconds) > tolerance:
            problems.append(f"duration {report.duration_seconds} != expected {expected_duration_seconds}")
    if expected_frames is not None and stream.frames != expected_frames:
        problems.append(f"decoded frame count {stream.frames} != expected {expected_frames}")
    if require_decode:
        if not report.cfr_passed:
            problems.append("decoded frame timestamps do not prove constant frame rate")
        for name, rate in (("average", stream.fps), ("nominal", stream.nominal_fps)):
            if rate is None or abs(rate - expected_fps) > 1e-6:
                problems.append(f"{name} fps {rate} != expected {expected_fps}")
    if stream.frames is not None and expected_fps > 0 and report.duration_seconds:
        expected_frames = expected_fps * report.duration_seconds
        if abs(stream.frames - expected_frames) > max(2.0, expected_frames * 0.05):
            problems.append(
                f"frame count {stream.frames} deviates from {expected_frames:.1f} "
                f"({expected_fps} fps × duration)"
            )
    if problems:
        raise MediaValidationError(
            "render artifact rejected: " + "; ".join(problems), report)
    return report

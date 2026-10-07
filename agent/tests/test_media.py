"""Media acceptance (media.py): a render only counts when the file proves it.

Offline-first: the missing/garbage/spec-mismatch paths run everywhere; the
decode-level ffprobe path runs only when ffprobe is installed (CI machines
without ffmpeg skip those checks explicitly, never silently).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from minecraft_film_agent.media import (
    MediaValidationError,
    ffprobe_available,
    probe_media,
    verify_render,
)

HAS_FFMPEG = shutil.which("ffmpeg") is not None
HAS_FFPROBE = ffprobe_available()


def _make_mp4(tmp_path: Path, *, seconds: int = 1, width: int = 320, height: int = 240) -> Path:
    target = tmp_path / "render.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:d={seconds}",
         "-r", "30", "-pix_fmt", "yuv420p", "-vcodec", "libx264",
         str(target)],
        check=True, capture_output=True, timeout=120,
    )
    return target


# -- missing and malformed artifacts ------------------------------------------------


def test_missing_file_is_rejected_with_evidence(tmp_path: Path) -> None:
    with pytest.raises(MediaValidationError) as error:
        verify_render(tmp_path / "gone.mp4", expected_width=1280, expected_height=720,
                      expected_fps=30.0, expected_min_duration_seconds=1.0)
    assert error.value.report.container == "missing"


def test_garbage_file_never_verifies(tmp_path: Path) -> None:
    junk = tmp_path / "fake.mp4"
    junk.write_bytes(b"not a video at all" * 100)
    with pytest.raises(MediaValidationError) as error:
        probe_media(junk)
    assert error.value.report.container == "unparsed"
    with pytest.raises(MediaValidationError):
        verify_render(junk, expected_width=1280, expected_height=720,
                      expected_fps=30.0, expected_min_duration_seconds=1.0)


# -- real artifacts (only where ffmpeg exists) ----------------------------------------


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed on this machine")
def test_conforming_render_verifies(tmp_path: Path) -> None:
    target = _make_mp4(tmp_path)
    report = verify_render(target, expected_width=320, expected_height=240,
                           expected_fps=30.0, expected_min_duration_seconds=0.5)
    assert report.decoder in ("ffprobe", "mp4-box-walk")
    assert report.duration_seconds is not None and report.duration_seconds >= 0.5


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed on this machine")
def test_dimension_mismatch_is_rejected(tmp_path: Path) -> None:
    target = _make_mp4(tmp_path, width=640, height=480)
    with pytest.raises(MediaValidationError) as error:
        verify_render(target, expected_width=1280, expected_height=720,
                      expected_fps=30.0, expected_min_duration_seconds=0.5)
    assert "width" in str(error.value) or "height" in str(error.value)


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed on this machine")
def test_too_short_render_is_rejected(tmp_path: Path) -> None:
    target = _make_mp4(tmp_path, seconds=1)
    with pytest.raises(MediaValidationError) as error:
        verify_render(target, expected_width=320, expected_height=240,
                      expected_fps=30.0, expected_min_duration_seconds=5.0)
    assert "duration" in str(error.value)


@pytest.mark.skipif(not (HAS_FFMPEG and HAS_FFPROBE),
                    reason="ffmpeg/ffprobe not installed on this machine")
def test_ffprobe_decoder_reported(tmp_path: Path) -> None:
    target = _make_mp4(tmp_path)
    report = probe_media(target)
    assert report.decoder == "ffprobe"
    kinds = {stream.kind for stream in report.streams}
    assert "video" in kinds

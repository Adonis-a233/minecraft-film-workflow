"""Video probe tests against hand-built minimal MP4 box structures."""

import struct

import pytest

from minecraft_film_agent.video import VideoProbeError, probe_video


def box(fourcc: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + fourcc + payload


def stsd_avc1(width: int, height: int) -> bytes:
    entry = (
        struct.pack(">I", 36)
        + b"avc1"
        + b"\x00" * 6
        + struct.pack(">H", 1)
        + b"\x00" * 2
        + b"\x00" * 2
        + b"\x00" * 12
        + struct.pack(">HH", width, height)
    )
    payload = b"\x00" * 4 + struct.pack(">I", 1) + entry
    return box(b"stsd", payload)


def mvhd_v0(timescale: int, duration: int) -> bytes:
    payload = (
        b"\x00" * 4
        + b"\x00" * 8
        + struct.pack(">II", timescale, duration)
        + b"\x00" * 80
    )
    return box(b"mvhd", payload)


def minimal_mp4(timescale: int = 1000, duration: int = 43467) -> bytes:
    stbl = box(b"stbl", stsd_avc1(1280, 720))
    minf = box(b"minf", stbl)
    mdia = box(b"mdia", minf)
    trak = box(b"trak", mdia)
    moov = box(b"moov", mvhd_v0(timescale, duration) + trak)
    ftyp = box(b"ftyp", b"isom" + struct.pack(">I", 512))
    return ftyp + moov


def test_probe_reads_codec_size_and_duration(tmp_path) -> None:
    path = tmp_path / "export.mp4"
    path.write_bytes(minimal_mp4())
    probe = probe_video(path)
    assert probe.has_moov is True
    assert probe.timescale == 1000
    assert probe.duration_seconds == pytest.approx(43.467)
    assert len(probe.tracks) == 1
    assert probe.tracks[0].fourcc == "avc1"
    assert probe.tracks[0].width == 1280
    assert probe.tracks[0].height == 720


def test_probe_mvhd_version_1(tmp_path) -> None:
    payload = (
        b"\x01" * 1
        + b"\x00" * 3
        + b"\x00" * 16
        + struct.pack(">I", 30)
        + struct.pack(">Q", 900)
        + b"\x00" * 80
    )
    trak = box(b"trak", box(b"mdia", box(b"minf", box(b"stbl", stsd_avc1(1920, 1080)))))
    data = box(b"ftyp", b"isom" + struct.pack(">I", 512)) + box(
        b"moov", box(b"mvhd", payload) + trak
    )
    path = tmp_path / "v1.mp4"
    path.write_bytes(data)
    probe = probe_video(path)
    assert probe.timescale == 30
    assert probe.duration_seconds == pytest.approx(30.0)
    assert (probe.tracks[0].width, probe.tracks[0].height) == (1920, 1080)


def test_probe_without_moov(tmp_path) -> None:
    path = tmp_path / "empty.mp4"
    path.write_bytes(box(b"ftyp", b"isom" + struct.pack(">I", 512)))
    probe = probe_video(path)
    assert probe.has_moov is False
    assert probe.duration_seconds is None
    assert probe.tracks == []


def test_probe_rejects_non_mp4(tmp_path) -> None:
    path = tmp_path / "not.mp4"
    path.write_bytes(b"RIFF0000WAVE")
    with pytest.raises(VideoProbeError):
        probe_video(path)

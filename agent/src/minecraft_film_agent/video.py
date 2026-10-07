"""Technical validation of exported video files (P4 acceptance).

A successful export dialog is not evidence. This module reads the MP4
container directly — box-walking with strict bounds checks — and reports
codec, dimensions, and duration so an export claim can be checked against
the file that was actually produced.
"""

from __future__ import annotations

import struct
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


MAX_BOX_DEPTH = 8


class SampleDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fourcc: str
    width: int | None = None
    height: int | None = None


class VideoProbe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    size_bytes: int
    has_moov: bool = False
    timescale: int | None = None
    duration_seconds: float | None = None
    tracks: list[SampleDescription] = Field(default_factory=list)


class VideoProbeError(ValueError):
    pass


class _Walker:
    def __init__(self, data: bytes, probe: VideoProbe):
        self.data = data
        self.probe = probe

    def children(self, start: int, end: int, depth: int) -> None:
        if depth > MAX_BOX_DEPTH:
            raise VideoProbeError("MP4 box nesting deeper than 8 levels")
        offset = start
        while offset + 8 <= end:
            size = struct.unpack(">I", self.data[offset:offset + 4])[0]
            box_type = self.data[offset + 4:offset + 8]
            if size == 0:
                size = end - offset
            elif size == 1:
                if offset + 16 > end:
                    return
                size = struct.unpack(">Q", self.data[offset + 8:offset + 16])[0]
            if size < 8 or offset + size > end:
                return  # truncated or malformed; keep what we have
            self.handle(box_type, offset + 8, offset + size, depth)
            offset += size

    def handle(self, box_type: bytes, payload_start: int, payload_end: int, depth: int) -> None:
        probe = self.probe
        if box_type == b"moov":
            probe.has_moov = True
            self.children(payload_start, payload_end, depth + 1)
        elif box_type == b"trak":
            self.children(payload_start, payload_end, depth + 1)
        elif box_type == b"mdia":
            self.children(payload_start, payload_end, depth + 1)
        elif box_type == b"minf":
            self.children(payload_start, payload_end, depth + 1)
        elif box_type == b"stbl":
            self.children(payload_start, payload_end, depth + 1)
        elif box_type == b"mvhd":
            version = self.data[payload_start]
            if version == 0:
                timescale, duration = struct.unpack(
                    ">II", self.data[payload_start + 12:payload_start + 20]
                )
            elif version == 1:
                timescale = struct.unpack(
                    ">I", self.data[payload_start + 20:payload_start + 24]
                )[0]
                duration = struct.unpack(
                    ">Q", self.data[payload_start + 24:payload_start + 32]
                )[0]
            else:
                return
            if timescale:
                probe.timescale = timescale
                probe.duration_seconds = duration / timescale
        elif box_type == b"stsd" and payload_end - payload_start >= 12:
            entry = payload_start + 8
            if entry + 36 > payload_end:
                return
            fourcc = self.data[entry + 4:entry + 8].decode("latin1").strip()
            width, height = struct.unpack(">HH", self.data[entry + 32:entry + 36])
            probe.tracks.append(
                SampleDescription(fourcc=fourcc, width=width or None, height=height or None)
            )

    def __init__(self, data: bytes, probe: VideoProbe):
        self.data = data
        self.probe = probe


def probe_video(path: Path) -> VideoProbe:
    data = path.read_bytes()
    probe = VideoProbe(path=str(path), size_bytes=len(data))
    if data[:8] != b"\x00\x00\x00\x18ftyp" and data[4:8] != b"ftyp":
        raise VideoProbeError(f"not an MP4 file (missing ftyp): {path}")
    _Walker(data, probe).children(0, len(data), 0)
    return probe

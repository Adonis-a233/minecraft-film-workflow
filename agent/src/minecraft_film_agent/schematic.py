"""Bounded Sponge v2/v3 NBT preflight with VarInt block data in YZX order.
Original files are only read; palette compatibility is checked by the live
importer against the pinned game registry before any block writes.
"""

from __future__ import annotations

import gzip
import io
import struct
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class SchematicError(ValueError):
    pass


class SchematicSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    data_version: int | None
    width: int
    height: int
    length: int
    volume: int
    block_count: int
    air_count: int
    palette_size: int
    palette: list[str]
    missing_blocks: int
    version: int = 2
    offset: list[int] = [0, 0, 0]
    block_entities: int = 0
    entities: int = 0
    has_biomes: bool = False


# -- minimal NBT ------------------------------------------------------------------
#
# Tags: 1 byte, 2 short, 3 int, 5 float, 6 double, 7 byte-array, 8 string,
# 9 list, 10 compound, 11 int-array, 12 long-array.

TAG_END = 0
TAG_BYTE = 1
TAG_SHORT = 2
TAG_INT = 3
TAG_LONG = 4
MAX_NBT_BYTES = 64 * 1024 * 1024
MAX_VOLUME = 262144
TAG_FLOAT = 5
TAG_DOUBLE = 6
TAG_BYTE_ARRAY = 7
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10
TAG_INT_ARRAY = 11
TAG_LONG_ARRAY = 12


def _read_string(data: bytes, offset: int) -> "tuple[str, int]":
    (length,) = struct.unpack_from(">H", data, offset)
    offset += 2
    if offset + length > len(data): raise SchematicError("truncated NBT string")
    value = data[offset:offset + length].decode("utf-8")
    return value, offset + length


def _read_payload(data: bytes, offset: int, tag: int, depth: int = 0) -> "tuple[object, int]":
    if depth > 64: raise SchematicError("NBT nesting exceeds 64")
    if tag == TAG_LONG:
        return struct.unpack_from(">q", data, offset)[0], offset + 8
    if tag == TAG_BYTE:
        return struct.unpack_from(">b", data, offset)[0], offset + 1
    if tag == TAG_SHORT:
        return struct.unpack_from(">h", data, offset)[0], offset + 2
    if tag == TAG_INT:
        return struct.unpack_from(">i", data, offset)[0], offset + 4
    if tag == TAG_FLOAT:
        return struct.unpack_from(">f", data, offset)[0], offset + 4
    if tag == TAG_DOUBLE:
        return struct.unpack_from(">d", data, offset)[0], offset + 8
    if tag == TAG_BYTE_ARRAY:
        (length,) = struct.unpack_from(">i", data, offset)
        offset += 4
        if length < 0 or offset + length > len(data): raise SchematicError("invalid NBT byte-array length")
        return data[offset:offset + length], offset + length
    if tag == TAG_STRING:
        return _read_string(data, offset)
    if tag == TAG_LIST:
        inner = data[offset]
        (count,) = struct.unpack_from(">i", data, offset + 1)
        offset += 5
        if count < 0 or count > MAX_VOLUME or (count and inner == TAG_END): raise SchematicError("invalid NBT list length/type")
        items: list[object] = []
        for _ in range(max(count, 0)):
            value, offset = _read_payload(data, offset, inner, depth + 1)
            items.append(value)
        return items, offset
    if tag == TAG_COMPOUND:
        compound: dict[str, object] = {}
        while True:
            tag_type = data[offset]
            offset += 1
            if tag_type == TAG_END:
                return compound, offset
            name, offset = _read_string(data, offset)
            value, offset = _read_payload(data, offset, tag_type, depth + 1)
            if name in compound: raise SchematicError("duplicate NBT tag: " + name)
            compound[name] = value
    if tag == TAG_INT_ARRAY:
        (length,) = struct.unpack_from(">i", data, offset)
        offset += 4
        if length < 0 or offset + 4 * length > len(data): raise SchematicError("invalid NBT array length")
        return list(struct.unpack_from(f">{length}i", data, offset)), offset + 4 * length
    if tag == TAG_LONG_ARRAY:
        (length,) = struct.unpack_from(">i", data, offset)
        offset += 4
        if length < 0 or offset + 8 * length > len(data): raise SchematicError("invalid NBT array length")
        return list(struct.unpack_from(f">{length}q", data, offset)), offset + 8 * length
    raise SchematicError(f"unsupported NBT tag type {tag}")


def read_nbt_root(data: bytes) -> "tuple[str, dict]":
    """Parses an uncompressed root compound; returns (root_name, payload)."""

    if not data or data[0] != TAG_COMPOUND:
        raise SchematicError("NBT root is not a compound")
    name, offset = _read_string(data, 1)
    payload, end = _read_payload(data, offset, TAG_COMPOUND)
    if end != len(data): raise SchematicError("trailing bytes after NBT root")
    return name, payload


def _write_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack(">H", len(encoded)) + encoded


def write_nbt_compound(name: str, payload: dict[str, "tuple[int, object]"]) -> bytes:
    """Serializes a root compound from {name: (tag_type, value)} pairs."""

    out = io.BytesIO()
    out.write(struct.pack(">B", TAG_COMPOUND))
    out.write(_write_string(name))
    for key, (tag, value) in payload.items():
        out.write(struct.pack(">B", tag))
        out.write(_write_string(key))
        out.write(_write_payload(tag, value))
    out.write(struct.pack(">B", TAG_END))
    return out.getvalue()


def _write_payload(tag: int, value: object) -> bytes:
    if tag == TAG_SHORT:
        return struct.pack(">h", value)  # type: ignore[arg-type]
    if tag == TAG_INT:
        return struct.pack(">i", value)  # type: ignore[arg-type]
    if tag == TAG_INT_ARRAY:
        array = list(value)  # type: ignore[arg-type]
        return struct.pack(">i", len(array)) + struct.pack(f">{len(array)}i", *array)
    if tag == TAG_BYTE_ARRAY:
        array = bytes(value)  # type: ignore[arg-type]
        return struct.pack(">i", len(array)) + array
    if tag == TAG_STRING:
        return _write_string(str(value))
    if tag == TAG_COMPOUND:
        inner = io.BytesIO()
        for key, (inner_tag, inner_value) in value.items():  # type: ignore[union-attr]
            inner.write(struct.pack(">B", inner_tag))
            inner.write(_write_string(key))
            inner.write(_write_payload(inner_tag, inner_value))
        inner.write(struct.pack(">B", TAG_END))
        return inner.getvalue()
    raise SchematicError(f"writing NBT tag {tag} is not supported by the fixture writer")


# -- Sponge schematic reading -------------------------------------------------------

def decode_varints(raw: bytes, volume: int) -> list[int]:
    """Sponge v2/v3: one positive palette index per VarInt, YZX order."""
    entries = []
    value = shift = 0
    for byte in raw:
        if shift >= 35 or (shift == 28 and byte > 7):
            raise SchematicError("palette VarInt exceeds positive signed int range")
        value |= (byte & 0x7f) << shift
        if byte & 0x80:
            shift += 7
        else:
            entries.append(value)
            if len(entries) > volume: raise SchematicError("BlockData has extra entries")
            value = shift = 0
    if shift: raise SchematicError("truncated palette VarInt")
    if len(entries) != volume:
        raise SchematicError(f"BlockData decodes to only {len(entries)} entries but the volume is {volume}")
    return entries


@dataclass(frozen=True)
class SchematicData:
    summary: SchematicSummary
    states: tuple[str, ...]


def load_schematic(path: Path) -> SchematicData:
    if not path.is_file(): raise SchematicError(f"schematic missing: {path}")
    try:
        with gzip.open(path, "rb") as stream: raw = stream.read(MAX_NBT_BYTES + 1)
        if len(raw) > MAX_NBT_BYTES: raise SchematicError("NBT exceeds 64MiB limit")
        root_name, root = read_nbt_root(raw)
        if "Schematic" in root and isinstance(root["Schematic"], dict):
            root = root["Schematic"]
        elif root_name != "Schematic":
            raise SchematicError(f"root compound is {root_name!r}, expected 'Schematic'")
        version = int(root["Version"])
        if version not in (2, 3): raise SchematicError(f"unsupported Sponge version {version}")
        width, height, length = (int(root[k]) & 0xffff for k in ("Width", "Height", "Length"))
        volume = width * height * length
        if min(width,height,length) <= 0 or volume > MAX_VOLUME:
            raise SchematicError(f"invalid/oversized dimensions {width}x{height}x{length}")
        blocks = root["Blocks"] if version == 3 else root
        palette = blocks["Palette"]
        if not isinstance(palette, dict) or not palette: raise SchematicError("palette must be a nonempty compound")
        indices = list(palette.values())
        if any(type(i) is not int or i < 0 for i in indices) or len(set(indices)) != len(indices):
            raise SchematicError("duplicate or invalid palette indices")
        raw_data = blocks["Data" if version == 3 else "BlockData"]
        if not isinstance(raw_data, bytes): raise SchematicError("BlockData must be an NBT byte array")
        entries = decode_varints(raw_data, volume)
        by_id = {i:state for state,i in palette.items()}
        unknown = set(entries)-set(by_id)
        if unknown: raise SchematicError(f"BlockData references indices absent from the palette: {sorted(unknown)[:8]}")
        states = tuple(by_id[i] for i in entries)
        air_count = sum(state.split("[",1)[0] in ("minecraft:air","minecraft:cave_air","minecraft:void_air") for state in states)
        offset = root.get("Offset", [0,0,0])
        if not isinstance(offset,list) or len(offset)!=3 or any(type(i) is not int for i in offset):
            raise SchematicError("Offset must contain exactly three integers")
        summary = SchematicSummary(path=str(path),version=version,data_version=int(root["DataVersion"]),
            width=width,height=height,length=length,volume=volume,block_count=volume-air_count,air_count=air_count,
            palette_size=len(palette),palette=sorted(palette),missing_blocks=0,offset=offset,
            block_entities=len(blocks.get("BlockEntities", [])),entities=len(root.get("Entities", [])),
            has_biomes=bool(root.get("Biomes") or root.get("BiomeData")))
        return SchematicData(summary,states)
    except (OSError,EOFError,IndexError,UnicodeDecodeError,struct.error,KeyError,TypeError,ValueError) as error:
        if isinstance(error,SchematicError): raise
        raise SchematicError(f"schematic parse failed: {error}") from error


def inspect_schematic(path: Path) -> SchematicSummary:
    return load_schematic(path).summary

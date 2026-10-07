"""Procured-asset registry (workflow v3 §6).

Originals are copied READ-ONLY into ``assets/<kind>/<asset_id>/`` and never
overwritten; records accumulate in ``assets/registry.json`` keyed by
asset_id. Every registration carries the sha256 it was registered with, and
``verify_asset`` re-hashes the stored file so a silently drifted asset is
caught before it reaches an import.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import shutil
from pathlib import Path

from .contracts import ContractError, validate_against_contract_v3
from .locking import RunLease, write_json

KIND_DIRS = {
    "schematic": "schematics",
    "map_save": "maps",
    "skin": "skins",
    "props": "props",
    "shaderpack": "shaderpacks",
    "resourcepack": "resourcepacks",
}


class AssetRegistryError(ValueError):
    pass


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def registry_path(workspace_root: Path) -> Path:
    return workspace_root / "assets" / "registry.json"


def load_registry(workspace_root: Path) -> dict[str, dict]:
    path = registry_path(workspace_root)
    if not path.is_file():
        return {}
    try:
        records=json.loads(path.read_text(encoding="utf-8"))
        for record in records: validate_record(record)
        if len({record["asset_id"] for record in records})!=len(records):
            raise AssetRegistryError("duplicate asset ids in registry")
        return {record["asset_id"]: record for record in records}
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise AssetRegistryError(f"asset registry is corrupt: {error}") from error


def register_asset(
    workspace_root: Path, record: dict, original_file: Path, *, overwrite: bool = False,
) -> dict:
    workspace_root=workspace_root.resolve()
    if not (workspace_root/"assets").resolve().is_relative_to(workspace_root):
        raise AssetRegistryError("assets directory escapes workspace")
    if overwrite: raise AssetRegistryError("originals are never overwritten; register a new asset id")
    with RunLease(workspace_root/"assets/registry.lease"):
        return _register_asset(workspace_root,record,original_file)


def _register_asset(
    workspace_root: Path,
    record: dict,
    original_file: Path,
    *,
    overwrite: bool = False,
) -> dict:
    """Validates the record against the v3 contract, copies the original
    read-only into the registry tree and appends the record."""

    try:
        # Shape check first (target/registered_at are filled in below).
        validate_against_contract_v3({
            **record,
            "target": {"path": "assets/placeholder"},
            "registered_at": "pending",
        }, "asset-record")
    except ContractError as error:
        raise AssetRegistryError(f"asset record rejected: {error}") from error
    asset_id = str(record["asset_id"])
    kind = str(record["kind"])
    if not original_file.is_file():
        raise AssetRegistryError(f"original file missing: {original_file}")

    existing = load_registry(workspace_root)
    if asset_id in existing and not overwrite:
        raise AssetRegistryError(
            f"asset_id {asset_id} is already registered; originals are never overwritten")

    target_dir = workspace_root / "assets" / KIND_DIRS[kind] / asset_id
    if not target_dir.resolve().is_relative_to(workspace_root/"assets"):
        raise AssetRegistryError("asset directory escapes workspace")
    if target_dir.exists() and not overwrite:
        raise AssetRegistryError(f"registry directory already exists: {target_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / original_file.name
    with original_file.open("rb") as source, target.open("xb") as destination:
        shutil.copyfileobj(source,destination)
    stored_hash = _sha256_of(target)
    claimed = record.get("source", {}).get("sha256")
    if claimed and claimed != stored_hash:
        target.unlink()
        raise AssetRegistryError(
            f"sha256 mismatch for {original_file.name}: claimed {claimed}, computed {stored_hash}")
    target.chmod(0o444)  # originals stay read-only (after verification)

    stored = {
        **record,
        "schema_version": 3,
        "target": {"path": str(target.relative_to(workspace_root)), "sha256": stored_hash},
        "registered_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    validate_against_contract_v3(stored, "asset-record")
    registry = dict(existing)
    registry[asset_id] = stored
    path = registry_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path,list(registry.values()))
    return stored


def verify_asset(workspace_root: Path, asset_id: str) -> dict:
    """Re-hashes the stored original against the record; raises on drift."""

    registry = load_registry(workspace_root)
    record = registry.get(asset_id)
    if record is None:
        raise AssetRegistryError(f"unknown asset_id: {asset_id}")
    target = record.get("target", {}).get("sha256")
    if not target:
        raise AssetRegistryError(f"asset {asset_id} has no stored hash to verify against")
    workspace_root=workspace_root.resolve()
    file_path = (workspace_root / record["target"]["path"]).resolve()
    expected=workspace_root/"assets"/KIND_DIRS[record["kind"]]/asset_id
    if not file_path.is_relative_to(expected) or not expected.resolve().is_relative_to(workspace_root/"assets"):
        raise AssetRegistryError("registered asset path escapes its owned directory")
    if not file_path.is_file():
        raise AssetRegistryError(f"registered asset file is missing: {file_path}")
    actual = _sha256_of(file_path)
    if actual != target:
        raise AssetRegistryError(
            f"asset {asset_id} drifted: registered {target}, file now {actual}")
    return record


def validate_record(record: dict) -> dict:
    """Schema-only validation for records whose files live elsewhere."""

    try:
        validate_against_contract_v3(record, "asset-record")
    except ContractError as error:
        raise AssetRegistryError(f"asset record rejected: {error}") from error
    return record


__all__ = [
    "AssetRegistryError",
    "KIND_DIRS",
    "load_registry",
    "register_asset",
    "registry_path",
    "validate_record",
    "verify_asset",
]

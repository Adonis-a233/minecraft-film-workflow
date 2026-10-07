"""Contract loading, cross-language validation, and canonical plan hashing.

The JSON Schemas under ``contracts/v1/`` are the source of truth shared with
the Java bridge. Python pydantic models mirror them; this module re-validates
model output against the schemas so the two representations cannot drift
without a failing test. All schema checks run offline.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import jsonschema


CONTRACT_SCHEMA_NAMES = (
    "production-plan",
    "shot-plan",
    "scene-plan",
    "timeline-plan",
    "camera-track",
    "export-plan",
    "run-manifest",
    "operation-request",
    "operation-result",
    "action-metadata",
)

CONTRACT_V2_SCHEMA_NAMES = (
    "operation-request",
    "operation-result",
    "capabilities",
    "game-state",
    "mocap-state",
)

CONTRACT_V3_SCHEMA_NAMES = (
    "operation-request",
    "operation-result",
    "capabilities",
    "master-view",
    "asset-record",
    "actor-plan",
    "edit-list",
)


class ContractError(ValueError):
    pass


def _candidate_dirs() -> list[Path]:
    """contracts/v1 next to the workspace root, then beside the source tree."""

    return [
        Path(__file__).resolve().parents[2] / "contracts" / "v1",
        Path(__file__).resolve().parents[3] / "contracts" / "v1",
    ]


@lru_cache(maxsize=None)
def load_schema(name: str, *, version: int = 1) -> dict[str, object]:
    if version == 1:
        names, subdirectory = CONTRACT_SCHEMA_NAMES, "v1"
    elif version == 2:
        names, subdirectory = CONTRACT_V2_SCHEMA_NAMES, "v2"
    elif version == 3:
        names, subdirectory = CONTRACT_V3_SCHEMA_NAMES, "v3"
    else:
        raise ContractError(f"unknown contract version: {version}")
    if name not in names:
        raise ContractError(f"unknown contract: {name} (v{version})")
    for directory in _candidate_dirs():
        path = directory.parent / subdirectory / f"{name}.schema.json"
        if path.is_file():
            schema = json.loads(path.read_text(encoding="utf-8"))
            try:
                jsonschema.Draft202012Validator.check_schema(schema)
            except jsonschema.SchemaError as error:
                raise ContractError(f"invalid schema {name}: {error}") from error
            return schema
    raise ContractError(f"contract schema not found on disk: {name} (v{version})")


def validate_against_contract_v2(instance: object, name: str) -> None:
    validator = jsonschema.Draft202012Validator(load_schema(name, version=2))
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(
            f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in errors[:5]
        )
        raise ContractError(f"{name} contract v2 violated: {details}")


def validate_against_contract_v3(instance: object, name: str) -> None:
    validator = jsonschema.Draft202012Validator(load_schema(name, version=3))
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(
            f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in errors[:5]
        )
        raise ContractError(f"{name} contract v3 violated: {details}")


def fixtures_root(version: int = 2) -> Path:
    for directory in _candidate_dirs():
        root = directory.parent / f"v{version}" / "fixtures"
        if root.is_dir():
            return root
    raise ContractError(f"contracts/v{version}/fixtures not found on disk")


def validate_against_contract(instance: object, name: str) -> None:
    validator = jsonschema.Draft202012Validator(load_schema(name))
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(
            f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in errors[:5]
        )
        raise ContractError(f"{name} contract violated: {details}")


def contract_payload(model) -> dict[str, object]:
    """Canonical dict for schema validation and hashing.

    ``exclude_none`` matters: the contracts treat an absent optional field and
    a null one identically, and strict schemas reject explicit nulls.
    """

    return model.model_dump(mode="json", exclude_none=True)  # type: ignore[attr-defined]


def canonical_json(payload: object) -> str:
    """Stable JSON: sorted keys, no whitespace, datetimes as ISO-8601 UTC."""

    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def plan_hash(payload: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def preview_commit_guard(preview_hash: str, commit_hash: str) -> None:
    """Two-phase execution (plan §8.2): commit only the exact previewed plan.

    If plan content changed after preview, the original plan_id is dead and
    the caller must produce a new preview instead of executing.
    """

    if preview_hash != commit_hash:
        raise ContractError(
            "plan changed after preview; the previewed plan_id is void — regenerate the preview"
        )

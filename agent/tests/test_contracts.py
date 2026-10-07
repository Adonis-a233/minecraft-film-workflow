"""Contract schema integrity and Python↔schema mirroring."""

from __future__ import annotations

import pytest

from minecraft_film_agent.contracts import (
    ContractError,
    canonical_json,
    load_schema,
    plan_hash,
    preview_commit_guard,
    validate_against_contract,
)
from minecraft_film_agent.production_models import (
    StageName,
    StageRecord,
    StageStatus,
)


def test_all_schemas_exist_and_are_valid() -> None:
    for name in (
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
    ):
        schema = load_schema(name)
        assert schema["$schema"].startswith("https://json-schema.org/draft/2020-12")


def test_production_plan_rejects_version_drift() -> None:
    payload = {
        "schema_version": 1,
        "production_id": "x-001",
        "minecraft_version": "1.22",
        "fabric_loader": "0.19.3",
        "target": {"width": 1280, "height": 720, "fps": 30, "codec": "h264"},
        "scenes": [{"scene_id": "s", "world_ref": "w", "shots": ["a"]}],
    }
    with pytest.raises(ContractError):
        validate_against_contract(payload, "production-plan")


def test_scene_plan_rejects_unknown_action_and_extra_fields() -> None:
    base = {
        "schema_version": 1,
        "plan_id": "p1",
        "title": "t",
        "world_name": "w",
        "objective": "o",
        "build_region": {"start": {"x": 0, "y": 0, "z": 0}, "end": {"x": 1, "y": 1, "z": 1}},
        "actions": [{"type": "teleport_everything"}],
    }
    with pytest.raises(ContractError):
        validate_against_contract(base, "scene-plan")
    base["actions"] = [{"type": "set_time", "value": 0, "evil": "field"}]
    with pytest.raises(ContractError):
        validate_against_contract(base, "scene-plan")


def test_scene_plan_accepts_minimal_example() -> None:
    from pathlib import Path

    example = Path(__file__).parents[2] / "examples" / "minimal-scene-plan.json"
    payload = __import__("json").loads(example.read_text(encoding="utf-8"))
    validate_against_contract(payload, "scene-plan")


def test_plan_hash_is_canonical_and_sensitive() -> None:
    left = {"b": 1, "a": [1, 2]}
    right = {"a": [1, 2], "b": 1}
    assert plan_hash(left) == plan_hash(right)
    assert plan_hash(left) != plan_hash({"b": 2, "a": [1, 2]})
    assert plan_hash(left).startswith("sha256:")
    assert canonical_json(left) == '{"a":[1,2],"b":1}'


def test_preview_commit_guard_voids_changed_plans() -> None:
    preview_commit_guard("sha256:" + "0" * 64, "sha256:" + "0" * 64)
    with pytest.raises(ContractError):
        preview_commit_guard("sha256:" + "0" * 64, "sha256:" + "1" * 64)


def test_stage_record_dump_matches_run_manifest_contract() -> None:
    from datetime import UTC, datetime

    record = StageRecord(
        run_id="run-1",
        stage=StageName.SAVE_MOCAP,
        attempt=1,
        status=StageStatus.FAILED,
        input_hash="sha256:" + "a" * 64,
        error_class=None,
        message="pending",
        recorded_at=datetime.now(UTC),
    )
    record = record.model_copy(
        update={"error_class": None, "status": StageStatus.SUCCEEDED, "message": None}
    )
    validate_against_contract(record.model_dump(mode="json", exclude_none=True), "run-manifest")

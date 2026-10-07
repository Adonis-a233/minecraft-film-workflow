"""Contract v3: async world-write pipeline semantics (workflow v3 §4).

The canonical fixtures under ``contracts/v3/fixtures/`` are the shared truth
for the Python client, the adapter and (via a future Java V3 fixture runner)
the bridge. Contract 2 stays frozen: v3 changes WHO waits (nobody) and WHERE
the truth lives (the persistent journal), not the write surface itself.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from minecraft_film_agent.contracts import (
    ContractError,
    fixtures_root,
    load_schema,
    validate_against_contract_v3,
)
from minecraft_film_agent.production_models import (
    CapabilitiesV3,
    JournalStateV3,
    OperationRequestV3,
    OperationResultV3,
)


FIXTURES = fixtures_root(3)


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _request_fixtures() -> list[Path]:
    return sorted((FIXTURES / "requests").glob("*.json"))


def _result_fixtures() -> list[Path]:
    return sorted((FIXTURES / "results").glob("*.json"))


# -- schemas exist and pin the new semantics --------------------------------


@pytest.mark.parametrize("name", ["operation-request", "operation-result", "capabilities"])
def test_v3_schemas_exist_and_are_valid(name: str) -> None:
    schema = load_schema(name, version=3)
    assert schema["$schema"].startswith("https://json-schema.org/draft/2020-12")
    if name == "capabilities":
        assert schema["properties"]["contract"]["const"] == 3
    else:
        assert schema["properties"]["schema_version"]["const"] == 3


def test_v3_request_surface_adds_replay_methods() -> None:
    methods = load_schema("operation-request", version=3)["properties"]["method"]["enum"]
    for required in (
        "replay.start_recording", "replay.stop_recording", "replay.await_master_saved",
        "replay.open_master", "replay.replace_camera_track", "replay.start_render",
        "replay.get_render_status", "replay.cancel_render",
    ):
        assert required in methods
    # v3 never exposes flashback writes; only the read-only status survives.
    assert "flashback.start_export" not in methods
    assert "flashback.get_export_status" in methods


def test_v3_capabilities_name_backends_and_fail_closed() -> None:
    schema = load_schema("capabilities", version=3)
    for required in ("recorder_backend", "replay_backend", "camera_backend", "render_backend"):
        assert required in schema["required"]
    assert schema["properties"]["replay_backend"]["enum"] == ["replaymod", "flashback", "none"]
    assert schema["properties"]["render_backend"]["enum"] == ["replaymod", "none"]


def test_capabilities_fixtures_validate() -> None:
    checked = 0
    for path in sorted((FIXTURES / "capabilities").glob("*.json")):
        payload = _load(path)
        validate_against_contract_v3(payload, "capabilities")
        CapabilitiesV3.model_validate(payload)
        checked += 1
    assert checked == 2
    closed = _load(FIXTURES / "capabilities/v3-bridge-no-replay.json")
    assert closed["replay_backend"] == "none" and closed["render_backend"] == "none"
    bound = _load(FIXTURES / "capabilities/v3-bridge-replaymod.json")
    assert bound["replay_backend"] == "replaymod" and bound["render_backend"] == "replaymod"


def test_v3_status_vocabulary_carries_the_async_lifecycle() -> None:
    statuses = load_schema("operation-result", version=3)["properties"]["status"]["enum"]
    for required in ("accepted", "pending", "succeeded", "failed", "unknown", "rejected"):
        assert required in statuses
    assert "observed" not in statuses  # v2-only state, never leaks into v3
    journal = load_schema("operation-result", version=3)["properties"]["journal_state"]["enum"]
    assert set(journal) == {state.value for state in JournalStateV3}
    errors = load_schema("operation-result", version=3)["properties"]["error_class"]["enum"]
    assert "operation_conflict" in errors and "operation_failed" in errors


def test_v2_contract_unchanged_by_v3() -> None:
    """Contract 2 stays frozen: v2 result still speaks observed, not accepted."""

    v2_result = load_schema("operation-result", version=2)
    assert "observed" in v2_result["properties"]["status"]["enum"]
    assert "accepted" not in v2_result["properties"]["status"]["enum"]
    v2_request = load_schema("operation-request", version=2)
    assert v2_request["properties"]["schema_version"]["const"] == 2


# -- request fixtures -------------------------------------------------------


def test_all_request_fixtures_validate() -> None:
    checked = 0
    for path in _request_fixtures():
        envelope = _load(path)
        request = envelope["request"]
        if path.name.startswith("malformed-"):
            with pytest.raises(ContractError):
                validate_against_contract_v3(request, "operation-request")
        else:
            validate_against_contract_v3(request, "operation-request")
            OperationRequestV3.model_validate(request)
        checked += 1
    assert checked == len(_request_fixtures()) == 6


def test_request_fixture_key_is_the_stage_scoped_identity() -> None:
    envelope = _load(FIXTURES / "requests/world-set-time.json")
    key = envelope["request"]["idempotency_key"]
    assert key == "v3-slice-20260928/stage-01/set-time"
    # run/stage/action: the key is generated once upstream and stays put.
    parts = key.split("/")
    assert len(parts) == 3


# -- result fixtures --------------------------------------------------------


def test_all_result_fixtures_validate() -> None:
    checked = 0
    for path in _result_fixtures():
        result = _load(path)
        if path.name.startswith("malformed-"):
            with pytest.raises(ContractError):
                validate_against_contract_v3(result, "operation-result")
        else:
            validate_against_contract_v3(result, "operation-result")
            OperationResultV3.model_validate(result)
        checked += 1
    assert checked == len(_result_fixtures()) == 6


def test_accepted_is_not_a_completion() -> None:
    accepted = OperationResultV3.model_validate(
        _load(FIXTURES / "results/accepted-world-write.json"))
    assert accepted.status == "accepted"
    assert accepted.journal_state is JournalStateV3.QUEUED


def test_succeeded_requires_a_proof_with_ok() -> None:
    succeeded = OperationResultV3.model_validate(
        _load(FIXTURES / "results/succeeded-with-proof.json"))
    assert succeeded.result["proof"]["ok"] is True


def test_failed_carries_the_proof_and_error_class() -> None:
    failed = OperationResultV3.model_validate(
        _load(FIXTURES / "results/failed-proof-mismatch.json"))
    assert failed.status == "failed"
    assert failed.error_class is not None
    assert failed.result["proof"]["ok"] is False


def test_unknown_recovery_names_the_interrupted_state() -> None:
    unknown = OperationResultV3.model_validate(
        _load(FIXTURES / "results/unknown-recovered-from-restart.json"))
    assert unknown.status == "unknown"
    assert unknown.result["recovered_from"] == "running"


def test_conflict_reports_both_param_hashes() -> None:
    conflict = OperationResultV3.model_validate(
        _load(FIXTURES / "results/rejected-params-conflict.json"))
    assert conflict.status == "rejected"
    assert conflict.error_class == "operation_conflict"
    assert conflict.result["submitted_params_hash"] != conflict.result["journaled_params_hash"]


# -- model round trip ---------------------------------------------------------


def test_python_models_mirror_the_v3_schemas() -> None:
    request = OperationRequestV3(
        run_id="run", operation_id="op", idempotency_key="run/stage/action",
        method="world.set_time",
        params={"value": 6000, "build_region": {
            "start": {"x": 0, "y": 64, "z": 0}, "end": {"x": 15, "y": 79, "z": 15}}},
    )
    validate_against_contract_v3(request.model_dump(mode="json", exclude_none=True),
                                 "operation-request")
    result = OperationResultV3(
        schema_version=3, operation_id="op", idempotency_key="run/stage/action",
        status="succeeded", journal_state=JournalStateV3.SUCCEEDED,
        result={"proof": {"ok": True}},
    )
    validate_against_contract_v3(result.model_dump(mode="json", exclude_none=True),
                                 "operation-result")


def test_v3_request_rejects_v2_only_methods() -> None:
    payload = {
        "schema_version": 3, "run_id": "run", "operation_id": "op",
        "idempotency_key": "run/x", "method": "flashback.start_export",
        "params": {},
    }
    with pytest.raises(ContractError):
        validate_against_contract_v3(payload, "operation-request")

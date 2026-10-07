"""Contract v2: schema integrity, Python↔schema mirroring, shared fixtures.

The canonical fixtures under ``contracts/v2/fixtures/`` are consumed by BOTH
this suite and the Java suite (``FixtureTests.java``). Neither language may
keep a private copy of a request or result; drift must fail at least one
suite. Contract 1 stays frozen — it is never edited to accommodate v2.
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
    validate_against_contract_v2,
)
from minecraft_film_agent.production_models import (
    CapabilitiesV2,
    GameStateV2,
    MocapPhase,
    MocapStateV2,
    OperationRequestV2,
    OperationResultV2,
    SessionPhase,
)


FIXTURES = fixtures_root()


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _request_fixtures() -> list[Path]:
    return sorted((FIXTURES / "requests").glob("*.json"))


def _result_fixtures() -> list[Path]:
    return sorted((FIXTURES / "results").glob("*.json"))


# -- schemas exist and are valid --------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["operation-request", "operation-result", "capabilities", "game-state", "mocap-state"],
)
def test_v2_schemas_exist_and_are_valid(name: str) -> None:
    schema = load_schema(name, version=2)
    assert schema["$schema"].startswith("https://json-schema.org/draft/2020-12")
    if name == "capabilities":
        assert schema["properties"]["contract"]["const"] == 2
    else:
        assert schema["properties"]["schema_version"]["const"] == 2


def test_v1_schemas_unchanged_by_v2() -> None:
    """Contract 1 must stay frozen: v1 result still allows a missing key,
    v2 forbids it — the meanings never silently merge."""

    v1_result = load_schema("operation-result", version=1)
    assert "idempotency_key" not in v1_result["required"]
    v2_result = load_schema("operation-result", version=2)
    assert "idempotency_key" in v2_result["required"]
    v1_request = load_schema("operation-request", version=1)
    assert "mocap.start_recording" in v1_request["properties"]["method"]["enum"]
    v2_request = load_schema("operation-request", version=2)
    assert "mocap.start_recording" not in v2_request["properties"]["method"]["enum"]


# -- request fixtures -------------------------------------------------------


def test_valid_request_fixtures_validate() -> None:
    checked = 0
    for path in _request_fixtures():
        if path.name.startswith("malformed-"):
            continue
        envelope = _load(path)
        validate_against_contract_v2(envelope["request"], "operation-request")
        checked += 1
    assert checked >= 4, "the shared request fixtures went missing"


def test_malformed_request_fixtures_are_rejected() -> None:
    for path in _request_fixtures():
        if not path.name.startswith("malformed-"):
            continue
        envelope = _load(path)
        with pytest.raises(ContractError):
            validate_against_contract_v2(envelope["request"], "operation-request")


def test_removing_any_required_request_field_fails() -> None:
    envelope = _load(FIXTURES / "requests" / "world-set-time.json")
    request = envelope["request"]
    required = load_schema("operation-request", version=2)["required"]
    assert set(required) <= set(request)
    for field in required:
        mutated = copy.deepcopy(request)
        del mutated[field]
        with pytest.raises(ContractError, match=f"operation-request contract v2"):
            validate_against_contract_v2(mutated, "operation-request")


# -- result fixtures --------------------------------------------------------


def test_valid_result_fixtures_validate() -> None:
    checked = 0
    for path in _result_fixtures():
        if path.name.startswith("malformed-"):
            continue
        validate_against_contract_v2(_load(path), "operation-result")
        checked += 1
    assert checked >= 8, "the shared result fixtures went missing"


def test_malformed_result_fixtures_are_rejected() -> None:
    for path in _result_fixtures():
        if not path.name.startswith("malformed-"):
            continue
        with pytest.raises(ContractError):
            validate_against_contract_v2(_load(path), "operation-result")


def test_removing_any_required_result_field_fails() -> None:
    payload = _load(FIXTURES / "results" / "applied-world-set-time.json")
    required = load_schema("operation-result", version=2)["required"]
    assert "idempotency_key" in required  # the F1 regression guard
    for field in required:
        mutated = copy.deepcopy(payload)
        del mutated[field]
        with pytest.raises(ContractError):
            validate_against_contract_v2(mutated, "operation-result")


def test_duplicate_idempotent_replay_fixture_is_an_applied_recorded_outcome() -> None:
    payload = _load(FIXTURES / "results" / "duplicate-idempotent-replay.json")
    validate_against_contract_v2(payload, "operation-result")
    assert payload["status"] == "applied"
    assert "already applied" in payload["message"]


# -- game-state / mocap-state / capabilities fixtures -----------------------


def test_game_state_fixtures_validate() -> None:
    for path in sorted((FIXTURES / "game-state").glob("*.json")):
        validate_against_contract_v2(_load(path), "game-state")


def test_mocap_state_fixtures_validate() -> None:
    for path in sorted((FIXTURES / "mocap-state").glob("*.json")):
        validate_against_contract_v2(_load(path), "mocap-state")


def test_capabilities_fixture_validates_and_is_mocap_only() -> None:
    payload = _load(FIXTURES / "capabilities" / "v2-mocap-only-no-flashback.json")
    validate_against_contract_v2(payload, "capabilities")
    assert payload["flashback_automation"] is False
    assert payload["typed_world_ops"] is True


# -- Python model mirroring: model output validates without normalization ---


def test_request_v2_model_matches_schema() -> None:
    request = OperationRequestV2(
        run_id="live-slice",
        operation_id="live-slice-world-set-time",
        idempotency_key="live-slice/world-set-time",
        method="world.set_time",
        params={"value": 6000},
    )
    validate_against_contract_v2(request.model_dump(mode="json", exclude_none=True), "operation-request")


def test_result_v2_model_matches_schema() -> None:
    result = OperationResultV2(
        operation_id="op-1",
        idempotency_key="run/op-1",
        status="observed",
        journal_state="observed",
        message="resolved via operation journal without re-execution",
    )
    validate_against_contract_v2(result.model_dump(mode="json", exclude_none=True), "operation-result")


def test_result_v2_requires_idempotency_key() -> None:
    with pytest.raises(ValueError):
        OperationResultV2.model_validate(
            {
                "schema_version": 2,
                "operation_id": "op-1",
                "status": "applied",
            }
        )


def test_game_state_model_roundtrip_and_gate() -> None:
    state = GameStateV2.model_validate(_load(FIXTURES / "game-state" / "in-world.json"))
    validate_against_contract_v2(state.model_dump(mode="json"), "game-state")
    assert state.pre_write_gate(
        expected_save="Marx Video Test",
        expected_dimension="minecraft:overworld",
        expected_player="CineProbe",
    ) is None

    wrong_save = state.model_copy(update={"save_name": "Other Save"})
    reason = wrong_save.pre_write_gate(
        expected_save="Marx Video Test",
        expected_dimension="minecraft:overworld",
        expected_player="CineProbe",
    )
    assert reason is not None and "save_name" in reason

    menu = GameStateV2.model_validate(_load(FIXTURES / "game-state" / "main-menu.json"))
    assert menu.pre_write_gate(
        expected_save="Marx Video Test",
        expected_dimension="minecraft:overworld",
        expected_player="CineProbe",
    ).startswith("session_phase")


def test_mocap_state_model_roundtrip() -> None:
    saved = MocapStateV2.model_validate(_load(FIXTURES / "mocap-state" / "saved.json"))
    validate_against_contract_v2(saved.model_dump(mode="json", exclude_none=True), "mocap-state")
    assert saved.state is MocapPhase.SAVED
    assert saved.artifact is not None and saved.artifact.sha256


def test_capabilities_model_mismatch_and_mocap_only_gates() -> None:
    capabilities = CapabilitiesV2.model_validate(
        _load(FIXTURES / "capabilities" / "v2-mocap-only-no-flashback.json")
    )
    assert capabilities.runtime_mismatches() == []
    assert capabilities.missing_for_mocap_only() == []
    drifted = capabilities.model_copy(update={"mocap": "1.3.9"})
    assert any("mocap" in issue for issue in drifted.runtime_mismatches())
    disabled_world_ops = capabilities.model_copy(update={"typed_world_ops": False})
    assert "typed_world_ops" in disabled_world_ops.missing_for_mocap_only()


# -- transcripts ------------------------------------------------------------


def test_transcript_pins_exist_for_both_supported_locales() -> None:
    for name in (
        "waiting-for-selection",
        "waiting-cancelled",
        "save-rejected-empty",
        "recording-started",
        "recording-stopped",
        "save-success",
    ):
        assert (FIXTURES / "transcripts" / "zh_cn" / f"{name}.txt").is_file(), name
    assert (FIXTURES / "transcripts" / "en_us" / "README.txt").is_file()
    assert (FIXTURES / "transcripts" / "unknown" / "axiom-tip.txt").is_file()


def test_zh_cn_waiting_pin_is_the_real_live_line() -> None:
    line = (FIXTURES / "transcripts" / "zh_cn" / "waiting-for-selection.txt").read_text(
        encoding="utf-8"
    ).strip()
    assert line.startswith("执行任何操作或再次使用")

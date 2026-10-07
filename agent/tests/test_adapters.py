"""Contract tests shared by every MinecraftAdapter, plus mock-specific checks.

Contract (design doc): identical result structure, an idempotency key on
every operation, uncertain outcomes never reported as success without a
state read, and state re-readable after failure.
"""

import json
from pathlib import Path

import pytest

from minecraft_film_agent.adapters import DryRunMinecraftAdapter, MockMinecraftAdapter
from minecraft_film_agent.models import RunState, ScenePlan
from minecraft_film_agent.workflow import ProductionWorkflow


def build_plan() -> ScenePlan:
    return ScenePlan.model_validate(
        {
            "plan_id": "contract-test",
            "title": "Contract test",
            "world_name": "Marx Video Test",
            "objective": "Adapter contract",
            "build_region": {
                "start": {"x": 0, "y": 60, "z": 0},
                "end": {"x": 8, "y": 70, "z": 8},
            },
            "actions": [
                {"type": "set_time", "value": 6000},
                {
                    "type": "fill",
                    "start": {"x": 0, "y": 64, "z": 0},
                    "end": {"x": 2, "y": 64, "z": 2},
                    "block": "minecraft:stone_bricks",
                    "placement": "keep",
                },
                {
                    "type": "set_block",
                    "position": {"x": 1, "y": 64, "z": 1},
                    "block": "minecraft:gold_block",
                    "placement": "keep",
                },
            ],
        }
    )


def run_through(tmp_path: Path, adapter) -> Path:
    workflow = ProductionWorkflow(tmp_path)
    workflow.prepare(build_plan(), "contract-run")
    workflow.approve("contract-run", "tester")
    workflow.execute("contract-run", adapter)
    return tmp_path / "work" / "runs" / "contract-run" / "results.jsonl"


def results_of(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_contract_dry_run(tmp_path: Path) -> None:
    results = results_of(run_through(tmp_path, DryRunMinecraftAdapter()))
    assert len(results) == 3
    assert all(result["status"] == "skipped" for result in results)
    assert all(result["idempotency_key"] for result in results)
    assert [result["idempotency_key"] for result in results] == [
        "contract-test-a000",
        "contract-test-a001",
        "contract-test-a002",
    ]


def test_contract_mock_applies_and_records_state(tmp_path: Path) -> None:
    results = results_of(run_through(tmp_path, MockMinecraftAdapter()))
    assert all(result["status"] == "applied" for result in results)
    assert all(result["idempotency_key"] for result in results)
    assert results[0]["observed_state"]["time"] == 6000
    # fill 3x1x3 = 9 blocks; the kept setblock lands on an occupied cell
    assert results[1]["observed_state"]["block_count"] == 9
    assert results[2]["observed_state"]["block_count"] == 9


def test_mock_keep_semantics(tmp_path: Path) -> None:
    adapter = MockMinecraftAdapter()
    workflow = ProductionWorkflow(tmp_path)
    workflow.prepare(build_plan(), "keep-run")
    workflow.approve("keep-run", "tester")
    workflow.execute("keep-run", adapter)
    # the kept gold_block must not have replaced the stone brick
    assert adapter.blocks[(1, 64, 1)] == "minecraft:stone_bricks"


def test_idempotency_keys_are_stable_and_unique() -> None:
    from minecraft_film_agent.compiler import validate_and_compile

    first = validate_and_compile(build_plan())
    second = validate_and_compile(build_plan())
    keys = [command.idempotency_key for command in first.commands]
    assert len(keys) == len(set(keys))
    assert keys == [command.idempotency_key for command in second.commands]


def test_uncertain_but_applied_resolves_through_state_read(tmp_path: Path) -> None:
    adapter = MockMinecraftAdapter(uncertain_applied={1})
    results = results_of(run_through(tmp_path, adapter))
    assert results[1]["status"] == "applied"
    assert "resolved applied via state read" in results[1]["message"]
    assert results[1]["observed_state"]["confirmed"] is True
    assert adapter.blocks[(0, 64, 0)] == "minecraft:stone_bricks"


def test_uncertain_and_lost_fails_the_run(tmp_path: Path) -> None:
    adapter = MockMinecraftAdapter(uncertain_lost={0})
    workflow = ProductionWorkflow(tmp_path)
    workflow.prepare(build_plan(), "lost-run")
    workflow.approve("lost-run", "tester")
    with pytest.raises(RuntimeError, match="state read shows not applied"):
        workflow.execute("lost-run", adapter)
    manifest = workflow.get_run("lost-run")
    assert manifest.state is RunState.FAILED
    results = results_of(
        tmp_path / "work" / "runs" / "lost-run" / "results.jsonl"
    )
    assert results[0]["status"] == "failed"
    assert results[0]["observed_state"]["confirmed"] is False
    # execution stops at the first failure; later commands never dispatched
    assert len(results) == 1
    assert adapter.executed == ["time set 6000"]

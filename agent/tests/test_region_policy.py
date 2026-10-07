"""Region policy: every world write must stay inside the declared build_region."""

import pytest
from pydantic import ValidationError

from minecraft_film_agent.models import MAX_REGION_BLOCKS, ScenePlan


def make_plan(actions: list[dict], region: dict | None = None) -> dict:
    return {
        "plan_id": "region-test",
        "title": "Region test",
        "world_name": "Marx Video Test",
        "objective": "Reject writes outside the declared region",
        "build_region": region
        or {
            "start": {"x": 0, "y": 60, "z": 0},
            "end": {"x": 8, "y": 70, "z": 8},
        },
        "actions": actions,
    }


def test_fill_inside_region_is_accepted() -> None:
    plan = make_plan(
        [
            {
                "type": "fill",
                "start": {"x": 0, "y": 64, "z": 0},
                "end": {"x": 8, "y": 70, "z": 8},
                "block": "minecraft:stone_bricks",
            }
        ]
    )
    assert ScenePlan.model_validate(plan) is not None


def test_fill_corner_outside_region_is_rejected() -> None:
    plan = make_plan(
        [
            {
                "type": "fill",
                "start": {"x": 0, "y": 64, "z": 0},
                "end": {"x": 9, "y": 64, "z": 0},
                "block": "minecraft:stone_bricks",
            }
        ]
    )
    with pytest.raises(ValidationError, match="outside the declared build_region"):
        ScenePlan.model_validate(plan)


def test_setblock_outside_region_is_rejected() -> None:
    plan = make_plan(
        [
            {
                "type": "set_block",
                "position": {"x": -1, "y": 64, "z": 0},
                "block": "minecraft:stone",
            }
        ]
    )
    with pytest.raises(ValidationError, match="outside the declared build_region"):
        ScenePlan.model_validate(plan)


def test_summon_outside_region_is_rejected() -> None:
    plan = make_plan(
        [
            {
                "type": "summon",
                "entity": "minecraft:villager",
                "position": {"x": 100, "y": 64, "z": 100},
            }
        ]
    )
    with pytest.raises(ValidationError, match="outside the declared build_region"):
        ScenePlan.model_validate(plan)


def test_missing_region_is_rejected() -> None:
    plan = make_plan([{"type": "set_time", "value": 1000}])
    del plan["build_region"]
    with pytest.raises(ValidationError):
        ScenePlan.model_validate(plan)


def test_oversized_region_is_rejected() -> None:
    plan = make_plan(
        [{"type": "set_time", "value": 1000}],
        region={
            "start": {"x": 0, "y": -64, "z": 0},
            "end": {"x": 100, "y": 319, "z": 100},
        },
    )
    with pytest.raises(ValidationError, match=str(MAX_REGION_BLOCKS)):
        ScenePlan.model_validate(plan)

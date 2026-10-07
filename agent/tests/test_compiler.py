from minecraft_film_agent.compiler import PlanValidationError, validate_and_compile
from minecraft_film_agent.models import ScenePlan


def make_plan(actions: list[dict]) -> ScenePlan:
    return ScenePlan.model_validate(
        {
            "plan_id": "compiler-test",
            "title": "Compiler test",
            "world_name": "Marx Video Test",
            "objective": "Compile deterministic commands",
            "build_region": {
                "start": {"x": 0, "y": 60, "z": 0},
                "end": {"x": 8, "y": 70, "z": 8},
            },
            "actions": actions,
        }
    )


def test_compiles_world_and_mocap_commands() -> None:
    plan = make_plan(
        [
            {"type": "set_time", "value": 6000},
            {
                "type": "fill",
                "start": {"x": 0, "y": 64, "z": 0},
                "end": {"x": 2, "y": 64, "z": 2},
                "block": "minecraft:stone",
                "placement": "keep",
            },
            {
                "type": "mocap_scene_add",
                "scene": "factory_scene",
                "recording": "worker_walk",
                "delay_ticks": 20,
                "offset": {"x": 3, "y": 0, "z": -2},
                "player_name": "WorkerA",
            },
        ]
    )
    validated = validate_and_compile(plan)
    assert [item.command for item in validated.commands] == [
        "time set 6000",
        "fill 0 64 0 2 64 2 minecraft:stone keep",
        "mocap scenes addTo factory_scene worker_walk 20 3 0 -2 WorkerA",
    ]


def test_rejects_large_fill() -> None:
    plan = ScenePlan.model_validate(
        {
            "plan_id": "compiler-test",
            "title": "Compiler test",
            "world_name": "Marx Video Test",
            "objective": "Compile deterministic commands",
            "build_region": {
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 40, "y": 40, "z": 40},
            },
            "actions": [
                {
                    "type": "fill",
                    "start": {"x": 0, "y": 0, "z": 0},
                    "end": {"x": 40, "y": 40, "z": 40},
                    "block": "minecraft:stone",
                }
            ],
        }
    )
    try:
        validate_and_compile(plan)
    except PlanValidationError as error:
        assert "68921 blocks" in str(error)
    else:
        raise AssertionError("large fill was accepted")


def test_rejects_replace_by_default() -> None:
    plan = make_plan(
        [
            {
                "type": "set_block",
                "position": {"x": 0, "y": 64, "z": 0},
                "block": "minecraft:air",
                "placement": "replace",
            }
        ]
    )
    try:
        validate_and_compile(plan)
    except PlanValidationError as error:
        assert "replacement is disabled" in str(error)
    else:
        raise AssertionError("replace was accepted")


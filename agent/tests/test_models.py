import pytest
from pydantic import ValidationError

from minecraft_film_agent.models import ScenePlan


def base_plan() -> dict:
    return {
        "plan_id": "model-test",
        "title": "Model test",
        "world_name": "Marx Video Test",
        "objective": "Validate safety boundaries",
        "build_region": {
            "start": {"x": -8, "y": 60, "z": -8},
            "end": {"x": 8, "y": 70, "z": 8},
        },
        "actions": [{"type": "set_time", "value": 1000}],
    }


def test_rejects_world_path() -> None:
    payload = base_plan()
    payload["world_name"] = "../other-world"
    with pytest.raises(ValidationError):
        ScenePlan.model_validate(payload)


def test_rejects_un_namespaced_block() -> None:
    payload = base_plan()
    payload["actions"] = [
        {
            "type": "set_block",
            "position": {"x": 0, "y": 64, "z": 0},
            "block": "stone",
        }
    ]
    with pytest.raises(ValidationError):
        ScenePlan.model_validate(payload)


def test_rejects_parent_traversal_in_artifacts() -> None:
    payload = base_plan()
    payload["expected_artifacts"] = ["../outside.mp4"]
    with pytest.raises(ValidationError):
        ScenePlan.model_validate(payload)


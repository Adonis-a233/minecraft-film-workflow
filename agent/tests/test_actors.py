import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from minecraft_film_agent.actors import ActorTakePlan, canonical_plan

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "contracts" / "v3" / "fixtures" / "actor"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_valid_actor_plan_matches_contract_and_hashes_deterministically():
    plan = ActorTakePlan.model_validate(load_fixture("valid-walk-look.json"))
    first, digest1 = canonical_plan(plan)
    second, digest2 = canonical_plan(plan)
    assert first == second
    assert digest1 == digest2
    assert digest1.startswith("sha256:")


def test_actor_plan_rejects_free_command_fields():
    with pytest.raises(ValidationError):
        ActorTakePlan.model_validate(load_fixture("invalid-free-command.json"))


@pytest.mark.parametrize("mutate", [
    lambda p: p["actors"][0]["steps"][1].update(action="run_command"),
    lambda p: p["actors"][0]["steps"][1].update(start_tick=21),
    lambda p: p["actors"][0]["steps"][1].update(target={"x": 20, "y": -60, "z": 1.5}),
    lambda p: p["actors"][0].update(player_name="name with spaces"),
    lambda p: p["actors"][0]["steps"][1].update(timeout_ticks=0),
    lambda p: p["actors"][0]["steps"][0].update(item_ref="minecraft:book"),
    lambda p: p["actors"][0]["steps"][0].update(action="hold_item",item_ref="minecraft:tnt"),
    lambda p: p["actors"][0]["steps"][0].update(action="hold_item"),
])
def test_actor_plan_rejects_unbounded_or_malformed_cues(mutate):
    payload = load_fixture("valid-walk-look.json")
    mutate(payload)
    with pytest.raises(ValidationError):
        ActorTakePlan.model_validate(payload)


def test_registered_book_is_the_only_supported_prop():
    payload = load_fixture("valid-walk-look.json")
    payload["actors"][0]["steps"][0].update(action="hold_item",item_ref="minecraft:book")
    plan=ActorTakePlan.model_validate(payload)
    assert canonical_plan(plan)[0]["actors"][0]["steps"][0]["item_ref"] == "minecraft:book"


def test_recoil_requires_short_flat_path():
    payload=load_fixture("valid-walk-look.json")
    cue=payload["actors"][0]
    cue["steps"][1]["action"]="recoil_to"
    cue["steps"][1]["target"]={**cue["start"],"x":cue["start"]["x"]+3.0}
    with pytest.raises(ValidationError,match="2.5"):
        ActorTakePlan.model_validate(payload)
    cue["steps"][1]["target"]["x"]=cue["start"]["x"]+1.0
    assert canonical_plan(ActorTakePlan.model_validate(payload))[0]["actors"][0]["steps"][1]["action"]=="recoil_to"


def test_material_drop_rejects_unbounded_height():
    payload=load_fixture("valid-walk-look.json")
    cue=payload["actors"][0];step=cue["steps"][0]
    step.update(action="drop_material",target={**cue["start"],"y":cue["start"]["y"]+13.0})
    with pytest.raises(ValidationError,match="2..12"):
        ActorTakePlan.model_validate(payload)


def test_registered_character_phone_pose_is_bounded_and_contract_valid():
    payload=load_fixture("valid-walk-look.json")
    payload["actors"][0]["skin_ref"]="classmate:zhou"
    payload["actors"][0]["steps"][0]["action"]="phone"
    assert canonical_plan(ActorTakePlan.model_validate(payload))[0]["actors"][0]["skin_ref"]=="classmate:zhou"
    payload["actors"][0]["skin_ref"]="C:/arbitrary.png"
    with pytest.raises(ValidationError):ActorTakePlan.model_validate(payload)


def test_phone_pose_without_registered_model_is_rejected():
    payload=load_fixture("valid-walk-look.json");payload["actors"][0]["steps"][0]["action"]="phone"
    with pytest.raises(ValidationError,match="registered model"):ActorTakePlan.model_validate(payload)


def test_board_requires_prepare_before_one_release_and_bounded_footprint():
    payload=load_fixture("valid-walk-look.json")
    cue=payload["actors"][0]
    cue["steps"]=[dict(start_tick=0,duration_ticks=50,action="prepare_board",target=dict(x=1.5,y=-54.,z=1.5)),dict(start_tick=50,duration_ticks=50,action="drop_board")]
    assert canonical_plan(ActorTakePlan.model_validate(payload))[0]["actors"][0]["steps"][1]["action"]=="drop_board"
    cue["steps"][0]["target"]["z"]=7.5
    with pytest.raises(ValidationError,match="footprint"):ActorTakePlan.model_validate(payload)
    cue["steps"]=[dict(start_tick=0,duration_ticks=100,action="drop_board")]
    with pytest.raises(ValidationError,match="previously"):ActorTakePlan.model_validate(payload)
    cue["steps"]=[dict(start_tick=0,duration_ticks=100,action="prepare_board",target=dict(x=1.5,y=-54.,z=1.5))]
    with pytest.raises(ValidationError,match="released"):ActorTakePlan.model_validate(payload)


def test_owned_grocery_pair_matches_contract():
    plan=ActorTakePlan.model_validate(load_fixture("valid-grocery-pickup.json"))
    assert canonical_plan(plan)[0]["actors"][1]["steps"][1]["action"]=="pickup_groceries"


def test_compact_owned_grocery_route_keeps_pair_and_full_timeline():
    payload=load_fixture("valid-grocery-pickup.json")
    payload["duration_ticks"]=1540
    payload["actors"][0]["steps"][1]["duration_ticks"]=1539
    payload["actors"][1]["steps"][1]["duration_ticks"]=1520
    canonical_plan(ActorTakePlan.model_validate(payload))
    payload["actors"][1]["steps"][1]["duration_ticks"]=80
    with pytest.raises(ValidationError):
        ActorTakePlan.model_validate(payload)


@pytest.mark.parametrize("violation",["missing_pickup","missing_scatter","early","wrong_role","out_of_reach","footprint","different_center","wrong_duration","wrong_anchor"])
def test_grocery_ownership_order_and_bounds_reject_invalid_plans(violation):
    payload=load_fixture("valid-grocery-pickup.json");elder,filmer=payload["actors"]
    if violation=="missing_pickup":payload["actors"]=[elder]
    elif violation=="missing_scatter":payload["actors"]=[filmer]
    elif violation=="early":filmer["steps"][0]["duration_ticks"]=10;filmer["steps"][1].update(start_tick=10);filmer["steps"].append(dict(start_tick=3050,duration_ticks=10,action="idle"))
    elif violation=="wrong_role":filmer["skin_ref"]="classmate:a"
    elif violation=="out_of_reach":filmer["start"]["x"]=5.0
    elif violation=="footprint":elder["start"]["x"]=7.5;elder["steps"][0]["target"]["x"]=7.5
    elif violation=="different_center":filmer["steps"][1]["target"]["x"]=2.0
    elif violation=="wrong_duration":filmer["steps"][1]["duration_ticks"]=80;filmer["steps"].append(dict(start_tick=100,duration_ticks=2960,action="idle"))
    elif violation=="wrong_anchor":filmer["start"]["z"]+=.1
    with pytest.raises(ValidationError):ActorTakePlan.model_validate(payload)


def test_long_ordinary_take_cannot_use_grocery_extension():
    payload=load_fixture("valid-walk-look.json")
    payload["duration_ticks"]=1201
    for actor in payload["actors"]:
        actor["steps"]=[dict(start_tick=0,duration_ticks=1201,action="idle")]
    with pytest.raises(ValidationError,match="registered owned grocery pickup"):
        ActorTakePlan.model_validate(payload)


@pytest.mark.parametrize("action",["phone_call","phone_call_sit"])
def test_call_pose_accepts_phone_role_and_rejects_missing_phone(action):
    payload=load_fixture("valid-walk-look.json");actor=payload["actors"][0]
    actor["skin_ref"]="classmate:chen";actor["steps"]=[{"start_tick":0,"duration_ticks":payload["duration_ticks"],"action":action}]
    plan=ActorTakePlan.model_validate(payload)
    assert canonical_plan(plan)[0]["actors"][0]["steps"][0]["action"]==action
    actor["skin_ref"]="classmate:teacher"
    with pytest.raises(ValidationError,match="phone-bearing"):ActorTakePlan.model_validate(payload)
    actor["skin_ref"]=None
    with pytest.raises(ValidationError,match="registered model"):ActorTakePlan.model_validate(payload)

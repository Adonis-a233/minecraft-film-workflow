import copy,json
from pathlib import Path
import pytest
from minecraft_film_agent.actors import ActorTakePlan,canonical_plan
ROOT=Path(__file__).resolve().parents[2]
def fixture():return json.loads((ROOT/'contracts/v3/fixtures/actor/valid-coat-pickup.json').read_text())
def test_source_plan_contract():
 plan=ActorTakePlan.model_validate(fixture());canonical_plan(plan)
@pytest.mark.parametrize('change',['role','without_pickup','preceding','following','short','far','left_hand','missing_target','item','region'])
def test_reject_unsafe_coat(change):
 raw=fixture();a=raw['actors'][0];s=a['steps'][1]
 if change=='role':a['skin_ref']='classmate:zhou'
 if change=='without_pickup':s.pop('target');s['action']='hold_coat'
 if change=='preceding':a['steps'][0]['action']='idle'
 if change=='following':a['steps'][2]['action']='walk_to';a['steps'][2]['target']=copy.deepcopy(a['start']);a['steps'][2]['timeout_ticks']=80
 if change=='short':s['duration_ticks']=59;a['steps'][2]['start_tick']=99;a['steps'][2]['duration_ticks']=101
 if change=='far':s['target']['z']=152.0
 if change=='left_hand':s['target']['x']=400.55
 if change=='missing_target':s.pop('target')
 if change=='item':s['item_ref']='minecraft:book'
 if change=='region':raw['build_region']['min']['x']=399.5
 with pytest.raises(ValueError):ActorTakePlan.model_validate(raw)

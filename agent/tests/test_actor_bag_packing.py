from pathlib import Path
import json
import pytest
from minecraft_film_agent.actors import ActorTakePlan,canonical_plan
R=Path(__file__).resolve().parents[2]
def plan():return json.loads((R/'contracts/v3/fixtures/actor/valid-bag-packing.json').read_text())
@pytest.mark.parametrize('role',['classmate:zhou','classmate:a'])
def test_registered_students(role):
 p=plan();p['actors'][0]['skin_ref']=role;canonical_plan(ActorTakePlan.model_validate(p))
@pytest.mark.parametrize('case',['no_model','worker','phone_prior','walk_after','short','long','target','item','ref','edge','repeat'])
def test_reject_unsafe_packing(case):
 p=plan();a=p['actors'][0];s=a['steps']
 if case=='no_model':a['skin_ref']=None
 if case=='worker':a['skin_ref']='classmate:chen'
 if case=='phone_prior':s[0]['action']='phone_sit'
 if case=='walk_after':s[2]['action']='idle'
 if case in ['short','long']:
  n=79 if case=='short' else 121;s[1]['duration_ticks']=n;s[2].update(start_tick=20+n,duration_ticks=180-n)
 if case=='target':s[1]['target']=a['start']
 if case=='item':s[1]['item_ref']='minecraft:book'
 if case=='ref':s[1]['actor_ref']='CH01'
 if case=='edge':p['build_region']['max']['x']=a['start']['x']+.5
 if case=='repeat':s[2]['action']='pack_bag_sit'
 with pytest.raises(ValueError):ActorTakePlan.model_validate(p)

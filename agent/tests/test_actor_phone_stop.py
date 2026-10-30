import json
from pathlib import Path
import pytest
from minecraft_film_agent.actors import ActorTakePlan,canonical_plan

def fixture():
    return json.loads((Path(__file__).resolve().parents[2]/'contracts/v3/fixtures/actor/valid-phone-stop.json').read_text())

def test_phone_stop_contract():
    p,_=canonical_plan(ActorTakePlan.model_validate(fixture()))
    assert p['actors'][0]['steps'][1]['action']=='phone_stop'

def test_recording_pose_can_stop_but_is_not_a_generic_phone_pose():
    p=fixture()
    p['actors'][0]['steps'][0]['action']='phone_record'
    canonical_plan(ActorTakePlan.model_validate(p))
    p['actors'][0]['skin_ref']='classmate:chen'
    with pytest.raises(ValueError):ActorTakePlan.model_validate(p)

@pytest.mark.parametrize('case',['role','no_model','idle','seated','short','long','target','actor_ref'])
def test_invalid_phone_stop_rejected(case):
    p=fixture();a=p['actors'][0];s=a['steps'][1]
    if case=='role':a['skin_ref']='classmate:chen'
    if case=='no_model':a['skin_ref']=None
    if case=='idle':a['steps'][0]['action']='idle'
    if case=='seated':a['steps'][0]['action']='phone_sit'
    if case in ('short','long'):
        length=29 if case=='short' else 61
        s['duration_ticks']=length;a['steps'][2].update(start_tick=60+length,duration_ticks=140-length)
    if case=='target':s['target']={'x':494.,'y':0.,'z':90.}
    if case=='actor_ref':s['actor_ref']='CH05'
    with pytest.raises(ValueError):ActorTakePlan.model_validate(p)

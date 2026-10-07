import json
from pathlib import Path
import pytest
from minecraft_film_agent.actors import ActorTakePlan, canonical_plan

def fixture():
    return json.loads((Path(__file__).resolve().parents[2]/'contracts/v3/fixtures/actor/valid-phone-putaway.json').read_text())

@pytest.mark.parametrize('seated',[True,False])
def test_valid_transition(seated):
    p=fixture();a=p['actors'][0]
    if not seated:
        for s,action in zip(a['steps'],['phone','phone_putaway','idle']):s['action']=action
    canonical_plan(ActorTakePlan.model_validate(p))

@pytest.mark.parametrize('case',['role','no_model','previous','following','last','short','long','target','actor_ref'])
def test_invalid_transition(case):
    p=fixture();a=p['actors'][0];step=a['steps'][1]
    if case=='role':a['skin_ref']='classmate:chen'
    if case=='no_model':a['skin_ref']=None
    if case=='previous':a['steps'][0]['action']='phone'
    if case=='following':a['steps'][2]['action']='idle'
    if case=='last':a['steps'].pop();p['duration_ticks']=100
    if case in ('short','long'):
        n=29 if case=='short' else 61
        step['duration_ticks']=n;a['steps'][2].update(start_tick=60+n,duration_ticks=140-n)
    if case=='target':step['target']=a['start']
    if case=='actor_ref':step['actor_ref']='CH01'
    with pytest.raises(ValueError):ActorTakePlan.model_validate(p)

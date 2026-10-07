import json
from pathlib import Path
import pytest
from minecraft_film_agent.actors import ActorTakePlan,canonical_plan
def fixture():
    return json.loads((Path(__file__).resolve().parents[2]/'contracts/v3/fixtures/actor/valid-phone-place.json').read_text())
def test_valid_phone_placement():
    p,_=canonical_plan(ActorTakePlan.model_validate(fixture()))
    assert p['actors'][0]['steps'][1]['target']['y']==2.025625
@pytest.mark.parametrize('case',['role','no_call','short','long','missing_target','high','far','moves_after','second_phone','actor_ref'])
def test_invalid_phone_placement(case):
    p=fixture();a=p['actors'][0];s=a['steps'][1]
    if case=='role':a['skin_ref']='classmate:filmer'
    if case=='no_call':a['steps'][0]['action']='phone_sit'
    if case in ['short','long']:
        length=39 if case=='short' else 81;s['duration_ticks']=length;a['steps'][2].update(start_tick=60+length,duration_ticks=140-length)
    if case=='missing_target':s.pop('target')
    if case=='high':s['target']['y']=2.5
    if case=='far':s['target']['z']=118.
    if case=='moves_after':a['steps'][2].update(action='walk_to',target={'x':517.,'y':1.,'z':116.},timeout_ticks=80)
    if case=='second_phone':a['steps'][2]['action']='phone_sit'
    if case=='actor_ref':s['actor_ref']='CH04'
    with pytest.raises(ValueError):ActorTakePlan.model_validate(p)

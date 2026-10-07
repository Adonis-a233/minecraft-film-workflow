import json
from pathlib import Path
import pytest
from minecraft_film_agent.actors import ActorTakePlan,canonical_plan

def fixture():
    return json.loads((Path(__file__).resolve().parents[2]/'contracts/v3/fixtures/actor/valid-push-contact.json').read_text())

def test_push_contact_contract():
    p,_=canonical_plan(ActorTakePlan.model_validate(fixture()))
    assert p['actors'][0]['steps'][1]['actor_ref']=='CH05'

@pytest.mark.parametrize('case',['unknown','self','role','long','moving','no_recoil'])
def test_invalid_push_contact_is_rejected(case):
    p=fixture();step=p['actors'][0]['steps'][1]
    if case=='unknown':step['actor_ref']='missing'
    if case=='self':step['actor_ref']='CH04'
    if case=='role':p['actors'][0]['skin_ref']='classmate:safety'
    if case=='long':step['duration_ticks']=21;p['actors'][0]['steps'][2].update(start_tick=61,duration_ticks=59)
    if case=='moving':p['actors'][1]['steps'][0]['action']='reach'
    if case=='no_recoil':p['actors'][1]['steps'][1]={'start_tick':50,'duration_ticks':40,'action':'idle'}
    with pytest.raises(ValueError):ActorTakePlan.model_validate(p)

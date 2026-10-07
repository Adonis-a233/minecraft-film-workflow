import copy,json
from pathlib import Path
import pytest
from minecraft_film_agent.actors import ActorTakePlan,canonical_plan

def fixture():
    root=Path(__file__).resolve().parents[2]
    return json.loads((root/'contracts/v3/fixtures/actor/valid-support-rise.json').read_text())

def test_supported_rise_contract():
    plan=ActorTakePlan.model_validate(fixture())
    payload,_=canonical_plan(plan)
    assert payload['actors'][0]['steps'][1]['actor_ref']=='CH05'

@pytest.mark.parametrize('case',['unknown','self','role','coverage','idle_ref'])
def test_support_rejects_invalid_binding(case):
    p=fixture();step=p['actors'][0]['steps'][1]
    if case=='unknown':step['actor_ref']='missing'
    if case=='self':step['actor_ref']='CH04'
    if case=='role':p['actors'][0]['skin_ref']='classmate:a'
    if case=='coverage':
        for actor in [p['actors'][0],p['actors'][2]]:
            actor['steps'][1]['duration_ticks']=60;actor['steps'][2].update(start_tick=100,duration_ticks=100)
    if case=='idle_ref':p['actors'][0]['steps'][0]['actor_ref']='CH05'
    with pytest.raises(ValueError):ActorTakePlan.model_validate(p)

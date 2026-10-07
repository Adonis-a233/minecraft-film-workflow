from pathlib import Path
import json
import pytest
from minecraft_film_agent.actors import ActorTakePlan, canonical_plan

ROOT = Path(__file__).resolve().parents[2]
def plan():
    return json.loads((ROOT/'contracts/v3/fixtures/actor/valid-standing-packing.json').read_text())

def test_chen_standing_contract():
    canonical_plan(ActorTakePlan.model_validate(plan()))

@pytest.mark.parametrize('case', ['student','no_model','seated_before','seated_after','short','long','target','item','ref','repeat','edge'])
def test_unsafe_standing_packing_rejected(case):
    p=plan();a=p['actors'][0];s=a['steps']
    if case=='student':a['skin_ref']='classmate:zhou'
    if case=='no_model':a['skin_ref']=None
    if case=='seated_before':s[0]['action']='sit'
    if case=='seated_after':s[2]['action']='sit'
    if case in ['short','long']:
        n=79 if case=='short' else 121
        s[1]['duration_ticks']=n;s[2].update(start_tick=20+n,duration_ticks=180-n)
    if case=='target':s[1]['target']=a['start']
    if case=='item':s[1]['item_ref']='minecraft:book'
    if case=='ref':s[1]['actor_ref']='CH04'
    if case=='repeat':s[2]['action']='pack_bag_stand'
    if case=='edge':p['build_region']['max']['z']=a['start']['z']+.5
    with pytest.raises(ValueError):ActorTakePlan.model_validate(p)

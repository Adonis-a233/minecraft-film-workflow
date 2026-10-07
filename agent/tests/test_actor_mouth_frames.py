import json,copy
from pathlib import Path
import pytest
from minecraft_film_agent.actors import ActorTakePlan,canonical_plan

def fixture():return json.loads((Path(__file__).resolve().parents[2]/'contracts/v3/fixtures/actor/valid-mouth-frames.json').read_text())
def test_mouth_frames_cover_take_and_survive_contract():
    p=ActorTakePlan.model_validate(fixture());assert len(p.actors[0].mouth_frames)==200
    assert canonical_plan(p)[0]['actors'][0]['mouth_frames']==fixture()['actors'][0]['mouth_frames']
@pytest.mark.parametrize('bad',[[0]*199,[0]*201,[3]*200,[-1]*200,[True]*200,[1.0]*200,['1']*200])
def test_reject_malformed_track(bad):
    raw=fixture();raw['actors'][0]['mouth_frames']=bad
    with pytest.raises(ValueError):ActorTakePlan.model_validate(raw)
def test_reject_vanilla_actor_mouth():
    raw=fixture();a=raw['actors'][0];a['skin_ref']=None;a['steps']=[dict(start_tick=0,duration_ticks=200,action='idle')]
    with pytest.raises(ValueError):ActorTakePlan.model_validate(raw)
def test_old_actor_plan_remains_valid():
    raw=fixture();del raw['actors'][0]['mouth_frames'];assert ActorTakePlan.model_validate(raw).actors[0].mouth_frames is None

import pytest
from pydantic import ValidationError
from minecraft_film_agent.production_models import ActorCue, ShotPlan
from minecraft_film_agent.timeline import compile_shot_timeline


def test_distinct_local_skins_survive_three_actor_compilation():
    skins = ['s01_ch03_efe', 's01_ch02_noor', 's01_ch01_steve']
    shot = ShotPlan(shot_id='s01', scene_id='S01', duration_ticks=220,
        recording={'pre_roll_ticks':20,'post_roll_ticks':20},
        actors=[ActorCue(actor_id=f'FilmCH0{3-i}',action_ref=f'action-{i}',
            start_tick=0,skin_file=skin) for i,skin in enumerate(skins)])
    timeline=compile_shot_timeline(shot,world_name='rehearsal',mocap_scene='scene',include_flashback=False)
    adds=[e.payload for e in timeline.events if e.type=='mocap.scene_add']
    assert [(p['player_name'],p['skin_file']) for p in adds] == list(zip(['FilmCH03','FilmCH02','FilmCH01'],skins))
    assert timeline.total_ticks==260
    assert timeline.events[-1].tick==240


@pytest.mark.parametrize('skin',['../other','C:/skin','file.png','skin start evil'])
def test_skin_binding_rejects_path_or_command_text(skin):
    with pytest.raises(ValidationError):
        ActorCue(actor_id='FilmCH03',action_ref='walk',start_tick=0,skin_file=skin)

"""Independent Sponge fixtures, process crash locks and real media assembly."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import nbtlib
import pytest

from minecraft_film_agent.assets import register_asset, AssetRegistryError
from minecraft_film_agent.edit import execute_edit, load_edit_list, EditPlanError
from minecraft_film_agent.importer import import_schematic, ImportError
from minecraft_film_agent.locking import RunLease, RunBusyError
from minecraft_film_agent.production_models import GameStateV2, OperationResultV3
from minecraft_film_agent.schematic import load_schematic, decode_varints, SchematicError

ROOT = Path(__file__).resolve().parents[2]
FFMPEG = ROOT / 'tools/ffmpeg/bin/ffmpeg.exe'
FFPROBE = ROOT / 'tools/ffmpeg/bin/ffprobe.exe'


def fixture(path, *, version=3, bad=False):
    # 300 is encoded as AC 02, independently of the implementation encoder.
    blocks = nbtlib.Compound({'Palette': nbtlib.Compound({
        'minecraft:air': nbtlib.Int(0),
        'minecraft:oak_stairs[facing=east]': nbtlib.Int(300)}),
        'Data': nbtlib.ByteArray([-84, 2, 0])})
    if bad:
        blocks['Palette'] = nbtlib.Compound({'minecraft:unknown': nbtlib.Int(300), 'minecraft:air': nbtlib.Int(0)})
    schematic = nbtlib.Compound({'Version': nbtlib.Int(version), 'DataVersion': nbtlib.Int(3955),
        'Width': nbtlib.Short(2), 'Height': nbtlib.Short(1), 'Length': nbtlib.Short(1),
        'Offset': nbtlib.IntArray([1, 0, -1])})
    if version == 3:
        schematic['Blocks'] = blocks
        file = nbtlib.File({'Schematic': schematic}, gzipped=True)
    else:
        schematic['Palette'] = blocks['Palette']; schematic['BlockData'] = blocks['Data']
        file = nbtlib.File(schematic, root_name='Schematic', gzipped=True)
    file.save(path)


@pytest.mark.parametrize('version', [2, 3])
def test_independent_sponge_fixture(tmp_path, version):
    source = tmp_path/'fixture.schem'; fixture(source, version=version)
    data = load_schematic(source)
    assert data.states == ('minecraft:oak_stairs[facing=east]', 'minecraft:air')
    assert data.summary.offset == [1, 0, -1] and data.summary.data_version == 3955


@pytest.mark.parametrize('raw', [b'\x80', b'\xff\xff\xff\xff\x08', b'\x00\x00'])
def test_malformed_varints(raw):
    with pytest.raises(SchematicError): decode_varints(raw, 1)


def test_process_death_releases_lease(tmp_path):
    path=tmp_path/'run.lease'; ready=tmp_path/'ready'
    code='from pathlib import Path; import time; from minecraft_film_agent.locking import RunLease\nwith RunLease(Path(__import__("sys").argv[1])):\n Path(__import__("sys").argv[2]).write_text("ready")\n time.sleep(60)'
    import os
    env={**os.environ, 'PYTHONPATH':os.pathsep.join(filter(None, (str(ROOT/'agent/src'), os.environ.get('PYTHONPATH'))))}
    process=subprocess.Popen([sys.executable,'-c',code,str(path),str(ready)],env=env)
    try:
        import time
        deadline=time.monotonic()+10
        while not ready.exists() and time.monotonic()<deadline: time.sleep(.02)
        assert ready.exists()
        with pytest.raises(RunBusyError):
            with RunLease(path): pass
        process.kill(); process.wait(timeout=10)
        with RunLease(path): pass
        assert path.exists()
    finally:
        if process.poll() is None: process.kill(); process.wait(timeout=10)


def asset(workspace, *, bad=False, method="bridge-keep"):
    source=workspace/'original.schem'; fixture(source,bad=bad)
    record={'schema_version':3,'asset_id':'test-scene','kind':'schematic',
        'source':{'path':str(source),'sha256':'sha256:'+hashlib.sha256(source.read_bytes()).hexdigest(),'size_bytes':source.stat().st_size},
        'import_method':method,'data_version':3955}
    register_asset(workspace,record,source)
    return source,record


class World:
    def __init__(self): self.blocks={}; self.writes=[]
    def call_v3(self,request):
        params=request.params
        if request.method=='bridge.get_runtime_versions': result={'minecraft':'1.21.1'}
        elif request.method=='bridge.get_game_state':
            result=GameStateV2(session_phase='in_world',save_name='test',player_name='actor',dimension='minecraft:overworld',paused=False,blocking_screen=False).model_dump(mode='json')
        elif request.method=='world.get_block':
            state=self.blocks.get((params['x'],params['y'],params['z']),'minecraft:air')
            result={'block':state.split('[',1)[0],'block_state':state}
            if 'validate_block' in params:
                result['block_state_valid']='unknown' not in params['validate_block']
                result['canonical_state']=params['validate_block']
        else:
            assert request.method=='world.set_block_keep'
            self.writes.append(request)
            self.blocks[(params['x'],params['y'],params['z'])]=params['block']
            return OperationResultV3(operation_id=request.operation_id,idempotency_key=request.idempotency_key,status='succeeded',result={'ok':True})
        return OperationResultV3(operation_id=request.operation_id,idempotency_key=request.idempotency_key,status='applied',result=result)
    def await_world_op_v3(self,run,key,submitted,**kwargs): return submitted


def importing(workspace,world):
    return import_schematic(workspace=workspace,client=world,asset_id='test-scene',run_id='import-test',world='test',player='actor',origin=(0,80,0),
        build_region={'start':{'x':0,'y':80,'z':-2},'end':{'x':4,'y':81,'z':2}},evidence_dir=workspace/'work/import',data_version=3955)


def test_import_offset_state_resume_and_drift(tmp_path):
    asset(tmp_path); world=World()
    assert importing(tmp_path,world)['verified_blocks']==1
    assert world.blocks[(1,80,-1)]=='minecraft:oak_stairs[facing=east]'
    importing(tmp_path,world); assert len(world.writes)==1
    world.blocks[(1,80,-1)]='minecraft:stone'
    with pytest.raises(ImportError,match='drifted'): importing(tmp_path,world)
    assert len(world.writes)==1


@pytest.mark.parametrize('bad', [True, False])
def test_import_rejects_before_any_mutation(tmp_path,bad):
    asset(tmp_path,bad=bad); world=World()
    if not bad: world.blocks[(1,80,-1)]='minecraft:stone'
    with pytest.raises(ImportError,match='invalid block|occupied'): importing(tmp_path,world)
    assert world.writes==[]


def test_original_cannot_be_overwritten(tmp_path):
    source,record=asset(tmp_path); before=source.read_bytes()
    with pytest.raises(AssetRegistryError,match='never overwritten'):
        register_asset(tmp_path,record,source,overwrite=True)
    assert source.read_bytes()==before


@pytest.mark.skipif(not FFMPEG.exists(),reason='pinned media tools unavailable')
def test_real_edit_audio_delay_fades_subtitle_and_output(tmp_path):
    import numpy as np
    video=tmp_path/'source.mp4'; audio=tmp_path/'tone.wav'
    subprocess.run([str(FFMPEG),'-v','error','-f','lavfi','-i','testsrc2=size=160x120:rate=30:duration=3','-c:v','libx264',str(video)],check=True)
    subprocess.run([str(FFMPEG),'-v','error','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=1',str(audio)],check=True)
    edit={'schema_version':3,'edit_id':'test-edit','output':{'path':'work/delivered.mp4','width':160,'height':120,'fps':30},
        'video_clips':[{'source':str(video),'take_from_seconds':1,'duration_seconds':2,'timeline_start_seconds':1},
                       {'source':str(video),'take_from_seconds':0,'duration_seconds':1,'timeline_start_seconds':0}],
        'audio_clips':[{'source':str(audio),'take_from_seconds':0,'duration_seconds':1,'timeline_start_seconds':1,'fade_in_seconds':.2,'fade_out_seconds':.2}],
        'subtitles':[{'start_seconds':.2,'end_seconds':.8,'text':'字幕验收'}]}
    report=execute_edit(edit,workspace=tmp_path,evidence_dir=tmp_path/'work/edit',ffmpeg=FFMPEG,ffprobe=FFPROBE)
    assert report['status']=='succeeded' and report['audio_decode_passed'] and (tmp_path/'work/delivered.mp4').exists()
    decoded=subprocess.run([str(FFMPEG),'-v','error','-i',str(tmp_path/'work/delivered.mp4'),'-vn','-ac','1','-ar','48000','-f','f32le','pipe:1'],capture_output=True,check=True)
    samples=np.frombuffer(decoded.stdout,dtype='<f4')
    def rms(a,b): return np.sqrt(np.mean(samples[int(a*48000):int(b*48000)]**2))
    assert rms(.1,.8)<.001 and rms(2.2,2.8)<.001
    assert rms(1.3,1.7)>.03
    assert rms(1.01,1.06)<rms(1.3,1.7)*.5
    assert rms(1.94,1.99)<rms(1.3,1.7)*.5
    with pytest.raises(EditPlanError,match='already exists'):
        execute_edit(edit,workspace=tmp_path,evidence_dir=tmp_path/'work/other',ffmpeg=FFMPEG,ffprobe=FFPROBE)
    edit['video_clips'][0]['timeline_start_seconds']=2
    with pytest.raises(EditPlanError,match='gap'): load_edit_list(edit)


def test_import_method_has_no_silent_fallback(tmp_path):
    asset(tmp_path,method="worldedit-schem"); world=World()
    with pytest.raises(ImportError,match="explicitly select bridge-keep"): importing(tmp_path,world)
    assert world.writes==[]

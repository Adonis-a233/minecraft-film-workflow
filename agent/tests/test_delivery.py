from pathlib import Path
import subprocess
import pytest

from minecraft_film_agent.delivery import assemble_delivery
from minecraft_film_agent.edit import EditPlanError
from minecraft_film_agent.photography import file_hash

ROOT=Path(__file__).resolve().parents[2]
FFMPEG=ROOT/'tools/ffmpeg/bin/ffmpeg.exe'
FFPROBE=ROOT/'tools/ffmpeg/bin/ffprobe.exe'


@pytest.mark.skipif(not FFMPEG.is_file(),reason='pinned media tools absent')
def test_delivery_resume_and_changed_master_block_publication(tmp_path):
    instance=tmp_path/'instance';master=instance/'replays/owned.mcpr';master.parent.mkdir(parents=True);master.write_bytes(b'accepted master')
    video=tmp_path/'assets/renders/source.mp4';video.parent.mkdir(parents=True)
    subprocess.run([str(FFMPEG),'-v','error','-f','lavfi','-i','testsrc2=size=160x120:rate=30:duration=1','-c:v','libx264',str(video)],check=True)
    proof={'output':'assets/renders/source.mp4','output_hash':file_hash(video),'master_id':'owned','master_hash':file_hash(master)}
    edit={'schema_version':3,'edit_id':'delivery-test','output':{'path':'assets/renders/final.mp4','width':160,'height':120,'fps':30},
        'video_clips':[{'source':proof['output'],'take_from_seconds':0,'duration_seconds':1,'timeline_start_seconds':0}]}
    kwargs=dict(workspace=tmp_path,instance=instance,exports=[proof],evidence_dir=tmp_path/'work/delivery',ffmpeg=FFMPEG,ffprobe=FFPROBE)
    first=assemble_delivery(edit,**kwargs)
    assert assemble_delivery(edit,**kwargs)['output_hash']==first['output_hash']
    before=(tmp_path/'assets/renders/final.mp4').read_bytes()
    master.write_bytes(b'changed master')
    with pytest.raises(EditPlanError,match='master changed'): assemble_delivery(edit,**kwargs)
    assert (tmp_path/'assets/renders/final.mp4').read_bytes()==before


def test_unaccepted_clip_is_rejected_before_output_writes(tmp_path):
    edit={'schema_version':3,'edit_id':'delivery-test','output':{'path':'assets/renders/final.mp4','width':160,'height':120,'fps':30},
        'video_clips':[{'source':'work/unaccepted.mp4','take_from_seconds':0,'duration_seconds':1,'timeline_start_seconds':0}]}
    with pytest.raises(EditPlanError,match='without accepted export proof'):
        assemble_delivery(edit,workspace=tmp_path,instance=tmp_path/'instance',exports=[],evidence_dir=tmp_path/'work/delivery',ffmpeg=FFMPEG,ffprobe=FFPROBE)
    assert not (tmp_path/'work').exists()

"""Export new views from a verified new master; never re-submit actor motion."""
import argparse,json
from pathlib import Path
from minecraft_film_agent.bridge_client import CinematicBridgeClient,CinematicBridgeConfig
from minecraft_film_agent.photography import ReplayPhotography,file_hash,publish_file
from minecraft_film_agent.media import verify_render
from minecraft_film_agent.locking import RunLease,write_json
import subprocess


def main():
    parser=argparse.ArgumentParser();parser.add_argument('package',type=Path)
    parser.add_argument('views',type=Path);parser.add_argument('--export-id',required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1];folder=args.package.resolve()
    import re
    if not folder.is_relative_to(root/'work') or not re.fullmatch('[a-z0-9-]{1,48}',args.export_id):raise ValueError('unsafe export identity')
    spec=json.loads((folder/'capture.json').read_text(encoding='utf-8'));instance=Path(spec['instance'])
    master=json.loads((folder/'master.json').read_text(encoding='utf-8'))
    if file_hash(Path(master['master_file']))!=master['master_hash']:raise ValueError('master changed')
    views=json.loads(args.views.read_text(encoding='utf-8'));onset=json.loads((folder/'trace-summary.json').read_text())['onset']
    client=CinematicBridgeClient(CinematicBridgeConfig('http://127.0.0.1:25575/rpc',(instance/'config/cinematicbridge.token').read_text().strip(),20))
    photo=ReplayPhotography(client,args.export_id,timeout=360)
    evidence=folder/args.export_id;evidence.mkdir(exist_ok=False)
    with RunLease(evidence/'export.lock'):
        photo.open_master(master['master_id'],master['master_hash'])
        outputs=[]
        for view in views:
            name=view['id']
            if not re.fullmatch('[a-z0-9-]{1,48}',name):raise ValueError('unsafe view')
            start=onset+view['start_tick'];end=onset+view['end_tick']
            if not onset<=start<end:raise ValueError('invalid range')
            output=instance/'bridge-renders'/args.export_id/(name+'.mp4')
            if output.exists():raise ValueError('output exists')
            output.parent.mkdir(parents=True,exist_ok=True)
            camera={'interpolation':'linear','keyframes':[dict(tick=t,position=view['position'],rotation=view['rotation'],fov=view['fov']) for t in (start,end)]}
            write_json(evidence/(name+'-submitted.json'),{'master':master,'view':view,'status':'submitted; query status before retry'})
            result=photo.render(master['master_id'],master['master_hash'],name,camera,output,start,end,1280,720,30)
            write_json(evidence/(name+'-render.json'),result.model_dump(mode='json'))
            report=verify_render(output,expected_width=1280,expected_height=720,expected_fps=30,expected_min_duration_seconds=(end-start)/20,expected_duration_seconds=(end-start)/20,expected_frames=(end-start)*30//20,require_decode=True,ffmpeg_path=root/'tools/ffmpeg/bin/ffmpeg.exe',ffprobe_path=root/'tools/ffmpeg/bin/ffprobe.exe')
            black=subprocess.run([str(root/'tools/ffmpeg/bin/ffmpeg.exe'),'-hide_banner','-i',str(output),'-vf','blackdetect=d=0.1:pix_th=0.02:pic_th=0.98','-an','-f','null','-'],capture_output=True,text=True)
            (evidence/(name+'-blackdetect.log')).write_text(black.stderr,encoding='utf-8')
            status='rejected_black_frames' if black.returncode or 'black_start:' in black.stderr else 'passed'
            destination=root/'assets/footage'/folder.name/(name+'.mp4')
            if status=='passed':publish_file(output,destination)
            outputs.append({'view':name,'path':str(destination if status=='passed' else output),'sha256':file_hash(output),'technical_status':status,'technical':report.model_dump(mode='json'),'human_review':'pending' if status=='passed' else 'not_submitted'})
            write_json(evidence/'candidates.json',outputs)
    print('export complete; human review pending')


if __name__=='__main__':main()

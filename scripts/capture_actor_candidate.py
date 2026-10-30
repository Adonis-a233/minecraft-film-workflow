"""Record one typed actor take and export pending-review candidates; never approve."""
import argparse, json, time, subprocess
from pathlib import Path
from minecraft_film_agent.actors import load_plan, start_take, wait_for_take
from minecraft_film_agent.bridge_client import CinematicBridgeClient, CinematicBridgeConfig
from minecraft_film_agent.locking import RunLease, write_json
from minecraft_film_agent.photography import ReplayPhotography, file_hash, publish_file
from minecraft_film_agent.media import verify_render
from lock_filming_runtime import snapshot

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('package',type=Path)
    ap.add_argument('--status',action='store_true'); args=ap.parse_args()
    root=Path(__file__).resolve().parents[1]; folder=args.package.resolve()
    spec=json.loads((folder/'capture.json').read_text(encoding='utf-8'))
    instance=Path(spec['instance']).resolve(); plan_path=folder/'actor-plan.json'; plan=load_plan(plan_path)
    video=spec.get('video',{'width':1280,'height':720,'fps':30})
    if video not in ({'width':1280,'height':720,'fps':30},{'width':1920,'height':1080,'fps':30}):
        raise ValueError('capture requires a supported 16:9/30fps output')
    if instance.parent!=root/'game/instances': raise ValueError('instance outside project')
    if file_hash(plan_path)!=spec['actor_plan_hash']: raise ValueError('actor plan pin changed')
    if file_hash(instance/'mods/cinematic-bridge-0.1.0.jar')!=spec['bridge_hash']: raise ValueError('bridge pin changed')
    if file_hash(root/'assets/actors/classmate-20261004/visual-binding-v10.json')!=spec['binding_hash']: raise ValueError('binding pin changed')
    runtime_lock=folder/'runtime-lock.json'
    if not args.status and runtime_lock.exists():
        if snapshot(instance)!=json.loads(runtime_lock.read_text(encoding='utf-8')):
            raise ValueError('filming stack changed; inspect runtime lock before recording')
    client=CinematicBridgeClient(CinematicBridgeConfig('http://127.0.0.1:25575/rpc',
        (instance/'config/cinematicbridge.token').read_text().strip(),20))
    photo=ReplayPhotography(client,plan.run_id,timeout=360)
    if args.status:
        for stage,method,params in [('state','bridge.get_game_state',{}),('actor','actor.get_take_status',{'take_id':plan.take_id}),
                                    ('master','replay.get_master_status',{}),('render','replay.get_render_status',{})]:
            print(stage,photo.call('inspect-'+stage,method,params).model_dump_json())
        return
    journal=folder/'capture-journal.json'; fingerprint=file_hash(folder/'capture.json')
    data=json.loads(journal.read_text()) if journal.exists() else {'spec_hash':fingerprint,'stages':{},'review':'pending','status':'running'}
    if data['spec_hash']!=fingerprint: raise ValueError('capture spec changed; create a new run')
    def stage(name, action):
        prior=data['stages'].get(name)
        if prior:
            if prior['status']=='succeeded': return prior['result']
            # Never blindly retry a write whose reply may have been lost.
            resolution=client.operation_status_v3(plan.run_id,plan.run_id+'/'+name)
            write_json(folder/(name+'-resolution.json'),resolution.model_dump(mode='json'))
            raise RuntimeError(name+' unresolved; inspect saved resolution and --status; no write was resent')
        data['stages'][name]={'status':'submitted'}; write_json(journal,data)
        try:
            result=action()
            if hasattr(result,'model_dump'): result=result.model_dump(mode='json')
            data['stages'][name]={'status':'succeeded','result':result}; write_json(journal,data)
            print(name,'succeeded',flush=True); return result
        except Exception as error:
            data['status']='blocked';data['stages'][name]['error']=str(error);write_json(journal,data); raise
    with RunLease(folder/'capture.lock'):
        caps=photo.poll('caps','bridge.capabilities',{},lambda r:r.status=='applied').result
        if any(caps.get(k)!='replaymod' for k in ('replay_backend','camera_backend','render_backend')):
            raise RuntimeError('ReplayMod capability preflight failed')
        for label,method in [('runtime-versions','bridge.get_runtime_versions'),('loaded-resourcepacks','bridge.get_resourcepacks')]:
            write_json(folder/(label+'.json'),photo.require(label,method,{}).model_dump(mode='json'))
        if 'record-stop' not in data['stages']:
            state=photo.poll('ready','bridge.get_game_state',{},lambda r:
                r.result.get('save_name')==plan.world and not r.result.get('blocking_screen') and not r.result.get('paused'))
            write_json(folder/'preflight-state.json',state.model_dump(mode='json'))
            stage('record-start',lambda:photo.require('record-start','replay.start_recording',{'timeline_id':plan.run_id}))
            def submit():
                r=start_take(client,plan,plan.run_id+'/actor-submit')
                if r.status not in ('applied','accepted','pending','succeeded'): raise RuntimeError(r.model_dump_json())
                return r
            stage('actor-submit',submit)
            def wait():
                r=wait_for_take(client,plan.run_id,plan.take_id,180)
                if r.result.get('take_state')!='succeeded': raise RuntimeError(r.model_dump_json())
                return r
            # Read-only wait may safely be repeated after a process interruption.
            try:
                result=wait()
            except Exception as error:
                data['status']='blocked';data['failure']=str(error);write_json(journal,data)
                raise
            write_json(folder/'actor-result.json',result.model_dump(mode='json'))
            rows=[json.loads(line) for line in Path(result.result['trace']).read_text(encoding='utf-8').splitlines()]
            if len(rows)!=len(plan.actors)*plan.duration_ticks: raise ValueError('incomplete authoritative trace')
            onset=round(rows[0]['replay_timestamp_ms']/50)
            write_json(folder/'trace-summary.json',{'rows':len(rows),'onset':onset,'trace':result.result['trace']})
            time.sleep(1)
            stage('record-stop',lambda:photo.require('record-stop','replay.stop_recording',{'timeline_id':plan.run_id}))
        master=photo.await_master(plan.run_id).result;write_json(folder/'master.json',master)
        if file_hash(Path(master['master_file']))!=master['master_hash']: raise ValueError('saved master changed')
        onset=json.loads((folder/'trace-summary.json').read_text())['onset']
        photo.open_master(master['master_id'],master['master_hash'])
        outputs=[]
        for view in spec['views']:
            name=view['id']; start=onset+view['start_tick']; end=onset+view['end_tick']
            camera={'interpolation':'linear','keyframes':[
                {'tick':start,'position':view['position'],'rotation':view['rotation'],'fov':view['fov']},
                {'tick':end,'position':view['position'],'rotation':view['rotation'],'fov':view['fov']}]}
            out=instance/'bridge-renders'/plan.run_id/(name+'.mp4')
            out.parent.mkdir(parents=True,exist_ok=True)
            stage('camera-'+name,lambda:photo.require('camera-'+name,'replay.replace_camera_track',{
                'timeline_id':master['master_id'],'master_hash':master['master_hash'],**camera}))
            stage('render-'+name,lambda:photo.require('render-'+name,'replay.start_render',{
                'timeline_id':master['master_id'],'master_hash':master['master_hash'],'range':{'start_tick':start,'end_tick':end},
                **video,'output_path':str(out)}))
            photo.poll('render-status-'+name,'replay.get_render_status',{},lambda r:r.result.get('state')=='rendered')
            report=verify_render(out,expected_width=video['width'],expected_height=video['height'],expected_fps=video['fps'],
                expected_min_duration_seconds=(end-start)/20,expected_duration_seconds=(end-start)/20,
                expected_frames=(end-start)*30//20,require_decode=True,
                ffmpeg_path=root/'tools/ffmpeg/bin/ffmpeg.exe',ffprobe_path=root/'tools/ffmpeg/bin/ffprobe.exe')
            black=subprocess.run([str(root/'tools/ffmpeg/bin/ffmpeg.exe'),'-hide_banner','-i',str(out),
                '-vf','blackdetect=d=0.1:pix_th=0.02:pic_th=0.98','-an','-f','null','-'],capture_output=True,text=True)
            (folder/(name+'-blackdetect.log')).write_text(black.stderr,encoding='utf-8')
            if black.returncode or 'black_start:' in black.stderr:
                outputs.append({'view':name,'path':str(out),'sha256':file_hash(out),
                    'technical_status':'rejected_black_frames' if black.returncode==0 else 'blackdetect_failed',
                    'human_review':'not_submitted','technical':report.model_dump(mode='json')})
                write_json(folder/'candidates.json',outputs)
                continue
            destination=root/'assets/footage'/plan.run_id/(name+'.mp4')
            if destination.exists():
                if file_hash(destination)!=file_hash(out): raise ValueError('publication path conflicts')
            else: publish_file(out,destination)
            outputs.append({'view':name,'path':str(destination),'sha256':file_hash(destination),
                'technical_status':'passed','technical':report.model_dump(mode='json'),'human_review':'pending'})
            write_json(folder/'candidates.json',outputs)
        data['status']='needs_review';write_json(journal,data)
        print('needs_review: candidates saved; no human approval recorded',flush=True)

if __name__=='__main__': main()

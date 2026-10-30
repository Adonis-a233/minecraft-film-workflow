"""Derive a camera from the filmed phone's back face, never a guessed external view.

Uses original v12 mesh coordinates and observed item_display quaternion + root
yaw. This geometric lens anchor is a production convention, not phone optics.
"""
import argparse
import json
import math
import zipfile
from pathlib import Path
from minecraft_film_agent.photography import file_hash


def rotate(q, v):
    x,y,z,w=q
    norm=math.sqrt(sum(n*n for n in q))
    if abs(norm-1)>.0001:raise ValueError('non-unit observed quaternion')
    tx,ty,tz=2*(y*v[2]-z*v[1]),2*(z*v[0]-x*v[2]),2*(x*v[1]-y*v[0])
    return [v[0]+w*tx+y*tz-z*ty,v[1]+w*ty+z*tx-x*tz,v[2]+w*tz+x*ty-y*tx]


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('package',type=Path)
    ap.add_argument('--start',type=int,default=100)
    ap.add_argument('--end',type=int,default=200)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--replay-eye-height',type=float,default=1.62,
                    help='Pinned ReplayMod CameraEntity inherits standing client-player eye offset')
    args=ap.parse_args()
    summary=json.loads((args.package/'trace-summary.json').read_text())
    trace=Path(summary['trace'])
    capture=json.loads((args.package/'capture.json').read_text())
    source_pack=Path(capture['instance'])/'resourcepacks/Classmate_Kanjian2_1.21.1_v12.zip'
    with zipfile.ZipFile(source_pack) as pack:
        meshes={n.split('/')[-1][:-5]:json.loads(pack.read(n)) for n in pack.namelist()
                if '/models/actor/filmer/' in n and n.endswith('.json')}
    grip_pack=Path(capture['instance'])/'resourcepacks/KJDS_Filmer_RecordGrip_candidate.zip'
    loaded=args.package/'loaded-resourcepacks.json'
    dependency_evidence={'source':str(loaded),'sha256':file_hash(loaded)}
    if grip_pack.name not in loaded.read_text():
        # Startup profile snapshots can be empty. The recording process's
        # ResourceManager reload log is historical evidence, not a later launch.
        log=args.package/'queue-game.log'
        reloads=[line for line in log.read_bytes().decode('utf-8',errors='replace').splitlines()
                 if 'Reloading ResourceManager:' in line]
        lock=json.loads((args.package/'runtime-lock.json').read_text())
        expected=lock['files_sha256'].get('resourcepacks/'+grip_pack.name)
        if not reloads or 'file/'+grip_pack.name not in reloads[-1].split(': Reloading ResourceManager: ')[-1].split(', ') or file_hash(grip_pack).removeprefix('sha256:')!=expected:
            raise ValueError('actual loaded recording grip dependency is not evidenced')
        dependency_evidence={'source':str(log),'sha256':file_hash(log),
                             'observation':reloads[-1],'runtime_lock_sha256':file_hash(args.package/'runtime-lock.json')}
    with zipfile.ZipFile(grip_pack) as pack:
        meshes['forearm_l_record']=json.loads(pack.read('assets/kanjian2/models/actor/filmer/forearm_l_record.json'))
    rows=[json.loads(l) for l in trace.read_text().splitlines()]
    selected=[r for r in rows if r['actor_id']=='CH06' and args.start<=r['planned_tick']<=args.end]
    if len(selected)!=args.end-args.start+1:raise ValueError('phone trace incomplete')
    frames=[]
    for r in selected:
        if r['action'] not in ('phone_record','drop_board') or not r['visual']['phone_visible']:
            raise ValueError('only visible filming phone supports this camera')
        part=next(p for p in r['visual']['parts'] if p['part']=='forearm_l')
        # Upper rear surface of the dedicated recording grip, units16px/block.
        local=[(8.15-8)/16,(6.95-8)/16,(4.89-8)/16]
        # Pinned vanilla ItemDisplayEntityRenderer.render multiplies Y(pi)
        # before item mesh rendering; translation is not rotated by that step.
        local=[-local[0],local[1],-local[2]]
        offset=rotate(part['local_rotation'],local)
        offset=[a+b for a,b in zip(offset,part['local_translation'])]
        direction=rotate(part['local_rotation'],[0,0,1])
        yawq=[0,math.sin(math.radians(-r['yaw'])/2),0,math.cos(math.radians(-r['yaw'])/2)]
        offset=rotate(yawq,offset);direction=rotate(yawq,direction)
        lens=[r[k]+offset[i] for i,k in enumerate(('x','y','z'))]
        # Check the optical point against the actual rotated model cubes,
        # including the actor's own head/chest/phone, not their unrotated AABBs.
        for observed in r['visual']['parts']:
            name=observed['part']
            mesh=meshes['forearm_l_record' if name=='forearm_l' else name]
            local_point=rotate([0,-yawq[1],0,yawq[3]],[lens[i]-r[k] for i,k in enumerate(('x','y','z'))])
            local_point=[v-t for v,t in zip(local_point,observed['local_translation'])]
            q=observed['local_rotation']
            local_point=rotate([-q[0],-q[1],-q[2],q[3]],local_point)
            local_point=[-local_point[0]*16+8,local_point[1]*16+8,-local_point[2]*16+8]
            for cube in mesh['elements']:
                if cube.get('rotation'):raise ValueError('rotated mesh requires exact cube rotation support')
                if all(lo+1e-6<v<hi-1e-6 for lo,v,hi in zip(cube['from'],local_point,cube['to'])):
                    raise ValueError(f'phone lens is inside filming actor mesh: {name}, tick{r["planned_tick"]}')
        # CameraProperties.Position calls CameraEntity.setCameraPosition (entity
        # feet), then Minecraft Camera adds standing eye height. Do not send the
        # optical center as entity feet. Preserve existing external view presets.
        position=[lens[0],lens[1]-args.replay_eye_height,lens[2]]
        rotation=[math.degrees(math.atan2(-direction[0],direction[2])),
                  -math.degrees(math.asin(max(-1,min(1,direction[1])))),0]
        frames.append(dict(tick=r['planned_tick'],position=position,rotation=rotation,fov=45))
    view=dict(id='phone-optical',start_tick=args.start,end_tick=args.end,**{k:frames[0][k] for k in ('position','rotation','fov')},keyframes=frames)
    with args.output.open('x',encoding='utf-8') as out:json.dump([view],out,indent=2)
    with args.output.with_suffix('.provenance.json').open('x',encoding='utf-8') as out:
        json.dump(dict(trace_sha256=file_hash(trace),anchor_model='filmer/forearm_l_record',
                       dependency_evidence=dependency_evidence,
                       lens_model_coordinates=[8.15,6.95,4.89],optical_axis=[0,0,-1],
                       replay_entity_eye_offset=args.replay_eye_height,
                       item_mesh_extra_rotation_y_degrees=180,
                       source_pack_sha256=file_hash(source_pack),
                       recording_grip_pack_sha256=file_hash(grip_pack),
                       optical_point_outside_filmer_meshes=True,
                       camera_source='authoritative same-take phone mesh transforms',human_review='pending'),out,indent=2)
    print(args.output)


if __name__=='__main__':main()

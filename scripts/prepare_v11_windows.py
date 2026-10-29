"""Prepare a new isolated Windows pilot from explicit preserved production inputs."""
from pathlib import Path
import argparse, hashlib, io, json, shutil, struct, zlib
import nbtlib
from minecraft_film_agent.actors import ActorTakePlan, canonical_plan

def digest(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def inventory(root):
    return {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob('*')) if p.is_file()}

def clean_owned(world):
    removed=[]
    for path in (world/'entities').glob('r.*.mca'):
        raw=path.read_bytes(); chunks={}; dirty=False
        for i in range(1024):
            offset=int.from_bytes(raw[i*4:i*4+3], 'big')*4096
            if not offset: continue
            length=int.from_bytes(raw[offset:offset+4], 'big'); blob=raw[offset+4:offset+4+length]
            if blob[0]!=2: raise ValueError('unsupported region compression')
            n=nbtlib.File.parse(io.BytesIO(zlib.decompress(blob[1:]))); keep=[]
            for entity in n.get('Entities', []):
                tags=[str(t) for t in entity.get('Tags', [])]
                owned=any(t.startswith(('mcfilm_', 'mcfilm-')) for t in tags)
                if owned:
                    if str(entity['id']) not in ('minecraft:item_display','minecraft:block_display','minecraft:falling_block'):
                        raise ValueError('unexpected owned entity type')
                    removed.append({'region':path.name,'type':str(entity['id']),'tags':tags}); dirty=True
                else: keep.append(entity)
            n['Entities']=nbtlib.List[nbtlib.Compound](keep)
            out=io.BytesIO(); n.write(out); chunks[i]=b'\x02'+zlib.compress(out.getvalue())
        if dirty:
            header=bytearray(8192); body=bytearray(); sector=2
            for i,blob in sorted(chunks.items()):
                payload=struct.pack('>I',len(blob))+blob; count=(len(payload)+4095)//4096
                if count>255: raise ValueError('oversize region chunk')
                header[i*4:i*4+4]=sector.to_bytes(3,'big')+bytes([count])
                body.extend(payload+bytes(count*4096-len(payload))); sector+=count
            path.write_bytes(header+body)
    return removed

def main():
    a=argparse.ArgumentParser(); a.add_argument('--source-instance',type=Path,required=True)
    a.add_argument('--source-world',required=True); a.add_argument('--source-plan',type=Path,required=True)
    a.add_argument('--pilot',choices=['contact','source'],default='contact')
    a.add_argument('--run-id',required=True); args=a.parse_args()
    import re
    if not re.fullmatch('[a-z0-9-]{1,48}',args.run_id): raise ValueError('unsafe run ID')
    root=Path(__file__).resolve().parents[1]; source=args.source_instance.resolve()
    if source.parent!=root/'game/instances': raise ValueError('source must be a registered project instance')
    world_source=(source/'saves'/args.source_world).resolve()
    if world_source.parent!=source/'saves': raise ValueError('unsafe world path')
    # Reject incompatible historical action contracts before copying any data.
    if args.pilot=='source':
        ActorTakePlan.model_validate_json(args.source_plan.read_text(encoding='utf-8'))
    evidence=root/'work'/args.run_id; evidence.mkdir(exist_ok=False)
    target=root/'game/instances'/args.run_id; target.mkdir(exist_ok=False)
    before=inventory(world_source)
    for name in ('mods','resourcepacks','shaderpacks'):
        shutil.copytree(source/name,target/name)
    (target/'config').mkdir()
    for p in (source/'config').iterdir():
        if p.is_file(): shutil.copy2(p,target/'config'/p.name)
    # Preserve onboarding/settings, but never copy a prior operation journal.
    if (source/'config/axiom').is_dir():
        shutil.copytree(source/'config/axiom',target/'config/axiom')
    for p in source.glob('*.json'):
        if p.name.startswith('1.21.1'): shutil.copy2(p,target/p.name)
    for p in source.glob('*.jar'): shutil.copy2(p,target/p.name)
    shutil.copy2(source/'options.txt',target/'options.txt')
    world_name='KJDS_'+args.run_id.replace('-','_')
    world=target/'saves'/world_name; shutil.copytree(world_source,world)
    removed=clean_owned(world)
    n=nbtlib.load(world/'level.dat'); n['Data']['LevelName']=nbtlib.String(world_name)
    if args.pilot=='contact':
        n['Data']['Player']['Pos']=nbtlib.List[nbtlib.Double]([496.,3.,96.])
        n['Data']['Player']['Rotation']=nbtlib.List[nbtlib.Float]([170.,24.])
    n.save(world/'level.dat')
    plan=json.loads(args.source_plan.read_text(encoding='utf-8'))
    plan.update(run_id=args.run_id,take_id=args.run_id+'-actors',world=world_name)
    if args.pilot=='contact': plan['duration_ticks']=200
    # A diagnostic excerpt ends before support/pickup. Never labels this the complete E event.
    for actor in plan['actors']:
        if args.pilot=='source': continue
        if actor['skin_ref']=='classmate:safety':
            actor['steps']=[{'start_tick':0,'duration_ticks':200,'action':'idle'}]
            actor.pop('mouth_frames',None)
            continue
        steps=[]
        for step in actor['steps']:
            if step['start_tick']>=200: break
            step=dict(step); step['duration_ticks']=min(step['duration_ticks'],200-step['start_tick'])
            if step['action']=='scatter_groceries': step={'start_tick':step['start_tick'],'duration_ticks':1,'action':'fall_down'}
            steps.append(step)
        actor['steps']=steps
        actor.pop('mouth_frames',None)
    model=ActorTakePlan.model_validate(plan); payload,ph=canonical_plan(model)
    (evidence/'actor-plan.json').write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8')
    if inventory(world_source)!=before: raise RuntimeError('source world changed during preparation')
    lock={'run_id':args.run_id,'scope':('10-second push/fall diagnostic; incomplete shared event' if args.pilot=='contact' else 'independent action diagnostic; not a complete screenplay shot'),
          'source_instance':str(source),'instance':str(target),'world':world_name,
          'source_world':str(world_source),'source_world_sha256':before,'removed_owned_from_copy':removed,
          'mods':inventory(target/'mods'),'resourcepacks':inventory(target/'resourcepacks'),
          'shaderpacks':inventory(target/'shaderpacks'),'options_sha256':digest(target/'options.txt'),
          'plan_hash':ph,'human_review':'pending','source_preserved':True}
    (evidence/'environment-lock.json').write_text(json.dumps(lock,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'instance':str(target),'world':world_name,'evidence':str(evidence),'plan_hash':ph}))

if __name__=='__main__': main()

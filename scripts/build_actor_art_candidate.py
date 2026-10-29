"""Re-UV existing display actors, preserving geometry, CMDs and rig transforms.

Requires Pillow and numpy. Output is a local derivative of the supplied licensed
pack, not an independently redistributable character pack. Never installs it.
"""
import argparse,base64,copy,hashlib,io,json,math,uuid,zipfile
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont

FACES=('north','south','east','west','up','down')

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def color(image,face):
    u,v,u1,v1=face['uv'];w,h=image.size
    return image.getpixel((min(w-1,int((u+u1)*w/32)),min(h-1,int((v+v1)*h/32))))

def tile(width,height,rgba,part,index,face,role,density):
    im=Image.new('RGBA',(width,height),rgba);d=ImageDraw.Draw(im)
    r,g,b,a=rgba
    def c(delta):return tuple(max(0,min(255,x+delta)) for x in (r,g,b))+(a,)
    cloth=(part=='body' and index in (0,2,3,4,5,6,7)) or part.startswith(('arm','leg')) or (part.startswith('forearm') and index==0) or (part.startswith('shin') and index==0)
    if cloth and min(width,height)>=3:
        # Subtle woven variation; seams, not random photographic noise.
        for y in range(height):
            for x in range(width):
                if (x+2*y)%7==0:im.putpixel((x,y),c(-3))
        d.line([(0,0),(0,height-1)],fill=c(-14),width=1)
        d.line([(width-1,0),(width-1,height-1)],fill=c(8),width=1)
        if face in ('north','south'):
            d.line([(1,height-2),(width-2,height-2)],fill=c(-12),width=1)
            if density==2 and width>5:
                for x in range(2,width-1,3):d.point((x,height-3),fill=c(17))
        if part=='body' and index==0 and face=='north' and width>=8:
            # Hem and shoulder yoke sit within the existing garment silhouette.
            d.line([(1,2*density),(width-2,2*density)],fill=c(-10))
        if role=='chen' and part=='body' and index in (2,3) and face=='north' and height>=10:
            y=height//2;d.rectangle((1,y,max(1,width-2),min(height-2,y+3*density)),outline=c(-23),width=1)
            d.line([(1,y),(max(1,width-2),y)],fill=c(22))
        if part.startswith(('leg','shin')) and face in ('north','south') and height>5:
            d.line([(max(1,width//3),height//3),(max(1,width//3),height-3)],fill=c(-7))
    # Hair/helmet have directional definition without changing face anatomy.
    if part.startswith('head') and index in range(1,9) and max(r,g,b)<100 and height>=3:
        for x in range(1,width,3*density):d.line([(x,0),(x,min(height-1,3*density))],fill=c(7))
    if role=='chen' and part.startswith('head') and index in (17,18,19) and width>=4:
        d.line([(0,height-1),(width-1,height-1)],fill=c(-17))
        if height>3:d.line([(1,1),(width-2,1)],fill=c(14))
    return im

def atlas_models(source,role,size,palette):
    density=size//128;atlas=Image.new('RGBA',(size,size),(0,0,0,0));requests={};out={};assignments=[];layout=[]
    for path,original in sorted(source.items()):
        if f'/actor/{role}/' not in path:continue
        model=copy.deepcopy(original);part=Path(path).stem
        model['textures']={'0':f'kanjian2:actor/{role}_art_{size}','particle':f'kanjian2:actor/{role}_art_{size}'}
        for index,e in enumerate(model.get('elements',[])):
            dims=[abs(b-a) for a,b in zip(e['from'],e['to'])]
            for face,f in e['faces'].items():
                axes=(0,1) if face in ('north','south') else (2,1) if face in ('east','west') else (0,2)
                w,h=[max(1,math.ceil(dims[a]*density)) for a in axes];rgba=color(palette,original['elements'][index]['faces'][face])
                key=(part.replace('_phone','').replace('_call','').replace('_mouth_1','').replace('_mouth_2',''),index,face,tuple(e['from']),tuple(e['to']),rgba,w,h)
                requests.setdefault(key,(part,index,face,w,h,rgba));assignments.append((f,key))
        out[path]=model
    # Largest rectangles first in a deterministic skyline. One gutter per island.
    skyline=[0]*size;positions={}
    for key,(part,index,face,w,h,rgba) in sorted(requests.items(),key=lambda kv:(-max(kv[1][3:5]),-kv[1][3]*kv[1][4],str(kv[0]))):
        choices=[(max(skyline[x:x+w+2]),x) for x in range(size-w-1)]
        if not choices:raise ValueError('face larger than atlas')
        y,x=min(choices)
        if y+h+2>size:raise ValueError(f'{role} atlas {size} overflows; no UV truncated')
        for col in range(x,x+w+2):skyline[col]=y+h+2
        x+=1;y+=1;positions[key]=(x,y,w,h);image=tile(w,h,rgba,part,index,face,role,density);atlas.paste(image,(x,y))
        atlas.paste(image.crop((0,0,w,1)),(x,y-1));atlas.paste(image.crop((0,h-1,w,h)),(x,y+h))
        atlas.paste(image.crop((0,0,1,h)),(x-1,y));atlas.paste(image.crop((w-1,0,w,h)),(x+w,y))
        layout.append(dict(part=part,element=index,face=face,rect=[x,y,w,h],base_rgba=rgba))
    for face,key in assignments:
        x,y,w,h=positions[key];face['uv']=[x*16/size,y*16/size,(x+w)*16/size,(y+h)*16/size];face['texture']='#0'
    return atlas,out,layout

def rotation(q):
    x,y,z,w=q
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])

def corners(e,face):
    x,y,z=e['from'];X,Y,Z=e['to']
    return np.array({'north':[(X,Y,z),(x,Y,z),(x,y,z),(X,y,z)],'south':[(x,Y,Z),(X,Y,Z),(X,y,Z),(x,y,Z)],'east':[(X,Y,Z),(X,Y,z),(X,y,z),(X,y,Z)],'west':[(x,Y,z),(x,Y,Z),(x,y,Z),(x,y,z)],'up':[(x,Y,z),(X,Y,z),(X,Y,Z),(x,Y,Z)],'down':[(x,y,Z),(X,y,Z),(X,y,z),(x,y,z)]}[face],dtype=float)

def render(models,role,pose,texture,angle,width=320,height=480):
    pixels=np.full((height,width,3),(231,228,222),dtype=np.uint8);depth=np.full((height,width),-1e9);a=math.radians(angle)
    right=np.array([math.cos(a),0,-math.sin(a)]);view=np.array([-math.sin(a),.05,-math.cos(a)]);view/=np.linalg.norm(view);up=np.cross(right,view)
    projected=[]
    for part,transform in pose.items():
        key=f'assets/kanjian2/models/actor/{role}/{part}.json'
        if key not in models:continue
        for e in models[key].get('elements',[]):
            for face in FACES:
                pts=(corners(e,face)-8)@rotation(transform['left_rotation']).T+np.array(transform['translation'])*16
                projected.extend(np.column_stack([pts@right,pts@up]))
    bounds=np.asarray(projected);lo=bounds.min(0);hi=bounds.max(0)
    scale=min((width-36)/max(1,hi[0]-lo[0]),(height-36)/max(1,hi[1]-lo[1]));center=(lo+hi)/2
    tex=np.asarray(texture.convert('RGB'));th,tw=tex.shape[:2]
    for part,transform in pose.items():
        path=f'assets/kanjian2/models/actor/{role}/{part}.json'
        if path not in models:continue
        mat=rotation(transform['left_rotation']);offset=np.array(transform['translation'])*16
        for e in models[path].get('elements',[]):
            for face,f in e['faces'].items():
                pts=(corners(e,face)-8)@mat.T+offset
                normal=np.cross(pts[2]-pts[0],pts[1]-pts[0]);length=np.linalg.norm(normal)
                if length<1e-9:continue
                normal/=length
                if normal@view<0:continue
                screen=np.column_stack([width/2+(pts@right-center[0])*scale,height/2-(pts@up-center[1])*scale,pts@view])
                u,v,U,V=f['uv'];uv=np.array([(u,v),(U,v),(U,V),(u,V)])*np.array([tw/16,th/16])
                shade=.78+.22*abs(normal@np.array([-.35,.65,-.68]))
                for ids in ((0,1,2),(0,2,3)):
                    tri=screen[list(ids)];tuv=uv[list(ids)];lo=np.maximum(np.floor(tri[:,:2].min(0)).astype(int),0);hi=np.minimum(np.ceil(tri[:,:2].max(0)).astype(int),[width-1,height-1])
                    if np.any(hi<lo):continue
                    xx,yy=np.meshgrid(np.arange(lo[0],hi[0]+1)+.5,np.arange(lo[1],hi[1]+1)+.5)
                    den=(tri[1,1]-tri[2,1])*(tri[0,0]-tri[2,0])+(tri[2,0]-tri[1,0])*(tri[0,1]-tri[2,1])
                    if abs(den)<1e-9:continue
                    w0=((tri[1,1]-tri[2,1])*(xx-tri[2,0])+(tri[2,0]-tri[1,0])*(yy-tri[2,1]))/den
                    w1=((tri[2,1]-tri[0,1])*(xx-tri[2,0])+(tri[0,0]-tri[2,0])*(yy-tri[2,1]))/den;w2=1-w0-w1
                    zz=w0*tri[0,2]+w1*tri[1,2]+w2*tri[2,2];cut=depth[lo[1]:hi[1]+1,lo[0]:hi[0]+1];mask=(w0>=0)&(w1>=0)&(w2>=0)&(zz>cut)
                    tx=np.clip((w0*tuv[0,0]+w1*tuv[1,0]+w2*tuv[2,0]).astype(int),0,tw-1);ty=np.clip((w0*tuv[0,1]+w1*tuv[1,1]+w2*tuv[2,1]).astype(int),0,th-1)
                    dest=pixels[lo[1]:hi[1]+1,lo[0]:hi[0]+1];dest[mask]=(tex[ty[mask],tx[mask]]*shade).astype(np.uint8);cut[mask]=zz[mask]
    return Image.fromarray(pixels)

def blockbench(models,role,pose,atlas):
    elements=[];groups=[]
    for part,t in pose.items():
        key=f'assets/kanjian2/models/actor/{role}/{part}.json'
        if key not in models:continue
        offset=np.array(t['translation'])*16;children=[]
        for i,e in enumerate(models[key]['elements']):
            uid=str(uuid.uuid5(uuid.NAMESPACE_URL,role+'/'+part+'/'+str(i)));children.append(uid)
            faces={f:{'uv':[v*atlas.width/16 for v in d['uv']],'texture':0} for f,d in e['faces'].items()}
            elements.append(dict(name=f'{part}_{i:02d}',uuid=uid,type='cube',**{'from':(np.array(e['from'])-8+offset).tolist(),'to':(np.array(e['to'])-8+offset).tolist()},origin=offset.tolist(),box_uv=False,faces=faces))
        groups.append(dict(name=part,origin=offset.tolist(),uuid=str(uuid.uuid5(uuid.NAMESPACE_URL,role+'/'+part)),children=children))
    stream=io.BytesIO();atlas.save(stream,format='PNG')
    return dict(meta=dict(format_version='4.10',model_format='free',box_uv=False),name=role+' art candidate',resolution=dict(width=atlas.width,height=atlas.height),elements=elements,outliner=groups,textures=[dict(name=f'{role}-atlas.png',uuid=str(uuid.uuid5(uuid.NAMESPACE_URL,role+'/atlas')),source='data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode(),width=atlas.width,height=atlas.height)])

def main():
    p=argparse.ArgumentParser();p.add_argument('--source-pack',type=Path,required=True);p.add_argument('--binding',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    root=args.output.resolve();root.mkdir(parents=True,exist_ok=False);sourcehash=sha(args.source_pack);bindinghash=sha(args.binding)
    z=zipfile.ZipFile(args.source_pack);source={n:json.loads(z.read(n)) for n in z.namelist() if '/models/actor/' in n and n.endswith('.json')}
    palette=Image.open(io.BytesIO(z.read('assets/kanjian2/textures/actor/palette.png'))).convert('RGBA');binding=json.loads(args.binding.read_text(encoding='utf-8'))
    manifest=dict(source_pack_sha256=sourcehash,binding_sha256=bindinghash,roles=['chen','a'],geometry_changed=False,installed=False,human_review='pending',runtime_passed=False,scope='local derivative; original asset license still applies',variants=[])
    for size in (128,256):
        candidate={};textures={};layouts={}
        for role in manifest['roles']:
            atlas,models,layout=atlas_models(source,role,size,palette);candidate.update(models);textures[role]=atlas;layouts[role]=layout
            directory=root/f'atlas-{size}';directory.mkdir(exist_ok=True);atlas.save(directory/f'{role}.png')
            (directory/f'{role}-uv.json').write_text(json.dumps(layout,indent=2),encoding='utf-8')
            pose=binding['roles'][role]['poses']['stand']
            (directory/f'{role}.bbmodel').write_text(json.dumps(blockbench(models,role,pose,atlas),ensure_ascii=False),encoding='utf-8')
            sheet=Image.new('RGB',(4*320,2*510),(231,228,222));draw=ImageDraw.Draw(sheet)
            for row,(label,mods,texture) in enumerate([('ORIGINAL V12',source,palette),(f'ART {size} / OFFLINE',candidate,atlas)]):
                for col,(view,angle) in enumerate([('FRONT',0),('THREE QUARTER',35),('SIDE',90),('BACK',180)]):
                    sheet.paste(render(mods,role,pose,texture,angle),(col*320,row*510+30));draw.text((col*320+12,row*510+9),f'{role.upper()} | {label} | {view}',fill=(50,52,55))
            sheet.save(directory/f'{role}-comparison.png')
            poses=Image.new('RGB',(4*320,2*510),(231,228,222));pd=ImageDraw.Draw(poses)
            for index,name in enumerate(('stand','phone','phone_call','sit','reach','pickup_crouch','support_low','ground_sit')):
                selected=binding['roles'][role]['poses'].get(name)
                if selected is None:
                    pd.text((index%4*320+12,index//4*510+9),f'{role.upper()} | {name} | NO STATIC PRESET',fill=(90,60,50))
                    continue
                preview_models=dict(candidate)
                variant='forearm_l_call' if name=='phone_call' else 'forearm_l_phone' if name=='phone' else None
                if variant:preview_models[f'assets/kanjian2/models/actor/{role}/forearm_l.json']=candidate[f'assets/kanjian2/models/actor/{role}/{variant}.json']
                x=index%4*320;y=index//4*510
                poses.paste(render(preview_models,role,selected,atlas,30),(x,y+30));pd.text((x+12,y+9),f'{role.upper()} | {name} | STATIC RIG / NOT LIVE',fill=(50,52,55))
            poses.save(directory/f'{role}-pose-check.png')
        pack=root/f'KJDS_Art_chen-a_{size}_candidate.zip'
        with zipfile.ZipFile(pack,'x',compression=zipfile.ZIP_DEFLATED) as out:
            out.writestr('pack.mcmeta',json.dumps({'pack':{'pack_format':34,'description':f'Local Chen/A art {size}; unapproved; requires original v12'}}))
            for n,d in candidate.items():out.writestr(n,json.dumps(d))
            for role,atlas in textures.items():
                stream=io.BytesIO();atlas.save(stream,format='PNG');out.writestr(f'assets/kanjian2/textures/actor/{role}_art_{size}.png',stream.getvalue())
        for n,d in candidate.items():
            original=copy.deepcopy(source[n]);revised=copy.deepcopy(d)
            original.pop('textures',None);revised.pop('textures',None)
            for model in (original,revised):
                for e in model['elements']:
                    if set(e['faces'])!=set(FACES):raise ValueError('unclosed source cube; do not hide it with a texture')
                    for face in e['faces'].values():face.pop('uv',None);face.pop('texture',None)
            if original!=revised:raise ValueError('geometry/rotation/face contract changed')
        manifest['variants'].append(dict(size=size,pack=pack.name,sha256=sha(pack),overridden_models=len(candidate),face_islands={role:len(layouts[role]) for role in layouts},geometry_equality_passed=True))
    if sha(args.source_pack)!=sourcehash or sha(args.binding)!=bindinghash:raise ValueError('original changed')
    (root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(root)

if __name__=='__main__':main()

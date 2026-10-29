"""Create standalone vanilla set-dressing schematics; never paste into a world."""
import argparse,hashlib,json
from pathlib import Path
import nbtlib
from PIL import Image,ImageDraw


def make_kit(name):
    cells={}
    def box(a,b,block):
        for x in range(a[0],b[0]+1):
            for y in range(a[1],b[1]+1):
                for z in range(a[2],b[2]+1):cells[(x,y,z)]='minecraft:'+block
    if name=='D-dorm-storage':
        # y=0 is floor level, not an extra solid pedestal. No actor contact furniture.
        box((0,0,0),(1,0,0),'barrel[facing=south,open=false]')
        box((0,1,0),(0,1,0),'bookshelf')
        box((1,1,0),(1,1,0),'potted_fern')
        box((0,2,0),(1,2,0),'spruce_slab[type=bottom,waterlogged=false]')
        box((3,0,0),(3,1,0),'oak_fence[east=false,north=false,south=false,waterlogged=false,west=false]')
        box((2,2,0),(4,2,0),'spruce_slab[type=bottom,waterlogged=false]')
        box((2,1,0),(2,1,0),'blue_wool')
        box((4,1,0),(4,1,0),'light_gray_wool')
        box((2,0,0),(2,0,0),'spruce_trapdoor[facing=south,half=bottom,open=false,powered=false,waterlogged=false]')
    elif name=='W-workroom-shelf':
        box((0,0,0),(1,0,0),'barrel[facing=south,open=false]')
        box((0,1,0),(1,1,0),'dark_oak_slab[type=bottom,waterlogged=false]')
        box((0,2,0),(1,2,0),'dark_oak_slab[type=bottom,waterlogged=false]')
        box((2,0,0),(2,0,0),'barrel[facing=south,open=false]')
        box((3,0,0),(3,0,0),'water_cauldron[level=3]')
        box((4,0,0),(4,0,0),'barrel[facing=south,open=false]')
        box((4,1,0),(4,1,0),'flower_pot')
        box((3,2,0),(4,2,0),'iron_bars[east=true,north=false,south=false,waterlogged=false,west=true]')
        box((2,1,0),(2,1,0),'orange_carpet')
    elif name=='C-classroom-background':
        box((0,0,0),(6,0,1),'oak_planks')
        box((0,1,0),(1,2,0),'bookshelf');box((5,1,0),(6,2,0),'bookshelf')
        box((2,1,0),(4,1,0),'white_terracotta');box((2,2,0),(4,2,0),'dark_oak_planks')
        box((3,3,0),(3,3,0),'flower_pot')
        box((0,3,0),(1,3,0),'oak_planks');box((5,3,0),(6,3,0),'oak_planks')
    elif name=='E-construction-background':
        box((0,0,0),(6,0,2),'smooth_stone')
        for x in range(7):box((x,1,0),(x,1,0),'yellow_concrete' if x%2 else 'black_concrete')
        box((0,2,0),(6,3,0),'light_gray_concrete')
        for x in (0,6):box((x,2,0),(x,5,0),'iron_block')
        box((0,5,0),(6,5,0),'iron_block')
        box((1,1,2),(2,1,2),'stripped_spruce_wood')
    return cells


def schematic(cells,path):
    size=[max(p[i] for p in cells)+1 for i in range(3)];palette=['minecraft:air']+sorted(set(cells.values()));index={s:i for i,s in enumerate(palette)}
    data=[]
    for y in range(size[1]):
        for z in range(size[2]):
            for x in range(size[0]):
                n=index[cells.get((x,y,z),'minecraft:air')]
                while n>127:data.append((n&127)|128);n>>=7
                data.append(n)
    payload=nbtlib.Compound({'Version':nbtlib.Int(2),'DataVersion':nbtlib.Int(3955),'Width':nbtlib.Short(size[0]),'Height':nbtlib.Short(size[1]),'Length':nbtlib.Short(size[2]),'Offset':nbtlib.IntArray([0,0,0]),'PaletteMax':nbtlib.Int(len(palette)),'Palette':nbtlib.Compound({s:nbtlib.Int(i) for s,i in index.items()}),'BlockData':nbtlib.ByteArray([v if v<128 else v-256 for v in data]),'BlockEntities':nbtlib.List[nbtlib.Compound]([]),'Entities':nbtlib.List[nbtlib.Compound]([])})
    nbtlib.File(payload,root_name='Schematic').save(path,gzipped=True)
    return size


def shape_boxes(state):
    """Illustrative shapes only: never use these as Minecraft collision truth."""
    if 'slab' in state:return [(0,0,0,1,.5,1)]
    if 'carpet' in state:return [(0,0,0,1,1/16,1)]
    if 'trapdoor' in state:return [(0,0,0,1,3/16,1)]
    if 'fence' in state:return [(6/16,0,6/16,10/16,1,10/16)]
    if 'iron_bars' in state:return [(0,0,7/16,1,1,9/16)]
    if 'cauldron' in state:
        return [(0,0,0,1,3/16,1),(0,0,0,2/16,1,1),(14/16,0,0,1,1,1),(0,0,0,1,1,2/16),(0,0,14/16,1,1,1)]
    if 'flower_pot' in state or 'potted_' in state:
        boxes=[(5/16,0,5/16,11/16,6/16,11/16)]
        if 'potted_' in state:boxes.append((6/16,6/16,6/16,10/16,13/16,10/16))
        return boxes
    return [(0,0,0,1,1,1)]


def preview(cells,title):
    """Two orthographic isometric views, visible faces sorted back to front."""
    import math
    image=Image.new('RGB',(1280,650),(231,228,222));d=ImageDraw.Draw(image)
    colors={'barrel':(121,91,60),'bookshelf':(140,109,74),'dark_oak':(81,62,47),'spruce':(123,95,65),'fence':(155,125,81),'blue_wool':(62,83,124),'light_gray':(165,168,161),'water_cauldron':(74,83,89),'iron':(156,165,166),'orange':(177,112,65),'potted_':(73,110,72),'flower_pot':(143,88,65),'yellow':(206,169,57),'black':(47,48,48)}
    for column,angle in enumerate((35,215)):
        a=math.radians(angle);co,si=math.cos(a),math.sin(a)
        def project(p):
            x,y,z=p;return (co*x-si*z,.4*(si*x+co*z)-y,si*x+co*z)
        polygons=[]
        for (x,y,z),state in cells.items():
            color=next((v for k,v in colors.items() if k in state),(150,146,133))
            for X,Y,Z,U,V,W in shape_boxes(state):
                X+=x;U+=x;Y+=y;V+=y;Z+=z;W+=z
                faces=[([(X,V,Z),(U,V,Z),(U,V,W),(X,V,W)],1.08)]
                faces.append(([(X,Y,W),(U,Y,W),(U,V,W),(X,V,W)] if co>0 else [(U,Y,Z),(X,Y,Z),(X,V,Z),(U,V,Z)],.92))
                faces.append(([(U,Y,Z),(U,Y,W),(U,V,W),(U,V,Z)] if si>0 else [(X,Y,W),(X,Y,Z),(X,V,Z),(X,V,W)],.76))
                for points,shade in faces:
                    points=[project(p) for p in points];polygons.append((sum(p[2] for p in points)/4,points,tuple(min(255,int(v*shade)) for v in color),state))
        allpoints=[p for _,ps,_,_ in polygons for p in ps];lo=[min(p[i] for p in allpoints) for i in (0,1)];hi=[max(p[i] for p in allpoints) for i in (0,1)]
        scale=min(530/(hi[0]-lo[0]),480/(hi[1]-lo[1]));center=[(l+h)/2 for l,h in zip(lo,hi)]
        for _,points,color,state in sorted(polygons,key=lambda p:p[0]):
            ps=[(column*640+320+(p[0]-center[0])*scale,325+(p[1]-center[1])*scale) for p in points]
            d.polygon(ps,fill=color,outline=tuple(max(0,v-25) for v in color))
        d.text((column*640+24,24),title+(' | FRONT' if column==0 else ' | REVERSE'),fill=(42,45,48))
    d.text((24,604),'OFFLINE DESIGN STUDY / PENDING REVIEW - approximate shapes, no game textures, lighting or collision verification',fill=(65,67,69))
    return image


def main():
    ap=argparse.ArgumentParser();ap.add_argument('output',type=Path);args=ap.parse_args();root=args.output.resolve();root.mkdir(parents=True,exist_ok=False)
    from minecraft_film_agent.schematic import load_schematic
    manifest={'status':'offline_art_candidate','design_revision':2,'installed':False,'human_review':'pending','new_mods':[],'design_source':'docs/materials-20261028/locations-and-look.md','placement_policy':'background modules only; preserve performance lanes and all existing furniture contact heights; no world writes by this generator','preview_limitations':'approximate block shapes and concept colors; not game textures or collision measurements','kits':[]}
    for name in ['D-dorm-storage','W-workroom-shelf','C-classroom-background','E-construction-background']:
        cells=make_kit(name);path=root/(name+'.schem');size=schematic(cells,path);loaded=load_schematic(path)
        if loaded.summary.block_count!=len(cells):raise ValueError('schematic roundtrip differs')
        preview(cells,name).save(root/(name+'.png'))
        (root/(name+'.json')).write_text(json.dumps({'size':size,'cells':[dict(position=p,state=s) for p,s in sorted(cells.items())]},indent=2),encoding='utf-8')
        manifest['kits'].append(dict(id=name,size=size,blocks=len(cells),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),contract_inspection=loaded.summary.model_dump(mode='json')))
    (root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8');print(root)


if __name__=='__main__':main()

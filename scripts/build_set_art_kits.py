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
        box((0,0,0),(6,0,2),'stripped_oak_wood')
        box((0,1,0),(0,4,1),'spruce_planks');box((3,1,0),(3,4,1),'spruce_planks')
        for y in (1,3):box((1,y,0),(2,y,0),'bookshelf')
        box((1,4,0),(2,4,1),'spruce_planks')
        box((5,1,0),(5,3,0),'stripped_oak_wood');box((4,4,0),(6,4,0),'stripped_oak_wood')
        box((4,2,0),(4,3,0),'light_gray_wool');box((6,2,0),(6,3,0),'blue_wool')
        box((1,2,1),(1,2,1),'flower_pot')
    elif name=='W-workroom-shelf':
        box((0,0,0),(6,0,2),'polished_andesite')
        for x in (0,3):box((x,1,0),(x,3,1),'stripped_dark_oak_wood')
        for y in (1,3):box((1,y,0),(2,y,1),'dark_oak_planks')
        box((1,2,0),(1,2,0),'barrel[facing=north,open=false]')
        box((2,2,0),(2,2,0),'light_gray_concrete')
        box((4,1,0),(6,1,1),'dark_oak_planks')
        box((4,2,0),(4,2,0),'cauldron');box((6,2,0),(6,2,0),'flower_pot')
        box((5,3,0),(5,3,0),'orange_wool')
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


def preview(cells,title):
    image=Image.new('RGB',(660,560),(231,228,222));d=ImageDraw.Draw(image);d.text((24,18),title+' | OFFLINE BLOCKOUT',fill=(45,48,48))
    colors={'oak':(156,122,75),'spruce':(108,78,51),'dark_oak':(74,55,40),'bookshelf':(143,108,69),'blue_wool':(60,80,130),'light_gray':(172,174,168),'white_terracotta':(199,182,164),'iron':(183,189,189),'yellow':(203,166,53),'black':(47,48,48),'orange':(181,110,62),'flower_pot':(133,83,61),'cauldron':(72,77,80),'barrel':(116,88,56),'stone':(141,145,143)}
    for (x,y,z),state in sorted(cells.items(),key=lambda kv:(-kv[0][0]-kv[0][2],kv[0][1])):
        color=next((v for k,v in colors.items() if k in state),(127,130,124));px=165+(x-z)*38;py=480-(x+z)*17-y*40
        top=[(px,py-40),(px+38,py-57),(px+76,py-40),(px+38,py-23)];left=[top[0],top[3],(px+38,py+17),(px,py)];right=[top[3],top[2],(px+76,py),(px+38,py+17)]
        for points,factor in ((top,1.08),(left,.83),(right,.96)):
            c=tuple(min(255,int(v*factor)) for v in color);d.polygon(points,fill=c,outline=tuple(max(0,v-15) for v in c))
        if 'bookshelf' in state:
            for k,col in enumerate([(76,93,100),(134,69,53),(192,166,99),(83,112,95)]):d.line((px+8+k*7,py-27+k*3,px+8+k*7,py-4+k*3),fill=col,width=4)
    d.text((24,530),'Concept colors / full-block preview; pots and collision require later game inspection.',fill=(70,72,74))
    return image


def main():
    ap=argparse.ArgumentParser();ap.add_argument('output',type=Path);args=ap.parse_args();root=args.output.resolve();root.mkdir(parents=True,exist_ok=False)
    from minecraft_film_agent.schematic import load_schematic
    manifest={'status':'offline_art_candidate','installed':False,'human_review':'pending','new_mods':[],'design_source':'docs/materials-20261028/locations-and-look.md','placement_policy':'background modules only; no world target or placement authorized by this file; preserve performance lanes and all existing furniture contact heights','kits':[]}
    for name in ['D-dorm-storage','W-workroom-shelf','C-classroom-background','E-construction-background']:
        cells=make_kit(name);path=root/(name+'.schem');size=schematic(cells,path);loaded=load_schematic(path)
        if loaded.summary.block_count!=len(cells):raise ValueError('schematic roundtrip differs')
        preview(cells,name).save(root/(name+'.png'))
        (root/(name+'.json')).write_text(json.dumps({'size':size,'cells':[dict(position=p,state=s) for p,s in sorted(cells.items())]},indent=2),encoding='utf-8')
        manifest['kits'].append(dict(id=name,size=size,blocks=len(cells),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),contract_inspection=loaded.summary.model_dump(mode='json')))
    (root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8');print(root)


if __name__=='__main__':main()

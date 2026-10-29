"""Local Chen/A phone grip geometry overlay; no changes to rig or phone pose."""
import argparse
import copy
import json
import zipfile
from io import BytesIO
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from build_actor_art_candidate import render, sha, blockbench


def gap(a, b):
    return float(np.linalg.norm(np.maximum(np.maximum(np.asarray(a['from'])-b['to'],
                                                      np.asarray(b['from'])-a['to']), 0)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--art', type=Path, required=True)
    ap.add_argument('--binding', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    binding = json.loads(args.binding.read_text(encoding='utf-8'))
    report = dict(status='offline_geometry_candidate', installed=False, runtime_passed=False,
                  human_review='pending', source_sha256=sha(args.art), binding_sha256=sha(args.binding),
                  policy='Original hand, sleeve, phone, rig and CMD unchanged; add one connecting finger pad per variant.',
                  limitations='AABB contact is static geometry evidence, not human grip or animation acceptance.', models=[])
    with zipfile.ZipFile(args.art) as source:
        models = {n: json.loads(source.read(n)) for n in source.namelist() if '/models/' in n}
        overrides = {}
        for role in ('chen', 'a'):
            texpath = next(n for n in source.namelist() if f'/textures/actor/{role}_art_' in n)
            texture = Image.open(BytesIO(source.read(texpath))).convert('RGBA')
            sheet = Image.new('RGB', (1280, 1000), (231,228,222)); draw = ImageDraw.Draw(sheet)
            for row, (variant, pose_name, lower, upper) in enumerate((
                    ('forearm_l_phone', 'phone', [9.15,2.4,5.2], [10.0,3.6,6.3]),
                    ('forearm_l_call', 'phone_call', [6.7,.9,6.4], [7.6,2.35,7.3]))):
                path = f'assets/kanjian2/models/actor/{role}/{variant}.json'
                original = models[path]; revised = copy.deepcopy(original)
                hand, phone = revised['elements'][2:4]
                pad = dict(name='grip_finger_pad', **{'from':lower,'to':upper}, faces=copy.deepcopy(hand['faces']))
                if gap(pad, hand) or gap(pad, phone):
                    raise ValueError('finger must join hand and phone; never hide a floating prop')
                revised['elements'].append(pad)
                assert revised['elements'][:-1] == original['elements']
                overrides[path] = revised
                report['models'].append(dict(model=path, original_phone_hand_gap_m=gap(hand, phone)/16,
                                             new_finger_hand_gap_m=gap(pad, hand)/16,
                                             new_finger_phone_gap_m=gap(pad, phone)/16,
                                             original_elements_preserved=True, added_elements=1))
                pose = binding['roles'][role]['poses'][pose_name]
                neutral = binding['roles'][role]['poses']['stand']
                editable = {f'assets/kanjian2/models/actor/{role}/forearm_l.json': revised}
                (args.output/f'{role}-{variant}.bbmodel').write_text(json.dumps(blockbench(editable,role,{'forearm_l':neutral['forearm_l']},texture)),encoding='utf-8')
                for col, (label, model, angle, full) in enumerate((
                        ('OLD GRIP',original,215,False),('FINGER PAD',revised,215,False),
                        ('FULL FRONT',revised,35,True),('FULL REVERSE',revised,215,True))):
                    preview = dict(models);preview[f'assets/kanjian2/models/actor/{role}/forearm_l.json']=model
                    chosen = pose if full else {p:pose[p] for p in ('arm_l','forearm_l')}
                    sheet.paste(render(preview,role,chosen,texture,angle,320,460),(col*320,row*500+30))
                    draw.text((col*320+8,row*500+8),f'{role.upper()} | {pose_name} | {label}',fill=(45,48,51))
            sheet.save(args.output/f'{role}-grip-comparison.png')
        output=args.output/'KJDS_Art_gripfix_candidate.zip'
        with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED) as pack:
            pack.writestr('pack.mcmeta',json.dumps({'pack':{'pack_format':34,'description':'Local Chen/A finger grip candidate; requires UV256 art and original v12'}}))
            for path,model in overrides.items():pack.writestr(path,json.dumps(model))
        report['pack']=output.name;report['sha256']=sha(output)
    (args.output/'manifest.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(args.output.resolve())


if __name__=='__main__':main()

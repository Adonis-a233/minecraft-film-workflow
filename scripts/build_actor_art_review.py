"""Offline joint detail sheets and explicit rig landmarks; no runtime claims."""
import argparse
import json
import zipfile
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from build_actor_art_candidate import render, rotation, sha


def point(transform, local):
    if transform.get('scale') != [1, 1, 1] or not np.allclose(transform['right_rotation'], [0, 0, 0, 1]):
        raise ValueError('this diagnostic requires unit scale and identity right rotation')
    return ((np.asarray(local) - 8) @ rotation(transform['left_rotation']).T
            + np.asarray(transform['translation']) * 16) / 16


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--art', type=Path, required=True)
    ap.add_argument('--binding', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    binding = json.loads(args.binding.read_text(encoding='utf-8'))
    report = dict(art_sha256=sha(args.art), binding_sha256=sha(args.binding),
                  status='offline_measurements_only', human_review='pending', roles={},
                  limitations=['Static presets do not cover runtime Java action trajectories.',
                               'Anchor separation is not a surface gap or collision measurement.',
                               'Hands use an authored reference center, not validated prop grip.'])
    with zipfile.ZipFile(args.art) as pack:
        models = {n: json.loads(pack.read(n)) for n in pack.namelist() if '/models/' in n}
        for role in ('chen', 'a'):
            from io import BytesIO
            texture_name = next(n for n in pack.namelist() if f'/textures/actor/{role}_art_' in n)
            texture = Image.open(BytesIO(pack.read(texture_name))).convert('RGBA')
            sheet = Image.new('RGB', (1280, 1440), (231, 228, 222))
            draw = ImageDraw.Draw(sheet)
            rows = []
            for row, name in enumerate(('stand', 'phone', 'phone_call', 'sit')):
                pose = binding['roles'][role]['poses'][name]
                mods = dict(models)
                variant = 'forearm_l_call' if name == 'phone_call' else 'forearm_l_phone' if name == 'phone' else None
                if variant:
                    mods[f'assets/kanjian2/models/actor/{role}/forearm_l.json'] = models[f'assets/kanjian2/models/actor/{role}/{variant}.json']
                measures = dict(pose=name, elbows={}, knees={}, hands={}, soles={})
                for side in ('l', 'r'):
                    for upper, lower, dest in (('arm', 'forearm', 'elbows'), ('leg', 'shin', 'knees')):
                        a = point(pose[f'{upper}_{side}'], [8, 2, 8])
                        b = point(pose[f'{lower}_{side}'], [8, 8, 8])
                        measures[dest][side] = dict(upper_endpoint_m=a.tolist(), lower_pivot_m=b.tolist(),
                                                   anchor_distance_m=float(np.linalg.norm(a-b)))
                    measures['hands'][side] = point(pose[f'forearm_{side}'], [8, 3, 8]).tolist()
                    measures['soles'][side] = point(pose[f'shin_{side}'], [8, 2, 7.5]).tolist()
                rows.append(measures)
                for col, (label, parts, angle) in enumerate((
                    ('ELBOW FRONT', ('arm_l', 'forearm_l'), 35),
                    ('ELBOW REVERSE', ('arm_l', 'forearm_l'), 215),
                    ('KNEE SIDE', ('leg_l', 'shin_l'), 90),
                    ('KNEE REVERSE', ('leg_l', 'shin_l'), 215))):
                    subset = {p: pose[p] for p in parts}
                    sheet.paste(render(mods, role, subset, texture, angle, 320, 318), (col*320, row*360+36))
                    draw.text((col*320+8, row*360+10), f'{role.upper()} | {name} | {label}', fill=(45,48,51))
            sheet.save(args.output / f'{role}-joint-details.png')
            report['roles'][role] = rows
    (args.output / 'landmarks.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(args.output.resolve())


if __name__ == '__main__':
    main()

"""Pin an isolated prepared package to the installed stack and calibrated views."""
import argparse, json
from pathlib import Path
from minecraft_film_agent.actors import load_plan
from minecraft_film_agent.photography import file_hash
from lock_filming_runtime import snapshot


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('package',type=Path)
    parser.add_argument('instance',type=Path)
    parser.add_argument('views',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    folder=args.package.resolve();instance=args.instance.resolve()
    if not folder.is_relative_to(root/'work') or instance.parent!=root/'game/instances':
        raise ValueError('isolated workspace package and instance required')
    plan=load_plan(folder/'actor-plan.json')
    if not (instance/'saves'/plan.world/'level.dat').is_file():
        raise ValueError('the exact planned world is absent')
    views=json.loads(args.views.read_text(encoding='utf-8'))
    ids=set()
    for view in views:
        import re,math
        name=view['id']
        if not re.fullmatch('[a-z0-9-]{1,48}',name) or name in ids:
            raise ValueError('unique safe view names required')
        ids.add(name)
        if not 0<=view['start_tick']<view['end_tick']<=plan.duration_ticks:
            raise ValueError('view outside take')
        if any(len(view[k])!=3 or not all(math.isfinite(x) for x in view[k]) for k in ('position','rotation')):
            raise ValueError('finite XYZ/rotation required')
        if not 1<=view['fov']<=179:raise ValueError('invalid FOV')
    data={'instance':str(instance),'actor_plan_hash':file_hash(folder/'actor-plan.json'),
          'bridge_hash':file_hash(instance/'mods/cinematic-bridge-0.1.0.jar'),
          'binding_hash':file_hash(root/'assets/actors/classmate-20261004/visual-binding-v10.json'),
          'views':views}
    if any((folder/name).exists() for name in ('capture.json','runtime-lock.json','capture-journal.json')):
        raise ValueError('package already configured; retain it and use a new run')
    for name,value in [('runtime-lock.json',snapshot(instance)),('capture.json',data)]:
        with (folder/name).open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2)


if __name__=='__main__':main()

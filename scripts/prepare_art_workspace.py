"""Prepare an isolated, non-recording art instance. Never launch or paste blocks.

Copies explicit worlds and baseline mods; selects one local art overlay above
the original pack. Stores source/copy hashes so restoration needs no overwrites.
"""
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(root):
    return {p.relative_to(root).as_posix(): sha(p)
            for p in sorted(root.rglob('*')) if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-instance', type=Path, required=True)
    parser.add_argument('--world', action='append', required=True)
    parser.add_argument('--art', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = args.source_instance.resolve()
    if source.parent != root / 'game/instances':
        raise ValueError('source must be a project instance')
    if not re.fullmatch(r'[a-z0-9-]{1,48}', args.run_id):
        raise ValueError('unsafe run ID')
    if len(set(args.world)) != len(args.world):
        raise ValueError('duplicate world')
    worlds = [(source / 'saves' / name).resolve() for name in args.world]
    if any(p.parent != source / 'saves' or not (p / 'level.dat').is_file() for p in worlds):
        raise ValueError('missing or unsafe world')
    art = args.art.resolve()
    manifest = json.loads((art.parent / 'manifest.json').read_text(encoding='utf-8'))
    expected = next(v['sha256'] for v in manifest['variants'] if v['pack'] == art.name)
    if sha(art) != expected:
        raise ValueError('candidate hash mismatch')
    if sha(source / 'resourcepacks/Classmate_Kanjian2_1.21.1_v12.zip') != manifest['source_pack_sha256']:
        raise ValueError('original character dependency differs from candidate source')
    target = root / 'game/instances' / args.run_id
    evidence = root / 'work' / args.run_id
    if target.exists() or evidence.exists():
        raise FileExistsError('new run ID required; never overwrite existing work')
    before = {str(world): inventory(world) for world in worlds}
    source_options = sha(source / 'options.txt')
    source_config = inventory(source / 'config')
    target.mkdir()
    evidence.mkdir()
    for name in ('mods', 'resourcepacks', 'shaderpacks'):
        shutil.copytree(source / name, target / name)
    (target / 'config').mkdir()
    # Only presentation configuration: no accounts, API keys or operation journals.
    for name in ('iris.properties', 'replaymod.json', 'sodium-options.json'):
        if (source / 'config' / name).is_file():
            shutil.copy2(source / 'config' / name, target / 'config' / name)
    for world in worlds:
        shutil.copytree(world, target / 'saves' / world.name)
        if inventory(target / 'saves' / world.name) != before[str(world)]:
            raise RuntimeError('world copy hash mismatch')
    shutil.copy2(art, target / 'resourcepacks' / art.name)
    options = (source / 'options.txt').read_text(encoding='utf-8')
    match = re.search(r'^resourcePacks:(.*)$', options, re.MULTILINE)
    if match is None:
        raise ValueError('missing original resource pack order')
    packs = json.loads(match[1])
    packs.append('file/' + art.name)
    for pack in packs:
        if pack.startswith('file/') and not (target / 'resourcepacks' / pack[5:]).exists():
            raise ValueError('missing selected resource pack: ' + pack)
    options = options[:match.start(1)] + json.dumps(packs) + options[match.end(1):]
    (target / 'options.txt').write_text(options, encoding='utf-8')
    replay_path = target / 'config/replaymod.json'
    replay = json.loads(replay_path.read_text(encoding='utf-8'))
    for key in ('recordSingleplayer', 'recordServer', 'autoStartRecording'):
        replay['recording'][key] = False
    replay_path.write_text(json.dumps(replay, indent=2) + '\n', encoding='utf-8')
    iris = target / 'config/iris.properties'
    properties = iris.read_text(encoding='utf-8')
    if not re.search(r'^enableShaders=', properties, re.MULTILINE):
        raise ValueError('missing Iris enable flag')
    iris.write_text(re.sub(r'^enableShaders=.*$', 'enableShaders=false', properties,
                           flags=re.MULTILINE), encoding='utf-8')
    if any(inventory(world) != before[str(world)] for world in worlds):
        raise RuntimeError('source world changed')
    if sha(source / 'options.txt') != source_options or inventory(source / 'config') != source_config:
        raise RuntimeError('source configuration changed')
    lock = dict(run_id=args.run_id, source_instance=str(source), instance=str(target),
                status='prepared_not_launched', runtime_passed=False, human_review='pending',
                source_worlds=before, source_preserved=True, original_pack_order=json.loads(match[1]),
                resource_pack_order=packs, mods=inventory(target / 'mods'),
                resourcepacks=inventory(target / 'resourcepacks'), config=inventory(target / 'config'),
                shaderpacks=inventory(target / 'shaderpacks'),
                automatic_recording=False, shaders_enabled=False, block_writes_executed=False)
    (evidence / 'environment-lock.json').write_text(json.dumps(lock, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(instance=str(target), worlds=args.world,
                          lock=str(evidence / 'environment-lock.json'))))


if __name__ == '__main__':
    main()

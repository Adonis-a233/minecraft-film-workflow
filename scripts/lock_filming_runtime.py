"""Hash the actual filming stack, excluding credentials and mutable journals."""
import argparse, hashlib, json
from pathlib import Path


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def snapshot(instance):
    files = {}
    for name in ('mods', 'resourcepacks', 'shaderpacks'):
        for path in sorted((instance/name).rglob('*')):
            if path.is_file():
                files[path.relative_to(instance).as_posix()] = sha(path)
    for name in ('iris.properties', 'ComplementaryReimagined_r5.2.2.txt'):
        path = instance/'config'/name
        if path.is_file():
            files[path.relative_to(instance).as_posix()] = sha(path)
    options = (instance/'options.txt').read_text(encoding='utf-8')
    selected = [line for line in options.splitlines() if line.startswith(
        ('resourcePacks:', 'incompatibleResourcePacks:'))]
    return {'files_sha256': files, 'resource_pack_order': selected}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('instance', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(snapshot(args.instance.resolve()), stream, indent=2)

"""Fetch frozen trial resources, verify bytes, never install into Minecraft."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--manifest', default='docs/execution-20261030/selected-downloads.json')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manifest_path = (root / args.manifest).resolve()
    if not manifest_path.is_relative_to(root / 'docs'):
        raise SystemExit('Manifest must be a repository docs file')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    for entry in manifest['files']:
        target = (root / entry['local_path']).resolve()
        if not target.is_relative_to(root / 'work'):
            raise SystemExit('Refusing destination outside work/')
        if target.exists():
            valid = target.stat().st_size == entry['bytes'] and hashlib.sha256(target.read_bytes()).hexdigest() == entry['sha256']
            if not valid:
                raise SystemExit(f'Existing file differs; preserve and investigate: {target}')
            print(f'VERIFIED {target}')
            continue
        if args.verify_only:
            raise SystemExit(f'MISSING {target}')
        source = urlsplit(entry['source_url'])
        if source.scheme != 'https' or source.hostname not in {'cdn.modrinth.com', 'www.dropbox.com'}:
            raise SystemExit('Source is not an approved locked resource host')
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + '.download')
        try:
            digest = hashlib.sha256()
            size = 0
            request = urllib.request.Request(entry['source_url'], headers={'User-Agent': 'minecraft-film-workflow/resource-lock'})
            with urllib.request.urlopen(request, timeout=60) as response, temp.open('xb') as stream:
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > entry['bytes']:
                        raise ValueError('Download exceeds pinned size')
                    digest.update(chunk)
                    stream.write(chunk)
            if size != entry['bytes'] or digest.hexdigest() != entry['sha256']:
                raise ValueError('Downloaded file does not match pinned bytes/hash')
            temp.replace(target)
        except Exception as exc:
            raise SystemExit(f'Blocked downloading {target.name}: {exc}; partial file retained, do not install') from exc
        print(f'DOWNLOADED AND VERIFIED {target}')
    print('Complete. Trial files only; nothing installed or visually approved.')


if __name__ == '__main__':
    main()

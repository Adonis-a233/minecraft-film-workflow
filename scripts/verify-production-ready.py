"""Verify the film delivery bytes without installing or changing the game."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
lock = json.loads((root / 'assets/production-v11-ready/delivery-lock.json').read_text(encoding='utf-8'))
for entry in lock['files']:
    path = (root / entry['path']).resolve()
    if not path.is_relative_to(root):
        raise SystemExit('Invalid delivery path')
    if not path.is_file():
        raise SystemExit(f'Missing: {entry["path"]}')
    data = path.read_bytes()
    if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
        raise SystemExit(f'Different bytes: {entry["path"]}')
print(f'Verified {len(lock["files"])} files. Runtime UV, sound alignment and visual review are separate.')

#!/usr/bin/env python3
"""Apply a same-source canonical runtime overlay to a freshly staged game.

The existing packager validates and stages the baseline first. This boundary
then validates the new authoring provenance and runtime formats independently;
old distribution receipts are never reused to describe replacement bytes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import package_game
import vrview

SOURCE = 'assets/authoring/weapon_animations.blend'
MAP = 'tools/nla_export/runtime_map.json'
SCHEMA = 'rust-duty-canonical-runtime-overlay/v1'


def digest(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def regular(root, relative):
    if (not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative
            or any(p in ('', '.', '..') for p in relative.split('/')) or relative.startswith('/')):
        raise ValueError('unsafe overlay path')
    return package_game.regular_file(root, relative)


def validate(root, overlay, destination):
    from nla_export.runtime import BUNDLES, load_map
    root, overlay, destination = map(Path, (root, overlay, destination))
    receipt = json.loads(regular(overlay, 'runtime-manifest.json').read_text())
    mapping = load_map(regular(root, MAP))
    if receipt.get('schema') != SCHEMA or receipt.get('source') != SOURCE:
        raise ValueError('unsupported canonical provenance')
    if receipt.get('source_sha256') != digest(regular(root, SOURCE).read_bytes())['sha256']:
        raise ValueError('canonical source hash mismatch')
    if receipt.get('runtime_map_sha256') != digest(regular(root, MAP).read_bytes())['sha256']:
        raise ValueError('runtime mapping hash mismatch')
    if receipt.get('mapped_clips') != mapping['clips'] or receipt.get('preserved_exports') != mapping['excluded']:
        raise ValueError('runtime mapping differs')
    expected = {'assets/animations.cfg'} | {
        f'assets/{b}/asset.{s}' for b in BUNDLES for s in ('vra', 'vrs', 'vrm')}
    expected |= {f'conversion/{c["id"]}/manifest.json' for c in mapping['clips']}
    if set(receipt.get('files', {})) != expected:
        raise ValueError('unexpected overlay file inventory')
    blobs = {}
    for relative, pin in receipt['files'].items():
        raw = regular(overlay, relative).read_bytes()
        if digest(raw) != pin:
            raise ValueError('overlay bytes differ: ' + relative)
        blobs[relative] = raw
    config = regular(root, 'assets/animations.cfg').read_bytes()
    if blobs['assets/animations.cfg'] != config or regular(destination, 'assets/animations.cfg').read_bytes() != config:
        raise ValueError('overlay changes existing runtime bindings')
    baseline = receipt.get('baseline_files', {})
    expected_base = {f'assets/{b}/asset.{s}' for b in BUNDLES for s in ('vra', 'vrs', 'vrm')}
    if set(baseline) != expected_base:
        raise ValueError('missing baseline asset hashes')
    for relative, pin in baseline.items():
        if digest(regular(destination, relative).read_bytes()) != pin:
            raise ValueError('staged baseline differs: ' + relative)
    preserved = receipt.get('preserved_companions', {})
    expected_preserved = {f'assets/{b}/asset.{s}' for b in BUNDLES if b != 'reload' for s in ('vrs', 'vrm')}
    if set(preserved) != expected_preserved:
        raise ValueError('missing preserved companion hashes')
    for relative, pin in preserved.items():
        if digest(blobs[relative]) != pin or baseline[relative] != pin:
            raise ValueError('preserved geometry differs: ' + relative)
    for bundle in BUNDLES:
        names = [f'assets/{bundle}/asset.{s}' for s in ('vra', 'vrs', 'vrm')]
        decoded = vrview.decode_vra(blobs[names[0]], vrs=blobs[names[1]], vrm=blobs[names[2]])
        previous = vrview.decode_vra(*(regular(destination, names[0]).read_bytes(),),
                                     vrs=regular(destination, names[1]).read_bytes(),
                                     vrm=regular(destination, names[2]).read_bytes())
        identity = lambda asset: [(c['name'], c['loop']) for c in asset['clips']]
        if identity(decoded) != identity(previous):
            raise ValueError('runtime clip order/name/loop binding changed: ' + bundle)
    return receipt, blobs, tuple(BUNDLES)


def apply(root, overlay, destination):
    destination = Path(destination).absolute()
    if destination.is_symlink() or not destination.is_dir():
        raise ValueError('destination must be a staged regular directory')
    if any(p.is_symlink() for p in destination.rglob('*')):
        raise ValueError('staged distribution contains a symlink')
    receipt, blobs, bundles = validate(root, overlay, destination)
    # Validate every byte before touching the staged game. Work on a sibling copy
    # so interrupted writes never leave a half-overlaid distribution in place.
    with tempfile.TemporaryDirectory(prefix='.canonical-package-', dir=destination.parent) as tmp:
        updated = Path(tmp) / 'game'
        shutil.copytree(destination, updated, symlinks=False)
        for bundle in bundles:
            folder = updated / 'assets' / bundle
            for old in folder.iterdir():
                if old.suffix in ('.json', '.gz') or old.name == 'README.md':
                    old.unlink()
        for relative, raw in blobs.items():
            target = updated / ('canonical-runtime/' + relative if relative.startswith('conversion/') else relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        original_receipt = regular(Path(overlay), 'runtime-manifest.json').read_bytes()
        original_path = 'canonical-runtime/source-overlay-manifest.json'
        (updated / original_path).write_bytes(original_receipt)
        installed = dict(receipt)
        installed['schema'] = 'rust-duty-canonical-runtime-package/v1'
        installed['overlay_schema'] = receipt['schema']
        installed['files'] = {
            ('canonical-runtime/' + name if name.startswith('conversion/') else name): pin
            for name, pin in receipt['files'].items()}
        installed['files'][original_path] = digest(original_receipt)
        (updated / 'CANONICAL_RUNTIME.json').write_text(json.dumps(installed, indent=2) + '\n')
        backup = Path(tmp) / 'baseline'
        destination.rename(backup)
        try:
            updated.rename(destination)
        except BaseException:
            backup.rename(destination)
            raise
    return {'source_sha256': receipt['source_sha256'], 'mapped_clips': len(receipt['mapped_clips']),
            'output': str(destination)}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path('.'))
    p.add_argument('--overlay', type=Path, required=True)
    p.add_argument('--destination', type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(apply(a.root, a.overlay, a.destination), indent=2))

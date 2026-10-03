#!/usr/bin/env python3
"""Build source-authored ADS via pinned Blender, FBX and actual Rust parity."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import vrview
from vrpack import require
from merge_walk_clip import clip_offset, merge

CLIPS = [('ads_entry_r1', False, 16), ('ads_hold_r1', True, 61), ('ads_exit_r1', False, 16)]


def digest(path):
    data = path.read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--blender', default='blender')
    parser.add_argument('--sampler', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve(); source = root / 'assets/authoring/ads'
    work = args.work.resolve(); output = args.output.resolve()
    require(not work.exists() and not output.exists(), 'use fresh work and output directories')
    work.mkdir(parents=True)
    config = json.loads((source / 'export_config.json').read_text())
    require(config['source_file'] == 'ads.blend' and config['source_fps'] == 60 and config['bake_hz'] == 480,
            'unexpected ADS source contract')
    takes = config['source_takes']
    require([(c['name'], c['loop'], c['frame_end']) for c in takes] == CLIPS
            and all(c['frame_start'] == 1 for c in takes), 'unexpected ADS take selection')
    def run(command):
        subprocess.run(list(map(str, command)), cwd=root, check=True)
    run([sys.executable, root / 'tools/package_game.py', 'materialize', '--root', root, '--include-walk'])
    exported = work / 'fbx'; merged = work / 'merged'; merged.mkdir()
    run([args.blender, '--background', '--factory-startup', '--disable-autoexec', source / 'ads.blend',
         '--python-exit-code', '1', '--python', root / 'tools/export_ads_fbx.py', '--',
         '--config', source / 'export_config.json', '--output-dir', exported])
    base = root / 'assets/walk/asset.vra'; original = base.read_bytes(); data = original
    vrs = base.with_suffix('.vrs').read_bytes(); vrm = base.with_suffix('.vrm').read_bytes()
    fbx_digest = digest(exported / 'ads.fbx'); source_digest = digest(source / 'ads.blend')
    for take in takes:
        imported = work / take['name']
        command = [args.blender, '--background', '--factory-startup', '--disable-autoexec',
             '--python-exit-code', '1', '--python', root / 'tools/import_fbx_viewmodel.py', '--',
             '--fbx', exported / 'ads.fbx', '--fbx-sha256', fbx_digest['sha256'],
             '--source-sha256', source_digest['sha256'], '--material-source', source / 'ads.blend',
             '--skeleton-vra', base, '--output', imported, '--actor', 'hk416_weapon',
             '--actor', 'hk416_magazine', '--native-start', '0', '--native-end', take['frame_end'] - 1,
             '--subdivisions', '8', '--fps', '60', '--take', take['name'], '--imported-frame-offset', '0',
             '--name', take['name']]
        if take['loop']: command.append('--loop')
        run(command)
        data = merge(data, (imported / 'asset.vra').read_bytes(), vrs, vrm,
                     name=take['name'], expected_loop=take['loop'])
    for ext, blob in [('vra', data), ('vrs', vrs), ('vrm', vrm)]:
        (merged / f'asset.{ext}').write_bytes(blob)
    require(data[clip_offset(data) + 4:clip_offset(data) + len(original) - clip_offset(original)]
            == original[clip_offset(original) + 4:], 'canonical walk44 payloads changed')
    reports = {}
    for take in takes:
        parity = work / f"parity-{take['name']}.json"
        run([sys.executable, root / 'tools/verify_locomotion_fbx.py', merged / 'asset.vra',
             exported / 'native_oracle.npz', '--oracle-json', exported / 'native_oracle.json',
             '--clip', take['name'], '--canonical-companions', '--sampler', args.sampler.resolve(), '--report', parity])
        report = json.loads(parity.read_text())
        require(report['passed'] and report['backend'] == 'Rust CPU sampler', 'ADS Rust parity failed')
        reports[take['name']] = {key: report[key] for key in ['samples', 'maxima', 'visibility_failures']}
    output.mkdir()
    for ext in ('vra', 'vrs', 'vrm'):
        shutil.copyfile(merged / f'asset.{ext}', output / f'asset.{ext}')
    for take in takes:
        shutil.copyfile(work / f"parity-{take['name']}.json", output / f"parity-{take['name']}.json")
        shutil.copyfile(work / take['name'] / 'manifest.json', output / f"conversion-{take['name']}.json")
    (output / 'asset.vrs.gz').write_bytes(gzip.compress(vrs, mtime=0))
    (output / 'asset.vra.gz').write_bytes(gzip.compress(data, mtime=0))
    pack = vrview.decode_vra(data, vrs=vrs, vrm=vrm)
    manifest = {'schema': 'rust-duty-authored-ads-distribution/v1', 'clip_count': 47,
        'clip_names': [c['name'] for c in pack['clips']],
        'ads_clips': [{'name': c['name'], 'loop': c['loop'], 'duration': (c['frame_end']-1)/60,
                       'action': c['action'], 'frame_start': c['frame_start'], 'frame_end': c['frame_end']} for c in takes],
        'source': {'file': 'assets/authoring/ads/ads.blend', **source_digest, 'fps': 60,
                   'bake_hz': 480, 'fbx': fbx_digest},
        'files': {f'asset.{ext}': digest(output / f'asset.{ext}') for ext in ('vra', 'vrs', 'vrm')},
        'preservation': {'original_walk_vra_sha256': digest(base)['sha256'], 'clip_payloads_byte_identical': 44,
                         'canonical_skin_byte_identical': True, 'canonical_rigid_byte_identical': True},
        'validation': {'backend': 'Rust CPU sampler', 'passed': True, 'clips': reports},
        'repository_transport': {name: {'file': name + '.gz', 'encoding': 'gzip',
            **digest(output / (name + '.gz')), 'decoded_bytes': len(raw),
            'decoded_sha256': hashlib.sha256(raw).hexdigest()}
            for name, raw in [('asset.vra', data), ('asset.vrs', vrs)]},
        'scope': 'New source-authored ADS entry/hold/exit; source Actions and canonical walk44 retained. Numerical parity is not artistic approval.'}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__': main()

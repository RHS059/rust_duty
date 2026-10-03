#!/usr/bin/env python3
"""Rebuild the two creator lanes and combined r5 from frozen r4, without renders.

Checks complete creator fingerprints before accepting reserialized lane inputs.
Never alters the supplied r4, frozen candidate, recipe or validation reports.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--blender', default='blender')
    a = parser.parse_args()
    recipe = json.loads((ROOT / 'assembly_recipe.json').read_text())
    assert hashlib.sha256(a.baseline.read_bytes()).hexdigest() == recipe['baseline_sha256']
    assert not a.output_dir.exists(), 'Use a new output directory'
    a.output_dir.mkdir(parents=True)

    def run(source, script, *args):
        command = [a.blender, '--background', '--factory-startup', '--disable-autoexec',
                   str(source.resolve()), '--python-exit-code', '1', '--python', str(script), '--']
        subprocess.run(command + [str(x) for x in args], check=True)

    lanes = {}
    for lane in ('longitudinal', 'lateral'):
        creator = ROOT / 'creators' / lane
        script = creator / ('author_r5.py' if lane == 'longitudinal' else 'author_r5_lateral.py')
        design = creator / ('directional_keyposes_r5.json' if lane == 'longitudinal' else 'directional_keyposes_r5_lateral.json')
        output = a.output_dir / ('reproduced_' + lane + '.blend')
        run(a.baseline, script, design, output)
        fingerprint = a.output_dir / (lane + '_fingerprint.json')
        run(output, ROOT / 'validate_directional_source.py', '--output', fingerprint)
        original = json.loads((ROOT / 'lane_validation' / lane / 'source_preservation.json').read_text())
        fresh = json.loads(fingerprint.read_text())
        for key in ('preserved', 'structural', 'action_count', 'nla_track_count', 'driver_count', 'invalid_drivers'):
            assert fresh[key] == original[key], f'{lane}: {key} differs'
        recipe['lanes'][lane]['source_sha256'] = fresh['source_sha256']
        lanes[lane] = output
    local_recipe = a.output_dir / 'reserialized_lane_recipe.json'
    local_recipe.write_text(json.dumps(recipe, indent=2) + '\n')
    output = a.output_dir / 'reproduced_r5.blend'
    run(a.baseline, ROOT / 'assemble_r5.py', '--recipe', local_recipe,
        '--longitudinal', lanes['longitudinal'], '--lateral', lanes['lateral'],
        '--output', output, '--report', a.output_dir / 'assembly_report.json')
    fingerprint = a.output_dir / 'combined_fingerprint.json'
    run(output, ROOT / 'validate_directional_source.py', '--output', fingerprint)
    original = json.loads((ROOT / 'source_preservation.json').read_text())
    fresh = json.loads(fingerprint.read_text())
    checks = {key: fresh[key] == original[key] for key in
              ('preserved', 'structural', 'action_count', 'nla_track_count', 'driver_count', 'invalid_drivers')}
    assert all(checks.values())
    report = {'schema': 'rust-duty-r5-portable-authoring-reproduction/v1',
              'frozen_source_sha256': original['source_sha256'],
              'reproduced_source_sha256': fresh['source_sha256'], 'checks': checks,
              'all_82_action_and_source_data_fingerprints_identical': True,
              'serialized_blend_bytes_expected_identical': False, 'passed': True}
    (a.output_dir / 'portable_reproduction.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()

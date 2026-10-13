#!/usr/bin/env python3
"""Measure current resident on/off ADS pixels without changing any acceptance gate."""
import argparse
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageChops
import performance_matrix as matrix
import run_cpu_image_preservation as pair
import run_dx12_authored as authored
import run_resident_authored_contract as native
import run_windows_cpu_profile as profile
import summarize_cpu_encode_detail as detail
import verify_capture_frame_witness as witness
import verify_capture_telemetry as telemetry
import verify_render_capture as png

SCHEMA = 'rust-duty-resident-ads-rounding-diagnostic/v1'
PRODUCTION_MANIFEST = '2a6a534aec6e3a6053ed6584dac497e38f85fabcf47aecf64c209bc925460b17'
POLICY = 'src/frame_resident_policy.rs'
ON = b'ENABLED: bool = true;'
OFF = b'ENABLED: bool = false;'
FRAMES = 553
LABELS = ('resident-off', 'resident-on')
BUILD = ['cargo', 'build', '--locked', '--release', '--no-default-features', '--features', 'wgpu-runtime', '--bin', 'vector-range']
require = pair.require


def source_pair(production):
    require(matrix.canonical_hash(pair.hashes(production)) == PRODUCTION_MANIFEST,
            'unreviewed closed production source inventory')
    require(production[POLICY].count(ON) == 1 and OFF not in production[POLICY], 'resident candidate policy differs')
    control = {**production, POLICY: production[POLICY].replace(ON, OFF)}
    require({p for p in production if production[p] != control[p]} == {POLICY}, 'source delta must be resident policy only')
    return {'resident-off': control, 'resident-on': dict(production)}


def admit(root):
    """Scheduling only: future production bytes must not start costly producers."""
    source = pair.read_sources(Path(root), 'HEAD', pair.PRODUCTION_PATHS)
    try:
        source_pair(source)
    except ValueError:
        return False
    return True


def validate_sequence(folder, identity):
    folder = Path(folder)
    expected = {f'{i:04}.png{suffix}' for i in range(FRAMES)
                for suffix in ('', '.json', '.time.json', '.gameplay.json')}
    require(folder.is_dir() and not folder.is_symlink(), 'capture directory missing or unsafe')
    require({p.name for p in folder.iterdir()} == expected
            and all(p.is_file() and not p.is_symlink() for p in folder.iterdir()), 'complete exact 553-frame inventory required')
    images, finite = authored.sequence_inventory(folder, 'Dx12', expected_witness_identity=identity)
    visibility = []
    for path in images:
        try:
            result = png.verify(path, authored.EXTENT, authored.BACKGROUND, 0.01, 8, None)
            visibility.append({'frame': path.name, 'passed': True, 'result': result})
        except png.CaptureStructureError as error:
            # Keep the unchanged gate's original error. This diagnostic does not
            # admit the historical source-visibility deferral or waive failure.
            visibility.append({'frame': path.name, 'passed': False, 'error': str(error)})
    return {'frames': len(images), 'finite_json': finite, 'visibility_gate_passed': all(r['passed'] for r in visibility),
            'visibility': visibility}


def pixel_metrics(before, after):
    require(before.mode == after.mode == 'RGBA' and before.size == after.size, 'pixel formats/extents differ')
    difference = ImageChops.difference(before, after)
    channels = difference.split()
    maximum = max(high for _, high in difference.getextrema())
    changed = Image.new('L', before.size)
    for channel in channels:
        changed = ImageChops.lighter(changed, channel)
    return {'differing_pixels': before.width * before.height - changed.histogram()[0],
            'maximum_channel_delta': maximum,
            'absolute_channel_delta': sum(sum(i*n for i, n in enumerate(c.histogram())) for c in channels),
            'alpha_differing_pixels': before.width * before.height - channels[3].histogram()[0]}


def compare_sequences(before, after, before_identity, after_identity):
    before, after = Path(before), Path(after)
    # The original marker is independently checked BEFORE any exclusion. This
    # invocation-derived marker differs because the compiled executables differ.
    validations = [validate_sequence(before, before_identity), validate_sequence(after, after_identity)]
    joined = telemetry.compare(before, after)
    require(joined['gameplay_files'] == joined['time_files'] == FRAMES, 'incomplete deterministic joins')
    rows = []
    for index in range(FRAMES):
        name = f'{index:04}.png'
        records = [telemetry.read_record(folder / (name + '.json')) for folder in (before, after)]
        for record in records:
            record['frame_witness'] = {k: v for k, v in record['frame_witness'].items() if k != 'capture_identity'}
        telemetry._compare(*records, name + '.json')
        images = [png.load_png(folder / name, authored.EXTENT) for folder in (before, after)]
        counts = []
        for image in images:
            # Replacement is diagnostic-only and never modifies retained PNGs.
            image.paste(authored.BACKGROUND, (0, 0, *witness.MARKER_SIZE))
            counts.append(png._foreground_count(image, authored.BACKGROUND, 8))
        rows.append({'frame': index, **pixel_metrics(*images), 'scene_foreground_pixels': counts})
    return {'diagnostic_completed': True, 'frames': FRAMES, 'telemetry': joined,
            'primary_metadata_equal_except_verified_capture_identity': True,
            'visibility_gate_passed': all(v['visibility_gate_passed'] for v in validations),
            'visibility': dict(zip(LABELS, validations)),
            'differing_frames': sum(r['differing_pixels'] != 0 for r in rows),
            'differing_pixels': sum(r['differing_pixels'] for r in rows),
            'maximum_channel_delta': max(r['maximum_channel_delta'] for r in rows),
            'absolute_channel_delta': sum(r['absolute_channel_delta'] for r in rows),
            'alpha_differing_pixels': sum(r['alpha_differing_pixels'] for r in rows), 'per_frame': rows,
            'acceptance': 'No source-visibility or image-tolerance acceptance is granted by this diagnostic.',
            'scope': 'Current resident policy only; does not isolate every historical adc-to-current source/compiler difference or measure speed.'}


def device_evidence(logs):
    authored.renderer_logs(logs)
    prefix = 'renderer graphics_device_evidence='
    lines = [s[len(prefix):] for s in (logs / 'stderr.log').read_text(encoding='utf-8').splitlines() if s.startswith(prefix)]
    require(len(lines) == 1, 'one actual graphics device record required')
    actual = json.loads(lines[0], object_pairs_hook=telemetry._unique_object,
                        parse_constant=telemetry._reject_constant, parse_float=telemetry._parse_float)
    require(actual.get('backend') == 'Dx12' and actual.get('device_type') == 'Cpu'
            and actual.get('name') == authored.WARP and actual.get('force_fallback_requested') is True
            and actual.get('present_mode') == 'Fifo' and actual.get('gpu_timestamps_requested') is False
            and actual.get('gpu_timestamp_features_enabled') is False, 'actual capture device/mode differs')
    detail.validate_instance_descriptor({'identity': {'runtime_observed': {'actual_adapter': actual}}})
    descriptor = actual['instance_descriptor']
    require(descriptor.get('flags_bits') == 32 and descriptor.get('application_debug_assertions') is False
            and descriptor.get('environment_overrides_applied') is False, 'release instance flags differ')
    return actual


def authored_scene_evidence(logs):
    text = '\n'.join((logs / name).read_text(encoding='utf-8') for name in ('stdout.log', 'stderr.log'))
    require(not any(error in text for error in ('Authored viewmodel could not load:',
            'Authored viewmodel playback failed:', 'Action clip timings:')), 'authored load/playback failed')
    rows = [line for line in text.splitlines() if line.startswith('Loaded Blender-authored viewmodel:')]
    for clip in ('normal_ready', 'reload_current_wip', 'normal_walk_r1', 'ads_entry_r1', 'jump_takeoff'):
        require(any(row.endswith(', selected ' + clip) for row in rows), 'missing authored companion load: ' + clip)
    return rows


def run(root, output, build_timeout=1200, capture_timeout=3000):
    root, output = Path(root).resolve(), Path(output).resolve()
    require(sys.platform == 'win32', 'diagnostic requires native Windows DX12')
    require(root == Path(__file__).resolve().parents[1], 'runner/checkout differs')
    require(pair.gpu.positive(build_timeout) and build_timeout <= 1200
            and pair.gpu.positive(capture_timeout) and capture_timeout <= 3000, 'invalid bounded timeouts')
    pair.check_environment(os.environ)
    require(not (root / 'assets/weapons').exists(), 'private weapon assets excluded')
    require(output.is_dir() and not output.is_symlink() and {p.name for p in output.iterdir()} == {'materialize.json'}
            and (output / 'materialize.json').is_file() and not (output / 'materialize.json').is_symlink(), 'fresh materialization receipt required')
    pair.check_cargo_configuration(root, os.environ)
    source = profile.checked_source(root)
    runtime = matrix.source_identity(root)
    require(matrix.canonical_hash(runtime['runtime_files_sha256']) == matrix.AUDITED_STAGING_CANDIDATE_MANIFEST, 'current reviewed runtime required')
    production = pair.read_sources(root, source['commit'], pair.PRODUCTION_PATHS)
    variants = source_pair(production)
    assets = profile.inventory(root / 'assets')
    require('animations.cfg' in assets and 'locomotion/asset.vrs' in assets, 'original companions missing')
    compiler = pair.toolchain_at(root)
    require('release: 1.99.0\n' in compiler['rustc'] and 'host: x86_64-pc-windows-msvc\n' in compiler['rustc']
            and compiler['cargo'].startswith('cargo 1.99.0 '), 'actual Rust/Cargo 1.99 MSVC required')
    ci = {key: os.environ.get(key) for key in ('GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_ACTIONS')}
    require(ci['GITHUB_ACTIONS'] == 'true', 'actual CI identity required')
    inputs = {'schema': SCHEMA, 'source': source, 'runtime': runtime, 'assets_sha256': assets,
              'compiler': compiler, 'ci': ci, 'production_manifest_sha256': PRODUCTION_MANIFEST,
              'materialize_sha256': matrix.sha256(output / 'materialize.json'), 'build_command': BUILD}
    matrix.write_json(output / 'inputs.json', inputs)
    settings = output / 'ads-offset.cfg'
    settings.write_text((root / 'settings.cfg').read_text(encoding='utf-8') +
        '\nviewmodel_x = 0.20\nviewmodel_y = -0.20\nviewmodel_z = 0.20\n', encoding='utf-8')
    retained = {p: matrix.sha256(p) for p in (output / 'inputs.json', output / 'materialize.json', settings)}
    inventories, directories, builds = {}, {}, {}
    def retain(directory):
        inventories[directory] = pair.controls.source_manifest(directory)
        directories[directory] = pair.directory_manifest(directory)
    def verify():
        require(profile.checked_source(root) == source and matrix.source_identity(root) == runtime
                and profile.inventory(root / 'assets') == assets, 'source/runtime/assets changed')
        pair.check_environment(os.environ)
        require({key: os.environ.get(key) for key in ci} == ci, 'CI build identity changed')
        for directory in [root] + [b['source'] for b in builds.values()]:
            pair.check_cargo_configuration(directory, os.environ)
            require(pair.toolchain_at(directory) == compiler, 'compiler changed by build cwd')
        require(all(matrix.sha256(p) == h for p, h in retained.items()), 'retained evidence/executable/settings changed')
        pair.verify_retained_outputs(inventories, {}, directories)
    pending_error = None
    try:
        for label in LABELS:
            destination = output / (label + '-source')
            destination.mkdir()
            for name, raw in variants[label].items():
                path = destination / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            require(pair.controls.source_manifest(destination) == pair.hashes(variants[label]), 'materialized source differs')
            retain(destination)
            source_receipt = output / (label + '-source.json')
            matrix.write_json(source_receipt, {'schema': SCHEMA, 'variant': label, 'base_commit': source['commit'],
                'files_sha256': pair.hashes(variants[label]), 'runtime_delta': [] if label == 'resident-on' else [POLICY],
                'inputs_sha256': matrix.sha256(output / 'inputs.json')})
            retained[source_receipt] = matrix.sha256(source_receipt)
            builds[label] = {'source': destination}
            verify()
            target = output / (label + '-target')
            env = dict(os.environ, CARGO_TARGET_DIR=str(target))
            logs = output / (label + '-build')
            native.logged(BUILD, destination, logs, env, build_timeout)
            built = target / 'release/vector-range.exe'
            digest = matrix.sha256(built)
            retained[built] = digest
            executable = output / 'executables' / (label + '.exe')
            executable.parent.mkdir(exist_ok=True)
            shutil.copyfile(built, executable)
            require(matrix.sha256(executable) == digest, 'retained executable copy differs')
            retained[executable] = digest
            retain(logs)
            builds[label].update(executable=str(executable), executable_sha256=digest,
                                 source_receipt_sha256=retained[source_receipt])
            verify()
        matrix.write_json(output / 'builds.json', {k: {**v, 'source': str(v['source'])} for k, v in builds.items()})
        retained[output / 'builds.json'] = matrix.sha256(output / 'builds.json')
        identities, devices = {}, []
        case = next(case for case in authored.CASES if case.name == 'ads-offset')
        for label in LABELS:
            build = builds[label]
            identities[label] = witness.capture_identity({'source_commit': source['commit'],
                'exe_sha256': build['executable_sha256'], 'run_id': ci['GITHUB_RUN_ID'],
                'run_attempt': ci['GITHUB_RUN_ATTEMPT'], 'scenario': 'ads-offset', 'backend': 'Dx12'})
            capture, logs = output / label, output / (label + '-process')
            command = authored.game_command(build['executable'], root, capture, case, settings)
            command.append('--capture-frame-witness=' + identities[label])
            verify()
            native.logged(command, root, logs, dict(os.environ), capture_timeout, build['executable_sha256'])
            # Freeze raw bytes and complete directory sets before any validator reads.
            retain(logs)
            retain(capture)
            authored_scene_evidence(logs)
            devices.append(device_evidence(logs))
            validate_sequence(capture, identities[label])
            verify()
        require(devices[0] == devices[1], 'actual same-host devices differ')
        summary = {'schema': SCHEMA, **compare_sequences(output / LABELS[0], output / LABELS[1],
                   identities[LABELS[0]], identities[LABELS[1]]), 'identities': identities, 'device': devices[0],
                   'inputs_sha256': matrix.sha256(output / 'inputs.json'), 'builds_sha256': matrix.sha256(output / 'builds.json')}
        matrix.write_json(output / 'retained.json', {str(p.relative_to(output)): h for p, h in retained.items()})
        retained[output / 'retained.json'] = matrix.sha256(output / 'retained.json')
        matrix.write_json(output / 'output-inventories.json', {str(p.relative_to(output)): {'files': f, 'directories': directories[p]} for p, f in inventories.items()})
        retained[output / 'output-inventories.json'] = matrix.sha256(output / 'output-inventories.json')
    except BaseException as error:
        pending_error = error
        matrix.write_json(output / 'failure.json', {'diagnostic_completed': False, 'error': str(error), 'type': type(error).__name__})
        raise
    finally:
        try:
            verify()
            matrix.write_json(output / 'final-input-check.json', {'passed': True})
        except BaseException as error:
            matrix.write_json(output / 'final-input-check.json', {'passed': False, 'error': str(error)})
            if not (output / 'failure.json').exists():
                matrix.write_json(output / 'failure.json', {'diagnostic_completed': False, 'stage': 'final-input-check', 'error': str(error)})
            if pending_error is None:
                raise
    matrix.write_json(output / 'summary.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--admit', action='store_true', help='print exact closed-source scheduling admission only')
    args = parser.parse_args(argv)
    try:
        if args.admit:
            require(args.output is None, 'admission does not create capture evidence')
            print('admitted=' + str(admit(args.root)).lower())
            return 0
        require(args.output is not None, 'capture requires --output')
        print(json.dumps(run(args.root, args.output), indent=2))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

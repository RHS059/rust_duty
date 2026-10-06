#!/usr/bin/env python3
"""Build one identical example against pinned baseline/candidate; run bounded WARP pairs."""
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tarfile
import time

BASELINE = '17023450076b668c279539e0e450b8cb58a7c1a2'
CANDIDATE = '5abf2bca825a252fb7ad6665c444c89861ee8ef9'
CANDIDATE_HASHES = {
    'src/render/frame.rs': 'd0bdefd2fe79f77c33e2ac4183346cccfcbae3a3d1fac6c7e2130e7d6648d91e',
    'src/render/plan.rs': 'c23e97a848435a610f5be0c72341ef8e5090fa2cd66846cda1b29159558a4c7e',
}
TOOLCHAIN = '1.99.0-x86_64-pc-windows-msvc'
EXAMPLE = 'pass_submission_benchmark'
HARNESS = f'examples/{EXAMPLE}.rs'
ALLOWED = {'src/render/frame.rs', 'src/render/plan.rs'}
SOURCE_PATHS = ['Cargo.toml', 'Cargo.lock', 'build.rs', 'build_number.rs',
                'LICENSE', 'src', 'updater', '.cargo', 'rust-toolchain.toml',
                'examples/renderer_contract.rs']
PAIRS = 4
FIXED_VALIDATORS = ['tools/run_renderer_contract.py', 'tools/run_dx12_smoke.py',
                    'tools/verify_capture_telemetry.py', 'tools/verify_render_capture.py']
CONTRACT_NAMES = {
    'quadrant.png', 'readback-width-65.png', 'quadrant-target.png', 'quadrant-target-composite.png',
    'ordered-a-red.png', 'ordered-b-green.png', 'depth-main-near.png', 'depth-target-near.png',
    'depth-target-reset.png', 'depth-main-preserved.png', 'depth-main-reset.png', 'depth-disabled.png',
    'alpha-target.png', 'alpha-main-display.png', 'alpha-composite.png', 'alpha-tinted-composite.png',
    'alpha-clear.png', 'alpha-opaque-source.png', 'text-100-percent.png', 'text-200-percent.png',
    'after-errors.png',
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def source_manifest(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'source symlink is unsupported: {path}')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return result


def pinned_source(repository):
    names = subprocess.check_output(['git', '-C', str(repository), 'ls-tree', '-r', '--name-only', BASELINE,
                                     '--', *SOURCE_PATHS]).decode().splitlines()
    if not {'Cargo.toml', 'Cargo.lock', *ALLOWED}.issubset(names):
        raise ValueError('pinned baseline compile sources are incomplete')
    # One archive read avoids hundreds of git processes; never archive game assets.
    archive = subprocess.check_output(['git', '-C', str(repository), 'archive', BASELINE, '--', *names])
    result = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        for member in stream:
            if member.isdir():
                continue
            path = Path(member.name)
            if not member.isfile() or path.is_absolute() or '..' in path.parts:
                raise ValueError(f'unsupported pinned source: {member.name}')
            result[member.name] = stream.extractfile(member).read()
    return result


def candidate_sources(baseline, root):
    result = {}
    for name, content in baseline.items():
        path = root / name
        if path.is_symlink() or (name in ALLOWED and not path.is_file()):
            raise ValueError(f'missing or symlinked candidate compile input: {name}')
        # Candidate is a two-file overlay; absent unchanged inputs come from the
        # pinned Git object, and any supplied unchanged inputs must match it.
        result[name] = path.read_bytes() if path.is_file() else content
        if name not in ALLOWED and result[name] != content:
            raise ValueError(f'candidate changes an input outside the two-file experiment: {name}')
    for folder in ('src', 'updater/src', '.cargo'):
        directory = root / folder
        if directory.exists():
            for path in directory.rglob('*'):
                if path.is_file() and path.relative_to(root).as_posix() not in baseline:
                    raise ValueError(f'unbound extra candidate compile input: {path}')
    changed = {name for name in baseline if baseline[name] != result[name]}
    if changed != ALLOWED:
        raise ValueError(f'expected only both passbatch files to change; found {sorted(changed)}')
    return result


def materialize(root, sources, harness):
    root.mkdir()
    for name, content in {**sources, HARNESS: harness}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return source_manifest(root)


def run_logged(command, cwd, log, env, timeout):
    started = time.time()
    record = {'command': [str(x) for x in command], 'cwd': str(cwd), 'started_unix': started,
              'timeout_seconds': timeout}
    write_json(log.with_suffix('.command.json'), record)
    try:
        with log.open('wb') as output:
            process = subprocess.run(command, cwd=cwd, env=env, stdout=output,
                                     stderr=subprocess.STDOUT, timeout=timeout, check=False)
        record['returncode'] = process.returncode
        if process.returncode:
            raise ValueError(f'process exited {process.returncode}; see {log}')
    except subprocess.TimeoutExpired:
        record['timed_out'] = True
        raise
    finally:
        record['elapsed_seconds'] = time.time() - started
        write_json(log.with_suffix('.command.json'), record)


def verify_shader_compiler(log):
    if 'renderer dx12_shader_compiler=Fxc' not in log.read_text(encoding='utf-8').splitlines():
        raise ValueError(f'native initialization did not report pinned Fxc shader compiler: {log}')


def device_evidence(log):
    verify_shader_compiler(log)
    prefix = 'renderer device_evidence='
    lines = [line[len(prefix):] for line in log.read_text(encoding='utf-8').splitlines() if line.startswith(prefix)]
    if len(lines) != 1:
        raise ValueError(f'expected exactly one native device evidence record: {log}')
    evidence = json.loads(lines[0])
    required = {'device_type', 'vendor_id', 'device_id', 'driver', 'driver_info',
                'present_mode', 'force_fallback_requested'}
    if not isinstance(evidence, dict) or set(evidence) != required:
        raise ValueError('native device evidence fields differ')
    if evidence['device_type'] != 'Cpu' or evidence['force_fallback_requested'] is not True or evidence['present_mode'] is not None:
        raise ValueError('expected headless forced-fallback CPU device evidence')
    if any(type(evidence[k]) is not int or evidence[k] < 0 for k in ('vendor_id', 'device_id')):
        raise ValueError('invalid actual vendor/device evidence')
    if any(type(evidence[k]) is not str for k in ('driver', 'driver_info')):
        raise ValueError('invalid actual driver evidence')
    return evidence


def require_same_devices(evidence):
    if len(evidence) < 2 or any(value != evidence[0] for value in evidence[1:]):
        raise ValueError('native device evidence differs between baseline/candidate/trials')
    return evidence[0]


def fixed_validation(directory, verifier_root, log, env):
    code = ('import json,sys; from run_renderer_contract import validate_outputs; '
            'print(json.dumps(validate_outputs(sys.argv[1]), sort_keys=True))')
    run_logged([sys.executable, '-c', code, str(directory)], verifier_root / 'tools', log, env, 60)
    result = json.loads(log.read_text(encoding='utf-8'))
    if result.get('passed') is not True or result.get('captures') != 21:
        raise ValueError('unchanged fixed-output validator did not pass all 21 cases')
    return result


def validate_report(report, source_hash):
    if not isinstance(report, dict):
        raise ValueError('report must be an object')
    expected = {'schema_version': 1, 'status': 'passed', 'fixture': 'pass-submission-synthetic-305-v1',
                'source_receipt_sha256': source_hash, 'platform': 'windows', 'backend': 'Dx12',
                'requested': 'dx12', 'adapter': 'Microsoft Basic Render Driver',
                'force_fallback_adapter': True, 'width': 320, 'height': 180,
                'prepared_draw_count': 305, 'nontext_draw_count': 135, 'glyph_draw_count': 170,
                'warmup_frames': 2, 'timed_frames': 4, 'timed_capture_count': 0,
                'presentation': False, 'gpu_timestamp_ms': None}
    for key, value in expected.items():
        if report.get(key) != value or type(report.get(key)) is not type(value):
            raise ValueError(f'invalid report identity/fixture field {key}')
    samples = report.get('whole_submit_ms')
    if not isinstance(samples, list) or len(samples) != 4:
        raise ValueError('four whole-submit samples are required')
    durations = samples + [report.get(key) for key in (
        'pre_control_submit_drain_png_ms', 'final_control_submit_drain_png_ms',
        'bounded_batch_with_final_control_ms')]
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in durations):
        raise ValueError('durations must be finite and positive')
    if report['bounded_batch_with_final_control_ms'] < sum(samples) + report['final_control_submit_drain_png_ms']:
        raise ValueError('batch duration cannot omit submission or final-control duration')


def exact_pixels(paths):
    from PIL import Image
    reference = None
    receipt = {}
    for path in paths:
        with Image.open(path) as image:
            if image.format != 'PNG' or image.size != (320, 180) or image.mode != 'RGBA':
                raise ValueError(f'wrong control image format/extent/mode: {path}')
            pixels = image.tobytes()
        if any(alpha != 255 for alpha in pixels[3::4]) or len(set(zip(*[iter(pixels)] * 4))) < 2:
            raise ValueError(f'uniform or nonopaque control: {path}')
        if reference is not None and pixels != reference:
            raise ValueError(f'control RGBA differs, zero tolerance: {path}')
        reference = pixels
        receipt[str(path)] = {'png_sha256': digest(path.read_bytes()), 'rgba_sha256': digest(pixels)}
    if len(receipt) < 2:
        raise ValueError('at least two independent controls are required')
    return receipt


def contract_pixels(baseline, candidate):
    """Keep production fixed expectations; additionally demand all 21 exact pixel matches."""
    from PIL import Image
    images = {}
    for label, directory in [('baseline', baseline), ('candidate', candidate)]:
        report = json.loads((directory / 'renderer-contract-report.json').read_text(encoding='utf-8'))
        expected = {'schema_version': 1, 'status': 'passed', 'native_execution': True,
                    'requested': 'dx12', 'backend': 'Dx12', 'adapter': 'Microsoft Basic Render Driver',
                    'force_fallback_adapter': True, 'platform': 'windows'}
        if any(report.get(k) != v or type(report.get(k)) is not type(v) for k, v in expected.items()):
            raise ValueError(f'{label} production renderer contract identity failed')
        captures = report.get('captures', [])
        if len(captures) != 21 or {c.get('filename') for c in captures} != CONTRACT_NAMES:
            raise ValueError(f'{label} contract report is missing/duplicating captures')
        failures = report.get('expected_failures', [])
        if len(failures) != 4 or {e.get('expected_error') for e in failures} != {
                'create capture directory', 'write capture', 'capture path must not be empty', 'non-finite'}:
            raise ValueError(f'{label} contract omitted expected failure/recovery cases')
        if any(e['expected_error'] not in e.get('actual_error', '') for e in failures):
            raise ValueError(f'{label} expected rejection reached a different error')
        present = {p.relative_to(directory).as_posix() for p in directory.rglob('*.png') if p.is_file()}
        if present != CONTRACT_NAMES:
            raise ValueError(f'{label} contract PNG set is not closed')
        images[label] = {}
        for name in sorted(CONTRACT_NAMES):
            size = {'readback-width-65.png': (65, 49), 'text-100-percent.png': (64, 48),
                    'text-200-percent.png': (128, 96), 'after-errors.png': (16, 16)}.get(name, (96, 64))
            with Image.open(directory / name) as image:
                if image.format != 'PNG' or image.mode != 'RGBA' or image.size != size:
                    raise ValueError(f'{label} contract capture extent/mode changed: {name}')
                images[label][name] = image.tobytes()
    receipt = {}
    for name in sorted(CONTRACT_NAMES):
        if images['baseline'][name] != images['candidate'][name]:
            raise ValueError(f'production contract pixels differ, zero tolerance: {name}')
        receipt[name] = {'rgba_sha256': digest(images['baseline'][name]),
                         'baseline_png_sha256': digest((baseline / name).read_bytes()),
                         'candidate_png_sha256': digest((candidate / name).read_bytes())}
    return receipt


def execute(args):
    if sys.platform != 'win32':
        raise ValueError('native diagnostic requires Windows; Linux can run its guard tests only')
    root = args.repository.resolve()
    candidate = args.candidate_root.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    verifier = output / 'verifier'
    verifier.mkdir()
    script_root = Path(__file__).resolve().parent.parent
    harness = (script_root / HARNESS).read_bytes()
    for name in (HARNESS, 'tools/run_pass_submission_benchmark.py', 'tools/test_pass_submission_benchmark.py'):
        destination = verifier / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(script_root / name, destination)
    for name in FIXED_VALIDATORS:
        pinned = subprocess.check_output(['git', '-C', str(root), 'show', f'{BASELINE}:{name}'])
        if (script_root / name).read_bytes() != pinned:
            raise ValueError(f'fixed contract validator changed from pinned baseline: {name}')
        (verifier / name).write_bytes(pinned)
    write_json(output / 'verifier-receipt.json', source_manifest(verifier))
    baseline = pinned_source(root)
    candidate_data = candidate_sources(baseline, candidate)
    for name, expected in CANDIDATE_HASHES.items():
        published = subprocess.check_output(['git', '-C', str(root), 'show', f'{CANDIDATE}:{name}'])
        if digest(published) != expected or digest(candidate_data[name]) != expected:
            raise ValueError(f'candidate is not the pinned published passbatch source: {name}')
    env = os.environ.copy()
    # Reject inherited compiler injection rather than silently changing its meaning.
    forbidden = ['RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'RUSTC', 'RUSTC_WRAPPER',
                 'RUSTC_WORKSPACE_WRAPPER', 'VR_WEAPON_ASSET', 'RUSTUP_TOOLCHAIN']
    if any(env.get(key) for key in forbidden):
        raise ValueError('unset inherited compiler/asset overrides: ' + ', '.join(key for key in forbidden if env.get(key)))
    settings = {'CARGO_TARGET_DIR': str(output / 'target'), 'CARGO_INCREMENTAL': '0',
                'CARGO_PROFILE_DEV_DEBUG': '0', 'CARGO_PROFILE_DEV_OPT_LEVEL': '2',
                'CARGO_BUILD_JOBS': '2', 'CI': 'true'}
    temp = output / 'temp'
    temp.mkdir()
    settings.update({key: str(temp) for key in ('TMP', 'TEMP', 'TMPDIR')})
    env.update(settings)
    toolchain = subprocess.check_output(['rustup', 'run', TOOLCHAIN, 'rustc', '-Vv'], env=env).decode()
    cargo_version = subprocess.check_output(['rustup', 'run', TOOLCHAIN, 'cargo', '-V'], env=env).decode()
    (output / 'rustc.txt').write_text(toolchain, encoding='utf-8')
    (output / 'cargo.txt').write_text(cargo_version, encoding='utf-8')
    builds = {}
    for label, sources in [('baseline', baseline), ('candidate', candidate_data)]:
        source = output / f'{label}-source'
        manifest = materialize(source, sources, harness)
        receipt_path = output / f'{label}-source-receipt.json'
        write_json(receipt_path, {'baseline_commit': BASELINE, 'candidate_commit': CANDIDATE, 'variant': label,
                                 'files': manifest, 'harness_sha256': digest(harness),
                                 'toolchain': toolchain, 'cargo': cargo_version,
                                 'build_environment': settings, 'assets': 'none; synthetic fixture only',
                                 'candidate_overlay_files': sorted(ALLOWED) if label == 'candidate' else []})
        source_hash = digest(receipt_path.read_bytes())
        build_env = {**env, 'PASS_SUBMISSION_SOURCE_SHA256': source_hash}
        log = output / f'{label}-build.log'
        command = ['rustup', 'run', TOOLCHAIN, 'cargo', 'build', '--locked', '--no-default-features',
                   '--features', 'wgpu-runtime', '--example', EXAMPLE, '--example', 'renderer_contract',
                   '--message-format=json-render-diagnostics']
        run_logged(command, source, log, build_env, 1200)
        if source_manifest(source) != manifest:
            raise ValueError(f'{label} compile source changed during build')
        artifacts = {EXAMPLE: [], 'renderer_contract': []}
        for line in log.read_text(encoding='utf-8').splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = item.get('target', {}).get('name')
            if item.get('reason') == 'compiler-artifact' and name in artifacts and item.get('executable'):
                artifacts[name].append(Path(item['executable']))
        if any(len(paths) != 1 for paths in artifacts.values()):
            raise ValueError(f'{label} Cargo did not identify exactly one binary per requested example')
        builds[label] = {'source_receipt_sha256': source_hash}
        for name, paths in artifacts.items():
            executable = output / f'{label}-{name}.exe'
            shutil.copyfile(paths[0], executable)
            builds[label][name] = {'executable_sha256': digest(executable.read_bytes()), 'executable': str(executable)}
        write_json(output / 'build-receipts.json', builds)
    fixed_checks = {}
    devices = []
    for label in builds:
        executable = builds[label]['renderer_contract']['executable']
        if digest(Path(executable).read_bytes()) != builds[label]['renderer_contract']['executable_sha256']:
            raise ValueError('compiled production contract changed before run')
        run_logged([executable, '--renderer=dx12', '--force-fallback-adapter',
                    '--output-dir', str(output / f'{label}-renderer-contract')],
                   output, output / f'{label}-renderer-contract.log', env, 180)
        devices.append(device_evidence(output / f'{label}-renderer-contract.log'))
        fixed_checks[label] = fixed_validation(output / f'{label}-renderer-contract', verifier,
                                               output / f'{label}-fixed-validator.log', env)
    same_device = require_same_devices(devices)
    source_receipts = [json.loads((output / f'{label}-source-receipt.json').read_text(encoding='utf-8'))
                       for label in ('baseline', 'candidate')]
    if any(source_receipts[0][key] != source_receipts[1][key] for key in ('toolchain', 'cargo', 'build_environment')):
        raise ValueError('baseline/candidate actual compiler or build settings differ')
    write_json(output / 'production-contract-fixed-validation.json', fixed_checks)
    write_json(output / 'native-device-evidence.json', {'baseline': devices[0], 'candidate': devices[1], 'equal': True})
    contract = contract_pixels(output / 'baseline-renderer-contract', output / 'candidate-renderer-contract')
    write_json(output / 'production-contract-exact-pixels.json', contract)
    trials = []
    controls = []
    for pair in range(PAIRS):
        for label in (['baseline', 'candidate'] if pair % 2 == 0 else ['candidate', 'baseline']):
            trial = output / f'pair-{pair + 1}-{label}'
            executable = Path(builds[label][EXAMPLE]['executable'])
            if digest(executable.read_bytes()) != builds[label][EXAMPLE]['executable_sha256']:
                raise ValueError('compiled executable changed before run')
            run_logged([str(executable), '--output-dir', str(trial)], output,
                       output / f'pair-{pair + 1}-{label}.log', env, 120)
            devices.append(device_evidence(output / f'pair-{pair + 1}-{label}.log'))
            require_same_devices(devices)
            report = json.loads((trial / 'report.json').read_text(encoding='utf-8'))
            validate_report(report, builds[label]['source_receipt_sha256'])
            controls.extend([trial / 'before.png', trial / 'after.png'])
            # Check each completed trial immediately, including against every prior build/trial.
            pixels = exact_pixels(controls)
            trials.append({'pair': pair + 1, 'variant': label, 'report': report})
            write_json(output / 'completed-trials.json', trials)
    summaries = {}
    for label in builds:
        selected = [t['report'] for t in trials if t['variant'] == label]
        summaries[label] = {
            'whole_submit_trial_medians_ms': [statistics.median(t['whole_submit_ms']) for t in selected],
            'median_whole_submit_ms': statistics.median([v for t in selected for v in t['whole_submit_ms']]),
            'final_control_submit_drain_png_ms': [t['final_control_submit_drain_png_ms'] for t in selected],
            'bounded_batch_with_final_control_ms': [t['bounded_batch_with_final_control_ms'] for t in selected],
        }
    summary = {'schema_version': 1, 'status': 'passed', 'baseline_commit': BASELINE, 'candidate_commit': CANDIDATE,
               'pair_count': PAIRS, 'builds': builds, 'timings': summaries, 'pixels': pixels,
               'production_renderer_contract': {'capture_count': 21, 'exact_pixels': contract,
                                                'fixed_validations': fixed_checks, 'device_evidence': same_device,
                                                'shader_compiler': 'Fxc', 'compiler_equal': True},
               'comparison': 'exact RGBA pixels across all before/after controls; zero tolerance',
               'scope': 'synthetic headless DX12 WARP whole-submit diagnostic; optimized dev profile; '
                        'no gameplay, surface acquisition/present, GPU timestamp, RTX measurement or FPS claim; '
                        'final-control duration includes one extra fixture, queue drain, readback and PNG I/O'}
    write_json(output / 'summary.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, required=True, help='Git repository containing the pinned baseline object')
    parser.add_argument('--candidate-root', type=Path, required=True, help='Source directory differing in frame.rs and plan.rs only')
    parser.add_argument('--output-dir', type=Path, required=True, help='New evidence directory; keeps exact source snapshots and logs')
    args = parser.parse_args(argv)
    output_existed = args.output_dir.exists()
    try:
        result = execute(args)
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
        if not output_existed and args.output_dir.is_dir():
            write_json(args.output_dir / 'failure.json', {'status': 'failed', 'error': str(error)})
        parser.exit(1, f'pass submission diagnostic failed: {error}\n')
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

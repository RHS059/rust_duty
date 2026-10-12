#!/usr/bin/env python3
"""Strict same-executable Windows GL/DX12 reload-return comparison.

Requires an already-built combined-feature game and existing source-validated
assets. No build, asset generation, tolerance or telemetry normalization occurs.
A pass covers this replay's exact metadata equality, not pixel binding or M4.
"""

import argparse
from contextlib import contextmanager
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import build_identity
import run_dx12_authored as authored
import run_windows_gl_reference_probe as gl_probe
from verify_capture_telemetry import read_record


FRAME_COUNT = 391
CASE = next(case for case in authored.CASES if case.name == 'reload-return')
ENVIRONMENT = {'GALLIUM_DRIVER': 'llvmpipe', 'LIBGL_ALWAYS_SOFTWARE': 'true'}
REPORT = 'same-platform-return-report.json'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def regular(path):
    path = Path(path)
    require(not path.is_symlink() and path.is_file(), f'missing or symlinked file: {path}')
    return path


def positive_timeout(value, label):
    require(type(value) in (int, float) and value > 0, f'{label} must be finite and positive')
    try:
        require(math.isfinite(value), f'{label} must be finite and positive')
    except OverflowError as error:
        raise ValueError(f'{label} must be finite and positive') from error


def input_hashes(root):
    """Same inventory as asset_evidence, checked again around each native run."""
    files = {}
    for path in sorted((root / 'assets').rglob('*')):
        require(not path.is_symlink(), f'symlinked asset entry: {path}')
        if path.is_file() and path.suffix in ('.vra', '.vrs', '.vrm', '.json', '.cfg'):
            files[path.relative_to(root).as_posix()] = authored.sha256(path)
    files['settings.cfg'] = authored.sha256(regular(root / 'settings.cfg'))
    return files


def capture_command(executable, root, output, backend):
    require(CASE.sequence == 'gameplay-return' and CASE.hz == 60
            and CASE.validator == 'verify_reload_return_capture.py', 'reload-return case contract changed')
    command = authored.game_command(executable, root, output, CASE, root / 'unused-offset.cfg')
    if backend == 'OpenGl':
        command = ['--renderer=gl' if arg == '--renderer=dx12' else arg
                   for arg in command if arg != '--force-fallback-adapter']
    else:
        require(backend == 'Dx12', 'unsupported comparison backend')
    command.append(f'--settings={root / "settings.cfg"}')
    return command


@contextmanager
def runtime_environment():
    old = {name: os.environ.get(name) for name in ENVIRONMENT}
    try:
        os.environ.update(ENVIRONMENT)
        yield
    finally:
        for name, value in old.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def stage_runtime(executable, runtime, manifest, destination):
    regular(manifest)
    require(runtime.is_dir() and not runtime.is_symlink(), 'runtime must be a real directory')
    lock = read_record(manifest)
    require(lock.get('architecture') == 'x86_64' and lock.get('runtime_environment') == ENVIRONMENT,
            'runtime must be pinned x86_64 llvmpipe with the expected process environment')
    entries = lock.get('dlls')
    require(isinstance(entries, list) and bool(entries), 'runtime has no pinned DLL closure')
    names = []
    for row in entries:
        require(isinstance(row, dict) and isinstance(row.get('dll'), str), 'invalid DLL pin')
        name = row['dll']
        require(Path(name).name == name and '/' not in name and '\\' not in name
                and ':' not in name and name.lower().endswith('.dll'), 'unsafe DLL pin path')
        names.append(name)
    require(len({name.casefold() for name in names}) == len(names), 'duplicate runtime DLL pin')
    pinned = gl_probe.validate_runtime(runtime, manifest)
    licenses = {}
    packages = lock.get('packages')
    require(isinstance(packages, list) and bool(packages), 'pinned runtime license packages are required')
    for package in packages:
        require(isinstance(package, dict) and isinstance(package.get('licenses'), list)
                and bool(package['licenses']), 'runtime package is missing pinned licenses')
        for license in package['licenses']:
            require(isinstance(license, dict) and isinstance(license.get('member'), str), 'invalid license pin')
            member = license['member']
            prefix = 'ucrt64/share/licenses/'
            require(member.startswith(prefix), 'license member is outside the pinned license tree')
            relative = member.removeprefix(prefix)
            require(relative and not any(part in ('', '.', '..') for part in relative.split('/'))
                    and '\\' not in relative and ':' not in relative, 'unsafe license pin path')
            name = 'licenses/' + relative
            require(name not in licenses, 'duplicate runtime license pin')
            source = regular(runtime / name)
            require(type(license.get('size')) is int and license['size'] > 0
                    and source.stat().st_size == license['size']
                    and authored.sha256(source) == license.get('sha256'), f'runtime license differs from pin: {name}')
            licenses[name] = license['sha256']
    destination.mkdir(parents=True, exist_ok=False)
    for name in [*names, 'staging-receipt.json']:
        shutil.copyfile(regular(runtime / name), destination / name)
    for name in licenses:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(runtime / name, target)
    shutil.copyfile(executable, destination / 'vector-range.exe')
    copied_manifest = destination / 'runtime-manifest.json'
    shutil.copyfile(manifest, copied_manifest)
    gl_probe.validate_runtime(destination, copied_manifest)
    return {**pinned, 'architecture': lock['architecture'], 'environment': ENVIRONMENT,
            'dll_sha256': {name: authored.sha256(destination / name) for name in names},
            'license_sha256': licenses,
            'staging_receipt_sha256': authored.sha256(destination / 'staging-receipt.json'),
            'loaded_modules_verified': False}


def process_record(logs, command, root):
    for name in ('invocation.json', 'process.json', 'stdout.log', 'stderr.log'):
        regular(logs / name)
    invocation = read_record(logs / 'invocation.json')
    process = read_record(logs / 'process.json')
    require(invocation.get('command') == command and invocation.get('cwd') == str(root),
            'process invocation does not match the requested command/root')
    require(process.get('status') == 'passed' and type(process.get('exit_code')) is int
            and process['exit_code'] == 0 and type(process.get('pid')) is int and process['pid'] > 0,
            'process did not record a clean bounded execution')
    return {'pid': process['pid'], 'status': process['status'], 'exit_code': process['exit_code'],
            'files_sha256': {name: authored.sha256(logs / name)
                             for name in ('invocation.json', 'process.json', 'stdout.log', 'stderr.log')}}


def validate_capture(folder, backend, logs):
    images, finite = authored.sequence_inventory(folder, backend)
    require(len(images) == FRAME_COUNT, f'{backend}: expected exactly {FRAME_COUNT} frames, got {len(images)}')
    adapter = None
    coverage = []
    for image in images:
        metadata = authored.capture_metadata(image, backend)
        current = metadata['adapter']
        if backend == 'OpenGl':
            require(metadata.get('requested') == 'gl' and current.casefold().startswith('llvmpipe'),
                    'GL capture must identify requested gl and actual OpenGl llvmpipe')
        else:
            require(backend == 'Dx12', 'unsupported comparison backend')
        require(adapter is None or adapter == current, 'adapter changed during the capture sequence')
        adapter = current
        timing = read_record(Path(f'{image}.time.json'))
        require(type(timing.get('sampling_hz')) in (int, Decimal) and timing['sampling_hz'] == 60,
                f'{image}: expected the unmodified 60 Hz sample stream')
        coverage.append(authored.verify_png(image, authored.EXTENT, authored.BACKGROUND, 0.01, 8, None)['foreground_coverage'])
    lines = []
    for name in ('stdout.log', 'stderr.log'):
        lines.extend(regular(logs / name).read_text(encoding='utf-8', errors='replace').splitlines())
    identities = [line for line in lines if line.startswith('renderer requested=')]
    requested = 'gl' if backend == 'OpenGl' else 'dx12'
    expected = f'renderer requested={requested} backend={backend} adapter={adapter}'
    require(bool(identities) and all(line == expected for line in identities),
            'startup renderer identity differs from the actual capture sidecars')
    compiler = None
    if backend == 'Dx12':
        authored.renderer_logs(logs)
        require(authored.FXC_LOG in (logs / 'stderr.log').read_text(encoding='utf-8', errors='replace').splitlines(),
                'DX12 must record Fxc initialization in stderr')
        compiler = 'Fxc'
    return {'backend': backend, 'adapter': adapter, 'requested': requested, 'frames': len(images),
            'sampling_hz': 60, 'renderer_logs': identities, 'shader_compiler': compiler,
            'finite_json': finite, 'all_images_checked': True,
            'minimum_foreground_coverage': min(coverage)}


def capture_hashes(folder):
    return {path.name: authored.sha256(regular(path)) for path in sorted(folder.iterdir())}


def run(executable, runtime, manifest, root, evidence, timeout=900, run_timeout=2100):
    require(sys.platform == 'win32', 'same-platform return comparison requires native Windows')
    positive_timeout(timeout, 'process timeout')
    positive_timeout(run_timeout, 'run timeout')
    raw_evidence = Path(evidence)
    require(not raw_evidence.exists() and not raw_evidence.is_symlink(), 'refusing existing comparison evidence')
    executable, runtime, manifest, root = map(Path, (executable, runtime, manifest, root))
    regular(executable)
    regular(manifest)
    require(not runtime.is_symlink(), 'runtime must not be a symlink')
    executable, runtime, manifest, root, evidence = [p.resolve() for p in (executable, runtime, manifest, root, raw_evidence)]
    require(root.is_dir() and evidence != root and evidence not in root.parents
            and root / 'assets' not in evidence.parents, 'invalid root or evidence location')
    regular(root / 'settings.cfg')
    regular(root / 'assets/animations.cfg')
    validator = regular(root / 'tools/verify_reload_return_capture.py')
    with executable.open('rb') as stream:
        require(stream.read(2) == b'MZ', 'expected a Windows game executable')
    context = build_identity.context()
    source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True, timeout=10).strip()
    require(source_commit == context['source']['commit'], 'checked-out source differs from workflow revision')
    evidence.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    summary = evidence / REPORT
    report = {'schema': 'rust-duty-windows-same-platform-return/v1', 'passed': False,
              'status': 'running', 'current_check': None, 'native_execution': False,
              'source': context['source'], 'display_version': context['display_version'],
              'executable_sha256': authored.sha256(executable), 'settings_sha256': authored.sha256(root / 'settings.cfg'),
              'validator_sha256': authored.sha256(validator), 'process_timeout_seconds': timeout,
              'run_timeout_seconds': run_timeout, 'checks': [], 'captures': {},
              'acceptance_complete': False, 'pixel_binding_proven': False,
              'loaded_modules_verified': False,
              'scope': 'Exact 391-frame same-executable Windows GL/DX12 gameplay-return replay. No field exclusions or numeric tolerance beyond the existing renderer-identity exception. Pixel binding, loaded DLL/CRT attestation, human visuals and M4 acceptance remain open.'}
    authored.write_json(summary, report)

    def remaining():
        left = run_timeout - (time.monotonic() - started)
        require(left > 0, 'whole-run comparison budget exhausted')
        return left

    def check(name, action):
        report['current_check'] = name
        authored.write_json(summary, report)
        began = time.monotonic()
        try:
            remaining()
            value = action()
            remaining()
            report['checks'].append({'name': name, 'passed': True, 'elapsed_seconds': time.monotonic() - began})
        except BaseException as error:
            report['checks'].append({'name': name, 'passed': False, 'error': f'{type(error).__name__}: {error}',
                                     'elapsed_seconds': time.monotonic() - began})
            report.update(status='failed' if isinstance(error, Exception) else 'interrupted', passed=False)
            authored.write_json(summary, report)
            raise
        report['current_check'] = None
        authored.write_json(summary, report)
        return value

    def execute(command, logs, renderer=False):
        authored.execute(command, root, logs, min(timeout, remaining()), renderer=renderer)
        return process_record(logs, command, root)

    staged = evidence / 'runtime'
    local_executable = staged / 'vector-range.exe'
    try:
        assets = check('source-validated-companions', lambda: authored.asset_evidence(root))
        report['assets'] = assets
        expected_inputs = assets['runtime_and_manifest_sha256']
        require(input_hashes(root) == expected_inputs, 'asset snapshot changed during validation')
        report['runtime'] = check('pinned-app-local-runtime', lambda: stage_runtime(executable, runtime, manifest, staged))
        expected_executable = report['executable_sha256']

        def unchanged_inputs():
            require(authored.sha256(regular(executable)) == expected_executable
                    and authored.sha256(regular(local_executable)) == expected_executable, 'combined executable changed')
            require(input_hashes(root) == expected_inputs, 'assets/settings changed between comparison stages')
            require(authored.sha256(regular(validator)) == report['validator_sha256'], 'reload-return validator changed')
            require(authored.sha256(regular(manifest)) == report['runtime']['manifest_sha256'], 'runtime manifest changed')
            gl_probe.validate_runtime(staged, staged / 'runtime-manifest.json')
            require(authored.sha256(staged / 'runtime-manifest.json') == report['runtime']['manifest_sha256'], 'staged runtime manifest changed')
            for name, expected in report['runtime']['license_sha256'].items():
                require(authored.sha256(regular(staged / name)) == expected, 'staged runtime license changed')

        check('staged-input-identity', unchanged_inputs)
        (evidence / 'captures').mkdir()
        with runtime_environment():
            for flag, expected in (('--build-version', context['version']), ('--build-label', context['display_version'])):
                logs = evidence / 'logs' / flag.removeprefix('--')
                def embedded_identity(flag=flag, expected=expected, logs=logs):
                    execute([str(local_executable), flag], logs)
                    require((logs / 'stdout.log').read_text(encoding='utf-8').strip() == expected,
                            f'combined executable {flag} disagrees with this source/build')
                check(flag.removeprefix('--'), embedded_identity)
            for name, backend in (('gl', 'OpenGl'), ('dx12', 'Dx12')):
                folder = evidence / 'captures' / name
                logs = evidence / 'logs' / name
                command = capture_command(local_executable, root, folder, backend)
                check(f'{name}/unchanged-inputs', unchanged_inputs)
                binding = {'command': command, 'cwd': str(root), 'source': context['source'],
                           'executable_sha256': expected_executable, 'settings_sha256': report['settings_sha256'],
                           'asset_hashes': expected_inputs, 'environment': ENVIRONMENT}
                authored.write_json(evidence / f'{name}-capture-binding.json', binding)
                report['captures'][name] = {'command': command, 'backend': backend, 'passed': False}
                process = check(f'{name}/capture', lambda command=command, logs=logs, backend=backend:
                                execute(command, logs, renderer=backend == 'Dx12'))
                report['native_execution'] = True
                validated = check(f'{name}/all-images-and-identity', lambda: validate_capture(folder, backend, logs))
                verification_logs = evidence / 'logs' / f'{name}-validator'
                check(f'{name}/unchanged-return-validator', lambda: execute(
                    [sys.executable, str(validator), str(folder)], verification_logs))
                verdict = authored.successful_report(regular(folder / 'verification.json'), list(folder.glob('*.png')))
                require(verdict.get('schema') == 'rust-duty-reload-return-capture/v2'
                        and type(verdict.get('frames')) is int and verdict['frames'] == FRAME_COUNT,
                        'reload-return verdict has wrong schema or frame count')
                report['captures'][name].update(validated, process=process, passed=True,
                                                 files_sha256=capture_hashes(folder))
                check(f'{name}/retained-input-identity', unchanged_inputs)
        report['parity'] = check('strict-all-field-parity', lambda: authored.compare_sequence(
            evidence / 'captures/gl', evidence / 'captures/dx12'))
        for name in ('gl', 'dx12'):
            require(capture_hashes(evidence / 'captures' / name) == report['captures'][name]['files_sha256'],
                    f'{name} capture evidence changed during comparison')
        check('final-input-identity', unchanged_inputs)
        report.update(passed=True, status='passed')
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
        report.update(passed=False, status='failed', error=f'{type(error).__name__}: {error}')
    finally:
        report['native_processes'] = {}
        for name in ('gl', 'dx12'):
            process_path = evidence / 'logs' / name / 'process.json'
            if process_path.is_file() and not process_path.is_symlink():
                try:
                    state = read_record(process_path)
                    pid = state.get('pid')
                    started_process = type(pid) is int and pid > 0
                    report['native_processes'][name] = {'pid': pid, 'status': state.get('status'),
                                                        'exit_code': state.get('exit_code'), 'started': started_process}
                    report['native_execution'] |= started_process
                except ValueError as error:
                    report['native_processes'][name] = {'error': str(error)}
        report['elapsed_seconds'] = time.monotonic() - started
        authored.write_json(summary, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('executable', 'runtime', 'manifest', 'root', 'evidence'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=900)
    parser.add_argument('--run-timeout', type=float, default=2100)
    args = parser.parse_args(argv)
    try:
        report = run(**vars(args))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'Windows return comparison failed: {error}', file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run one complete Windows legacy/DX12 authored pair, never a shortened replay."""

import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import time

import dx12_authored_shards as shared
import run_dx12_authored as authored
from run_windows_same_platform_return import runtime_environment
from verify_capture_telemetry import read_record, validate
from verify_render_capture import verify as verify_png


ROLES = ('windows-legacy', 'dx12')
LEGACY_TIMEOUT = 900
VALIDATOR_TIMEOUT = 900
STOCK_TIMEOUT = 120


def require(condition, message):
    if not condition:
        raise ValueError(message)


def windows_only():
    require(sys.platform == 'win32', 'authored native shards require Windows')


def positive(value, label):
    require(type(value) in (int, float) and math.isfinite(value) and value > 0,
            f'{label} must be finite and positive')


def legacy_renderer_logs(logs):
    lines = []
    for name in ('stdout.log', 'stderr.log'):
        lines += (Path(logs) / name).read_text(encoding='utf-8', errors='replace').splitlines()
    identities = [line for line in lines if line.startswith('renderer requested=')]
    adapters = []
    for line in identities:
        match = re.fullmatch(r'renderer requested=gl backend=OpenGl adapter=(.+)', line)
        require(match is not None and bool(match.group(1).strip()),
                f'expected actual explicit legacy OpenGl identity, got {line!r}')
        adapters.append(match.group(1))
    require(adapters and len(set(adapters)) == 1,
            'legacy capture needs one consistent nonblank actual OpenGl adapter')
    require(adapters[0].casefold().startswith('llvmpipe'), 'app-local GL must actually report llvmpipe')
    return {'renderer': identities, 'adapter': adapters[0]}


def role_command(executable, root, folder, case, offset, role):
    require(role in ROLES, 'unknown capture role')
    command = authored.game_command(executable, root, folder, case, offset)
    if role == 'windows-legacy':
        command = ['--renderer=gl' if argument == '--renderer=dx12' else argument
                   for argument in command if argument != '--force-fallback-adapter']
    return command


def validate_role_images(folder, role, expected_frames):
    require(role in ROLES, 'unknown capture role')
    require(type(expected_frames) is int and expected_frames > 0, 'invalid expected frame count')
    backend, requested = ('OpenGl', 'gl') if role == 'windows-legacy' else ('Dx12', 'dx12')
    images, finite = authored.sequence_inventory(Path(folder), backend)
    require(len(images) == expected_frames,
            f'{role}: expected all {expected_frames} frames, got {len(images)}')
    adapters, coverage = set(), []
    for path in images:
        metadata = authored.capture_metadata(path, backend)
        require(metadata.get('requested') == requested, f'{path}: wrong requested renderer')
        adapters.add(metadata['adapter'])
        coverage.append(verify_png(path, authored.EXTENT, authored.BACKGROUND, 0.01, 8, None)['foreground_coverage'])
    require(len(adapters) == 1, f'{role}: capture adapters differ')
    if role == 'windows-legacy':
        require(next(iter(adapters)).casefold().startswith('llvmpipe'), 'authored GL capture must actually use llvmpipe')
    return {'frames': len(images), 'finite_json': finite, 'all_images_checked': True,
            'adapter': next(iter(adapters)), 'minimum_foreground_coverage': min(coverage)}


def validate_stock_probe(folder, expected_adapter=None):
    # Historical check/path name retained for artifact compatibility. This now
    # probes the pinned app-local Mesa reference, never an assumed stock driver.
    folder = Path(folder)
    image = folder / 'stock-gl.png'
    validate(folder, expected_backend='OpenGl')
    metadata = authored.capture_metadata(image, 'OpenGl')
    require(metadata.get('requested') == 'gl', 'reference probe must explicitly request gl')
    require(metadata['adapter'].casefold().startswith('llvmpipe'), 'reference probe must actually use llvmpipe')
    if expected_adapter is not None:
        require(metadata['adapter'] == expected_adapter, 'stock OpenGl log and sidecar adapters differ')
    require((metadata['width'], metadata['height']) == authored.EXTENT, 'stock capture extent differs')
    return {'adapter': metadata['adapter'],
            'image': verify_png(image, authored.EXTENT, authored.BACKGROUND, 0.01, 8, None)}


def historical_manifest(folder):
    """Receipt after workflow-owned exact current-run/attempt artifact downloads."""
    folder = Path(folder)
    for case in authored.CASES:
        images, _ = authored.sequence_inventory(folder / case.baseline, 'OpenGl')
        require(len(images) == shared.PROFILES[case.name]['expected_frames'],
                f'historical {case.name}: incomplete baseline frame count')
        authored.baseline_verdicts(folder / case.baseline, images)
    return {'schema': 'rust-duty-dx12-authored-historical/v1', **shared.context(),
            'files': shared.inventory_files(folder, exclude=())}


def prepare(executable, fixture, root, legacy_linux, evidence):
    windows_only()
    evidence = Path(evidence).absolute()
    require(not evidence.is_symlink() and not evidence.exists(), 'refusing existing preparation evidence')
    evidence = evidence.resolve()
    evidence.mkdir(parents=True)
    try:
        manifest = shared.make_input_manifest(executable, fixture, root)
        historical = historical_manifest(legacy_linux)
        authored.write_json(evidence / 'input-manifest.json', manifest)
        authored.write_json(evidence / 'historical-manifest.json', historical)
        return manifest
    except BaseException as error:
        authored.write_json(evidence / 'failure.json', {'passed': False, 'error': f'{type(error).__name__}: {error}'})
        raise


def required_checks(scenario):
    if scenario == 'lighting-orientation':
        names = ['validated-inputs', 'orientation-renderer-contract']
        names += [f'lighting/{stem}' for stem, _ in authored.lighting_commands(Path('game'), Path('.'), Path('lighting'))]
        return names + ['lighting-existing-validator-and-images', 'inputs-unchanged']
    names = ['validated-inputs', 'windows-legacy/stock-probe']
    names += [f'{role}/{stage}' for role in ROLES for stage in ('capture', 'finite-images', 'existing-validator')]
    names += ['layered-pair-deferred-to-aggregate' if scenario.startswith('layered-') else 'same-windows-strict-parity']
    return names + ['inputs-unchanged']


class Journal:
    def __init__(self, evidence, report):
        self.evidence, self.report = evidence, report
        self.started = time.monotonic()
        self.save()

    def remaining(self):
        return self.report['run_timeout_seconds'] - (time.monotonic() - self.started)

    def save(self):
        self.report['elapsed_seconds'] = round(time.monotonic() - self.started, 6)
        authored.write_json(self.evidence / 'summary.json', self.report)

    def check(self, name, action, *, ready=True):
        started = time.monotonic()
        self.report['current_check'] = name
        self.save()
        print(f'[{name}] running', flush=True)
        try:
            require(ready, 'blocked by a failed required capture or input check')
            if self.remaining() <= 0:
                self.report['budget_exhausted'] = True
                raise RuntimeError('whole-shard deadline exhausted; check not attempted')
            result = action()
            require(self.remaining() > 0, 'check completed after whole-shard deadline')
            row = {'name': name, 'passed': True, 'result': result}
        except Exception as error:
            row = {'name': name, 'passed': False, 'error': f'{type(error).__name__}: {error}'}
        except BaseException as error:
            self.report['checks'].append({'name': name, 'passed': False,
                                         'error': f'{type(error).__name__}: {error}',
                                         'elapsed_seconds': round(time.monotonic() - started, 6)})
            self.report['status'] = 'interrupted'
            self.save()
            raise
        if self.remaining() <= 0:
            self.report['budget_exhausted'] = True
        row['elapsed_seconds'] = round(time.monotonic() - started, 6)
        self.report['checks'].append(row)
        self.report['current_check'] = None
        self.save()
        print(f'[{name}] {"passed" if row["passed"] else row["error"]}', flush=True)
        return row

    def execute(self, command, root, logs, timeout, *, renderer=False):
        remaining = self.remaining()
        require(remaining > 0, 'whole-shard deadline exhausted before process launch')
        return authored.execute(command, root, logs, min(timeout, remaining), renderer=renderer)


def run_shard(executable, fixture, root, evidence, input_manifest, scenario, *,
              capture_timeout=None, run_timeout=None):
    windows_only()
    require(scenario in shared.PROFILES, 'unknown scenario')
    profile = shared.PROFILES[scenario]
    capture_timeout = profile['capture_timeout_seconds'] if capture_timeout is None else capture_timeout
    run_timeout = profile['run_timeout_seconds'] if run_timeout is None else run_timeout
    positive(capture_timeout, 'capture timeout')
    positive(run_timeout, 'run timeout')
    require(not Path(evidence).is_symlink(), 'refusing existing shard evidence symlink')
    executable, fixture, root, evidence = [Path(path).resolve() for path in (executable, fixture, root, evidence)]
    require(root.is_dir(), 'working directory missing')
    require(not evidence.exists(), 'refusing existing shard evidence')
    host = {'runner_name': os.environ.get('RUNNER_NAME'), 'runner_os': os.environ.get('RUNNER_OS'),
            'runner_arch': os.environ.get('RUNNER_ARCH')}
    require(host['runner_os'] == 'Windows' and all(type(v) is str and v.strip() for v in host.values()),
            'native shard requires actual Windows runner identity')
    evidence.mkdir(parents=True)
    report = {'schema': 'rust-duty-dx12-authored-shard/v1', 'scenario': scenario,
              'binding': {}, 'platform': 'win32', 'host': host,
              'status': 'running', 'passed': False, 'acceptance_complete': False,
              'automated_landmark_gate': 'open', 'current_check': None, 'elapsed_seconds': 0.0,
              'run_timeout_seconds': run_timeout, 'budget_exhausted': False, 'checks': [],
              'capture_paths': shared.capture_paths(scenario), 'files': {},
              'gl_reference': None, 'gl_runtime_path': 'gl-runtime',
              'app_local_executable': str(evidence / 'gl-runtime/vector-range.exe')}
    journal = Journal(evidence, report)
    manifest = None
    try:
        def validate_inputs():
            nonlocal manifest
            manifest = read_record(Path(input_manifest)) if not isinstance(input_manifest, dict) else input_manifest
            binding = shared.verify_input_manifest(manifest, executable, fixture, root)
            report['binding'] = binding
            report['gl_reference'] = manifest['gl_reference']
            source = root / shared.GL_RUNTIME_PATH
            destination = evidence / 'gl-runtime'
            shutil.copytree(source, destination)
            shutil.copyfile(executable, destination / 'vector-range.exe')
            shared.verify_gl_reference(destination, manifest['gl_reference'], game_sha256=binding['executable_sha256'])
            return binding

        inputs = journal.check('validated-inputs', validate_inputs)
        if inputs['passed']:
            # Scoped process environment only; no installed driver, registry or
            # system graphics changes. Both roles use the identical copied exe.
            with runtime_environment():
                local_executable = evidence / 'gl-runtime/vector-range.exe'
                if scenario == 'lighting-orientation':
                    run_auxiliary(journal, local_executable, fixture, root, capture_timeout)
                else:
                    run_pair(journal, local_executable, root, scenario, capture_timeout)
        else:
            for name in required_checks(scenario)[1:-1]:
                journal.check(name, lambda: None, ready=False)
        def unchanged():
            binding = shared.verify_input_manifest(manifest, executable, fixture, root)
            shared.verify_gl_reference(evidence / 'gl-runtime', manifest['gl_reference'], game_sha256=binding['executable_sha256'])
            return binding
        journal.check('inputs-unchanged', unchanged, ready=inputs['passed'])
        require([row['name'] for row in report['checks']] == required_checks(scenario),
                'internal shard check inventory differs')
        report['passed'] = not report['budget_exhausted'] and all(row['passed'] is True for row in report['checks'])
        report['status'] = 'passed' if report['passed'] else 'failed'
    except BaseException as error:
        report['passed'] = False
        report['status'] = 'failed' if isinstance(error, Exception) else 'interrupted'
        report['fatal_error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        try:
            report['files'] = shared.inventory_files(evidence)
        except Exception as error:
            report.update(passed=False, status='failed', fatal_error=f'inventory seal failed: {error}')
        if journal.remaining() <= 0:
            report.update(passed=False, status='failed', budget_exhausted=True)
        journal.save()
    return report


def run_pair(journal, executable, root, scenario, capture_timeout):
    evidence, report = journal.evidence, journal.report
    case = next(case for case in authored.CASES if case.name == scenario)
    offset = evidence / 'ads-offset.cfg'
    offset.write_text((root / 'settings.cfg').read_text(encoding='utf-8')
                      + '\nviewmodel_x = 0.20\nviewmodel_y = -0.20\nviewmodel_z = 0.20\n', encoding='utf-8')
    logs = evidence / 'logs'

    def stock_probe():
        folder = evidence / 'stock-gl'
        folder.mkdir()
        image = folder / 'stock-gl.png'
        command = [str(executable), '--renderer=gl', '--no-update', '--procedural-weapon',
                   '--reference-viewport', '--capture', f'--output={image}']
        process = logs / 'windows-legacy-stock-probe'
        journal.execute(command, root, process, STOCK_TIMEOUT)
        identity = legacy_renderer_logs(process)
        return {'identity': identity, **validate_stock_probe(folder, identity['adapter'])}

    stock = journal.check('windows-legacy/stock-probe', stock_probe)
    successes = {}
    for role in ROLES:
        folder = evidence / report['capture_paths'][role]
        process_logs = logs / f'{role}-capture'
        command = role_command(executable, root, folder, case, offset, role)

        def capture(role=role, command=command, process_logs=process_logs):
            result = journal.execute(command, root, process_logs,
                                     LEGACY_TIMEOUT if role == 'windows-legacy' else capture_timeout,
                                     renderer=role == 'dx12')
            return {**result, **legacy_renderer_logs(process_logs)} if role == 'windows-legacy' else result

        captured = journal.check(f'{role}/capture', capture, ready=role != 'windows-legacy' or stock['passed'])

        def images(role=role, folder=folder, process_logs=process_logs):
            result = validate_role_images(folder, role, shared.PROFILES[scenario]['expected_frames'])
            if role == 'windows-legacy':
                require(result['adapter'] == legacy_renderer_logs(process_logs)['adapter'],
                        'legacy log and capture adapters differ')
            return result

        finite = journal.check(f'{role}/finite-images', images, ready=captured['passed'])
        validator = case.validator or 'verify_layered_locomotion_capture.py'
        checked = journal.check(f'{role}/existing-validator',
            lambda folder=folder, role=role, validator=validator: journal.execute(
                [sys.executable, str(root / 'tools' / validator), str(folder)], root,
                logs / f'{role}-validator', VALIDATOR_TIMEOUT), ready=captured['passed'] and finite['passed'])
        successes[role] = captured['passed'] and finite['passed'] and checked['passed']
    if scenario.startswith('layered-'):
        journal.check('layered-pair-deferred-to-aggregate', lambda: {'rates': ['layered-30', 'layered-60']},
                      ready=all(successes.values()))
    else:
        journal.check('same-windows-strict-parity', lambda: authored.compare_sequence(
            evidence / report['capture_paths']['windows-legacy'], evidence / report['capture_paths']['dx12']),
            ready=all(successes.values()))


def run_auxiliary(journal, executable, fixture, root, timeout):
    evidence = journal.evidence
    logs = evidence / 'logs'

    def orientation():
        folder = evidence / 'renderer-contract'
        identity = journal.execute([str(fixture), '--renderer=dx12', '--force-fallback-adapter',
                                    f'--output-dir={folder}'], root, logs / 'renderer-contract', timeout, renderer=True)
        return {'logs': identity, **authored.validate_orientation(folder)}

    journal.check('orientation-renderer-contract', orientation)
    lighting = evidence / 'captures/dx12/lighting'
    lighting.mkdir(parents=True)
    complete = True
    for stem, command in authored.lighting_commands(executable, root, lighting):
        row = journal.check(f'lighting/{stem}', lambda command=command, stem=stem:
                            journal.execute(command, root, logs / f'lighting-{stem}', timeout, renderer=True))
        complete = complete and row['passed']
    journal.check('lighting-existing-validator-and-images', lambda: authored.validate_lighting(lighting), ready=complete)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare_parser = commands.add_parser('prepare')
    run_parser = commands.add_parser('run')
    for command in (prepare_parser, run_parser):
        command.add_argument('--executable', type=Path, required=True)
        command.add_argument('--renderer-contract', type=Path, required=True)
        command.add_argument('--root', type=Path, default=Path.cwd())
        command.add_argument('--evidence', type=Path, required=True)
    prepare_parser.add_argument('--legacy-linux', type=Path, required=True)
    run_parser.add_argument('--input-manifest', type=Path, required=True)
    run_parser.add_argument('--scenario', choices=shared.SCENARIOS, required=True)
    run_parser.add_argument('--timeout', type=float)
    run_parser.add_argument('--run-timeout', type=float)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            result = prepare(args.executable, args.renderer_contract, args.root, args.legacy_linux, args.evidence)
            passed = True
        else:
            result = run_shard(args.executable, args.renderer_contract, args.root, args.evidence,
                               args.input_manifest, args.scenario, capture_timeout=args.timeout,
                               run_timeout=args.run_timeout)
            passed = result['passed']
    except (OSError, ValueError, RuntimeError) as error:
        print(f'Authored shard failed: {error}', file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())

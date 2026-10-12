#!/usr/bin/env python3
"""Independent Windows GL/DX12 authored capture shards and mandatory aggregation.

capture --case NAME --executable GAME --renderer-contract FIXTURE --runtime MESA
        --manifest LOCK --root ROOT --evidence NEW [--timeout 2400 --run-timeout 7200]
aggregate --input NAME=SHARD_DIR (exactly eight replay cases plus auxiliary)
          --root ROOT --evidence NEW [--timeout 900 --run-timeout 7200]

Schedule at most four capture jobs concurrently in CI. Each replay shard runs
both backends sequentially using one unchanged game binary. Auxiliary captures
12 lighting poses per backend and the separate DX12-only renderer_contract
executable. Aggregate accepts no incomplete case set and reruns every original
validator, including both cross-case gates. No build, asset generation, numeric
normalization, tolerance change, GPU emulation, or native execution on Linux.
A capture-stage pass is not a suite pass. Human/pixel-landmark/M4 acceptance
always remains open, even after all automated matrix gates pass.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
import os
from pathlib import Path, PureWindowsPath
import platform
import shutil
import subprocess
import sys
import time

import build_identity
import run_dx12_authored as authored
import run_windows_same_platform_return as pair
from revalidate_reused_companions import no_links, relative_path
from verify_capture_telemetry import _compare, read_record

COUNTS = dict(zip((case.name for case in authored.CASES), (403, 214, 223, 553, 553, 337, 673, 391)))
CASE_CONTRACT = (
    ('jump-gameplay', 'gameplay-jump', 60, 'verify_jump_capture.py'),
    ('reload-gameplay', 'gameplay-reload', None, 'verify_gameplay_capture.py'),
    ('walk-gameplay', 'gameplay-walk', None, 'verify_gameplay_walk_capture.py'),
    ('ads-gameplay', 'gameplay-ads', None, 'verify_gameplay_ads_capture.py'),
    ('ads-offset', 'gameplay-ads', None, 'verify_gameplay_ads_capture.py'),
    ('layered-30', 'gameplay-layered', 30, None),
    ('layered-60', 'gameplay-layered', 60, None),
    ('reload-return', 'gameplay-return', 60, 'verify_reload_return_capture.py'))
CASES = {case.name: case for case in authored.CASES}
INPUTS = (*COUNTS, 'auxiliary')
BACKENDS = {'gl': 'OpenGl', 'dx12': 'Dx12'}
REPORT = 'authored-matrix-report.json'
SCHEMA = 'rust-duty-windows-authored-matrix/v1'
OFFSET = '\nviewmodel_x = 0.20\nviewmodel_y = -0.20\nviewmodel_z = 0.20\n'
REQUIRED_TOOLS = {
    'run_windows_authored_matrix.py', 'run_windows_same_platform_return.py',
    'run_dx12_authored.py', 'run_windows_gl_reference_probe.py', 'revalidate_reused_companions.py',
    'verify_capture_telemetry.py', 'verify_render_capture.py', 'verify_lighting_capture.py',
    'verify_layered_locomotion_capture.py', 'verify_ads_placement_capture.py',
    *(case.validator for case in authored.CASES if case.validator)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def contract():
    require(tuple((c.name, c.sequence, c.hz, c.validator) for c in authored.CASES) == CASE_CONTRACT,
            'original authored case contract changed; review matrix counts and gates')
    require(sum(COUNTS.values()) == 3347 and len(COUNTS) == 8, 'incomplete replay matrix')
    require(authored.lighting.VIEWS == [('front', -90, 0), ('right', 0, 0), ('back', 90, 0),
                                       ('left', 180, 0), ('up', -90, 35), ('down', -90, -35)],
            'original lighting view contract changed')
    require(authored.EXTENT == (960, 540) and authored.RENDERER_IDENTITY == {'backend', 'adapter', 'requested'},
            'reference extent or exact primary-metadata exception changed')


def hashes(folder, *, omit_verdict=False):
    folder = no_links(folder)
    result = {}
    for path in sorted(folder.rglob('*')):
        no_links(path, file=not path.is_dir())
        if path.is_file() and not (omit_verdict and path.name == 'verification.json'):
            result[path.relative_to(folder).as_posix()] = authored.sha256(path)
    return result


def payload_hashes(evidence):
    result = {}
    for name in ('captures', 'logs', 'renderer-contract'):
        folder = evidence / name
        if folder.exists():
            result.update({f'{name}/{p}': value for p, value in hashes(folder).items()})
    for name in ('ads-offset.cfg',):
        if (evidence / name).exists():
            result[name] = authored.sha256(no_links(evidence / name, file=True))
    return result


def tool_hashes(root):
    paths = sorted((root / 'tools').glob('*.py'))
    require(REQUIRED_TOOLS <= {p.name for p in paths}, 'missing current validator/helper code')
    return {p.name: authored.sha256(no_links(p, file=True)) for p in paths}


def platform_identity():
    return {'sys_platform': sys.platform, 'os_name': os.name, 'machine': platform.machine(),
            'windows_version': platform.version(),
            'runner_image': {k: os.environ.get(k) for k in ('RUNNER_OS', 'RUNNER_ARCH', 'ImageOS', 'ImageVersion')}}


def switch_backend(command, backend):
    require(backend in BACKENDS.values(), 'unknown backend')
    if backend == 'OpenGl':
        return ['--renderer=gl' if item == '--renderer=dx12' else item
                for item in command if item != '--force-fallback-adapter']
    return list(command)


def capture_command(executable, root, folder, case, offset, backend):
    command = authored.game_command(executable, root, folder, case, offset)
    if case.name != 'ads-offset':
        command.append(f'--settings={root / "settings.cfg"}')
    return switch_backend(command, backend)


def renderer_identity(logs, backend, adapter):
    requested = 'gl' if backend == 'OpenGl' else 'dx12'
    if backend == 'OpenGl':
        require(isinstance(adapter, str) and adapter.casefold().startswith('llvmpipe'), 'GL must actually use llvmpipe')
    else:
        authored.renderer_logs(logs)
    lines = []
    for name in ('stdout.log', 'stderr.log'):
        lines += no_links(logs / name, file=True).read_text(encoding='utf-8', errors='replace').splitlines()
    actual = [line for line in lines if line.startswith('renderer requested=')]
    require(actual and all(line == f'renderer requested={requested} backend={backend} adapter={adapter}' for line in actual),
            'startup identity differs from actual capture sidecars')
    return actual


def validate_sequence(folder, case, backend, logs):
    images, finite = authored.sequence_inventory(folder, backend)
    require(len(images) == COUNTS[case.name], f'{case.name}: expected exactly {COUNTS[case.name]} frames')
    adapter, coverage = None, []
    for image in images:
        metadata = authored.capture_metadata(image, backend)
        require(metadata.get('requested') == ('gl' if backend == 'OpenGl' else 'dx12'), 'wrong requested renderer')
        require(adapter is None or adapter == metadata['adapter'], 'adapter changed within replay')
        adapter = metadata['adapter']
        rate = read_record(Path(f'{image}.time.json')).get('sampling_hz')
        require(type(rate) in (int, Decimal), 'sampling_hz must retain a finite numeric type')
        if case.hz is not None:
            require(rate == case.hz, 'explicit capture sample rate changed')
        # Default cadence is proven by the unchanged command (no --capture-hz)
        # and exact time-sidecar parity, not a newly rounded rate constant.
        coverage.append(authored.verify_png(image, authored.EXTENT, authored.BACKGROUND, 0.01, 8, None)['foreground_coverage'])
    identities = renderer_identity(logs, backend, adapter)
    return {'frames': len(images), 'backend': backend, 'adapter': adapter, 'finite_json': finite,
            'renderer_logs': identities, 'all_images_checked': True, 'minimum_foreground_coverage': min(coverage)}


def exact_sequence(gl, dx12):
    images, _ = authored.sequence_inventory(gl, 'OpenGl')
    authored.sequence_inventory(dx12, 'Dx12')
    result = authored.compare(gl, dx12)
    result['capture_metadata_files'] = authored.compare_capture_metadata(gl, dx12, images)
    return result


def lighting_stems():
    return [f'{pose}_{name}' for pose in ('ready', 'reload') for name, _, _ in authored.lighting.VIEWS]


def validate_lighting(folder, backend, logs):
    raw = {stem + suffix for stem in lighting_stems()
           for suffix in ('.png', '.png.json', '.png.world.png', '.png.world.png.json', '.png.lighting.json')}
    actual = {p.name for p in folder.iterdir()}
    require(actual in (raw, raw | {'verification.json'}), 'lighting inventory missing or unexpected')
    finite = authored.validate(folder, expected_backend=backend)
    adapter = None
    for stem in lighting_stems():
        image = folder / f'{stem}.png'
        authored.validate_lighting_record(Path(f'{image}.lighting.json'))
        for png, background, extent in ((image, authored.BACKGROUND, authored.EXTENT),
                                        (Path(f'{image}.world.png'), authored.WORLD_BACKGROUND, None)):
            metadata = authored.capture_metadata(png, backend)
            require(metadata.get('requested') == ('gl' if backend == 'OpenGl' else 'dx12'), 'lighting request mismatch')
            require(adapter is None or adapter == metadata['adapter'], 'lighting adapter changed')
            adapter = metadata['adapter']
            size = (metadata['width'], metadata['height'])
            require(min(size) > 0 and (extent is None or size == extent), 'lighting extent changed')
            authored.verify_png(png, size, background, 0.01, 8, None)
        renderer_identity(logs / f'lighting-{stem}', backend, adapter)
    # This unchanged validator writes only verification.json, which is the sole
    # derived file allowed above. Contact sheets are generated outside raw input.
    result = authored.lighting.verify(folder)
    require(result.get('passed') is True and result.get('frames') == 12, 'lighting verdict incomplete')
    return {'finite_json': finite, 'existing_validator': result, 'viewmodel_images_checked': 12,
            'world_images_checked': 12, 'backend': backend, 'adapter': adapter}


def exact_lighting(gl, dx12):
    for stem in lighting_stems():
        _compare(authored.validate_lighting_record(gl / f'{stem}.png.lighting.json'),
                 authored.validate_lighting_record(dx12 / f'{stem}.png.lighting.json'), f'{stem}/lighting')
        for suffix in ('.png.json', '.png.world.png.json'):
            before, after = read_record(gl / (stem + suffix)), read_record(dx12 / (stem + suffix))
            _compare({k: v for k, v in before.items() if k not in authored.RENDERER_IDENTITY},
                     {k: v for k, v in after.items() if k not in authored.RENDERER_IDENTITY}, stem + suffix)
    return {'passed': True, 'lighting_records': 12, 'capture_metadata_files': 24,
            'excluded_primary_fields': sorted(authored.RENDERER_IDENTITY)}


def orientation_build_identity(folder, context):
    record = read_record(folder / 'renderer-contract-report.json')
    require(record.get('build_version') == context['version']
            and record.get('build_number') == context['build_number'],
            'separate orientation fixture embedded build identity mismatch')
    return authored.validate_orientation(folder)


def verdict(folder):
    report = authored.successful_report(folder / 'verification.json', sorted(folder.glob('*.png')))
    return {'schema': report['schema'], 'passed': True,
            'sha256': authored.sha256(folder / 'verification.json')}


class Session:
    def __init__(self, root, evidence, stage, timeout, run_timeout, case=None):
        pair.positive_timeout(timeout, 'process timeout')
        pair.positive_timeout(run_timeout, 'run timeout')
        self.root = no_links(root)
        self.evidence = Path(os.path.abspath(evidence))
        require(not self.evidence.exists() and not self.evidence.is_symlink(), 'refusing existing evidence')
        require(self.evidence != self.root and self.evidence not in self.root.parents
                and self.root / 'assets' not in self.evidence.parents, 'unsafe evidence location')
        self.evidence.parent.mkdir(parents=True, exist_ok=True)
        no_links(self.evidence.parent)
        self.evidence.mkdir()
        self.started, self.timeout, self.run_timeout = time.monotonic(), timeout, run_timeout
        self.report = {'schema': SCHEMA, 'stage': stage, 'case': case, 'passed': False, 'status': 'running',
                       'automated_matrix_passed': False, 'acceptance_complete': False,
                       'automated_landmark_gate': 'open', 'pixel_binding_proven': False,
                       'loaded_modules_verified': False, 'native_execution': False,
                       'checks': [], 'processes': {}, 'pending_gates': list(INPUTS) if stage == 'aggregate' else ['mandatory-aggregate'],
                       'process_timeout_seconds': timeout, 'run_timeout_seconds': run_timeout,
                       'scope': 'Automated capture/validator/parity stage only; measured landmarks, human review, real-GPU playtest and M4 remain open.'}
        self.save()

    def save(self):
        self.report['elapsed_seconds'] = time.monotonic() - self.started
        authored.write_json(self.evidence / REPORT, self.report)

    def remaining(self):
        value = self.run_timeout - (time.monotonic() - self.started)
        require(value > 0, 'whole-run budget exhausted')
        return value

    def check(self, name, action):
        self.report['current_check'] = name
        self.save()
        began = time.monotonic()
        try:
            self.remaining()
            result = action()
            self.remaining()
        except BaseException as error:
            self.report['checks'].append({'name': name, 'passed': False, 'error': f'{type(error).__name__}: {error}'})
            self.report.update(status='failed' if isinstance(error, Exception) else 'interrupted', error=str(error))
            self.save()
            raise
        self.report['checks'].append({'name': name, 'passed': True, 'elapsed_seconds': time.monotonic() - began})
        self.report['current_check'] = None
        self.save()
        return result

    def execute(self, name, command, *, native=False, dx12=False):
        logs = self.evidence / 'logs' / relative_path(name)
        self.report['processes'][name] = {'command': command, 'cwd': str(self.root),
                                          'logs': logs.relative_to(self.evidence).as_posix(), 'native': native}
        self.save()
        try:
            authored.execute(command, self.root, logs, min(self.timeout, self.remaining()), renderer=dx12)
            return pair.process_record(logs, command, self.root)
        finally:
            state = logs / 'process.json'
            if native and state.is_file():
                pid = read_record(state).get('pid')
                self.report['native_execution'] |= type(pid) is int and pid > 0
            self.save()

    def validator(self, label, filename, folders):
        command = [sys.executable, str(self.root / 'tools' / filename), *(str(p) for p in folders)]
        self.execute(label, command)
        return self.evidence / 'logs' / label / 'stdout.log'


def current_identity(root):
    context = build_identity.context()
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True, timeout=30).strip()
    require(commit == context['source']['commit'], 'checkout differs from current workflow source')
    tracked = ['build.rs', 'build_number.rs', 'Cargo.toml', 'Cargo.lock', 'src', 'examples', 'tools']
    subprocess.check_call(['git', 'diff', '--quiet', '--no-ext-diff', 'HEAD', '--', *tracked], cwd=root, timeout=30)
    extra = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '--', *tracked],
                                    cwd=root, text=True, timeout=30)
    require(not extra.strip(), 'untracked source/helper files invalidate current source binding')
    return context


def capture(case, executable, renderer_contract, runtime, manifest, root, evidence, timeout=2400, run_timeout=7200):
    contract()
    require(sys.platform == 'win32', 'capture requires actual native Windows')
    require(case in INPUTS, 'unknown capture case')
    root = no_links(root)
    executable, renderer_contract, manifest = [no_links(p, file=True) for p in (executable, renderer_contract, manifest)]
    runtime = no_links(runtime)
    for binary in (executable, renderer_contract):
        with binary.open('rb') as stream:
            require(stream.read(2) == b'MZ', 'native Windows executable required')
    session = Session(root, evidence, 'capture', timeout, run_timeout, case)
    report = session.report
    try:
        context = current_identity(root)
        tools = tool_hashes(root)
        assets = session.check('current-source-validated-assets', lambda: authored.asset_evidence(root))
        require(pair.input_hashes(root) == assets['runtime_and_manifest_sha256'], 'asset inventory changed')
        staged = session.evidence / 'runtime'
        runtime_record = session.check('pinned-local-runtime', lambda: pair.stage_runtime(executable, runtime, manifest, staged))
        shutil.copyfile(renderer_contract, staged / 'renderer-contract.exe')
        binding = {'source': context['source'], 'display_version': context['display_version'],
                   'game_executable_sha256': authored.sha256(executable),
                   'renderer_contract_sha256': authored.sha256(renderer_contract),
                   'renderer_contract_role': 'Separate DX12-only fixture; not the GL/DX12 game executable.',
                   'assets': assets['runtime_and_manifest_sha256'], 'tool_sha256': tools,
                   'runtime': runtime_record, 'platform': platform_identity()}
        report['binding'] = binding
        report['execution_root'] = str(root)
        report['execution_evidence'] = str(session.evidence)
        report['python_executable'] = sys.executable
        offset = session.evidence / 'ads-offset.cfg'
        if case == 'ads-offset':
            offset.write_text((root / 'settings.cfg').read_text(encoding='utf-8') + OFFSET, encoding='utf-8')
            report['offset_settings_sha256'] = authored.sha256(offset)
        def unchanged():
            require(pair.input_hashes(root) == binding['assets'] and tool_hashes(root) == tools, 'assets/settings/tools changed')
            require(authored.sha256(executable) == authored.sha256(staged / 'vector-range.exe') == binding['game_executable_sha256'], 'game executable changed')
            require(authored.sha256(renderer_contract) == authored.sha256(staged / 'renderer-contract.exe') == binding['renderer_contract_sha256'], 'orientation fixture changed')
            pair.gl_probe.validate_runtime(staged, staged / 'runtime-manifest.json')
            require(authored.sha256(manifest) == runtime_record['manifest_sha256'], 'runtime manifest changed')
            require(authored.sha256(no_links(staged / 'staging-receipt.json', file=True)) == runtime_record['staging_receipt_sha256'], 'runtime receipt changed')
            for name, expected in runtime_record['license_sha256'].items():
                require(authored.sha256(no_links(staged / name, file=True)) == expected, 'runtime license changed')
            if case == 'ads-offset':
                require(authored.sha256(offset) == report['offset_settings_sha256'], 'offset settings changed')
        with pair.runtime_environment():
            for flag, expected in (('--build-version', context['version']), ('--build-label', context['display_version'])):
                name = flag.removeprefix('--')
                session.check(name, lambda flag=flag, name=name: session.execute(name, [str(staged / 'vector-range.exe'), flag]))
                require((session.evidence / 'logs' / name / 'stdout.log').read_text(encoding='utf-8').strip() == expected, 'embedded game build identity mismatch')
            if case == 'auxiliary':
                folder = session.evidence / 'renderer-contract'
                command = [str(staged / 'renderer-contract.exe'), '--renderer=dx12', '--force-fallback-adapter', f'--output-dir={folder}']
                session.check('orientation/inputs', unchanged)
                session.check('orientation/capture', lambda: session.execute('orientation', command, native=True, dx12=True))
                report['orientation'] = session.check('orientation/validator', lambda: orientation_build_identity(folder, context))
            for label, backend in BACKENDS.items():
                session.check(f'{label}/inputs', unchanged)
                folder = session.evidence / 'captures' / label / ('lighting' if case == 'auxiliary' else case)
                folder.parent.mkdir(parents=True, exist_ok=True)
                if case == 'auxiliary':
                    folder.mkdir()
                    for stem, command in authored.lighting_commands(staged / 'vector-range.exe', root, folder):
                        command = switch_backend(command + [f'--settings={root / "settings.cfg"}'], backend)
                        session.check(f'{label}/{stem}/capture', lambda command=command, stem=stem:
                                      session.execute(f'{label}/lighting-{stem}', command, native=True, dx12=backend == 'Dx12'))
                    value = session.check(f'{label}/lighting-validator', lambda: validate_lighting(folder, backend, session.evidence / 'logs' / label))
                else:
                    selected = CASES[case]
                    command = capture_command(staged / 'vector-range.exe', root, folder, selected, offset, backend)
                    session.check(f'{label}/capture', lambda: session.execute(f'{label}/capture', command, native=True, dx12=backend == 'Dx12'))
                    value = session.check(f'{label}/images', lambda: validate_sequence(folder, selected, backend, session.evidence / 'logs' / label / 'capture'))
                    filename = selected.validator or 'verify_layered_locomotion_capture.py'
                    session.check(f'{label}/individual-validator', lambda: session.validator(f'{label}/validator', filename, [folder]))
                    value['individual_verdict'] = verdict(folder)
                report.setdefault('captures', {})[label] = value
                session.check(f'{label}/retained-inputs', unchanged)
        left, right = [session.evidence / 'captures' / b / ('lighting' if case == 'auxiliary' else case) for b in BACKENDS]
        report['parity'] = session.check('exact-pair-parity', lambda: exact_lighting(left, right) if case == 'auxiliary' else exact_sequence(left, right))
        session.check('final-input-identity', unchanged)
        report['payload_sha256'] = payload_hashes(session.evidence)
        session.remaining()
        report.update(passed=True, status='passed')
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
        report.update(passed=False, status='failed', error=f'{type(error).__name__}: {error}')
    finally:
        session.save()
    return report


def parse_inputs(values):
    result = {}
    for value in values:
        name, separator, folder = value.partition('=')
        require(separator and name in INPUTS and name not in result, 'duplicate/unknown NAME=DIR input')
        result[name] = no_links(Path(folder))
    require(set(result) == set(INPUTS), 'aggregate requires all eight replay cases plus auxiliary')
    require(len(set(result.values())) == len(INPUTS), 'shard inputs must be distinct directories')
    return result


def expected_process_commands(name, record):
    def original_path(value):
        windows = PureWindowsPath(value)
        return windows if windows.is_absolute() else Path(value)
    root, evidence = original_path(record['execution_root']), original_path(record['execution_evidence'])
    require(root.is_absolute() and evidence.is_absolute(), 'original process paths must be absolute')
    game = evidence / 'runtime/vector-range.exe'
    commands = {flag.removeprefix('--'): [str(game), flag] for flag in ('--build-version', '--build-label')}
    if name == 'auxiliary':
        commands['orientation'] = [str(evidence / 'runtime/renderer-contract.exe'), '--renderer=dx12',
                                   '--force-fallback-adapter', f'--output-dir={evidence / "renderer-contract"}']
    for label, backend in BACKENDS.items():
        destination = evidence / 'captures' / label / ('lighting' if name == 'auxiliary' else name)
        if name == 'auxiliary':
            for stem, command in authored.lighting_commands(game, root, destination):
                commands[f'{label}/lighting-{stem}'] = switch_backend(command + [f'--settings={root / "settings.cfg"}'], backend)
        else:
            case = CASES[name]
            commands[f'{label}/capture'] = capture_command(game, root, destination, case, evidence / 'ads-offset.cfg', backend)
            filename = case.validator or 'verify_layered_locomotion_capture.py'
            commands[f'{label}/validator'] = [record['python_executable'], str(root / 'tools' / filename), str(destination)]
    return commands


def validate_offset(folder, record, settings):
    offset = no_links(folder / 'ads-offset.cfg', file=True)
    require(settings is not None and authored.sha256(offset) == record['offset_settings_sha256'], 'offset hash/matching base settings required')
    require(offset.read_text(encoding='utf-8') == settings.read_text(encoding='utf-8') + OFFSET,
            'offset configuration differs from original XYZ contract')


def inspect_shard(name, folder, expected_context, settings=None):
    record = read_record(no_links(folder / REPORT, file=True))
    require(record.get('schema') == SCHEMA and record.get('stage') == 'capture' and record.get('case') == name
            and record.get('passed') is True and record.get('status') == 'passed'
            and record.get('native_execution') is True and record.get('automated_matrix_passed') is False,
            f'{name}: missing successful native capture-stage verdict')
    binding = record['binding']
    _compare(binding['source'], expected_context['source'], f'{name}/source-run-attempt')
    require(binding['platform']['sys_platform'] == 'win32', 'capture is not native Windows')
    require(payload_hashes(folder) == record['payload_sha256'], f'{name}: retained payload differs')
    runtime = folder / 'runtime'
    pair.gl_probe.validate_runtime(runtime, runtime / 'runtime-manifest.json')
    require(authored.sha256(runtime / 'runtime-manifest.json') == binding['runtime']['manifest_sha256'], 'runtime lock changed')
    require(authored.sha256(no_links(runtime / 'staging-receipt.json', file=True)) == binding['runtime']['staging_receipt_sha256'], 'shard runtime receipt changed')
    require(authored.sha256(no_links(runtime / 'vector-range.exe', file=True)) == binding['game_executable_sha256'], 'shard game executable changed')
    require(authored.sha256(no_links(runtime / 'renderer-contract.exe', file=True)) == binding['renderer_contract_sha256'], 'shard orientation fixture changed')
    for path, expected in binding['runtime']['license_sha256'].items():
        require(authored.sha256(no_links(runtime / relative_path(path), file=True)) == expected, 'shard runtime license changed')
    expected_processes = expected_process_commands(name, record)
    require(set(record['processes']) == set(expected_processes), 'missing or unexpected process evidence')
    for key, process in record['processes'].items():
        _compare(process['command'], expected_processes[key], f'{name}/{key}/original-command')
        require(process['logs'] == f'logs/{key}' and process['cwd'] == record['execution_root'], 'process path/root mismatch')
        expected_native = key == 'orientation' or key.endswith('/capture') or '/lighting-' in key
        require(process.get('native') is expected_native, 'native process role mismatch')
        pair.process_record(folder / relative_path(process['logs']), process['command'], Path(process['cwd']))
    for flag, expected in (('build-version', expected_context['version']), ('build-label', expected_context['display_version'])):
        require((folder / 'logs' / flag / 'stdout.log').read_text(encoding='utf-8').strip() == expected,
                'retained embedded game identity mismatch')
    if name == 'ads-offset':
        validate_offset(folder, record, settings)
    if name == 'auxiliary':
        authored.renderer_logs(folder / 'logs/orientation')
    native = [p for p in record['processes'].values() if p.get('native') is True]
    require(len(native) == (25 if name == 'auxiliary' else 2), 'native capture process count incomplete')
    return record


def review_outputs(evidence, root):
    result = authored.review_guides(evidence / 'captures/dx12/ads-gameplay', evidence / 'captures/gl/ads-gameplay',
                                    evidence / 'review/landmarks', root)
    for label in BACKENDS:
        folder = evidence / 'review' / f'lighting-{label}'
        shutil.copytree(evidence / 'captures' / label / 'lighting', folder)
        for pose in ('ready', 'reload'):
            authored.lighting.contact_sheet(folder, pose)
        authored.lighting.contact_sheet(folder, 'ready', '.world.png')
    return result


def aggregate(inputs, root, evidence, timeout=900, run_timeout=7200):
    contract()
    roots = parse_inputs(inputs)
    session = Session(root, evidence, 'aggregate', timeout, run_timeout)
    report = session.report
    try:
        context = current_identity(session.root)
        records = {name: session.check(f'{name}/retained-shard', lambda name=name: inspect_shard(name, roots[name], context, session.root / 'settings.cfg')) for name in INPUTS}
        binding = records[INPUTS[0]]['binding']
        for name in INPUTS:
            _compare(binding, records[name]['binding'], f'{name}/identical-source-binary-runtime-assets-settings-tools-platform')
        require(tool_hashes(session.root) == binding['tool_sha256'], 'aggregate validator/tool code differs from captures')
        assets = session.check('current-source-validated-assets', lambda: authored.asset_evidence(session.root))
        require(pair.input_hashes(session.root) == binding['assets'] == assets['runtime_and_manifest_sha256'], 'aggregate runtime inputs differ')
        report['binding'] = json.loads((roots[INPUTS[0]] / REPORT).read_text(encoding='utf-8'))['binding']
        report['input_report_sha256'] = {name: authored.sha256(roots[name] / REPORT) for name in INPUTS}
        for name in INPUTS:
            for label in BACKENDS:
                source = roots[name] / 'captures' / label / ('lighting' if name == 'auxiliary' else name)
                destination = session.evidence / 'captures' / label / source.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, destination)
                require(hashes(source) == hashes(destination), 'copied capture bytes changed')
        shutil.copytree(roots['auxiliary'] / 'renderer-contract', session.evidence / 'renderer-contract')
        report['orientation'] = session.check('orientation-existing-validator', lambda: orientation_build_identity(session.evidence / 'renderer-contract', context))
        raw_before = hashes(session.evidence / 'captures', omit_verdict=True)
        for label, backend in BACKENDS.items():
            parent = session.evidence / 'captures' / label
            for case in authored.CASES:
                folder = parent / case.name
                session.check(f'{label}/{case.name}/images', lambda case=case, folder=folder:
                              validate_sequence(folder, case, backend, roots[case.name] / 'logs' / label / 'capture'))
                if case.validator:
                    session.check(f'{label}/{case.name}/original-validator', lambda case=case, folder=folder:
                                  session.validator(f'{label}/{case.name}-validator', case.validator, [folder]))
                    verdict(folder)
            stdout = session.check(f'{label}/ads-placement', lambda: session.validator(f'{label}/ads-placement',
                                   'verify_ads_placement_capture.py', [parent / 'ads-gameplay', parent / 'ads-offset']))
            placement = read_record(stdout)
            require(placement.get('schema') == 'rust-duty-ads-placement-capture/v1' and placement.get('passed') is True
                    and placement.get('frames') == COUNTS['ads-offset'], 'ADS placement report incomplete')
            shutil.copyfile(stdout, parent / 'ads-offset-verification.json')
            stdout = session.check(f'{label}/layered-cross-rate', lambda: session.validator(f'{label}/layered-cross-rate',
                                   'verify_layered_locomotion_capture.py', [parent / 'layered-30', parent / 'layered-60']))
            shutil.copyfile(stdout, parent / 'layered-rate-verification.json')
            session.check(f'{label}/layered-verdict-binding', lambda: authored.layered_rate_verdict(parent))
            session.check(f'{label}/lighting-existing-validator', lambda:
                          validate_lighting(parent / 'lighting', backend, roots['auxiliary'] / 'logs' / label))
        report['parity'] = {}
        for case in authored.CASES:
            report['parity'][case.name] = session.check(f'{case.name}/strict-all-field-parity', lambda case=case:
                authored.compare_sequence(session.evidence / 'captures/gl' / case.name, session.evidence / 'captures/dx12' / case.name))
        report['lighting_parity'] = session.check('lighting/strict-all-field-parity', lambda:
            exact_lighting(session.evidence / 'captures/gl/lighting', session.evidence / 'captures/dx12/lighting'))
        # Only grouped verdicts were added outside replay folders; preserve all
        # original rendered images and sidecars, never rewrite captured telemetry.
        raw_after = hashes(session.evidence / 'captures', omit_verdict=True)
        added = {f'{b}/{p}' for b in BACKENDS for p in ('ads-offset-verification.json', 'layered-rate-verification.json')}
        require({k: v for k, v in raw_after.items() if k not in added} == raw_before,
                'validator modified original capture bytes or inventory')
        session.check('landmark-guides-and-lighting-sheets-not-approval', lambda: review_outputs(session.evidence, session.root))
        require(tool_hashes(session.root) == binding['tool_sha256'] and pair.input_hashes(session.root) == binding['assets'], 'aggregate source inputs changed')
        for name in INPUTS:
            require(authored.sha256(roots[name] / REPORT) == report['input_report_sha256'][name]
                    and payload_hashes(roots[name]) == records[name]['payload_sha256'], 'original shard evidence changed')
        session.remaining()
        report.update(passed=True, status='passed', automated_matrix_passed=True, pending_gates=[],
                      frames_per_backend=sum(COUNTS.values()), lighting_poses_per_backend=12,
                      source_capture_native_execution=True)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
        report.update(passed=False, status='failed', error=f'{type(error).__name__}: {error}')
    finally:
        session.save()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='mode', required=True)
    capture_parser = commands.add_parser('capture')
    capture_parser.add_argument('--case', choices=INPUTS, required=True)
    for name in ('executable', 'renderer-contract', 'runtime', 'manifest'):
        capture_parser.add_argument('--' + name, type=Path, required=True)
    aggregate_parser = commands.add_parser('aggregate')
    aggregate_parser.add_argument('--input', dest='inputs', action='append', required=True, metavar='NAME=DIR')
    for child in (capture_parser, aggregate_parser):
        for name in ('root', 'evidence'):
            child.add_argument('--' + name, type=Path, required=True)
        child.add_argument('--timeout', type=float, default=2400 if child is capture_parser else 900)
        child.add_argument('--run-timeout', type=float, default=7200)
    args = vars(parser.parse_args(argv))
    mode = args.pop('mode')
    try:
        report = (capture if mode == 'capture' else aggregate)(**args)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f'Authored matrix rejected: {error}', file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

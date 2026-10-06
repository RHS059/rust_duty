#!/usr/bin/env python3
"""Strict, non-rendering aggregation of nine same-run Windows authored shards.

Incoming artifacts are immutable. Validators run on verified fresh copies, and
historical Linux differences are diagnostics rather than renderer acceptance.
A machine pass leaves measured-landmark, human visual and real-GPU gates open.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
import math
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import sys
import time

import dx12_authored_shards as shards
import run_dx12_authored as authored
import run_dx12_authored_shard as shard_runner
from verify_capture_telemetry import _compare, read_record

SCHEMA = 'rust-duty-dx12-authored-aggregate/v1'
ROLES = ('windows-legacy', 'dx12')
CASES = {case.name: case for case in authored.CASES}
LAYERED = ('layered-30', 'layered-60')


def plain(value):
    """Only reporting values use float conversion; parity remains lossless."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [plain(item) for item in value]
    return value


def number(value, name):
    if type(value) not in (int, float, Decimal) or not math.isfinite(value) or value < 0:
        raise ValueError(f'{name} must be a finite nonnegative number')
    return value


def local_checks(scenario):
    names = ['validated-inputs']
    if scenario in CASES:
        names += ['windows-legacy/stock-probe']
        for role in ROLES:
            names += [f'{role}/{suffix}' for suffix in ('capture', 'finite-images', 'existing-validator')]
        names += ['layered-pair-deferred-to-aggregate' if scenario in LAYERED else 'same-windows-strict-parity']
    else:
        names += ['orientation-renderer-contract']
        names += [f'lighting/{stem}' for stem, _ in authored.lighting_commands(Path('game'), Path('.'), Path('lighting'))]
        names += ['lighting-existing-validator-and-images']
    return names + ['inputs-unchanged']


def validated_manifest(path, root, *, expected_context=None):
    manifest = read_record(path)
    expected = {'schema': 'rust-duty-dx12-authored-inputs/v1', 'platform': 'win32',
                'build_selection': {'default_enabled': False, 'features': ['legacy-macroquad', 'wgpu-runtime']},
                'binding': manifest.get('binding'), 'gl_reference': manifest.get('gl_reference'), 'expected_scenarios': list(shards.SCENARIOS)}
    _compare(manifest, expected, 'input manifest')
    binding = manifest['binding']
    shards.validate_binding(binding, expected_context=expected_context)
    reference = shards.make_gl_reference(root / shards.GL_RUNTIME_PATH, root / shards.GL_LOCK_PATH)
    _compare(manifest['gl_reference'], reference, 'input GL reference')
    if shards.gl_reference_digest(reference) != binding['gl_reference_sha256']:
        raise ValueError('GL reference is not bound to the input manifest')
    # No executable is run here. Its immutable hash is supplied by the build
    # manifest and must agree byte-for-byte in all nine shard bindings.
    for name, field in (('Cargo.toml', 'cargo_manifest_sha256'), ('Cargo.lock', 'cargo_lock_sha256')):
        if shards._read_regular(root / name, canonical_lf=True) != binding[field]:
            raise ValueError(f'{name}: source differs from input manifest')
    # Reuse the shared no-link/no-reparse/regular-file and read-race checks.
    assets = {f'assets/{name}': shards._read_regular(path)
              for name, path in shards._walk_files(root / 'assets')
              if path.suffix in ('.vra', '.vrs', '.vrm', '.json', '.cfg')}
    assets['settings.cfg'] = shards._read_regular(root / 'settings.cfg')
    _compare(assets, binding['runtime_and_manifest_sha256'], 'source runtime/assets')
    return binding


def read_shard(folder, scenario, binding, *, expected_context=None):
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError(f'{scenario}: shard must be a real directory')
    summary_hash = authored.sha256(folder / 'summary.json')
    report = read_record(folder / 'summary.json')
    required = {'schema', 'scenario', 'binding', 'platform', 'host', 'status', 'passed',
                'acceptance_complete', 'automated_landmark_gate', 'current_check', 'elapsed_seconds',
                'run_timeout_seconds', 'budget_exhausted', 'checks', 'capture_paths', 'files',
                'gl_reference', 'gl_runtime_path', 'app_local_executable'}
    if not required <= set(report):
        raise ValueError(f'{scenario}: missing shard summary fields {sorted(required - set(report))}')
    for key, expected in (('schema', 'rust-duty-dx12-authored-shard/v1'), ('scenario', scenario),
                          ('platform', 'win32'), ('acceptance_complete', False),
                          ('automated_landmark_gate', 'open')):
        _compare(report[key], expected, f'{scenario}/{key}')
    shards.validate_binding(report['binding'], expected_context=expected_context)
    shards.compare_binding(binding, report['binding'])
    # Inspect the closed no-link artifact inventory before reading any retained
    # invocation or runtime path from downloaded evidence.
    shards.verify_files(folder, report['files'])
    if report['gl_runtime_path'] != 'gl-runtime':
        raise ValueError('unexpected app-local runtime path')
    reference = shards.verify_gl_reference(folder / 'gl-runtime', report['gl_reference'],
                                           game_sha256=binding['executable_sha256'])
    if shards.gl_reference_digest(reference) != binding['gl_reference_sha256']:
        raise ValueError('shard GL reference differs from prepared input')
    local_executable = report['app_local_executable']
    if (type(local_executable) is not str
            or not (Path(local_executable).is_absolute() or PureWindowsPath(local_executable).is_absolute())
            or not local_executable.replace('\\', '/').endswith('/gl-runtime/vector-range.exe')):
        raise ValueError('missing original app-local executable path')
    game_logs = (['windows-legacy-stock-probe', 'windows-legacy-capture', 'dx12-capture']
                 if scenario in CASES else
                 [f'lighting-{stem}' for stem, _ in authored.lighting_commands(Path('game'), Path('.'), Path('lighting'))])
    for name in game_logs:
        path = folder / 'logs' / name / 'invocation.json'
        # Missing logs remain a per-role failure below, preserving independent
        # valid DX12 evidence when an earlier GL probe could not run.
        if path.exists():
            command = read_record(path).get('command')
            if not isinstance(command, list) or not command or command[0] != local_executable:
                raise ValueError('native command did not use the same hash-bound app-local game')
    _compare(report['capture_paths'], shards.capture_paths(scenario), f'{scenario}/capture_paths')
    host = report['host']
    if (type(host) is not dict or set(host) != {'runner_name', 'runner_os', 'runner_arch'}
            or any(type(value) is not str or not value.strip() for value in host.values())
            or host['runner_os'] != 'Windows'):
        raise ValueError(f'{scenario}: missing genuine Windows runner identity')
    if report['current_check'] is not None and type(report['current_check']) is not str:
        raise ValueError(f'{scenario}: current_check must be a check name or null')
    if report['status'] not in ('passed', 'failed', 'interrupted', 'running'):
        raise ValueError(f'{scenario}: unsupported status')
    if type(report['passed']) is not bool or type(report['budget_exhausted']) is not bool:
        raise ValueError(f'{scenario}: verdicts must be booleans')
    number(report['elapsed_seconds'], 'elapsed_seconds')
    number(report['run_timeout_seconds'], 'run_timeout_seconds')
    if report['run_timeout_seconds'] != shards.PROFILES[scenario]['run_timeout_seconds']:
        raise ValueError(f'{scenario}: unexpected run time allowance')
    checks = report['checks']
    if type(checks) is not list:
        raise ValueError(f'{scenario}: checks must be an array')
    expected_names = local_checks(scenario)
    names = []
    for row in checks:
        if (type(row) is not dict or not {'name', 'passed', 'elapsed_seconds'} <= set(row)
                or type(row['name']) is not str or type(row['passed']) is not bool):
            raise ValueError(f'{scenario}: malformed check')
        if set(row) != {'name', 'passed', 'elapsed_seconds', 'result' if row['passed'] else 'error'}:
            raise ValueError(f'{scenario}: invalid check outcome fields')
        if row['passed']:
            if type(row['result']) is not dict or not row['result']:
                raise ValueError(f'{scenario}: passing check result must be a nonempty object')
            if row['name'] in ('validated-inputs', 'inputs-unchanged'):
                shards.compare_binding(binding, row['result'])
            if row['name'].endswith('/existing-validator'):
                _compare(row['result'], {'exit_code': 0}, 'existing validator process result')
        elif type(row['error']) is not str or not row['error']:
            raise ValueError(f'{scenario}: failed check must retain its error')
        number(row['elapsed_seconds'], f'{scenario}/{row["name"]}/elapsed_seconds')
        names.append(row['name'])
    if names != [name for name in expected_names if name in names]:
        raise ValueError(f'{scenario}: reordered, duplicate or unexpected checks')
    shards.verify_files(folder, report['files'])
    if authored.sha256(folder / 'summary.json') != summary_hash:
        raise ValueError(f'{scenario}: summary changed while validating artifact')
    return report


def require_checks(report, names):
    rows = {row['name']: row for row in report['checks']}
    for name in names:
        if name not in rows or rows[name]['passed'] is not True:
            raise ValueError(f'{report["scenario"]}: required successful check missing: {name}')
    return rows


def shard_pass(report):
    require_checks(report, local_checks(report['scenario']))
    if (report['passed'] is not True or report['status'] != 'passed'
            or report['budget_exhausted'] is not False or report['current_check'] is not None
            or report['elapsed_seconds'] >= report['run_timeout_seconds']):
        raise ValueError(f'{report["scenario"]}: shard did not finish successfully within its budget')
    if report['scenario'] in LAYERED:
        row = next(row for row in report['checks'] if row['name'] == 'layered-pair-deferred-to-aggregate')
        _compare(row['result'], {'rates': list(LAYERED)}, 'deferred layered pair')
    return {'passed': True, 'required_checks': local_checks(report['scenario'])}


def copy_verified(source, destination):
    recorded = shards.inventory_files(source, exclude=())
    if not recorded:
        raise ValueError(f'{source}: empty evidence tree')
    shutil.copytree(source, destination, symlinks=False)
    shards.verify_files(destination, recorded, exclude=())
    shards.verify_files(source, recorded, exclude=())
    return destination


def legacy_logs(folder):
    return shard_runner.legacy_renderer_logs(folder)['adapter']


def process_receipt(logs, timeout_limit, expected_images):
    """A passing check cannot vouch for a canceled or failed recorded process."""
    state = read_record(logs / 'process.json')
    invocation = read_record(logs / 'invocation.json')
    if (state.get('schema') != 'rust-duty-capture-process/v1' or state.get('status') != 'passed'
            or 'error' in state or 'cleanup' in state
            or type(state.get('exit_code')) is not int or state['exit_code'] != 0
            or type(state.get('pid')) is not int or state['pid'] <= 0
            or type(state.get('png_files')) is not int or state['png_files'] != expected_images):
        raise ValueError(f'{logs}: incomplete, canceled or failed capture process')
    elapsed = number(state.get('elapsed_seconds'), 'process elapsed_seconds')
    timeout = number(state.get('timeout_seconds'), 'process timeout_seconds')
    if not 0 < timeout <= timeout_limit or elapsed >= timeout:
        raise ValueError(f'{logs}: capture process exceeded its allowed budget')
    _compare(invocation.get('timeout_seconds'), timeout, 'invocation timeout')
    command = invocation.get('command')
    if (type(command) is not list or not command
            or any(type(argument) is not str or not argument for argument in command)
            or type(invocation.get('cwd')) is not str or not invocation['cwd']):
        raise ValueError(f'{logs}: malformed process invocation')
    return command


def capture_invocation(folder, scenario, role, count, expected_witness_identity):
    limit = 900 if role == 'windows-legacy' else shards.PROFILES[scenario]['capture_timeout_seconds']
    command = process_receipt(folder / 'logs' / f'{role}-capture', limit, count)
    flags = [argument for argument in command
             if argument == '--capture-frame-witness' or argument.startswith('--capture-frame-witness=')]
    if flags != [f'--capture-frame-witness={expected_witness_identity}']:
        raise ValueError(f'{scenario}/{role}: capture invocation changed exact frame witness identity')
    case = CASES[scenario]
    for prefix, expected in (('--renderer=', ['--renderer=gl' if role == 'windows-legacy' else '--renderer=dx12']),
                             ('--capture-sequence=', [f'--capture-sequence={case.sequence}']),
                             ('--capture-hz=', [] if case.hz is None else [f'--capture-hz={case.hz}'])):
        if [argument for argument in command if argument.startswith(prefix)] != expected:
            raise ValueError(f'{scenario}/{role}: capture invocation changed {prefix}')
    for flag in ('--no-update', '--reference-viewport'):
        if command.count(flag) != 1:
            raise ValueError(f'{scenario}/{role}: missing exact {flag}')
    if command.count('--force-fallback-adapter') != int(role == 'dx12'):
        raise ValueError(f'{scenario}/{role}: wrong fallback adapter selection')
    if scenario == 'ads-offset':
        arguments = [argument for argument in command if argument.startswith('--settings=')]
        if len(arguments) != 1:
            raise ValueError('Windows ADS placement capture needs exactly one settings file')
        if not (folder / 'ads-offset.cfg').is_file():
            raise ValueError('Windows ADS offset settings evidence is missing')
    elif any(argument.startswith('--settings=') for argument in command):
        raise ValueError(f'{scenario}/{role}: unexpected capture settings override')
    return command


def stock_probe(folder, report, assembled):
    require_checks(report, ['windows-legacy/stock-probe'])
    logs = folder / 'logs/windows-legacy-stock-probe'
    command = process_receipt(logs, 120, 1)
    for flag in ('--renderer=gl', '--no-update', '--procedural-weapon', '--reference-viewport', '--capture'):
        if command.count(flag) != 1:
            raise ValueError(f'stock GL probe is missing exact {flag}')
    if ([argument for argument in command if argument.startswith('--renderer=')] != ['--renderer=gl']
            or '--force-fallback-adapter' in command):
        raise ValueError('stock probe is not an explicit native GL attempt')
    adapter = legacy_logs(logs)
    copied = copy_verified(folder / 'stock-gl', assembled / 'stock-gl' / report['scenario'])
    shard_runner.validate_stock_probe(copied, expected_adapter=adapter)
    return adapter


def validator_receipt(logs, case, relative_capture, verdict):
    command = process_receipt(logs, 900, 0)
    expected_script = case.validator or 'verify_layered_locomotion_capture.py'
    if (len(command) != 3 or command[1].replace('\\', '/').rsplit('/', 1)[-1] != expected_script
            or not command[2].replace('\\', '/').endswith('/' + relative_capture)):
        raise ValueError('local validator invocation differs from the existing strict CLI')
    expected = {'captures': [verdict]} if case.name in LAYERED else verdict
    _compare(read_record(logs / 'stdout.log'), expected, 'local validator stdout/verification report')
    return {'exit_code': 0, 'verified_stdout': True}


def copy_role(folder, report, role, assembled, binding):
    scenario = report['scenario']
    rows = require_checks(report, ['validated-inputs', 'inputs-unchanged'] +
                          [f'{role}/{suffix}' for suffix in ('capture', 'finite-images', 'existing-validator')])
    result = rows[f'{role}/finite-images']['result']
    count = shards.PROFILES[scenario]['expected_frames']
    if type(result) is not dict or type(result.get('frames')) is not int or result['frames'] != count or result.get('all_images_checked') is not True:
        raise ValueError(f'{scenario}/{role}: incomplete image validation receipt')
    relative = CASES[scenario].baseline if role == 'windows-legacy' else scenario
    destination = assembled / role / relative
    witness_identity = shard_runner.role_witness_identity(binding, scenario, role)
    capture_invocation(folder, scenario, role, count, witness_identity)
    probe_adapter = stock_probe(folder, report, assembled) if role == 'windows-legacy' else None
    copy_verified(folder / report['capture_paths'][role], destination)
    validated = shard_runner.validate_role_images(destination, role, count,
                                                  expected_witness_identity=witness_identity)
    images = sorted(destination.glob('*.png'))
    verdict = authored.successful_report(destination / 'verification.json', images)
    validator_receipt(folder / 'logs' / f'{role}-validator', CASES[scenario], report['capture_paths'][role], verdict)
    log = folder / 'logs' / f'{role}-capture'
    if role == 'windows-legacy':
        adapter = legacy_logs(log)
        if adapter != probe_adapter:
            raise ValueError('stock GL probe and authored replay used different adapters')
        if validated['adapter'] != adapter:
            raise ValueError(f'{scenario}: legacy log and capture renderer identity disagree')
    else:
        authored.renderer_logs(log)
    return {**validated, 'path': destination.relative_to(assembled.parent).as_posix()}


def copy_auxiliary(folder, report, assembled):
    require_checks(report, local_checks('lighting-orientation'))
    orientation = copy_verified(folder / report['capture_paths']['orientation'], assembled / 'renderer-contract')
    process_receipt(folder / 'logs/renderer-contract', 900,
                    sum(1 for path in orientation.glob('*.png') if path.is_file()))
    authored.renderer_logs(folder / 'logs/renderer-contract')
    orientation_result = authored.validate_orientation(orientation)
    light = copy_verified(folder / report['capture_paths']['dx12'], assembled / 'dx12/lighting')
    for stem, _ in authored.lighting_commands(Path('game'), Path('.'), light):
        process_receipt(folder / 'logs' / f'lighting-{stem}', 900, 1)
        authored.renderer_logs(folder / 'logs' / f'lighting-{stem}')
    # These are the existing validator's derived contact sheets. Only our fresh
    # copy is changed; all incoming raw and derived bytes remain intact.
    previous_lighting = read_record(light / 'verification.json')
    for name in ('verification.json', 'ready_directions.png', 'reload_directions.png', 'ready_world_directions.png'):
        (light / name).unlink(missing_ok=True)
    lighting_result = authored.validate_lighting(light)
    _compare(previous_lighting, read_record(light / 'verification.json'), 'lighting validator receipt')
    return {'orientation': orientation_result, 'lighting': lighting_result}


def validate_shard_set(folder):
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError('shards root must be a real directory')
    children = list(folder.iterdir())
    if ({path.name for path in children} != set(shards.SCENARIOS)
            or any(path.is_symlink() or not path.is_dir() for path in children)):
        raise ValueError('expected exactly the nine scenario artifact directories')
    return {'scenarios': list(shards.SCENARIOS)}


def historical_sequence(folder, scenario):
    images, finite = authored.sequence_inventory(folder, 'OpenGl')
    if len(images) != shards.PROFILES[scenario]['expected_frames']:
        raise ValueError(f'{scenario}: historical Linux capture has unexpected frame count')
    authored.baseline_verdicts(folder, images)
    return {'frames': len(images), 'finite_json': finite}


def same_windows_parity(baseline, candidate, scenario, source_folder):
    if scenario == 'ads-offset':
        settings = []
        for role in ROLES:
            command = read_record(source_folder / 'logs' / f'{role}-capture/invocation.json')['command']
            arguments = [argument for argument in command if argument.startswith('--settings=')]
            if len(arguments) != 1:
                raise ValueError('Windows ADS placement capture needs exactly one settings file')
            settings.append(arguments)
        _compare(settings[0], settings[1], 'same-Windows ADS placement settings')
    return authored.compare_sequence(baseline, candidate)


def expected_checks(*, ads_source_supplement=False):
    names = ['validated-inputs', 'exact-nine-shards']
    if ads_source_supplement:
        names += ['ads-source-supplement/bound-leaf']
    for scenario in shards.SCENARIOS:
        corrected = ads_source_supplement and scenario == 'ads-offset'
        names += [f'{scenario}/artifact-integrity',
                  f'{scenario}/{"source-correction-eligibility" if corrected else "local-checks"}']
        names += ([f'{scenario}/{role}/{"corrected-assembled-evidence" if corrected else "assembled-evidence"}' for role in ROLES] if scenario in CASES
                  else ['lighting-orientation/assembled-evidence'])
    for role in ROLES:
        names += [f'{role}/ads-placement-existing-validator', f'{role}/layered-rates-existing-validator']
    names += [f'{scenario}/same-windows-strict-parity' for scenario in CASES]
    names += ['historical-linux/source-bound-inputs']
    names += [f'{scenario}/historical-linux-diagnostic' for scenario in CASES]
    return names + ['landmark-guides-not-a-landmark-pass', 'inputs-unchanged']


def offset_correction_eligibility(report):
    """Accept only the original image failure and its exact blocked dependents.

    This does not turn any historical check into a pass. The original structure
    failure must also recur as a typed exception on the immutable native bytes.
    """
    if (report['scenario'] != 'ads-offset' or report['passed'] is not False
            or report['status'] != 'failed' or report['budget_exhausted'] is not False
            or report['current_check'] is not None
            or report['elapsed_seconds'] >= report['run_timeout_seconds']):
        raise ValueError('ADS source correction requires a completed, non-timeout failed offset shard')
    if [row['name'] for row in report['checks']] != local_checks('ads-offset'):
        raise ValueError('ADS correction requires the complete original offset check inventory')
    rows = require_checks(report, ['validated-inputs', 'inputs-unchanged',
                                  'windows-legacy/stock-probe', 'windows-legacy/capture', 'dx12/capture'])
    failed_roles = []
    blocked = 'ValueError: blocked by a failed required capture or input check'
    for role in ROLES:
        finite = rows[f'{role}/finite-images']
        validator = rows[f'{role}/existing-validator']
        if finite['passed']:
            require_checks(report, [f'{role}/existing-validator'])
        else:
            error = finite['error']
            prefix, _, detail = error.partition(': ')
            if (prefix not in ('CaptureError', 'CaptureStructureError')
                    or not (detail in ('uniform image: no rendered structure',
                                       'near-uniform image: insufficient rendered structure')
                            or re.fullmatch(r'.+: foreground coverage 0\.\d{6} below 0\.010000', detail))):
                raise ValueError('ADS source correction cannot excuse an unrelated original image failure')
            if validator['passed'] or validator.get('error') != blocked:
                raise ValueError('ADS source correction requires an originally blocked validator')
            failed_roles.append(role)
    if not failed_roles or rows['same-windows-strict-parity']['passed'] or rows['same-windows-strict-parity'].get('error') != blocked:
        raise ValueError('ADS source correction requires originally blocked same-Windows parity')
    return {'original_status': report['status'], 'original_passed': report['passed'],
            'failed_image_roles': failed_roles, 'original_checks_preserved': True}


class AdsSourceSupplement:
    """Narrow intake for a separately retained ADS leaf and its source anchors.

    All nine original shards remain authoritative inputs. The leaf is evidence
    to bind and recheck, never a substitute for aggregate validators.
    """
    def __init__(self, request):
        required = {'leaf_summary', 'source_packet', 'source_receipt_sha256',
                    'capture_rustc_sha256', 'capture_context', 'leaf_verifier_context', 'verifier_context'}
        shards._exact_keys(request, required, 'ADS source supplement request')
        self.request = request
        self.capture_context = shards._validate_context(request['capture_context'])
        self.leaf_verifier_context = shards._validate_context(request['leaf_verifier_context'])
        self.verifier_context = shards._validate_context(request['verifier_context'])
        _compare(self.verifier_context, shards.context(), 'actual aggregate verifier GitHub identity')
        for field in ('source_receipt_sha256', 'capture_rustc_sha256'):
            if type(request[field]) is not str or not re.fullmatch('[0-9a-f]{64}', request[field]):
                raise ValueError(f'ADS supplement requires an independently retained {field}')
        self.summary = Path(request['leaf_summary']).absolute()
        self.source_packet = Path(request['source_packet']).absolute()
        if self.summary.name != 'summary.json':
            raise ValueError('ADS leaf inventory must accompany its root summary.json')
        self.packet = self.fallback = None
        self.original_hashes = {}

    def load(self, binding, incoming, input_manifest, evidence):
        # Lazy import avoids the leaf caller's existing aggregate import cycle.
        import revalidate_ads_offset as leaf
        self.leaf_hash = shards._read_regular(self.summary)
        saved = read_record(self.summary)
        required = {'schema', 'passed', 'acceptance_complete', 'capture_context', 'verifier_context',
                    'scope', 'checks', 'original_capture_verdicts', 'source_fallback', 'capture_binding',
                    'source_production_commit', 'source_packet_sha256', 'source_receipt_sha256',
                    'capture_rustc_sha256', 'source_profiles', 'actual_gl_profile', 'files'}
        shards._exact_keys(saved, required, 'ADS leaf summary')
        for field, expected in (('schema', leaf.SCHEMA), ('passed', True), ('acceptance_complete', False),
                                ('capture_context', self.capture_context), ('verifier_context', self.leaf_verifier_context),
                                ('source_production_commit', binding['source_commit'])):
            _compare(saved[field], expected, f'ADS leaf/{field}')
        shards.validate_binding(saved['capture_binding'], expected_context=self.capture_context)
        shards.compare_binding(binding, saved['capture_binding'])
        for field in ('source_receipt_sha256', 'capture_rustc_sha256'):
            _compare(saved[field], self.request[field], f'ADS leaf/{field}')
        self.packet_hash = shards._read_regular(self.source_packet)
        _compare(saved['source_packet_sha256'], self.packet_hash, 'ADS leaf/source packet')
        shards.verify_files(self.summary.parent, saved['files'])
        expected = [f'{scenario}/{role}/{suffix}' for scenario in leaf.SCENARIOS for role in ROLES
                    for suffix in ('finite-images', 'existing-validator')]
        expected += [f'{role}/ads-placement-existing-validator' for role in ROLES]
        expected += [f'{scenario}/same-windows-strict-parity' for scenario in leaf.SCENARIOS]
        expected += ['all-original-and-bound-inputs-unchanged']
        checks = saved['checks']
        if (type(checks) is not list or any(type(row) is not dict for row in checks)
                or [row.get('name') for row in checks] != expected
                or any(row.get('passed') is not True for row in checks)):
            raise ValueError('ADS leaf must retain every successful revalidation check')
        for row in checks:
            fields = {'name', 'passed'} if row['name'] == expected[-1] else {'name', 'passed', 'result'}
            shards._exact_keys(row, fields, 'ADS leaf check')
            if 'result' in fields and (type(row['result']) is not dict or not row['result']):
                raise ValueError('ADS leaf check requires its complete result')
        shards._exact_keys(saved['source_fallback'], ROLES, 'ADS leaf source fallback')
        if (any(type(value) is not list for value in saved['source_fallback'].values())
                or not any(saved['source_fallback'].values())):
            raise ValueError('ADS leaf must retain an exercised source correction')
        original = self.summary.parent / 'original-verdicts'
        _compare(shards._read_regular(original / 'input-manifest.json'), shards._read_regular(input_manifest),
                 'ADS leaf/original full input manifest')
        shards._exact_keys(saved['original_capture_verdicts'], leaf.SCENARIOS, 'ADS leaf original verdicts')
        preserved = evidence / 'original-verdicts'
        preserved.mkdir()
        self.original_reports = {}
        for scenario in leaf.SCENARIOS:
            folder = incoming / scenario
            report = read_shard(folder, scenario, binding, expected_context=self.capture_context)
            digest = shards._read_regular(folder / 'summary.json')
            _compare(saved['original_capture_verdicts'][scenario],
                     {'summary_sha256': digest, 'passed': report['passed'], 'status': report['status']},
                     f'ADS leaf/original {scenario} summary')
            _compare(shards._read_regular(original / f'{scenario}-summary.json'), digest,
                     f'ADS leaf/retained {scenario} summary bytes')
            self.original_hashes[scenario] = digest
            self.original_reports[scenario] = report
            shutil.copyfile(folder / 'summary.json', preserved / f'{scenario}-summary.json')
            # Every retained native frame/sidecar must be the same original
            # bytes; verification.json is a newly derived validator outcome.
            for role in ROLES:
                relative = report['capture_paths'][role]
                destination = f'assembled/{role}/{CASES[scenario].baseline}'
                for name, raw_hash in report['files'].items():
                    if name.startswith(relative + '/') and name != relative + '/verification.json':
                        key = destination + name[len(relative):]
                        _compare(saved['files'].get(key), raw_hash, f'ADS leaf/native bytes/{key}')
        shard_pass(self.original_reports['ads-gameplay'])
        eligibility = offset_correction_eligibility(self.original_reports['ads-offset'])
        shutil.copyfile(self.summary, evidence / 'ads-source-leaf-summary.json')
        self.saved = saved
        return {'leaf_summary_sha256': self.leaf_hash, 'capture_context': self.capture_context,
                'leaf_verifier_context': self.leaf_verifier_context,
                'verifier_context': self.verifier_context, 'capture_binding': binding,
                'source_receipt_sha256': self.request['source_receipt_sha256'],
                'capture_rustc_sha256': self.request['capture_rustc_sha256'],
                'source_packet_sha256': self.packet_hash, 'original_capture_verdicts': saved['original_capture_verdicts'],
                **eligibility}

    def prepare(self, folder, report, assembled, binding):
        import revalidate_ads_offset as leaf
        if not hasattr(self, 'saved'):
            raise ValueError('validated ADS leaf unavailable')
        eligibility = offset_correction_eligibility(report)
        self.invocations, self.folders = {}, {}
        self.probe_adapter = stock_probe(folder, report, assembled)
        for role in ROLES:
            self.invocations[role] = leaf.exact_invocation(folder, report, role, 'ads-offset')
            relative = CASES['ads-offset'].baseline if role == 'windows-legacy' else 'ads-offset'
            destination = assembled / role / relative
            copy_verified(folder / report['capture_paths'][role], destination)
            self.folders[role] = destination
        self.packet = leaf.source_binding.bind_source_packet(self.source_packet,
            expected_receipt_sha256=self.request['source_receipt_sha256'],
            expected_compiler_sha256=self.request['capture_rustc_sha256'], native_binding=binding,
            original_invocations=self.invocations, native_frame_dirs=self.folders,
            native_offset_settings=folder / 'ads-offset.cfg')
        _compare(self.saved['source_profiles'], self.packet.headers_by_role, 'ADS leaf/source profiles')
        self.fallback = leaf.AdsOffsetFallback(self.packet, self.folders)
        self.eligibility = eligibility
        return eligibility

    def copy_role(self, folder, report, role, assembled, binding, process, root):
        import revalidate_ads_offset as leaf
        if self.fallback is None:
            raise ValueError('bound ADS source correction unavailable')
        destination = self.folders[role]
        identity = shard_runner.role_witness_identity(binding, 'ads-offset', role)
        count = shards.PROFILES['ads-offset']['expected_frames']
        # Independently establish that the old failure is exactly the typed
        # generic image predicate; any metadata/witness/decode error escapes.
        failed = False
        try:
            shard_runner.validate_role_images(destination, role, count, expected_witness_identity=identity)
        except shard_runner.CaptureStructureError:
            failed = True
        if failed != (role in self.eligibility['failed_image_roles']):
            raise ValueError('original ADS image failure does not recur on its bound native bytes')
        validated = shard_runner.validate_role_images(destination, role, count,
            expected_witness_identity=identity, source_visibility=self.fallback)
        logs = folder / 'logs' / f'{role}-capture'
        if role == 'windows-legacy':
            adapter = legacy_logs(logs)
            if adapter != self.probe_adapter or validated['adapter'] != adapter:
                raise ValueError('ADS stock probe, replay log and sidecar adapters differ')
            profile = leaf.native_gl_profile(folder, binding, adapter, self.invocations[role])
            _compare(self.saved['actual_gl_profile'], profile, 'ADS leaf/actual native GL profile')
        else:
            authored.renderer_logs(logs)
        if role not in self.eligibility['failed_image_roles']:
            rows = require_checks(report, [f'{role}/finite-images', f'{role}/existing-validator'])
            result = rows[f'{role}/finite-images']['result']
            if type(result.get('frames')) is not int or result['frames'] != count or result.get('all_images_checked') is not True:
                raise ValueError('ADS original successful image receipt is incomplete')
            old_verdict = authored.successful_report(destination / 'verification.json', sorted(destination.glob('*.png')))
            validator_receipt(folder / 'logs' / f'{role}-validator', CASES['ads-offset'], report['capture_paths'][role], old_verdict)
        log = assembled.parent / 'logs' / f'ads-offset-{role}-corrected-validator'
        process([sys.executable, str(root / 'tools' / CASES['ads-offset'].validator), str(destination)], log)
        verdict = authored.successful_report(destination / 'verification.json', sorted(destination.glob('*.png')))
        if verdict.get('schema') != 'rust-duty-native-ads-capture/v1' or type(verdict.get('frames')) is not int or verdict['frames'] != count:
            raise ValueError('corrected ADS existing validator report incomplete')
        _compare(verdict, read_record(log / 'stdout.log'), 'corrected ADS validator stdout/report')
        return {**validated, 'path': destination.relative_to(assembled.parent).as_posix(),
                'existing_validator': verdict, 'source_fallback': self.fallback.records[role],
                'original_checks_preserved': True}

    def verify_unchanged(self):
        if self.packet is None or self.fallback is None:
            raise ValueError('complete bound ADS correction unavailable')
        if not any(self.fallback.records.values()):
            raise ValueError('ADS source correction did not exercise a coverage/structure correction')
        self.packet.verify_unchanged()
        shards.verify_files(self.summary.parent, self.saved['files'])
        _compare(shards._read_regular(self.summary), self.leaf_hash, 'unchanged ADS leaf summary')
        _compare(shards._read_regular(self.source_packet), self.packet_hash, 'unchanged ADS source packet')


def run(root, incoming, legacy_linux, evidence, input_manifest, timeout=900, *,
        historical_manifest, run_timeout=2400, ads_source_supplement=None):
    root, incoming, legacy_linux, evidence, input_manifest, historical_manifest = [Path(path).absolute() for path in
        (root, incoming, legacy_linux, evidence, input_manifest, historical_manifest)]
    supplement = AdsSourceSupplement(ads_source_supplement) if ads_source_supplement is not None else None
    capture_context = supplement.capture_context if supplement else None
    sources = [incoming, legacy_linux]
    if supplement:
        sources += [supplement.summary.parent, supplement.source_packet.parent]
    for source in sources:
        if evidence.resolve().is_relative_to(source.resolve()) or source.resolve().is_relative_to(evidence.resolve()):
            raise ValueError('evidence must be disjoint from incoming artifact trees')
    evidence.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = {'schema': SCHEMA, 'status': 'running', 'passed': False, 'acceptance_complete': False,
              'automated_landmark_gate': 'open', 'human_visual_gate': 'open', 'real_gpu_playtest_gate': 'open',
              'started_at': datetime.now(timezone.utc).isoformat(), 'current_check': None,
              'elapsed_seconds': 0, 'run_timeout_seconds': run_timeout if math.isfinite(run_timeout) else None,
              'budget_exhausted': False, 'binding': None,
              'expected_checks': expected_checks(ads_source_supplement=supplement is not None), 'checks': [], 'diagnostics': []}
    if supplement:
        report.update(capture_context=capture_context, verifier_context=supplement.verifier_context)
    summary = evidence / 'summary.json'
    authored.write_json(summary, report)

    def check(name, action):
        check_started = time.monotonic()
        report['current_check'] = name
        authored.write_json(summary, report)
        try:
            if not math.isfinite(run_timeout) or run_timeout <= 0:
                raise ValueError('run timeout must be finite and positive')
            if time.monotonic() - started >= run_timeout:
                report['budget_exhausted'] = True
                raise RuntimeError('whole-run time budget exhausted; check not attempted')
            result = action()
            row = {'name': name, 'passed': True, 'result': plain(result)}
        except Exception as error:
            row = {'name': name, 'passed': False, 'error': f'{type(error).__name__}: {error}'}
        except BaseException as error:
            report['checks'].append({'name': name, 'passed': False, 'error': f'{type(error).__name__}: {error}',
                                     'elapsed_seconds': round(time.monotonic() - check_started, 6)})
            report.update(status='interrupted', current_check=name)
            authored.write_json(summary, report)
            raise
        row['elapsed_seconds'] = round(time.monotonic() - check_started, 6)
        elapsed = time.monotonic() - started
        if elapsed >= run_timeout:
            report['budget_exhausted'] = True
            row = {key: value for key, value in row.items() if key != 'result'}
            row.update(passed=False, error='whole-run time budget exhausted')
        report['checks'].append(row)
        report.update(current_check=None, elapsed_seconds=round(elapsed, 6))
        authored.write_json(summary, report)
        return row['passed']

    def process(command, logs):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('timeout must be finite and positive')
        remaining = run_timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise RuntimeError('whole-run time budget exhausted before subprocess launch')
        return authored.execute(command, root, logs, min(timeout, 900, remaining))

    binding, input_manifest_hash = None, None
    def inputs():
        nonlocal binding, input_manifest_hash
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('timeout must be finite and positive')
        input_manifest_hash = authored.sha256(input_manifest)
        binding = validated_manifest(input_manifest, root, expected_context=capture_context)
        report['binding'] = binding
        shutil.copyfile(input_manifest, evidence / 'input-manifest.json')
        return binding
    check('validated-inputs', inputs)

    check('exact-nine-shards', lambda: validate_shard_set(incoming))
    if supplement:
        def load_supplement():
            if binding is None:
                raise ValueError('validated full input manifest unavailable')
            result = supplement.load(binding, incoming, input_manifest, evidence)
            report['ads_source_supplement'] = result
            return result
        check('ads-source-supplement/bound-leaf', load_supplement)
    loaded, available, source_hashes = {}, set(), {}
    assembled = evidence / 'assembled'
    for scenario in shards.SCENARIOS:
        folder = incoming / scenario
        def load(scenario=scenario, folder=folder):
            if binding is None:
                raise ValueError('validated input manifest unavailable')
            loaded[scenario] = read_shard(folder, scenario, binding, expected_context=capture_context)
            source_hashes[scenario] = authored.sha256(folder / 'summary.json')
            if supplement and scenario in supplement.original_hashes:
                _compare(source_hashes[scenario], supplement.original_hashes[scenario],
                         f'{scenario}: original summary changed after supplement intake')
            return {'scenario': scenario, 'files': len(loaded[scenario]['files'])}
        check(f'{scenario}/artifact-integrity', load)
        corrected = supplement is not None and scenario == 'ads-offset'
        if corrected:
            check(f'{scenario}/source-correction-eligibility',
                  lambda: supplement.prepare(folder, loaded['ads-offset'], assembled, binding))
        else:
            check(f'{scenario}/local-checks', lambda scenario=scenario: shard_pass(loaded[scenario]))
        if scenario in CASES:
            for role in ROLES:
                def role_copy(scenario=scenario, role=role, folder=folder):
                    result = (supplement.copy_role(folder, loaded[scenario], role, assembled, binding, process, root)
                              if corrected else copy_role(folder, loaded[scenario], role, assembled, binding))
                    available.add((scenario, role))
                    return result
                check(f'{scenario}/{role}/{"corrected-assembled-evidence" if corrected else "assembled-evidence"}', role_copy)
        else:
            check('lighting-orientation/assembled-evidence', lambda folder=folder: copy_auxiliary(folder, loaded['lighting-orientation'], assembled))

    def need(names, role):
        missing = [name for name in names if (name, role) not in available]
        if missing:
            raise ValueError(f'{role}: validated captures unavailable: {missing}')
        return [assembled / role / (CASES[name].baseline if role == 'windows-legacy' else name) for name in names]

    def pair(role, layered):
        names = LAYERED if layered else ('ads-gameplay', 'ads-offset')
        folders = need(names, role)
        validator = 'verify_layered_locomotion_capture.py' if layered else 'verify_ads_placement_capture.py'
        log = evidence / 'logs' / f'{role}-{"layered-rates" if layered else "ads-placement"}'
        previous = [read_record(folder / 'verification.json') for folder in folders] if layered else []
        process([sys.executable, str(root / 'tools' / validator), *map(str, folders)], log)
        result = read_record(log / 'stdout.log')
        destination = folders[0].parent / 'layered-rate-verification.json' if layered else folders[1].parent / 'ads-offset-verification.json'
        # Preserve the actual CLI stdout, including the compound layered schema.
        shutil.copyfile(log / 'stdout.log', destination)
        if layered:
            for folder, before in zip(folders, previous):
                _compare(before, read_record(folder / 'verification.json'), 'layered local validator receipt')
            authored.layered_rate_verdict(folders[0].parent)
        elif result.get('passed') is not True or result.get('schema') != 'rust-duty-ads-placement-capture/v1' or type(result.get('frames')) is not int or result['frames'] != shards.PROFILES['ads-gameplay']['expected_frames']:
            raise ValueError('ADS placement validator did not return its complete passing report')
        return result

    for role in ROLES:
        check(f'{role}/ads-placement-existing-validator', lambda role=role: pair(role, False))
        check(f'{role}/layered-rates-existing-validator', lambda role=role: pair(role, True))
    for scenario in CASES:
        def parity(scenario=scenario):
            before = need([scenario], 'windows-legacy')[0]
            after = need([scenario], 'dx12')[0]
            return same_windows_parity(before, after, scenario, incoming / scenario)
        check(f'{scenario}/same-windows-strict-parity', parity)

    # Historical provenance and immutable diagnostics are implemented below;
    # every malformed or missing source-bound input remains a required failure.
    historical = {}
    def historical_inputs():
        if binding is None:
            raise ValueError('validated input manifest unavailable')
        historical.update(load_historical(legacy_linux, evidence / 'historical-linux', binding, historical_manifest))
        shutil.copyfile(historical_manifest, evidence / 'historical-manifest.json')
        return {'files': len(historical['files'])}
    check('historical-linux/source-bound-inputs', historical_inputs)
    for scenario in CASES:
        def diagnostic(scenario=scenario):
            if not historical:
                raise ValueError('validated historical Linux inputs unavailable')
            baseline = historical['root'] / CASES[scenario].baseline
            historical_sequence(baseline, scenario)
            candidate = need([scenario], 'dx12')[0]
            try:
                result = authored.compare_sequence(baseline, candidate)
                entry = {'scenario': scenario, 'exact_match': True, 'result': plain(result)}
            except ValueError as error:
                entry = {'scenario': scenario, 'exact_match': False, 'difference': str(error)}
            entry['acceptance_predicate'] = False
            report['diagnostics'].append(entry)
            authored.write_json(evidence / 'historical-linux-diagnostics.json', {'comparisons': report['diagnostics']})
            return entry
        check(f'{scenario}/historical-linux-diagnostic', diagnostic)

    def review():
        return authored.review_guides(need(['ads-gameplay'], 'dx12')[0], need(['ads-gameplay'], 'windows-legacy')[0], evidence / 'review', root)
    check('landmark-guides-not-a-landmark-pass', review)
    def immutable():
        for scenario, saved in loaded.items():
            shards.verify_files(incoming / scenario, saved['files'])
            if authored.sha256(incoming / scenario / 'summary.json') != source_hashes[scenario]:
                raise ValueError(f'{scenario}: incoming summary changed during aggregation')
        if historical:
            shards.verify_files(legacy_linux, historical['files'], exclude=())
            if authored.sha256(historical_manifest) != historical['manifest_sha256']:
                raise ValueError('historical manifest changed during aggregation')
        if binding is None:
            raise ValueError('validated input manifest unavailable')
        shards.compare_binding(binding, validated_manifest(input_manifest, root, expected_context=capture_context))
        if authored.sha256(input_manifest) != input_manifest_hash:
            raise ValueError('input manifest changed during aggregation')
        if supplement:
            supplement.verify_unchanged()
        return {'incoming_artifacts_unchanged': True}
    check('inputs-unchanged', immutable)
    report['passed'] = ([row['name'] for row in report['checks']] == report['expected_checks']
                        and not report['budget_exhausted']
                        and all(row['passed'] is True for row in report['checks']))
    report.update(status='passed' if report['passed'] else 'failed', current_check=None,
                  elapsed_seconds=round(time.monotonic() - started, 6),
                  scope='Automated same-Windows renderer parity only. Historical Linux numeric differences are diagnostics. Landmark, human visual and real-GPU gates remain open.')
    if supplement:
        report['scope'] += ' ADS-offset coverage/structure uses receipt-bound conditional source visibility; the original failed verdict is preserved.'
    authored.write_json(summary, report)
    return report


def load_historical(folder, destination, binding, manifest_path):
    """Verify the build-preparation receipt for this attempt's exact downloads.

    This is a workflow download receipt, not an embedded Linux producer record.
    The caller must fetch the attempt-specific current-run artifacts first.
    """
    manifest = read_record(manifest_path)
    context = {key: binding[key] for key in ('source_commit', 'run_id', 'run_attempt')}
    expected = {'schema': 'rust-duty-dx12-authored-historical/v1', **context, 'files': manifest.get('files')}
    _compare(manifest, expected, 'historical artifact download receipt')
    shards.verify_files(folder, manifest['files'], exclude=())
    if not manifest['files']:
        raise ValueError('historical Linux inventory is empty')
    copy_verified(folder, destination)
    # Individual sequence verdicts are checked separately so a malformed or
    # failed unrelated baseline does not suppress valid independent diagnostics.
    return {'root': destination, 'files': manifest['files'],
            'manifest_sha256': authored.sha256(manifest_path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--shards', type=Path, required=True)
    parser.add_argument('--legacy-linux', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--input-manifest', type=Path, required=True)
    parser.add_argument('--historical-manifest', type=Path, required=True)
    parser.add_argument('--ads-source-supplement', type=Path,
                        help='Explicit ADS leaf request JSON: leaf_summary, source_packet, independent receipt/compiler SHA256 anchors, capture_context, leaf_verifier_context, verifier_context. Paths are relative to the current directory.')
    parser.add_argument('--timeout', type=float, default=900)
    parser.add_argument('--run-timeout', type=float, default=2400)
    args = parser.parse_args(argv)
    try:
        report = run(args.root, args.shards, args.legacy_linux, args.evidence, args.input_manifest,
                     args.timeout, historical_manifest=args.historical_manifest, run_timeout=args.run_timeout,
                     ads_source_supplement=read_record(args.ads_source_supplement) if args.ads_source_supplement else None)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f'authored shard aggregation failed: {error}', file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())

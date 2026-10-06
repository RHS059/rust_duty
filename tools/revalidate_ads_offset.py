#!/usr/bin/env python3
"""Revalidate immutable Windows ADS artifacts with a bound source fallback.

Capture source/run/executable and verifier source/run remain separate. Incoming
failed verdicts and all native bytes are preserved. The result covers only the
ADS pair correction, not the other authored shards or the open human/GPU gates.
"""
import argparse
from copy import deepcopy
import json
import math
from pathlib import Path, PureWindowsPath
import shutil
import sys

import ads_source_visibility_binding as source_binding
import aggregate_dx12_authored as aggregate
import compare_source_visibility
import dx12_authored_shards as shared
import run_dx12_authored as authored
import run_dx12_authored_shard as shard
from verify_capture_telemetry import _compare, read_record
from verify_render_capture import load_png, _foreground_count

SCHEMA = 'rust-duty-ads-source-revalidation/v1'
ROLES = ('windows-legacy', 'dx12')
SCENARIOS = ('ads-gameplay', 'ads-offset')


def require(value, message):
    if not value:
        raise ValueError(message)


def manifest_binding(path, expected_context):
    record = read_record(path)
    _compare(record, {'schema': 'rust-duty-dx12-authored-inputs/v1', 'platform': 'win32',
                      'build_selection': {'default_enabled': False, 'features': ['legacy-macroquad', 'wgpu-runtime']},
                      'binding': record.get('binding'), 'gl_reference': record.get('gl_reference'),
                      'expected_scenarios': list(shared.SCENARIOS)}, 'native input manifest')
    shared.validate_binding(record['binding'], expected_context=expected_context)
    require(shared.gl_reference_digest(record['gl_reference']) == record['binding']['gl_reference_sha256'],
            'native manifest GL reference does not match its digest')
    return record


def exact_invocation(folder, report, role, scenario):
    identity = shard.role_witness_identity(report['binding'], scenario, role)
    command = aggregate.capture_invocation(folder, scenario, role, 553, identity)
    invocation = read_record(folder / 'logs' / f'{role}-capture/invocation.json')
    # Reconstruct the entire historical argv using its recorded paths. Reject
    # additional capture/pose/settings overrides, not merely known flag counts.
    def argument(prefix):
        values = [arg[len(prefix):] for arg in command if arg.startswith(prefix)]
        require(len(values) == 1 and values[0], f'expected one {prefix}')
        return values[0]
    native_cwd = invocation['cwd']
    require(Path(native_cwd).is_absolute() or PureWindowsPath(native_cwd).is_absolute(), 'native working directory must be absolute')
    root = Path(native_cwd)
    native_executable = report['app_local_executable'].replace('\\', '/')
    native_evidence = native_executable.rsplit('/gl-runtime/vector-range.exe', 1)[0]
    case = next(case for case in authored.CASES if case.name == scenario)
    output = argument('--output=')
    require(output.replace('\\', '/') == native_evidence + '/' + report['capture_paths'][role],
            'native output path differs from sealed capture folder')
    require(argument('--animation-manifest=').replace('\\', '/') == str(root / 'assets/animations.cfg').replace('\\', '/'),
            'native animation manifest path differs from original working directory')
    offset = argument('--settings=') if scenario == 'ads-offset' else str(folder / 'unused.cfg')
    if scenario == 'ads-offset':
        # Original Windows absolute paths remain data; do not read them on this host.
        require((Path(offset).is_absolute() or PureWindowsPath(offset).is_absolute())
                and offset.replace('\\', '/') == native_evidence + '/ads-offset.cfg', 'unexpected original offset settings path')
    expected = shard.role_command(report['app_local_executable'], root, output, case, offset, role)
    expected.append(f'--capture-frame-witness={identity}')
    # Path separator spelling can differ when inspecting Windows evidence on
    # Linux; compare only path-bearing arguments with canonical slash spelling.
    def normalized(argv):
        return [arg.replace('\\', '/') if i == 0 or arg.startswith(('--animation-manifest=', '--output=', '--settings=')) else arg
                for i, arg in enumerate(argv)]
    _compare(normalized(command), normalized(expected), f'{scenario}/{role}: exact native argv')
    return invocation


def native_gl_profile(folder, binding, adapter, invocation):
    records = {'gl_precision_receipt': [], 'gl_target_capture_receipt': []}
    for name in ('stdout.log', 'stderr.log'):
        path = folder / 'logs/windows-legacy-capture' / name
        for line in path.read_text(encoding='utf-8').splitlines():
            for key, found in records.items():
                prefix = f'renderer {key}='
                if line.startswith(prefix):
                    found.append(source_binding._parse(line[len(prefix):], str(path)))
    require(len(records['gl_precision_receipt']) == 1, 'missing or repeated bound GL precision receipt')
    cap = records['gl_precision_receipt'][0]
    identity = shard.role_witness_identity(binding, 'ads-offset', 'windows-legacy')
    for key, expected in {'schema': 'rust-duty-gl-precision-receipt/v1', 'backend': 'OpenGl',
                          'platform': 'windows', 'architecture': 'x86_64', 'capture_identity': identity,
                          'adapter': adapter, 'measurement_complete': True, 'phase': 'capture_before_readback'}.items():
        _compare(cap.get(key), expected, f'GL capability receipt/{key}')
    require(cap.get('subpixel', {}).get('status') == 'reported'
            and type(cap['subpixel'].get('bits')) is int and cap['subpixel']['bits'] >= 8,
            'GL raster subpixel profile unsupported')
    for stage, bits, exponent in [('vertex_high_float', 23, 127), ('vertex_low_float', 10, 15),
                                  ('fragment_medium_float', 10, 15), ('fragment_low_float', 10, 15)]:
        precision = cap.get('shader_precision', {}).get(stage, {})
        limits = precision.get('range')
        require(precision.get('status') == 'reported' and type(precision.get('precision_bits')) is int
                and precision['precision_bits'] >= bits and type(limits) is list and len(limits) == 2
                and all(type(value) is int and value >= exponent for value in limits), f'GL {stage} precision profile unsupported')
    output = next(arg.split('=', 1)[1] for arg in invocation['command'] if arg.startswith('--output='))
    targets = records['gl_target_capture_receipt']
    require(len(targets) == 1, 'missing or ambiguous actual GL target receipt')
    target = targets[0]
    for key, expected in {'schema': 'rust-duty-gl-target-capture-receipt/v1', 'capture_identity': identity,
                          'width': 960, 'height': 540, 'depth': True,
                          'miniquad_sample_count_parameter': 0, 'allocation': 'plain_non_resolving_texture_target',
                          'phase': 'capture_before_readback'}.items():
        _compare(target.get(key), expected, f'GL target receipt/{key}')
    require(target.get('capture_path', '').replace('\\', '/') == output.replace('\\', '/') + '/0000.png',
            'GL target receipt differs from the first original capture')
    return {'capability_receipt': cap, 'target_receipt': target,
            'arithmetic_clipping_fragment_envelopes': 'Declared source engineering assumptions; capability receipt does not prove them.'}


class AdsOffsetFallback:
    """Only constructed after the full packet and every native frame bind."""
    def __init__(self, bound, folders):
        require(type(bound) is source_binding.BoundSourcePacket, 'source packet has not been bound')
        self.bound = bound
        self.folders = {role: Path(folder).absolute() for role, folder in folders.items()}
        self.records = {role: [] for role in ROLES}

    def verify_image(self, path, role, index, *, original_error):
        path = Path(path).absolute()
        require(role in ROLES and path == self.folders[role] / f'{index:04}.png',
                'source fallback is restricted to the bound ADS-offset frame')
        row = self.bound.verify_frame_binding(path, role, index)
        image = load_png(path, authored.EXTENT)
        with path.open('rb') as source:
            header = source.read(29)
        require(len(header) == 29 and header[12:16] == b'IHDR' and header[24:26] == bytes([8, 6]),
                'source fallback requires an actual RGBA8 PNG')
        result = compare_source_visibility.compare(image, row)
        coverage = _foreground_count(image, authored.BACKGROUND, 8) / (960 * 540)
        record = {'frame': index, 'original_generic_failure': original_error,
                  'classification': row['classification'], **result, 'foreground_coverage': coverage}
        self.records[role].append(record)
        return record


def run(*, input_manifest, gameplay_shard, offset_shard, source_packet, source_receipt_sha256, capture_rustc_sha256, evidence,
        capture_context, verifier_context, timeout=900):
    shared._validate_context(capture_context)
    shared._validate_context(verifier_context)
    _compare(verifier_context, shared.context(), "actual verifier GitHub identity")
    require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 900, "invalid revalidation process timeout")
    evidence = Path(evidence).absolute()
    sources = {'ads-gameplay': Path(gameplay_shard).absolute(), 'ads-offset': Path(offset_shard).absolute()}
    for folder in (*sources.values(), Path(source_packet).absolute().parent):
        require(not evidence.resolve().is_relative_to(folder.resolve()) and not folder.resolve().is_relative_to(evidence.resolve()),
                'new evidence must be disjoint from original captures and source packet')
    require(not evidence.exists() and not evidence.is_symlink(), 'refusing existing revalidation output')
    evidence.mkdir(parents=True)
    report = {'schema': SCHEMA, 'passed': False, 'acceptance_complete': False,
              'capture_context': capture_context, 'verifier_context': verifier_context,
              'scope': 'ADS pair automated revalidation only; other authored/world, landmark, human and real-GPU gates remain unchanged/open.',
              'checks': [], 'original_capture_verdicts': {}, 'source_fallback': {}}
    original_hashes = {}
    packet = None
    try:
        manifest = manifest_binding(Path(input_manifest), capture_context)
        manifest_hash = shared._read_regular(Path(input_manifest))
        binding = manifest['binding']
        report['capture_binding'] = deepcopy(binding)
        original = evidence / 'original-verdicts'
        original.mkdir()
        shutil.copyfile(input_manifest, original / 'input-manifest.json')
        loaded, invocations, copied = {}, {}, {}
        for scenario, folder in sources.items():
            loaded[scenario] = aggregate.read_shard(folder, scenario, binding, expected_context=capture_context)
            saved = loaded[scenario]
            _compare(saved['gl_reference'], manifest['gl_reference'], f'{scenario}: native GL reference')
            # Failed image checks may be corrected; failed/incomplete captures,
            # stock execution or changing inputs may never be excused.
            aggregate.require_checks(saved, ['validated-inputs', 'inputs-unchanged', 'windows-legacy/stock-probe',
                                              'windows-legacy/capture', 'dx12/capture'])
            require(saved['budget_exhausted'] is False and saved['current_check'] is None
                    and saved['status'] in ('failed', 'passed'), 'capture shard incomplete or timed out')
            original_hashes[scenario] = authored.sha256(folder / 'summary.json')
            shutil.copyfile(folder / 'summary.json', original / f'{scenario}-summary.json')
            report['original_capture_verdicts'][scenario] = {'summary_sha256': original_hashes[scenario],
                                                           'passed': saved['passed'], 'status': saved['status']}
            if scenario == 'ads-gameplay':
                aggregate.shard_pass(saved)
            aggregate.stock_probe(folder, saved, evidence / 'assembled')
            for role in ROLES:
                invocation = exact_invocation(folder, saved, role, scenario)
                invocations[(scenario, role)] = invocation
                relative = next(case.baseline for case in authored.CASES if case.name == scenario)
                destination = evidence / 'assembled' / role / relative
                aggregate.copy_verified(folder / saved['capture_paths'][role], destination)
                copied[(scenario, role)] = destination
        frame_dirs = {role: copied[('ads-offset', role)] for role in ROLES}
        packet = source_binding.bind_source_packet(source_packet, expected_receipt_sha256=source_receipt_sha256,
                   expected_compiler_sha256=capture_rustc_sha256, native_binding=binding,
                   original_invocations={role: invocations[('ads-offset', role)] for role in ROLES},
                   native_frame_dirs=frame_dirs, native_offset_settings=sources['ads-offset'] / 'ads-offset.cfg')
        fallback = AdsOffsetFallback(packet, frame_dirs)
        report['source_production_commit'] = packet.source_base_commit
        report['source_packet_sha256'] = authored.sha256(source_packet)
        report['source_receipt_sha256'] = source_receipt_sha256
        report['capture_rustc_sha256'] = capture_rustc_sha256
        report['source_profiles'] = packet.headers_by_role
        for scenario, folder in sources.items():
            for role in ROLES:
                destination = copied[(scenario, role)]
                identity = shard.role_witness_identity(binding, scenario, role)
                result = shard.validate_role_images(destination, role, 553, expected_witness_identity=identity,
                            source_visibility=fallback if scenario == 'ads-offset' else None)
                logs = folder / 'logs' / f'{role}-capture'
                if role == 'windows-legacy':
                    actual = aggregate.legacy_logs(logs)
                else:
                    authored.renderer_logs(logs)
                    actual = authored.WARP
                require(result['adapter'] == actual, 'native log and capture sidecars disagree')
                if scenario == 'ads-offset' and role == 'windows-legacy':
                    report['actual_gl_profile'] = native_gl_profile(folder, binding, actual, invocations[(scenario, role)])
                report['checks'].append({'name': f'{scenario}/{role}/finite-images', 'passed': True, 'result': aggregate.plain(result)})
                command = [sys.executable, str(Path(__file__).with_name('verify_gameplay_ads_capture.py')), str(destination)]
                authored.execute(command, Path(__file__).parents[1], evidence / 'logs' / f'{scenario}-{role}-validator', timeout)
                verdict = authored.successful_report(destination / 'verification.json', sorted(destination.glob('*.png')))
                require(verdict.get('schema') == 'rust-duty-native-ads-capture/v1' and type(verdict.get('frames')) is int
                        and verdict['frames'] == 553, 'existing ADS validator report incomplete')
                _compare(verdict, read_record(evidence / 'logs' / f'{scenario}-{role}-validator/stdout.log'),
                         'existing ADS validator stdout/report')
                report['checks'].append({'name': f'{scenario}/{role}/existing-validator', 'passed': True, 'result': aggregate.plain(verdict)})
        for role in ROLES:
            logs = evidence / 'logs' / f'{role}-ads-placement'
            command = [sys.executable, str(Path(__file__).with_name('verify_ads_placement_capture.py')),
                       str(copied[('ads-gameplay', role)]), str(copied[('ads-offset', role)])]
            authored.execute(command, Path(__file__).parents[1], logs, timeout)
            verdict = read_record(logs / 'stdout.log')
            require(verdict.get('schema') == 'rust-duty-ads-placement-capture/v1' and verdict.get('passed') is True
                    and type(verdict.get('frames')) is int and verdict['frames'] == 553, 'ADS pair validator incomplete')
            shutil.copyfile(logs / 'stdout.log', copied[('ads-offset', role)].parent / 'ads-offset-verification.json')
            report['checks'].append({'name': f'{role}/ads-placement-existing-validator', 'passed': True, 'result': aggregate.plain(verdict)})
        for scenario in SCENARIOS:
            parity = aggregate.same_windows_parity(copied[(scenario, 'windows-legacy')], copied[(scenario, 'dx12')], scenario, sources[scenario])
            report['checks'].append({'name': f'{scenario}/same-windows-strict-parity', 'passed': True, 'result': aggregate.plain(parity)})
        report['source_fallback'] = fallback.records
        require(report['source_fallback']['windows-legacy'] or report['source_fallback']['dx12'], 'no coverage correction was exercised')
        packet.verify_unchanged()
        for scenario, folder in sources.items():
            shared.verify_files(folder, loaded[scenario]['files'])
            require(authored.sha256(folder / 'summary.json') == original_hashes[scenario], 'original failed/passed verdict changed')
        require(shared._read_regular(Path(input_manifest)) == manifest_hash, 'original native manifest changed')
        report['checks'].append({'name': 'all-original-and-bound-inputs-unchanged', 'passed': True})
        report['passed'] = True
    except Exception as error:
        report['failure'] = f'{type(error).__name__}: {error}'
    finally:
        try:
            report['files'] = shared.inventory_files(evidence)
        except Exception as error:
            report.update(passed=False, failure=f'revalidation output inventory failed: {error}')
        authored.write_json(evidence / 'summary.json', aggregate.plain(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('input-manifest', 'gameplay-shard', 'offset-shard', 'source-packet', 'evidence'):
        parser.add_argument('--' + name, type=Path, required=True)
    for kind in ('capture', 'verifier'):
        for key in ('source', 'run-id', 'run-attempt'):
            parser.add_argument(f'--{kind}-{key}', required=True)
    parser.add_argument('--capture-rustc-sha256', required=True, help='Independently recovered fingerprint of the actual captured Windows compiler.')
    parser.add_argument('--source-receipt-sha256', required=True, help='Independently retained source replay receipt digest; never taken from packet contents.')
    parser.add_argument('--timeout', type=float, default=900)
    args = vars(parser.parse_args(argv))
    capture = {key: args.pop('capture_' + argument) for key, argument in [('source_commit', 'source'), ('run_id', 'run_id'), ('run_attempt', 'run_attempt')]}
    verifier = {key: args.pop('verifier_' + argument) for key, argument in [('source_commit', 'source'), ('run_id', 'run_id'), ('run_attempt', 'run_attempt')]}
    result = run(**args, capture_context=capture, verifier_context=verifier)
    print(json.dumps(aggregate.plain(result), indent=2, allow_nan=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

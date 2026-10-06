#!/usr/bin/env python3
"""Run a bounded later Windows corroboration; never approve original captures.

Prepared inputs stay immutable apart from source/target. All generated traces,
process receipts and native buffers live in a separate fresh evidence directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys

import ads_source_visibility_binding as binding
import bind_reviewed_gl_supplement as reviewed_gl
import build_ads_source_packet as producer
import extract_native_profile_evidence as extraction
import prepare_finite_probe_inputs as preparation

TARGET = 'x86_64-pc-windows-msvc'
TOOLCHAIN = '1.99.0-' + TARGET
EXAMPLES = ('source_visibility_geometry_probe', 'finite_warp_probe')
MAX_REVIEW = 31 * 1024 * 1024
MAX_LOG = 256 * 1024
FALSE_FLAGS = ('original_capture_reproduced', 'original_native_upload_identity_verified',
               'original_profile_flags_modified', 'universal_profile_verified',
               'profile_native_verified', 'acceptance_complete')
require = extraction.require
safe_path = extraction.safe_path


def write_json(path, value):
    preparation.write_new(path, preparation.encoded(value))


def digest(path):
    return producer.digest(path)


def build_command(cargo):
    return [str(cargo), 'build', '--locked', '--release', '--no-default-features',
            '--features', 'legacy-macroquad,wgpu-runtime', '--target', TARGET,
            '--example', EXAMPLES[0], '--example', EXAMPLES[1]]


def distinct_roots(*roots):
    roots = [safe_path(root) for root in roots]
    require(all(a != b and a not in b.parents and b not in a.parents
                for i, a in enumerate(roots) for b in roots[i + 1:]),
            'prepared, packet, verifier and runtime roots must be disjoint')
    return roots


def read_json(path, limit=32 * 1024 * 1024):
    return preparation.parse(extraction.read_regular(path, limit))


def records(path):
    # A trace can exceed the bounded review artifact size; parse one line at a time.
    safe_path(path)
    with path.open('rb') as stream:
        for line in stream:
            require(len(line) <= 64 * 1024 * 1024, 'oversized JSONL record')
            yield preparation.parse(line)


class TraceMismatch(ValueError):
    def __init__(self, frame, differences):
        self.details = {'frame': frame, 'differences': differences,
                        'comparison': 'Exact original state comparison; no numerical tolerance applied.'}
        super().__init__(f'frame {frame}: original trace fields differ; see trace_mismatch in summary')


def differences(actual, expected, path=''):
    if type(actual) is type(expected) and isinstance(actual, dict) and set(actual) == set(expected):
        return [item for key in actual for item in differences(actual[key], expected[key], path + '/' + key)]
    if type(actual) is type(expected) and isinstance(actual, list) and len(actual) == len(expected):
        return [item for index, (a, b) in enumerate(zip(actual, expected))
                for item in differences(a, b, path + '/' + str(index))]
    if actual == expected:
        return []
    category = ('derived_proof_bound' if path.endswith('/maximum_bottom_upper') else
                'gameplay_or_time' if any(key in path for key in ('native_gameplay', 'native_time')) else
                'support_mask' if any(key in path for key in ('required_contrast_runs', 'possible_support_runs')) else
                'source_state')
    return [{'field': path, 'category': category, 'original': expected, 'later': actual}]


def companion_name(value, root):
    """Map only a verified source-root prefix; never compare basenames alone."""
    prefix = binding._recorded_path(str(root)) + '/'
    path = binding._recorded_path(value)
    require(path.startswith(prefix), 'source companion path escapes verified root')
    name = path[len(prefix):]
    require(name in binding.COMPANIONS and name.endswith('.vra'), 'unknown source companion path')
    return name


def compare_trace(trace, original, frame_ids, backend, *, empty, source_root=None, original_root=None):
    original_records = records(original)
    old_header = next(original_records)
    old_rows = {row['frame']: row for row in original_records}
    require(list(old_rows) == list(range(553)), 'original frame inventory changed')
    current = records(trace)
    header = next(current)
    require(header.get('schema') == 'rust-duty-source-geometry-probe/v1' and
            header.get('source_certificate_schema') == old_header['schema'] and
            header.get('requested_frames') == frame_ids and
            header.get('original_native_observations') is False, 'trace schema/scope differs')
    require(header.get('backend_profile') == binding.BACKEND_PROFILES[
        'windows-legacy' if backend == 'opengl' else 'dx12'], 'trace backend differs')
    for key, value in old_header.items():
        if key != 'schema':
            actual = header.get(key)
            if key == 'sources' and source_root is not None:
                actual = [{**entry, 'vra': companion_name(entry['vra'], source_root)} for entry in actual]
                value = [{**entry, 'vra': companion_name(entry['vra'], original_root)} for entry in value]
            require(key in header and actual == value, f'trace header differs: {key}')
    require(all(header.get(key) is False for key in extraction.UNPROVEN_FLAGS) and
            header.get('acceptance_verdict', 'missing') is None, 'trace original flags changed')
    result, seen = [], []
    for row in current:
        frame = row.get('frame')
        require(type(frame) is int and frame in frame_ids and frame not in seen, 'trace frame scope differs')
        seen.append(frame)
        added = {'geometry_domain', 'triangle_trace', 'original_native_observations'}
        require(set(row) == set(old_rows[frame]) | added, 'trace state inventory differs')
        actual = {key: value for key, value in row.items() if key not in added}
        expected = dict(old_rows[frame])
        if source_root is not None:
            actual['companion_catalog_vra'] = companion_name(actual['companion_catalog_vra'], source_root)
            expected['companion_catalog_vra'] = companion_name(expected['companion_catalog_vra'], original_root)
        mismatches = differences(actual, expected)
        if mismatches:
            raise TraceMismatch(frame, mismatches)
        require(row['original_native_observations'] is False and
                row['unsupported_clip_triangles'] == 0 and row['possible_support_complete'] is True,
                f'frame {frame}: unsupported or conflated trace')
        domains = [mesh['domain'] for mesh in row['geometry_domain']]
        require(domains and all(domain.get('normal_or_exact_zero_no_overflow') is True and
                type(domain.get('unsupported_domain_nodes')) is int and domain['unsupported_domain_nodes'] == 0 and
                type(domain.get('checked_abstract_nodes')) is int and domain['checked_abstract_nodes'] > 0 and
                type(domain.get('minimum_nonzero_dyadic_exponent')) is int and
                domain['minimum_nonzero_dyadic_exponent'] >= -126 and
                isinstance(domain.get('maximum_rounded_magnitude_upper'), (float, int)) and
                math.isfinite(domain['maximum_rounded_magnitude_upper']) and
                0 <= domain['maximum_rounded_magnitude_upper'] < 2**128 for domain in domains),
                f'frame {frame}: arithmetic domain is unresolved')
        require(type(row['triangle_trace']) is list, 'triangle trace is not a list')
        if empty:
            require(row['classification'] == 'expected_empty_under_profile' and
                    row['required_contrast_samples'] == row['possible_samples'] == 0 and
                    row['required_contrast_runs'] == row['possible_support_runs'] == [] and
                    row['unclassified_triangles'] == 0 and
                    row['source_triangles'] == row['outside_bottom'] + row['hidden_source_triangles'] and
                    row['triangle_trace'] == [], f'frame {frame}: empty support is not established')
            for mesh in row['meshes']:
                require(mesh['state'] == 'source_actor_hidden' or
                        (mesh['state'] == 'enumerated' and mesh['unclassified'] == 0 and
                         mesh['outside_bottom'] == mesh['triangles'] and mesh['maximum_bottom_upper'] < 0),
                        f'frame {frame}: no strict empty separator')
        else:
            require(row['classification'] == 'potentially_visible_unresolved' and
                    row['required_contrast_samples'] > 0 and row['triangle_trace'],
                    f'frame {frame}: visible scope differs')
        result.append({'frame': frame, 'full_original_state_equal': True,
                       'minimum_nonzero_dyadic_exponent': min(d['minimum_nonzero_dyadic_exponent'] for d in domains),
                       'maximum_rounded_magnitude_upper': max(d['maximum_rounded_magnitude_upper'] for d in domains),
                       'unsupported_domain_nodes': 0, 'empty_support_separated': empty})
    require(seen == frame_ids, 'trace frame sequence incomplete')
    return {'backend': backend, 'empty': empty, 'frame_count': len(seen), 'frames': result,
            'trace': digest(trace), 'original_source': digest(original),
            'later_corroboration': True, 'original_profile_flags_modified': False,
            'profile_native_verified': False, 'acceptance_verdict': None}


def canonical_lf(source, output):
    """Keep raw Windows text and a separately identified exact LF representation."""
    raw = extraction.read_regular(source, 1024 * 1024 * 1024)
    canonical = raw.replace(b'\r\n', b'\n')
    require(b'\r' not in canonical, 'non-CRLF carriage return in generated output')
    output = safe_path(output)
    with output.open('xb') as stream:
        stream.write(canonical)
    require(digest(output) == {'bytes': len(canonical), 'sha256': hashlib.sha256(canonical).hexdigest()},
            'canonical output changed while writing')
    return {'raw': digest(source), 'canonical': digest(output), 'transform': 'CRLF to LF only'}


def verify_native_report(path, trace, executable, frame_ids):
    report = read_json(path)
    expected = {'schema': 'rust-duty-finite-warp-corroboration/v1', 'status': 'passed',
                'native_execution': True, 'later_corroboration': True,
                'original_capture_reproduced': False, 'original_native_upload_identity_verified': False,
                'original_profile_flags_modified': False, 'universal_profile_verified': False,
                'acceptance_verdict': None, 'required_mask_changed': False, 'possible_mask_changed': False,
                'source_receipt_sha256': extraction.FILES[extraction.PACKET + 'source-receipt.json'][1],
                'original_dx12_jsonl_sha256': extraction.FILES[extraction.PACKET + 'oracle-output/frames-dx12.jsonl'][1],
                'trace_sha256': digest(trace)['sha256'], 'executable_sha256': digest(executable)['sha256']}
    require(all(key in report and type(report[key]) is type(value) and report[key] == value
                for key, value in expected.items()), 'native result binding/flags differ')
    require([row.get('frame') for row in report.get('frames', [])] == frame_ids, 'native frame scope incomplete')
    config = report.get('build_configuration', {})
    require(config.get('legacy_macroquad') is True and config.get('wgpu_runtime') is True and
            config.get('audio') is False and config.get('debug_assertions') is False and
            config.get('required_rust_toolchain') == '1.99.0', 'native build configuration differs')
    native = report.get('native_identity', {})
    require(native.get('backend') == 'Dx12' and native.get('device_type') == 'Cpu' and
            native.get('adapter') == 'Microsoft Basic Render Driver' and native.get('compiler') == 'Fxc' and
            native.get('runtime_modules'), 'native WARP identity incomplete')
    return {'native_report': digest(path), 'frames': len(frame_ids), 'status': 'passed',
            'native_identity': native, 'later_corroboration': True, 'acceptance_verdict': None}


def package_review(full, bounded):
    """Closed summary/log/PNG allowlist; never copy inputs, source or binaries."""
    require(not bounded.exists(), 'bounded output must be fresh')
    bounded.mkdir(parents=True)
    names = ['summary.json', 'preparation-receipt.json', 'provider-metadata.json',
             'inputs-and-implementation-before.json', 'inputs-and-implementation-after.json',
             'compiled-executables.json', 'evidence-inventory.json',
             'compiler/rustc-Vv-before.txt', 'compiler/rustc-Vv-after.txt',
             'gl/geometry-summary.json', 'gl/reviewed-binding.json', 'gl/canonicalization.json',
             'native/report.json']
    names += sorted(path.relative_to(full).as_posix() for path in (full / 'comparisons').glob('*.json'))
    names += sorted(path.relative_to(full).as_posix() for path in (full / 'logs').glob('*/*')
                    if path.name in ('stdout.log', 'stderr.log', 'invocation.json'))
    names += sorted(path.relative_to(full).as_posix() for path in (full / 'native').glob('frame-*/coverage.png'))
    included, omitted, used = {}, {}, 0
    # Reserve space for the packaging receipt, which itself counts toward the cap.
    for name in names:
        path = full / name
        if not path.exists():
            continue
        item = digest(path)
        if path.suffix == '.log' and item['bytes'] > MAX_LOG:
            with path.open('rb') as stream:
                data = stream.read(MAX_LOG // 2)
                stream.seek(-MAX_LOG // 2, os.SEEK_END)
                data += b'\n[Middle omitted from review copy; full log retained separately.]\n' + stream.read()
            truncated = True
        else:
            if item['bytes'] > MAX_REVIEW - 1024 * 1024 - used:
                omitted[name] = {**item, 'reason': 'bounded review byte limit; full evidence retained'}
                continue
            data = path.read_bytes()
            truncated = False
        if len(data) > MAX_REVIEW - 1024 * 1024 - used:
            omitted[name] = {**item, 'reason': 'bounded review byte limit; full evidence retained'}
            continue
        destination = bounded / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        included[name] = {'source': item, 'review': digest(destination), 'truncated': truncated}
        used += len(data)
    write_json(bounded / 'review-inventory.json', {
        'schema': 'rust-duty-finite-warp-review-package/v1', 'later_corroboration': True,
        'maximum_bytes': MAX_REVIEW, 'files': included, 'omitted': omitted,
        'original_inventory_assets_and_binaries_included': False, 'acceptance_verdict': None})
    total = sum(path.stat().st_size for path in bounded.rglob('*') if path.is_file())
    require(total <= MAX_REVIEW, 'bounded review artifact exceeds 31 MiB')
    return total


def run(args):
    fresh, packet, verifier, output = distinct_roots(
        args.prepared_root, args.packet_root, args.verifier_root, args.output_dir)
    provider = safe_path(args.provider_metadata)
    require(not output.exists(), 'runtime output must be fresh')
    full = output / 'full'
    full.mkdir(parents=True)
    caller = preparation.caller_identity(verifier, os.environ)
    summary = {'schema': 'rust-duty-finite-warp-profile-runner/v1', 'status': 'failed',
               'later_corroboration': True, **{key: False for key in FALSE_FLAGS}, 'acceptance_verdict': None,
               'caller_context': caller, 'capture_context': extraction.CAPTURE_CONTEXT,
               'original_source_context': extraction.SOURCE_CONTEXT, 'preparation_receipt_sha256': args.receipt_sha256,
               'phase': 'setup', 'toolchain': TOOLCHAIN, 'target': TARGET, 'executions': {}}
    executables = {}
    implementation = {}
    derived = {}
    source = fresh / 'source'
    original = fresh / 'original'

    def guard():
        current_caller = preparation.caller_identity(verifier, os.environ)
        require(current_caller == caller, 'later caller changed during execution')
        prepared = preparation.verify(packet, provider, verifier, fresh, caller, args.receipt_sha256)
        env = producer.execution_environment(source, TOOLCHAIN)
        require(env == execution_env, 'execution environment changed')
        raw = subprocess.check_output(['rustc', '-Vv'], cwd=source, env=env)
        producer.checked_compiler(raw, extraction.COMPILER_SHA256)
        current = {name: digest(path) for name, path in implementation.items()}
        require(current == implementation_before, 'caller implementation/tool bytes changed')
        for name, item in derived.items():
            require(digest(full / name) == item, 'generated corroboration input changed: ' + name)
        for name, item in executables.items():
            require(digest(source / f'target/{TARGET}/release/examples/{name}.exe') == item,
                    'compiled example changed during execution')
        return {'prepared_files': prepared['files'], 'receipt_sha256': args.receipt_sha256,
                'implementation': current, 'executables': dict(executables), 'derived_inputs': dict(derived),
                'compiler_output_sha256': hashlib.sha256(raw).hexdigest()}

    def execute(name, command, timeout):
        summary['phase'] = name
        before = guard()
        write_json(full / f'executions/{name}-before.json', before)
        try:
            receipt = producer.process(command, source, execution_env, full / f'logs/{name}', timeout)
            summary['executions'][name] = receipt
        finally:
            after = guard()
            write_json(full / f'executions/{name}-after.json', after)
            require(before == after, f'{name}: immutable input/compiler/executable identity changed')

    try:
        require(sys.platform == 'win32' and platform.machine() in ('AMD64', 'x86_64'),
                'finite native corroboration requires Windows x86_64')
        prepared = preparation.verify(packet, provider, verifier, fresh, caller, args.receipt_sha256)
        require(not (source / 'target').exists(), 'prepared source target must be absent before the sole build')
        execution_env = producer.execution_environment(source, TOOLCHAIN)
        compiler_before = subprocess.check_output(['rustc', '-Vv'], cwd=source, env=execution_env)
        producer.checked_compiler(compiler_before, extraction.COMPILER_SHA256)
        cargo = subprocess.check_output(['rustup', 'which', '--toolchain', TOOLCHAIN, 'cargo'],
                                        env=execution_env, text=True).strip()
        rustc = subprocess.check_output(['rustup', 'which', '--toolchain', TOOLCHAIN, 'rustc'],
                                        env=execution_env, text=True).strip()
        implementation = {f'verifier/{p.relative_to(verifier).as_posix()}': p
                          for p in sorted((verifier / 'tools').glob('*.py'))}
        implementation['verifier/.github/workflows/finite-warp-profile.yml'] = verifier / preparation.WORKFLOW
        implementation.update({'installed/cargo': Path(cargo), 'installed/rustc': Path(rustc)})
        implementation_before = {name: digest(path) for name, path in implementation.items()}
        write_json(full / 'provider-metadata.json', read_json(provider))
        write_json(full / 'preparation-receipt.json', prepared)
        (full / 'compiler').mkdir()
        (full / 'compiler/rustc-Vv-before.txt').write_bytes(compiler_before)
        write_json(full / 'inputs-and-implementation-before.json', guard())
        execute('build-two-diagnostics-once', build_command(cargo), 3600)
        executables.update({name: digest(source / f'target/{TARGET}/release/examples/{name}.exe') for name in EXAMPLES})
        write_json(full / 'compiled-executables.json', executables)
        recorded_root = read_json(original / 'source-packet.json')['recorded_root']
        summary['companion_path_comparison'] = {
            'original_recorded_root': recorded_root, 'restored_source_root': source.as_posix(),
            'mapping': 'Only exact verified root prefixes map to original allowed companion names; raw traces are unchanged.'}
        frames = {kind: read_json(fresh / f'{kind}-frames.json') for kind in ('visible', 'empty')}
        require(frames['visible'] == list(preparation.VISIBLE) and len(frames['empty']) == 160,
                'bounded frame scope changed')
        (full / 'traces').mkdir()
        for backend in ('opengl', 'dx12'):
            for kind in ('visible', 'empty'):
                name = f'geometry-{backend}-{kind}'
                trace = full / f'traces/{backend}-{kind}.jsonl'
                execute(name, [str(source / f'target/{TARGET}/release/examples/{EXAMPLES[0]}.exe'),
                               str(source / 'assets/animations.cfg'), str(source / 'ads-offset.cfg'),
                               backend, str(trace), str(fresh / f'{kind}-frames.json')], 1800)
                comparison = compare_trace(trace, original / f'oracle-output/frames-{backend}.jsonl',
                                           frames[kind], backend, empty=kind == 'empty',
                                           source_root=source.as_posix(), original_root=recorded_root)
                write_json(full / f'comparisons/{backend}-{kind}.json', comparison)
                derived[trace.relative_to(full).as_posix()] = comparison['trace']
        gl = full / 'gl'
        gl.mkdir()
        execute('gl-clipping-model', [sys.executable, str(verifier / 'tools/audit_source_visibility_geometry.py'),
                '--trace', str(full / 'traces/opengl-visible.jsonl'), '--native', str(original / 'oracle-output/frames-opengl.jsonl'),
                '--output', str(gl / 'clipped-raw.jsonl'), '--summary', str(gl / 'geometry-summary.json')], 3600)
        normalization = {'geometry': canonical_lf(gl / 'clipped-raw.jsonl', gl / 'clipped-reviewed.jsonl')}
        derived['gl/clipped-reviewed.jsonl'] = digest(gl / 'clipped-reviewed.jsonl')
        execute('gl-fragment-model', [sys.executable, str(verifier / 'tools/narrow_ads_fragment_support.py'),
                                     str(gl / 'clipped-reviewed.jsonl'), str(gl / 'fragment-raw.json')], 3600)
        normalization['fragment'] = canonical_lf(gl / 'fragment-raw.json', gl / 'fragment-reviewed.json')
        write_json(gl / 'canonicalization.json', normalization)
        derived['gl/fragment-reviewed.json'] = digest(gl / 'fragment-reviewed.json')
        summary['gl_canonicalization'] = normalization
        hashes_match = all(digest(path)['sha256'] == reviewed_gl._REVIEWED_SHA256[key]
                           for key, path in (('geometry', gl / 'clipped-reviewed.jsonl'),
                                             ('fragment', gl / 'fragment-reviewed.json')))
        summary['reviewed_gl_hashes_match'] = hashes_match
        if hashes_match:
            execute('gl-strict-reviewed-binding', [sys.executable, str(verifier / 'tools/bind_reviewed_gl_supplement.py'),
                    '--source-receipt', str(original / 'source-receipt.json'),
                    '--native-source', str(original / 'oracle-output/frames-opengl.jsonl'),
                    '--geometry', str(gl / 'clipped-reviewed.jsonl'), '--fragment', str(gl / 'fragment-reviewed.json'),
                    '--capture-context', *extraction.CAPTURE_CONTEXT.values(),
                    '--source-context', *extraction.SOURCE_CONTEXT.values(), '--output', str(gl / 'reviewed-binding.json')], 600)
        else:
            summary['reviewed_gl_binding'] = 'Not bound: later output differs from the exact reviewed hashes.'
        native_exe = source / f'target/{TARGET}/release/examples/{EXAMPLES[1]}.exe'
        dx_trace = full / 'traces/dx12-visible.jsonl'
        execute('finite-warp-native', [str(native_exe), '--native', '--trace', str(dx_trace),
                '--original-jsonl', str(original / 'oracle-output/frames-dx12.jsonl'),
                '--source-receipt', str(original / 'source-receipt.json'), '--source-root', str(source),
                '--output-dir', str(full / 'native')], 3600)
        summary['native_corroboration'] = verify_native_report(full / 'native/report.json', dx_trace, native_exe, frames['visible'])
        summary['status'] = 'bounded_later_corroboration_passed'
        summary['phase'] = 'completed'
    except Exception as exc:
        summary['error'] = f'{type(exc).__name__}: {exc}'
        if isinstance(exc, TraceMismatch):
            summary['trace_mismatch'] = exc.details
        raise
    finally:
        try:
            if implementation:
                write_json(full / 'inputs-and-implementation-after.json', guard())
                compiler_after = subprocess.check_output(['rustc', '-Vv'], cwd=source, env=execution_env)
                producer.checked_compiler(compiler_after, extraction.COMPILER_SHA256)
                (full / 'compiler/rustc-Vv-after.txt').write_bytes(compiler_after)
        except Exception as exc:
            summary['status'] = 'failed'
            summary['final_integrity_error'] = f'{type(exc).__name__}: {exc}'
        write_json(full / 'summary.json', summary)
        write_json(full / 'evidence-inventory.json', {path.relative_to(full).as_posix(): digest(path)
                   for path in sorted(full.rglob('*')) if path.is_file()})
        package_review(full, output / 'review')
        require(summary['status'] == 'bounded_later_corroboration_passed',
                'later corroboration incomplete; retained full evidence and bounded review')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('packet-root', 'provider-metadata', 'verifier-root', 'prepared-root', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--receipt-sha256', required=True)
    args = parser.parse_args()
    result = run(args)
    print(json.dumps({'status': result['status'], 'later_corroboration': True,
                      'profile_native_verified': False, 'acceptance_verdict': None}))


if __name__ == '__main__':
    main()

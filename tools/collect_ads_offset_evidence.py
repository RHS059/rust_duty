#!/usr/bin/env python3
"""Retain a complete ADS-offset capture pending mandatory source/aggregate checks.

This is a collection guard, never a source-visibility or authored acceptance
verdict. It permits only reproduced typed image-structure failures and their
exact blocked dependents, with every original byte and failed check retained.
"""
import argparse
import os
from pathlib import Path
import sys

import aggregate_dx12_authored as aggregate
import dx12_authored_shards as shared
import revalidate_ads_offset as leaf
import run_dx12_authored as authored
import run_dx12_authored_shard as shard
from verify_capture_telemetry import _compare, compare, read_record
from verify_render_capture import CaptureStructureError, _foreground_count, load_png, verify

SCHEMA = 'rust-duty-ads-offset-collection/v1'


def require(value, message):
    if not value:
        raise ValueError(message)


def current_context():
    require(os.environ.get('GITHUB_ACTIONS') == 'true', 'collection requires the actual GitHub runner')
    require(os.environ.get('GITHUB_REPOSITORY') == 'RHS059/rust_duty', 'collection requires the assigned repository')
    require(os.environ.get('GITHUB_REF') == 'refs/heads/main', 'collection requires current main')
    require(os.environ.get('GITHUB_WORKFLOW_REF') ==
            'RHS059/rust_duty/.github/workflows/build.yml@refs/heads/main',
            'collection requires the ordinary current build workflow')
    context = shared.context()
    require(os.environ.get('GITHUB_WORKFLOW_SHA') == context['source_commit'],
            'collection workflow differs from the current captured source')
    return context


def inspect_offset_collection(folder, binding, *, expected_context):
    """Read-only inspection; success means evidence is collectable, not accepted."""
    folder = Path(folder).absolute()
    shared.validate_binding(binding, expected_context=expected_context)
    original_sha256 = shared._read_regular(folder / 'summary.json')
    report = aggregate.read_shard(folder, 'ads-offset', binding, expected_context=expected_context)
    require('fatal_error' not in report, 'a fatal shard error cannot be deferred')
    if report['passed']:
        aggregate.shard_pass(report)
        failed_roles = []
    else:
        failed_roles = aggregate.offset_correction_eligibility(report)['failed_image_roles']
    rows = {row['name']: row for row in report['checks']}
    stock_logs = folder / 'logs/windows-legacy-stock-probe'
    stock_command = aggregate.process_receipt(stock_logs, 120, 1)
    for flag in ('--renderer=gl', '--no-update', '--procedural-weapon', '--reference-viewport', '--capture'):
        require(stock_command.count(flag) == 1, f'stock GL probe is missing exact {flag}')
    require([arg for arg in stock_command if arg.startswith('--renderer=')] == ['--renderer=gl']
            and '--force-fallback-adapter' not in stock_command, 'stock probe is not explicit native GL')
    stock_adapter = shard.legacy_renderer_logs(stock_logs)['adapter']
    shard.validate_stock_probe(folder / 'stock-gl', stock_adapter)
    frame_dirs, inspections, invocations = {}, {}, {}
    for role in aggregate.ROLES:
        invocations[role] = leaf.exact_invocation(folder, report, role, 'ads-offset')
        frames = folder / report['capture_paths'][role]
        frame_dirs[role] = frames
        backend = 'OpenGl' if role == 'windows-legacy' else 'Dx12'
        identity = shard.role_witness_identity(binding, 'ads-offset', role)
        images, finite = authored.sequence_inventory(frames, backend, expected_witness_identity=identity)
        require(len(images) == shared.PROFILES['ads-offset']['expected_frames'], 'collection requires every ADS-offset frame')
        failures, adapters = [], set()
        for index, path in enumerate(images):
            metadata = authored.capture_metadata(path, backend)
            require(metadata.get('requested') == ('gl' if role == 'windows-legacy' else 'dx12'),
                    'collection frame has the wrong requested renderer')
            adapters.add(metadata['adapter'])
            try:
                verify(path, authored.EXTENT, authored.BACKGROUND, 0.01, 8, None)
            except CaptureStructureError as error:
                require(role in failed_roles, 'an originally passing image check no longer passes')
                image = load_png(path, authored.EXTENT)
                with path.open('rb') as source:
                    header = source.read(29)
                require(len(header) == 29 and header[12:16] == b'IHDR' and header[24:26] == bytes([8, 6]),
                        'deferred source inspection requires actual RGBA8 PNG')
                failures.append({'frame': index, 'error': str(error),
                                 'foreground_coverage': _foreground_count(image, authored.BACKGROUND, 8) / (960 * 540)})
        require(len(adapters) == 1, 'collection frame adapters differ')
        require(bool(failures) == (role in failed_roles), 'original image failure did not recur as typed structure failure')
        logs = folder / 'logs' / f'{role}-capture'
        if role == 'windows-legacy':
            adapter = shard.legacy_renderer_logs(logs)['adapter']
            require(adapter == stock_adapter == next(iter(adapters)), 'stock/log/frame GL adapter differs')
        else:
            authored.renderer_logs(logs)
        if role not in failed_roles:
            result = rows[f'{role}/finite-images']['result']
            require(type(result.get('frames')) is int and result['frames'] == len(images)
                    and result.get('all_images_checked') is True, 'incomplete originally passing image receipt')
            verdict = authored.successful_report(frames / 'verification.json', images)
            aggregate.validator_receipt(folder / 'logs' / f'{role}-validator', aggregate.CASES['ads-offset'],
                                        report['capture_paths'][role], verdict)
        inspections[role] = {'frames': len(images), 'finite_json': finite,
                             'all_images_decoded': True, 'typed_structure_failures': failures}
    # The normal aggregate still reruns its original parity gate. This read-only
    # early check also refuses to defer a capture with any telemetry difference.
    parity = compare(frame_dirs['windows-legacy'], frame_dirs['dx12'])
    metadata_count = authored.compare_capture_metadata(frame_dirs['windows-legacy'], frame_dirs['dx12'],
                                                       sorted(frame_dirs['windows-legacy'].glob('*.png')))
    if failed_roles:
        leaf.native_gl_profile(folder, binding, stock_adapter, invocations['windows-legacy'])
    shared.verify_files(folder, report['files'])
    require(shared._read_regular(folder / 'summary.json') == original_sha256, 'original shard summary changed during collection')
    return {'schema': SCHEMA, 'collection_ready': True, 'needs_supplement': bool(failed_roles),
            'acceptance_complete': False, 'acceptance_deferred': bool(failed_roles),
            'capture_context': expected_context, 'capture_binding': binding,
            'original_summary_sha256': original_sha256, 'original_status': report['status'],
            'original_passed': report['passed'], 'original_checks_preserved': True,
            'images': inspections, 'exact_telemetry': parity, 'capture_metadata_files': metadata_count,
            'required_next_check': 'source-bound ADS leaf and original complete nine-shard aggregate'
                if failed_roles else 'original complete nine-shard aggregate'}


def run(*, root, input_manifest, evidence, receipt, capture_exit_code):
    root, input_manifest, evidence, receipt = map(lambda p: Path(p).absolute(), (root, input_manifest, evidence, receipt))
    require(sys.platform == 'win32', 'ordinary authored collection requires Windows')
    context = current_context()
    require(not receipt.exists() and not receipt.is_symlink(), 'refusing to replace a collection receipt')
    require(not receipt.resolve().is_relative_to(evidence.resolve()), 'collection receipt must be outside the immutable shard')
    manifest_sha256 = shared._read_regular(input_manifest)
    manifest = leaf.manifest_binding(input_manifest, context)
    binding = shared.verify_input_manifest(manifest, root / 'target/release/vector-range.exe',
                                           root / 'target/release/examples/renderer_contract.exe', root)
    result = inspect_offset_collection(evidence, binding, expected_context=context)
    require(type(capture_exit_code) is int and capture_exit_code == (1 if result['needs_supplement'] else 0),
            'capture exit status does not match the complete original shard verdict')
    shared.verify_input_manifest(manifest, root / 'target/release/vector-range.exe',
                                 root / 'target/release/examples/renderer_contract.exe', root)
    require(shared._read_regular(input_manifest) == manifest_sha256, 'native input manifest changed during collection')
    result['input_manifest_sha256'] = manifest_sha256
    receipt.parent.mkdir(parents=True, exist_ok=True)
    authored.write_json(receipt, aggregate.plain(result))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'input-manifest', 'evidence', 'receipt'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--capture-exit-code', type=int, required=True)
    args = parser.parse_args(argv)
    try:
        result = run(**vars(args))
        print('ADS-offset evidence retained; acceptance deferred to the mandatory aggregate.'
              if result['needs_supplement'] else 'Original ADS-offset checks passed; evidence retained.')
        return 0
    except Exception as error:
        print(f'ADS-offset collection rejected: {type(error).__name__}: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Restore only pinned original source/inputs for a later finite Windows probe.

No download, Cargo, Rust compiler or executable is run by this preparer. The
caller owns native execution and independently retains the preparation hash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess

import ads_source_visibility_binding as binding
import build_ads_source_packet as producer
import extract_native_profile_evidence as extraction

WORKFLOW = '.github/workflows/finite-warp-profile.yml'
TOOLCHAIN = '1.99.0-x86_64-pc-windows-msvc'
TARGET = 'x86_64-pc-windows-msvc'
SCHEMA = 'rust-duty-finite-probe-input-preparation/v1'
RECEIPT = 'preparation-receipt.json'
MAX_FILE = 32 * 1024 * 1024
MAX_SELECTED = 300 * 1024 * 1024
EXCLUDED = frozenset({
    'examples/source_visibility_certificate.rs', 'tools/build_ads_source_packet.py',
    'oracle-output/original-authored_viewmodel.rs', 'oracle-output/rustc-Vv.txt',
    'oracle-output/original-authored-inputs.log', 'oracle-output/compiler-recovery.json',
    'oracle-output/native-input-manifest.json', 'oracle-output/build-receipt.json',
    f'target/{TARGET}/release/examples/source_visibility_certificate.exe',
})
ROOT_PRODUCTION = frozenset({
    'Cargo.toml', 'Cargo.lock', 'build.rs', 'build_number.rs',
    'updater/Cargo.toml', 'updater/Cargo.lock', 'updater/build.rs',
    'assets/weapons/hk416a5.vrm',
})
OVERLAYS = (
    'examples/source_visibility_geometry_probe.rs',
    'examples/source_visibility_geometry/domain.rs',
    'examples/finite_warp_probe.rs', 'src/render/finite_warp_probe.rs',
    'src/render/mesh.rs', 'src/render/mod.rs',
)
MOD_SUFFIX = (b'\n/// Source-driven diagnostic fixture; never used by gameplay or original captures.\n'
              b'#[cfg(feature = "wgpu-runtime")]\n#[doc(hidden)]\npub mod finite_warp_probe;\n')
MESH_START = b'    /// Later finite corroboration only.'
MESH_END = b'    /// Three immutable buffers'
VISIBLE = (17,18,19,20,58,59,60,61,77,78,79,80,81,82,83,84,85,163,164,165,
           170,171,172,173,174,175,176,177,178,179,216,217,258,259,315,316,317,
           318,319,320,321,322,414,415,467,468,469,517,518,519)
require = extraction.require
safe_path = extraction.safe_path
read_regular = extraction.read_regular


def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def parse(raw):
    def reject(value):
        raise ValueError(f'nonfinite JSON: {value}')
    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject)


def relative(name):
    require(type(name) is str and name and '\\' not in name and ':' not in name,
            'invalid relative inventory path')
    path = PurePosixPath(name)
    require(not path.is_absolute() and path.as_posix() == name and
            all(part not in ('.', '..') and not part.endswith((' ', '.')) for part in path.parts),
            'noncanonical relative inventory path')
    require(all(part.split('.')[0].upper() not in
                {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
                 *(f'LPT{i}' for i in range(1, 10))} for part in path.parts), 'reserved Windows path')
    return name


def caller_identity(root, environ):
    expected = {'GITHUB_ACTIONS': 'true', 'GITHUB_SERVER_URL': 'https://github.com',
                'GITHUB_REPOSITORY': extraction.REPOSITORY, 'GITHUB_REF': 'refs/heads/main',
                'GITHUB_EVENT_NAME': 'push', 'GITHUB_RUN_ATTEMPT': '1',
                'GITHUB_WORKFLOW_REF': f'{extraction.REPOSITORY}/{WORKFLOW}@refs/heads/main'}
    require(all(environ.get(key) == value for key, value in expected.items()),
            'requires exact finite main push workflow, first attempt')
    commit, run = environ.get('GITHUB_SHA', ''), environ.get('GITHUB_RUN_ID', '')
    require(re.fullmatch(r'[0-9a-f]{40}', commit) and environ.get('GITHUB_WORKFLOW_SHA') == commit,
            'caller workflow/source mismatch')
    require(re.fullmatch(r'[1-9][0-9]*', run) and run not in
            (extraction.CAPTURE_CONTEXT['run_id'], extraction.SOURCE_CONTEXT['run_id']),
            'invalid or conflated caller run')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=root, text=True)
    require(head == commit and not dirty, 'requires clean checkout of caller commit')
    # Untracked additions must not supply any executable helper or overlay.
    tracked = set(subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0'))
    require(set(OVERLAYS).issubset(tracked), 'all overlays must be published in caller commit')
    return {'repository': extraction.REPOSITORY, 'workflow': WORKFLOW, 'source_commit': commit,
            'run_id': run, 'run_attempt': '1', 'event': 'push', 'branch': 'main'}


def validate_inventory(packet, receipt):
    entries = receipt['inputs_and_implementation_before']
    require(type(entries) is dict and len(entries) == 137 and
            entries == receipt['inputs_and_implementation_after'], 'original inventory must have 137 stable entries')
    require(type(packet.get('files')) is dict and set(packet['files']) == set(entries),
            'packet inventory key mismatch')
    require(packet.get('input_files') == {name: name for name in binding.INPUTS},
            'consumed input set differs from original 18 companions and 3 configs')
    require(len({name.casefold() for name in entries}) == len(entries), 'case-aliased inventory keys')
    for name, item in entries.items():
        relative(name)
        require(packet['files'][name] == 'inventory/' + name, 'noncanonical packet file mapping')
        require(type(item) is dict and set(item) == {'bytes', 'sha256'} and
                type(item['bytes']) is int and 0 < item['bytes'] <= MAX_FILE and
                type(item['sha256']) is str and re.fullmatch('[0-9a-f]{64}', item['sha256']),
                f'invalid inventory identity: {name}')
    selected = set(entries) - EXCLUDED
    require(EXCLUDED.issubset(entries) and len(selected) == 128 and
            binding.INPUTS.issubset(selected), 'unexpected restoration scope')
    # Same production boundary as build_ads_source_packet.production_files;
    # exact receipt SHA fixes all members. No asset discovery or expansion.
    require(all(name in ROOT_PRODUCTION or name in binding.INPUTS or
                name.startswith(('src/', 'updater/src/')) for name in selected),
            'unselected source/input path')
    require(sum(entries[name]['bytes'] for name in selected) <= MAX_SELECTED, 'restoration byte bound')
    require(receipt.get('toolchain') == TOOLCHAIN, 'original compiler toolchain mismatch')
    oracle = receipt['oracle_execution']
    require(oracle['platform'] == 'win32' and oracle['host'] == oracle['target'] == TARGET and
            oracle['profile'] == 'release' and oracle['features'] == producer.FEATURES,
            'original oracle build context mismatch')
    return {name: entries[name] for name in sorted(selected)}


def checked_overlay(name, old, new):
    if name == 'src/render/mesh.rs':
        require(new.count(MESH_START) == new.count(MESH_END) == 1, 'mesh diagnostic markers differ')
        first, last = new.index(MESH_START), new.index(MESH_END)
        require(first < last and new[:first] + new[last:] == old,
                'mesh overlay changes original production bytes')
    elif name == 'src/render/mod.rs':
        require(new.endswith(MOD_SUFFIX) and new[:-len(MOD_SUFFIX)] == old,
                'module overlay changes original production bytes')
    else:
        require(old is None, 'new diagnostic overlay collides with original source')
    return new


def load_inputs(packet_root, provider_path, verifier_root):
    provider = extraction.verify_provider(parse(read_regular(provider_path, extraction.MAX_JSON_BYTES)))
    pinned = {}
    for name, (size, digest) in extraction.FILES.items():
        suffix = name.removeprefix(extraction.PACKET)
        data = read_regular(packet_root / suffix, MAX_FILE)
        require((size is None or len(data) == size) and identity(data)['sha256'] == digest,
                f'pinned original file mismatch: {suffix}')
        pinned[name] = data
    receipt = extraction.validate_documents(pinned)
    packet = parse(pinned[extraction.PACKET + 'source-packet.json'])
    selected = validate_inventory(packet, receipt)
    originals = {}
    for name in (*selected, 'oracle-output/original-authored_viewmodel.rs', 'oracle-output/rustc-Vv.txt'):
        data = read_regular(packet_root / packet['files'][name], MAX_FILE)
        require(identity(data) == receipt['inputs_and_implementation_before'][name],
                f'original inventory bytes changed: {name}')
        originals[name] = data
    producer.reviewed_bridge(originals['oracle-output/original-authored_viewmodel.rs'],
                             originals['src/authored_viewmodel.rs'])
    producer.checked_compiler(originals['oracle-output/rustc-Vv.txt'], extraction.COMPILER_SHA256)
    overlays = {name: read_regular(verifier_root / name, MAX_FILE) for name in OVERLAYS}
    for name, data in overlays.items():
        checked_overlay(name, originals.get(name), data)
    return provider, pinned, selected, originals, overlays


def frame_lists(raw, backend='dx12'):
    records = [parse(line) for line in raw.splitlines()]
    require(backend in ('dx12', 'opengl'), 'unsupported frame backend')
    role = 'dx12' if backend == 'dx12' else 'windows-legacy'
    require(len(records) == 554 and records[0]['backend_profile'] == binding.BACKEND_PROFILES[role],
            'original frame backend context differs')
    rows = records[1:]
    require(all(type(row.get('frame')) is int and row['frame'] == i for i, row in enumerate(rows)),
            'original source frame sequence differs')
    empty = [row['frame'] for row in rows if row['classification'] == 'expected_empty_under_profile']
    require(len(empty) == 160 and not set(empty).intersection(VISIBLE), 'empty frame scope differs')
    for frame in (*VISIBLE, *empty):
        row = rows[frame]
        require(row.get('acceptance_verdict', 'missing') is None and
                row.get('possible_support_complete') is True and
                type(row.get('unsupported_clip_triangles')) is int and row['unsupported_clip_triangles'] == 0,
                'unproven/unsupported selected original frame')
        for field in ('possible_samples', 'required_contrast_samples'):
            require(type(row.get(field)) is int and row[field] >= 0, 'invalid source sample count')
        if frame in VISIBLE:
            require(row['classification'] == 'potentially_visible_unresolved' and
                    row['possible_samples'] >= row['required_contrast_samples'] > 0 and
                    row['required_contrast_runs'] and row['possible_support_runs'], 'visible source scope differs')
        else:
            require(row['possible_samples'] == row['required_contrast_samples'] == 0 and
                    row['required_contrast_runs'] == row['possible_support_runs'] == [], 'empty source scope differs')
    return {'visible-frames.json': list(VISIBLE), 'empty-frames.json': empty,
            'fallback-frames.json': sorted([*VISIBLE, *empty])}


def write_new(path, data):
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
    require(read_regular(path, MAX_FILE) == data, 'output changed during write')


def closed_inventory(root, expected, allow_target):
    observed = set()
    for directory, dirs, files in os.walk(safe_path(root), followlinks=False):
        for name in list(dirs):
            path = safe_path(Path(directory) / name)
            require(stat.S_ISDIR(path.lstat().st_mode), 'unexpected output directory')
            relative_path = path.relative_to(root).as_posix()
            if relative_path == 'source/target' and allow_target:
                dirs.remove(name)  # Fresh Cargo outputs are never restored inputs.
            else:
                require(any(item.startswith(relative_path + '/') for item in expected),
                        f'unexpected output directory: {relative_path}')
        for name in files:
            path = safe_path(Path(directory) / name)
            item = path.relative_to(root).as_posix()
            require(item in expected, f'unexpected output file: {item}')
            require(identity(read_regular(path, MAX_FILE)) == expected[item], f'output changed: {item}')
            observed.add(item)
    require(observed == set(expected), 'closed output inventory mismatch')


def expected_outputs(pinned, selected, originals, overlays):
    outputs = {'source/' + name: originals[name] for name in selected}
    outputs.update({'source/' + name: data for name, data in overlays.items()})
    outputs.update({'original/' + name.removeprefix(extraction.PACKET): data for name, data in pinned.items()})
    for name in ('original-authored_viewmodel.rs', 'rustc-Vv.txt'):
        outputs['original/' + name] = originals['oracle-output/' + name]
    frames = frame_lists(pinned[extraction.PACKET + 'oracle-output/frames-dx12.jsonl'])
    require(frame_lists(pinned[extraction.PACKET + 'oracle-output/frames-opengl.jsonl'], 'opengl') == frames,
            'GL/DX source-driven finite frame scopes differ')
    outputs.update({name: encoded(value) for name, value in frames.items()})
    return outputs


def prepare(packet_root, provider_path, verifier_root, output, caller):
    output = safe_path(output)
    require(not output.exists(), 'output must be fresh')
    provider, pinned, selected, originals, overlays = load_inputs(packet_root, provider_path, verifier_root)
    outputs = expected_outputs(pinned, selected, originals, overlays)
    report = {'schema': SCHEMA, 'caller_context': caller, 'source_provider': provider,
              'capture_context': extraction.CAPTURE_CONTEXT, 'source_execution_context': extraction.SOURCE_CONTEXT,
              'source_base_commit': extraction.CAPTURE_CONTEXT['source_commit'], 'toolchain': TOOLCHAIN,
              'capture_rustc_sha256': extraction.COMPILER_SHA256,
              'restored_original_inventory': selected, 'diagnostic_overlays': {name: identity(data) for name, data in overlays.items()},
              'files': {name: identity(data) for name, data in outputs.items()},
              'new_native_execution': False, 'profile_native_verified': False, 'acceptance_verdict': None,
              'scope': 'Only pinned original source and 21 inputs, with six explicitly bound diagnostic overlays. '
                       'Production bytes recover exactly after removing reviewed additions. '
                       'Pinned visible IDs define finite scope; empty IDs come from original source classifications. '
                       'No native comparator, profile acceptance, intermediate identity or execution is established.'}
    raw = encoded(report)
    output.mkdir(parents=True, exist_ok=False)
    for name, data in outputs.items():
        write_new(output / name, data)
    write_new(output / RECEIPT, raw)
    anchor = identity(raw)['sha256']
    verify(packet_root, provider_path, verifier_root, output, caller, anchor, allow_target=False)
    return anchor


def verify(packet_root, provider_path, verifier_root, output, caller, anchor, *, allow_target=True):
    require(type(anchor) is str and re.fullmatch('[0-9a-f]{64}', anchor), 'external receipt SHA required')
    raw = read_regular(output / RECEIPT, extraction.MAX_JSON_BYTES)
    require(identity(raw)['sha256'] == anchor, 'preparation receipt differs from external anchor')
    report = parse(raw)
    require(report.get('schema') == SCHEMA and report.get('caller_context') == caller,
            'preparation caller/schema changed')
    require(report.get('capture_context') == extraction.CAPTURE_CONTEXT and
            report.get('source_execution_context') == extraction.SOURCE_CONTEXT and
            report.get('source_base_commit') == extraction.CAPTURE_CONTEXT['source_commit'] and
            report.get('toolchain') == TOOLCHAIN and
            report.get('capture_rustc_sha256') == extraction.COMPILER_SHA256,
            'preparation source/capture/compiler context changed')
    require(report.get('new_native_execution') is False and report.get('profile_native_verified') is False and
            report.get('acceptance_verdict', 'missing') is None, 'preparation flags must remain false/null')
    provider, pinned, selected, originals, overlays = load_inputs(packet_root, provider_path, verifier_root)
    outputs = expected_outputs(pinned, selected, originals, overlays)
    expected = {name: identity(data) for name, data in outputs.items()}
    require(report.get('files') == expected and report.get('restored_original_inventory') == selected and
            report.get('diagnostic_overlays') == {name: identity(data) for name, data in overlays.items()} and
            report.get('source_provider') == provider, 'preparation inputs or overlays changed')
    closed_inventory(output, {**expected, RECEIPT: identity(raw)}, allow_target)
    packet = parse(pinned[extraction.PACKET + 'source-packet.json'])
    producer.validate_consumed_inputs(output / 'source', {'binding': packet['capture_binding']},
                                      output / 'source/ads-offset.cfg')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'verify', 'verify-provider'))
    parser.add_argument('--provider-metadata', type=Path, required=True)
    parser.add_argument('--verifier-root', type=Path, default=Path.cwd())
    parser.add_argument('--packet-root', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--receipt-sha256')
    args = parser.parse_args()
    verifier = safe_path(args.verifier_root)
    caller = caller_identity(verifier, os.environ)
    provider = safe_path(args.provider_metadata)
    if args.command == 'verify-provider':
        print(json.dumps(extraction.verify_provider(parse(read_regular(provider, extraction.MAX_JSON_BYTES))), sort_keys=True))
        return
    require(args.packet_root is not None and args.output_dir is not None, 'packet-root and output-dir required')
    packet, output = safe_path(args.packet_root), safe_path(args.output_dir)
    require(not (output == packet or output in packet.parents or packet in output.parents or
                 output == verifier or output in verifier.parents), 'overlapping source/output roots')
    if args.command == 'prepare':
        require(args.receipt_sha256 is None, 'prepare emits an external anchor; it does not consume one')
        anchor = prepare(packet, provider, verifier, output, caller)
        print('FINITE_PREPARATION_RECEIPT_SHA256=' + anchor, flush=True)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
                stream.write(f'receipt_sha256={anchor}\n')
    else:
        verify(packet, provider, verifier, output, caller, args.receipt_sha256)
        print('Pinned original source, inputs, diagnostics and separate contexts are unchanged.')


if __name__ == '__main__':
    main()

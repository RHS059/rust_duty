#!/usr/bin/env python3
"""Run fresh current-source profile checks using independently prepared tools.

The native images are only used to select which original generic failures need
proof. They never supply a mask, geometry bound, or visibility expectation.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys

import ads_source_visibility_binding as source
import build_ads_source_packet as producer
import current_ads_native_binding as native
import current_ads_profile_proof as gl
import dx12_authored_shards as shared
import prepare_current_ads_profile as prepared
from verify_capture_telemetry import _compare, read_record

SCHEMA = 'rust-duty-current-ads-profile/v1'
require = source._require


def run(*, root, input_manifest, source_packet, bound_source, source_receipt_sha256,
        profile_oracle, profile_oracle_receipt_sha256, capture_rustc_sha256,
        fallback_frames, evidence, build_identity):
    root, input_manifest, source_packet, profile_oracle, evidence = [Path(p).absolute() for p in
        (root, input_manifest, source_packet, profile_oracle, evidence)]
    require(not evidence.exists(), 'current profile output must be fresh')
    source.shared._exact_keys(fallback_frames, source.ROLES, 'current fallback frame roles')
    require(any(fallback_frames.values()), 'current profile requires a reproduced generic failure')
    for frames in fallback_frames.values():
        if frames:
            gl.frame_ids(frames)
    verified = prepared.verify_precompiled(profile_oracle, root, input_manifest,
        profile_oracle_receipt_sha256, capture_rustc_sha256)
    raw_preparation = read_record(verified['receipt_path'])
    _compare(raw_preparation['recorded_root'].replace('\\', '/'), root.as_posix(), 'current profile original build root')
    require(type(bound_source) is source.BoundSourcePacket, 'current profile needs an independently bound source packet')
    native_rows = native.bind_all_native_frames(bound_source)
    descriptor = read_record(source_packet)
    source_receipt = bound_source._portable(source_packet.parent, descriptor['receipt'])
    require(shared._read_regular(source_receipt) == source_receipt_sha256,
            'current profile source receipt differs from independent anchor')
    expected = {role: bound_source._portable(source_packet.parent, descriptor['source_outputs'][role]) for role in source.ROLES}
    evidence.mkdir(parents=True)
    package = evidence / 'precompiled'
    package.mkdir()
    for name in (*prepared.FILES, 'receipt.json'):
        producer.copy_packet_file(profile_oracle / name, package / name, producer.digest(profile_oracle / name))
    env = producer.execution_environment(root, raw_preparation['active_toolchain_alias'])
    executions, traces, selections, proof_outputs = {}, {}, {}, {}
    for role in source.ROLES:
        frames = fallback_frames[role]
        if not frames:
            continue
        backend = source.BACKENDS[role][0]
        selections[role] = f'{backend}-frames.json'
        producer.write_json(evidence / selections[role], frames)
        trace = evidence / f'{backend}-trace.jsonl'
        command = [str(package / prepared.EXECUTABLES['source_visibility_geometry_probe']),
                   str(root / 'assets/animations.cfg'),
                   str(bound_source._portable(source_packet.parent, descriptor['files'][descriptor['input_files']['ads-offset.cfg']])),
                   backend, str(trace), str(evidence / selections[role])]
        prepared.verify_precompiled(package, root, input_manifest, profile_oracle_receipt_sha256, capture_rustc_sha256)
        executions[backend + '-geometry'] = producer.process(command, root, env,
                                                             evidence / 'logs' / (backend + '-geometry'), 2700)
        traces[role] = trace.name
        if role == 'windows-legacy':
            command = [sys.executable, str(root / 'tools/current_ads_profile_proof.py'),
                       '--trace', str(trace), '--expected', str(expected[role]),
                       '--source-receipt', str(source_receipt), '--expected-receipt-sha256', source_receipt_sha256,
                       '--frames', str(evidence / selections[role]), '--output-dir', str(evidence / 'gl')]
            executions['gl-model'] = producer.process(command, root, env, evidence / 'logs/gl-model', 3600)
            proof_outputs[role] = 'gl/proof.json'
        else:
            # The current WARP all-triangle/fragment probe is required only for
            # positive support. Strictly separated empty rows are still covered
            # by the complete arithmetic/triangle partition in the same trace.
            visible = [frame for frame in frames
                       if bound_source.rows_by_role[role][frame]['classification'] != 'expected_empty_under_profile']
            if visible:
                producer.write_json(evidence / 'dx12-visible-frames.json', visible)
                rows = list(gl.records(trace))
                visible_trace = evidence / 'dx12-visible-trace.jsonl'
                header = rows[0]
                header['requested_frames'] = visible
                with visible_trace.open('x', encoding='utf-8', newline='\n') as output:
                    # Preserve float tokens: decimal expected state is part of
                    # the original source replay, so select raw JSONL bytes.
                    output.write(json.dumps(header, default=float, separators=(',', ':')) + '\n')
                    raw_lines = trace.read_bytes().splitlines()
                    for line, row in zip(raw_lines[1:], rows[1:]):
                        if row['frame'] in visible:
                            output.write(line.decode('utf-8') + '\n')
                command = [str(package / prepared.EXECUTABLES['finite_warp_probe']), '--native',
                           '--trace', str(visible_trace), '--original-jsonl', str(expected[role]),
                           '--source-receipt', str(source_receipt), '--source-root', str(root),
                           '--output-dir', str(evidence / 'warp'),
                           '--current-source-receipt-sha256', source_receipt_sha256,
                           '--frames-json', str(evidence / 'dx12-visible-frames.json')]
                prepared.verify_precompiled(package, root, input_manifest, profile_oracle_receipt_sha256, capture_rustc_sha256)
                executions['dx12-native'] = producer.process(command, root, env, evidence / 'logs/dx12-native', 3600)
                proof_outputs[role] = 'warp/report.json'
    bound_source.verify_unchanged()
    prepared.verify_precompiled(package, root, input_manifest, profile_oracle_receipt_sha256, capture_rustc_sha256)
    manifest = {'schema': SCHEMA, 'capture_binding': deepcopy(bound_source.capture_binding),
                'build_identity': deepcopy(build_identity), 'source_packet_sha256': shared._read_regular(source_packet),
                'source_receipt_sha256': source_receipt_sha256, 'capture_rustc_sha256': capture_rustc_sha256,
                'profile_oracle_receipt_sha256': profile_oracle_receipt_sha256,
                'input_manifest': 'precompiled/input-manifest.json', 'precompiled': 'precompiled',
                'fallback_frames': deepcopy(fallback_frames), 'selections': selections, 'traces': traces,
                'proof_outputs': proof_outputs, 'executions': executions,
                'native_input_binding': native_rows, 'acceptance_verdict': None,
                'files': shared.inventory_files(evidence, exclude=())}
    path = evidence / 'current-profile.json'
    producer.write_json(path, manifest)
    return {'path': path, 'sha256': shared._read_regular(path)}

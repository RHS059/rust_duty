#!/usr/bin/env python3
"""Accept only a complete, fresh current-frame ADS profile certificate.

Historical finite classes remain separate. This path binds current asset-derived
expectations to actual submitted inputs, fresh GL operational proofs and a native
WARP all-triangle/fragment corroboration. Existing image checks still decide
whether the captures satisfy those independently derived obligations.
"""
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import re
from pathlib import Path

import ads_source_visibility_binding as source
import current_ads_build_context as context
import current_ads_native_binding as native
import current_ads_profile_proof as gl
import finite_ads_profile_binding as historical
import prepare_current_ads_profile as prepared
import run_current_ads_profile as runner
from verify_capture_telemetry import _compare, read_record

SCHEMA = runner.SCHEMA
# The operational proof is specific to these Mesa/LLVM runtime implementation bytes.
# Unlike an application source whitelist, this bounds only the numerical model.
MESA_RUNTIME = {'libffi-8.dll': 'f96cf79b75f33a10023d001673b564538023395c94b3c58e1db53114976a7c25', 'libgallium_wgl.dll': '42362a4b7063591ad1f2bf5d1dbf26fb808ac49cb419ac237d63c8f1cb49bc75', 'libgcc_s_seh-1.dll': '68ca4574b331402879dec403ba4f14491c9b8fc4aa3f4a41432008714b9bc5df', 'libiconv-2.dll': '94ec68fb8d342b6c91b6b48a8d95092819cdcd006a7166e0b68062f946afd08a', 'libintl-8.dll': '0e5a178731e6be6d115442a6ade3df7f03265cd1fc4338f8b6f86a8001cbf582', 'libLLVM-22.dll': 'ecef91d79184533faa2d74d1965c0737843f4c2e02c7cb8dd3309a6c97ddec9b', 'libSPIRV-Tools.dll': '1f7de3a18d76fa6ffa27ce54cf6f532d44a819075bc162f5814c0e5dc427e224', 'libstdc++-6.dll': 'b30dbd914d903992acb28b38455947153886656beafbd91c465c31aa258f9c45', 'libsystre-0.dll': 'f933efd15c898dd2040e21f15801e3c7dc186f5b2cee353c9747afc9e5b54000', 'libtre-5.dll': '1014afb8649e6eba839748cc0ad5dc542249df831ee483f7a93e465e223f7bae', 'libwinpthread-1.dll': '76cc52adfcdb8c800813b2ae8da42a908934eb1ee54ce8e9744fc8d703c76ee1', 'libxml2-16.dll': '5cf84e4be1d9da56a6269b1bd18c8ab5fcce11087aa24002dfce57e46238455b', 'libzstd.dll': '48368ab0ca622d0ec12f41ce85d91f22866bf5da92c77a69a06483564c93816c', 'opengl32.dll': 'f73078a77b51c634faa36f616a8eb9f7f1b30f82b21d689267b9146dbbc8b943', 'zlib1.dll': '11cd91171765cd65f1c3362e3df67e5f5a618a6b88c8cdec899b802eaf1c7b0d'}
require = source._require


def verify_shader_semantics(raw):
    """The empty-frame separator uses only this fixed vertex operation graph.

    Bind semantic kernels rather than unrelated source files or historical rows.
    Comments/whitespace and unrelated fragment entry points may change freely.
    """
    text = re.sub(r'//[^\n]*|/\*.*?\*/', '', raw.decode('utf-8'), flags=re.S)
    compact = re.sub(r'\s+', '', text)
    for expression in (
        'struct Transform { mvp: mat4x4<f32>, };',
        '@group(0) @binding(0) var<uniform> transform: Transform;',
        '@vertex fn vs_main(input: VertexInput) -> VertexOutput { var output: VertexOutput; '
        'output.position = transform.mvp * vec4<f32>(input.position,1.0); '
        'output.uv = input.uv; output.color = input.color; return output; }',
        '@fragment fn fs_straight(input: VertexOutput) -> @location(0) vec4<f32> { '
        'return textureSample(color_texture,color_sampler,input.uv) * input.color; }',
    ):
        require(compact.count(re.sub(r'\s+', '', expression)) == 1,
                'current shader lies outside the certified arithmetic/fragment operation graph')


def _snapshot(value):
    return historical._canonical(value)


def _read_trace(path, expected, frames):
    records = list(gl.records(path))
    require(records and records[0].get('requested_frames') == frames, 'current trace frame scope differs')
    rows = gl.rows_by_frame(records[1:], 'current trace')
    require(list(rows) == frames, 'current trace is incomplete or out of order')
    for frame, row in rows.items():
        original = expected[frame]
        keys = set(row) - gl.TRACE_EXTRAS
        require(keys == set(original), 'current trace source state inventory differs')
        _compare({key: row[key] for key in keys}, original, 'current trace full source state')
        meshes = gl.source_meshes(row, records[0]['sources'])
        domains = gl.arithmetic_domains(row, meshes)
        gl.triangles_and_partition(row, meshes, domains)
        if original['classification'] == 'expected_empty_under_profile':
            require(original['unclassified_triangles'] == original['required_contrast_samples'] ==
                    original['possible_samples'] == original['unsupported_clip_triangles'] == 0
                    and original['possible_support_complete'] is True and not row['triangle_trace']
                    and original['source_triangles'] == original['outside_bottom'] + original['hidden_source_triangles'],
                    'current empty frame lacks complete source separation')
    return records[0], rows


def _process(ledger, folder, name, saved, expected_command, root):
    receipt = ledger._json(folder / 'logs' / name / 'invocation.json')
    _compare(receipt, saved, 'current original process receipt')
    command = source._oracle_process(receipt, source._recorded_path(root.as_posix()), 'current profile ' + name)
    normalize = lambda parts: [str(part).replace('\\', '/') for part in parts]
    _compare(normalize(command), normalize(expected_command), 'current profile exact execution argv')


def _warp(ledger, folder, manifest, packet, trace_rows, prepared_receipt, executable, expected_path):
    visible = [frame for frame in manifest['fallback_frames']['dx12']
               if packet.rows_by_role['dx12'][frame]['classification'] != 'expected_empty_under_profile']
    if not visible:
        require('dx12' not in manifest['proof_outputs'] and 'dx12-native' not in manifest['executions'],
                'unexpected current native positive-support evidence')
        return None
    report = ledger._json(folder / manifest['proof_outputs']['dx12'])
    expected = {'schema': 'rust-duty-current-warp-corroboration/v1', 'status': 'passed',
        'native_execution': True, 'later_corroboration': True, 'original_capture_reproduced': False,
        'original_native_upload_identity_verified': False, 'original_profile_flags_modified': False,
        'universal_profile_verified': False, 'acceptance_verdict': None,
        'required_mask_changed': False, 'possible_mask_changed': False,
        'source_receipt_sha256': manifest['source_receipt_sha256'],
        'original_dx12_jsonl_sha256': ledger._remember(expected_path)['sha256'],
        'trace_sha256': ledger._remember(folder / 'dx12-visible-trace.jsonl')['sha256'],
        'executable_sha256': ledger._remember(executable)['sha256'],
        'viewport': [0, 0, 960, 540], 'target_format': 'Rgba8Unorm', 'sample_count': 1,
        'depth_enabled': False, 'blend_modes': ['disabled', 'production_alpha_over_opaque_black',
                                             'production_alpha_over_opaque_white'],
        'fragment_entry_point': 'fs_straight', 'frame_witness_excluded': [0, 0, 64, 22]}
    for key, value in expected.items():
        _compare(report.get(key), value, 'current WARP ' + key)
    _compare(report.get('current_source_scope'), {'frames': visible,
        'frames_json_sha256': ledger._remember(folder / 'dx12-visible-frames.json')['sha256'],
        'complete_source_partitions_checked': True, 'receipt_anchor_origin': 'independent caller argument',
        'source_expectations_receipt_bound': True, 'native_capture_upload_identity_verified': False}, 'current WARP scope')
    config = report.get('build_configuration', {})
    for key, value in {'legacy_macroquad': True, 'wgpu_runtime': True, 'audio': False,
                       'debug_assertions': False, 'required_rust_toolchain': prepared_receipt['toolchain']}.items():
        _compare(config.get(key), value, 'current WARP build ' + key)
    rows = report.get('frames')
    require(type(rows) is list and [row.get('frame') for row in rows] == visible, 'current WARP complete frame scope missing')
    triangles = required = color_triangles = 0
    for result in rows:
        frame = result['frame']
        original = packet.rows_by_role['dx12'][frame]
        count = len(trace_rows[frame]['triangle_trace'])
        require(count > 0 and original['required_contrast_samples'] > 0, 'current visible support unresolved')
        for key, value in {'source_triangles': count, 'per_triangle_support_guard_passed': True,
                           'required_samples': original['required_contrast_samples'],
                           'production_alpha_blend_endpoints_verified': True,
                           'negative_controls': {key: 'rejected' for key in historical.CONTROLS}}.items():
            _compare(result.get(key), value, 'current WARP frame ' + key)
        frame_dir = folder / 'warp' / f'frame-{frame:04}'
        for key, name in (('draws_sha256', 'draws.jsonl'), ('color_observations_sha256', 'color-observations.jsonl')):
            _compare(result.get(key), ledger._remember(frame_dir / name)['sha256'], 'current WARP raw ' + key)
        triangles += count
        required += original['required_contrast_samples']
        color_triangles += result['color_probe_triangles']
    _compare(report.get('source_triangle_count'), triangles, 'current all-triangle WARP scope')
    _compare(report.get('support_guard_draw_count'), triangles, 'current all-triangle WARP guards')
    _compare(report.get('color_probe_triangle_count'), color_triangles, 'current fragment WARP scope')
    identity = report.get('native_identity')
    require(type(identity) is dict and identity.get('backend') == 'Dx12' and identity.get('device_type') == 'Cpu'
            and identity.get('adapter') == 'Microsoft Basic Render Driver' and identity.get('compiler') == 'Fxc'
            and identity.get('runtime_modules'), 'current native WARP identity missing')
    return identity


@dataclass(frozen=True)
class BoundCurrentAdsProfile:
    source_packet: source.BoundSourcePacket = field(repr=False)
    _ledger: source.BoundSourcePacket = field(repr=False)
    _rows: dict = field(repr=False)
    _state: dict = field(repr=False)
    _summary: dict = field(repr=False)
    _path: Path = field(repr=False)
    _files: dict = field(repr=False)
    bounded_ads_profile_established: bool = field(default=True, init=False)

    def summary(self):
        return deepcopy(self._summary)

    def verify_frame_binding(self, path, role, index):
        require(role in self._rows and index in self._rows[role], 'current fallback outside certified frame scope')
        original = self.source_packet.verify_frame_binding(path, role, index)
        _compare(_snapshot(original), self._state[role][index], 'late current source state mutation')
        return deepcopy(self._rows[role][index])

    def verify_unchanged(self):
        _compare(self.source_packet.capture_binding, self._summary['capture_binding'], 'late current capture binding mutation')
        self.source_packet.verify_unchanged()
        self._ledger.verify_unchanged()
        actual = source.shared.inventory_files(self._path.parent, exclude=())
        actual.pop(self._path.name)
        _compare(actual, self._files, 'current profile evidence file set changed')
        for role, rows in self._state.items():
            for index, state in rows.items():
                _compare(_snapshot(self.source_packet.rows_by_role[role][index]), state, 'late current source state mutation')


def bind_current_ads_profile(*, source_packet, source_packet_path, reviewed_class,
                             expected_class_sha256, native_runtime_logs):
    require(type(source_packet) is source.BoundSourcePacket, 'current profile requires independently bound source')
    ledger = source.BoundSourcePacket()
    path = Path(reviewed_class).absolute()
    require(ledger._remember(path)['sha256'] == native._sha(expected_class_sha256, 'current independent profile anchor'),
            'current profile differs from independently retained SHA256')
    manifest = ledger._json(path)
    require(manifest.get('schema') == SCHEMA, 'unsupported current profile')
    source.shared._exact_keys(manifest, ('schema', 'capture_binding', 'build_identity', 'source_packet_sha256',
        'source_receipt_sha256', 'capture_rustc_sha256', 'profile_oracle_receipt_sha256', 'input_manifest',
        'precompiled', 'fallback_frames', 'selections', 'traces', 'proof_outputs', 'executions',
        'native_input_binding', 'acceptance_verdict', 'files'), 'current profile manifest')
    _compare(manifest['acceptance_verdict'], None, 'current profile is not full acceptance')
    source.shared.compare_binding(manifest['capture_binding'], source_packet.capture_binding)
    identity = context.current_build_identity()
    _compare(manifest['build_identity'], identity, 'current profile actual build identity')
    root = Path(__file__).resolve().parents[1]
    context.check_build_checkout(root, identity)
    packet_path = Path(source_packet_path).absolute()
    _compare(ledger._remember(packet_path)['sha256'], manifest['source_packet_sha256'], 'current exact source packet')
    descriptor = ledger._json(packet_path)
    shader_path = ledger._portable(packet_path.parent, descriptor['files']['src/render/mesh.wgsl'])
    verify_shader_semantics(ledger._read(shader_path))
    receipt_path = ledger._portable(packet_path.parent, descriptor['receipt'])
    _compare(ledger._remember(receipt_path)['sha256'], manifest['source_receipt_sha256'], 'current source receipt anchor')
    folder = path.parent
    actual = source.shared.inventory_files(folder, exclude=())
    actual.pop(path.name)
    _compare(actual, manifest['files'], 'complete current proof file inventory')
    for name, digest in actual.items():
        _compare(ledger._remember(ledger._portable(folder, name))['sha256'], digest, 'current profile file ' + name)
    prebuilt = prepared.verify_precompiled(folder / manifest['precompiled'], root,
        folder / manifest['input_manifest'], manifest['profile_oracle_receipt_sha256'], manifest['capture_rustc_sha256'])
    preparation = ledger._json(prebuilt['receipt_path'])
    native_manifest = ledger._json(folder / manifest['input_manifest'])
    reference = native_manifest['gl_reference']
    actual_dlls = {name: digest for name, digest in reference['files'].items() if name.lower().endswith('.dll')}
    _compare(actual_dlls, MESA_RUNTIME, 'current GL operational model/runtime identity')
    _compare(native.bind_all_native_frames(source_packet, ledger), manifest['native_input_binding'],
             'complete current native input receipts')
    source.shared._exact_keys(manifest['fallback_frames'], source.ROLES, 'current fallback scope')
    active = {role for role in source.ROLES if manifest['fallback_frames'][role]}
    require(active, 'current certificate has no fallback scope')
    for field_name in ('traces', 'selections'):
        source.shared._exact_keys(manifest[field_name], active, 'current proof ' + field_name)
    expected_paths, traces, rows, states = {}, {}, {}, {}
    offset = ledger._portable(packet_path.parent, descriptor['files'][descriptor['input_files']['ads-offset.cfg']])
    for role in source.ROLES:
        frames = manifest['fallback_frames'][role]
        rows[role], states[role] = {}, {}
        if not frames:
            continue
        gl.frame_ids(frames)
        backend = source.BACKENDS[role][0]
        expected_path = ledger._portable(packet_path.parent, descriptor['source_outputs'][role])
        expected_paths[role] = expected_path
        selected_path = ledger._portable(folder, manifest['selections'][role])
        # read_record is object-only; selected frames deliberately use an array.
        _compare(json.loads(selected_path.read_text()), frames, 'current selected frames')
        trace_path = ledger._portable(folder, manifest['traces'][role])
        header, trace_rows = _read_trace(trace_path, source_packet.rows_by_role[role], frames)
        traces[role] = trace_rows
        _process(ledger, folder, backend + '-geometry', manifest['executions'][backend + '-geometry'],
            [prebuilt['executables']['source_visibility_geometry_probe'], root / 'assets/animations.cfg',
             offset, backend, trace_path, selected_path], root)
        computed = None
        if role == 'windows-legacy':
            # Recompute from input geometry, never trust a successful proof.json
            # assertion or the current PNG's foreground to manufacture masks.
            computed = gl.validate_gl_proof(source_packet.rows_by_role[role], list(trace_rows.values()),
                frames=frames, expected_header=source_packet.headers_by_role[role], trace_header=header)
            saved = ledger._json(ledger._portable(folder, manifest['proof_outputs'][role]))
            _compare(saved['frames'], computed['frames'], 'current recomputed GL obligations')
            _process(ledger, folder, 'gl-model', manifest['executions']['gl-model'],
                [manifest['executions']['gl-model']['command'][0], root / 'tools/current_ads_profile_proof.py',
                 '--trace', trace_path, '--expected', expected_path, '--source-receipt', receipt_path,
                 '--expected-receipt-sha256', manifest['source_receipt_sha256'], '--frames', selected_path,
                 '--output-dir', folder / 'gl'], root)
        for index, frame in enumerate(frames):
            original = source_packet.rows_by_role[role][frame]
            row = deepcopy(original)
            if computed is not None:
                certified = computed['frames'][index]
                row.update(required_contrast_runs=certified['required_runs'], possible_support_runs=certified['possible_runs'],
                           required_contrast_samples=certified['required_samples'], possible_samples=certified['possible_samples'])
            row.update(bounded_ads_profile_established=True, profile_class_id='current-frame-geometry-v1')
            rows[role][frame], states[role][frame] = row, _snapshot(original)
    runtime = {}
    if 'dx12' in active:
        warp = _warp(ledger, folder, manifest, source_packet, traces['dx12'], preparation,
                     prebuilt['executables']['finite_warp_probe'], expected_paths['dx12'])
        if warp is not None:
            _process(ledger, folder, 'dx12-native', manifest['executions']['dx12-native'],
                [prebuilt['executables']['finite_warp_probe'], '--native', '--trace', folder / 'dx12-visible-trace.jsonl',
                 '--original-jsonl', expected_paths['dx12'], '--source-receipt', receipt_path,
                 '--source-root', root, '--output-dir', folder / 'warp', '--current-source-receipt-sha256',
                 manifest['source_receipt_sha256'], '--frames-json', folder / 'dx12-visible-frames.json'], root)
            runtime = historical._runtime_identity(ledger, native_runtime_logs, warp, source_packet)
    summary = {'schema': 'rust-duty-bound-current-ads-profile/v1', 'class_id': 'current-frame-geometry-v1',
               'current_profile_sha256': expected_class_sha256, 'capture_binding': deepcopy(source_packet.capture_binding),
               'build_identity': identity, 'fallback_frames': deepcopy(manifest['fallback_frames']),
               'runtime_identity': runtime, 'native_input_binding_verified': True,
               'bounded_ads_profile_established': True, 'native_profile_binding_verified': False,
               'profile_native_verified': False, 'acceptance_complete': False, 'acceptance_verdict': None}
    result = BoundCurrentAdsProfile(source_packet, ledger, rows, states, summary, path, deepcopy(actual))
    result.verify_unchanged()
    return result

#!/usr/bin/env python3
"""Bind one reviewed finite ADS equivalence class to a fresh capture packet.

An independently retained descriptor SHA is a review anchor, never a digest
learned from the candidate. Original packet binding and image/telemetry/witness
validators remain mandatory. This module grants only a separately typed finite
profile for the declared 210 ADS-offset fallback rows of each backend.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

import ads_source_visibility_binding as source
import bind_reviewed_gl_supplement as gl
import build_ads_source_packet as producer
import extract_native_profile_evidence as extraction
import prepare_finite_probe_inputs as preparation
import run_renderer_contract as renderer_contract

SCHEMA = 'rust-duty-finite-ads-reviewed-class/v1'
PASS_BATCHING_SCHEMA = 'rust-duty-finite-ads-pass-batching-class/v1'
PASS_BATCHING_CLASS = 'ads-offset-8f571464-finite-pass-batching-v1'
ORIGINAL_CLASS_SHA256 = '96dfb631be9d59f6cf35d87e4f3c17a4a4303d74787bb773a8c47672efb53331'
# Independently reviewed Windows run 37482428571, attempt 1, artifact 11422371812.
# This is the retained review receipt anchor, never a candidate/test digest.
PASS_BATCHING_NATIVE_REVIEW_SHA256 = '4c2ae5f087ac1e548a9285f635fbb17de9de3defbaa4fab0da014fdb5c976699'
PASS_BATCHING_COMMITS = {
    'baseline': '17023450076b668c279539e0e450b8cb58a7c1a2',
    'candidate': '5abf2bca825a252fb7ad6665c444c89861ee8ef9',
}
PASS_BATCHING_PAIRS = {
    'baseline': {
        'src/render/frame.rs': {'bytes': 15694, 'sha256': '6791f92af105eff40835d710aea7ee4dd5edd8f3e263067564333cf42887b9e3'},
        'src/render/plan.rs': {'bytes': 21875, 'sha256': '5e81c060a90c95d6b1a90c2d0a8951219c47df7330f0aae6447166e20d1f3acf'},
    },
    'candidate': {
        'src/render/frame.rs': {'bytes': 25184, 'sha256': 'd0bdefd2fe79f77c33e2ac4183346cccfcbae3a3d1fac6c7e2130e7d6648d91e'},
        'src/render/plan.rs': {'bytes': 22649, 'sha256': 'c23e97a848435a610f5be0c72341ef8e5090fa2cd66846cda1b29159558a4c7e'},
    },
}

GPU_CPU_SCHEMA = 'rust-duty-finite-ads-gpu-cpu-class/v1'
GPU_CPU_CLASS = 'ads-offset-8f571464-finite-gpu-cpu-v1'
PASS_BATCHING_CLASS_SHA256 = '2895c1f4f0039f5a850c7b30196c5d77f4b2e563bc211f8b9fb51ca15f639c4c'
# Deliberately absent: no new native controls have been independently reviewed.
GPU_CPU_NATIVE_REVIEW_SHA256 = None
GPU_CPU_COMMITS = {
    'baseline': 'b085f31d71e8eeb4dd9f36786a9c7e82da90b809',
    'candidate': 'ebf4bcb7f489766e3c7ec188c35db9bb4146c62b',
}
# Exact canonical production bytes plus the exact existing diagnostic suffix.
GPU_CPU_VARIANTS = {
    'baseline': {
        'production': {
            'src/app.rs': {'bytes': 73361, 'sha256': '244d6a65fa6534abbc3dcc42e2ef57f0592bd5976e053083449f4cb2254ca472'},
            'src/frame_performance.rs': {'bytes': 26106, 'sha256': 'd32746635a4ef297ce6c1e22514d3a18cf9b57975e79f4db9e0102965cb8ac22'},
            'src/frame_performance_session.rs': {'bytes': 15320, 'sha256': '60773c62527d99ca27fa4315eb360121eec14b3645504e5c6a5bc2e4f59aee5f'},
            'src/graphics_device.rs': None,
            'src/lib.rs': {'bytes': 1701, 'sha256': '090d44a59fb9b4d6de1a98e6199f157afce88ed81a1930395675ee542d6217cc'},
            'src/main.rs': {'bytes': 6126, 'sha256': 'c4018780c2db8c7fb5681d7ea65656e78217b4dbac870cab928f589e5a8d472f'},
            'src/pause_menu.rs': {'bytes': 42678, 'sha256': '509ac8fc2787454e0a7af657eff40bab8fe9b5f3d7e8d4328fd213581377fce2'},
            'src/render/backend.rs': {'bytes': 8609, 'sha256': '2ffa4502d858c3e291c599bb50e0ec50d3187b7473005d28858a7914a76b3ed0'},
            'src/render/device.rs': {'bytes': 23610, 'sha256': '02dd7452dcc310276ee3eb03c2a96d84c2c97c29a6282cbc4cff627ff2227723'},
            'src/render/frame.rs': {'bytes': 25184, 'sha256': 'd0bdefd2fe79f77c33e2ac4183346cccfcbae3a3d1fac6c7e2130e7d6648d91e'},
            'src/render/mod.rs': {'bytes': 713, 'sha256': '81c52fb079336e131299091a0445353b7bfe566517621ec1516922e19f2047db'},
            'src/render/runtime.rs': {'bytes': 19444, 'sha256': 'f1372755c241bad6aba2109a0a86f0396537e79dbe7651f24ec2d872fbb393ee'},
        },
        'reviewed_additions': {
            'src/render/mod.rs': {'bytes': 872, 'sha256': '201b223624a59e84f73cc3d114c6e6e7e797b6d1d121a781301f195867a6ac74'},
        },
    },
    'candidate': {
        'production': {
            'src/app.rs': {'bytes': 75655, 'sha256': 'c282e402b35b0edee452eff30741251b729a936e90431c94387eb14c3cb918da'},
            'src/frame_performance.rs': {'bytes': 31117, 'sha256': 'dfd68b9970a9b38cfef2b60a8b75238350c89466fc6e5a0d9d54413758c415bd'},
            'src/frame_performance_session.rs': {'bytes': 19408, 'sha256': '4b72fe3910f08d2a4dd7e9dcaea7557675451275010c72c75da7b37d654d577c'},
            'src/graphics_device.rs': {'bytes': 18112, 'sha256': '731d3ad664ed8b8cc358e19f7ec321646af8fbe50872ccf63322128264418e8b'},
            'src/lib.rs': {'bytes': 1726, 'sha256': 'd99219a4e4fcc06d73d3841b0b6d6fa40edcb4ac2aa5e1882cd5f66cda7284b1'},
            'src/main.rs': {'bytes': 6421, 'sha256': '04f2c0ce85c2ceac6ccf9b215e043df097107749a676dfa3d2661334b6463f41'},
            'src/pause_menu.rs': {'bytes': 65356, 'sha256': 'c08e8fc87407bc9cfda5cfadf7f92eb5802e7abb625e0b66e9d96c5d8f0bca9e'},
            'src/render/backend.rs': {'bytes': 8833, 'sha256': '4a9c1efab9ecb5a462cd55f2a2b9bb10959f2e4d318f53dd439d75a01b6c8603'},
            'src/render/device.rs': {'bytes': 28061, 'sha256': 'fe742b814bcc55ab3b5d13ad70a03dcef54e5369a7b3a82665a016eec16a6763'},
            'src/render/frame.rs': {'bytes': 25738, 'sha256': 'aad7d066764a658b3dc8a3dbd1eaed2fb3bb69708effbbffe16a9b6fc07d8628'},
            'src/render/mod.rs': {'bytes': 724, 'sha256': 'b5fce38c777a6619526f578bf3970bc31c38420ec1b6b57f10413647b2dbfb2f'},
            'src/render/runtime.rs': {'bytes': 20650, 'sha256': '67af6a5ee23d3db06a526abe3b5df6dc5e325365dce436562e1e4e31381a3e48'},
        },
        'reviewed_additions': {
            'src/render/mod.rs': {'bytes': 883, 'sha256': 'c78768f1c1144a14618960975fe43027293fa1a8a21cb147eea9bef6e44c7bae'},
        },
    },
}

EVIDENCE_KEYS = ('runner', 'native', 'gl_binding', 'opengl_empty', 'dx12_empty', 'opengl_visible', 'dx12_visible',
                 'preparation', 'before', 'after', 'executables', 'compiler_before', 'compiler_after',
                 'build_invocation', 'native_invocation')
DEVICE_FIELDS = ('device_type', 'vendor_id', 'device_id', 'driver', 'driver_info')
CONTROLS = ('missing_native_draws', 'missing_triangle_receipt', 'shrunken_possible',
            'enlarged_required', 'nonopaque_alpha_readback', 'greater_than_three_byte_readback',
            'one_pixel_support_escape_native_occlusion')
FALSE_FLAGS = ('native_profile_binding_verified', 'profile_native_verified',
               'original_profile_flags_modified', 'acceptance_complete')
require = source._require
equal = source.telemetry._compare


def _sha(value, label):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value), f'{label}: missing SHA-256')
    return value


def _identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def _external_descriptor(value):
    """External JSON can never impersonate a verified loader's internal state."""
    require(type(value) is dict, 'external descriptor must be an object')
    for marker, label in (('_pass_batching', 'pass-batching'), ('_gpu_cpu', 'GPU/CPU')):
        require(marker not in value, 'reserved internal ' + label + ' state in external descriptor')
    return value


def _read_class_reference(ledger, class_path, item, digest, label):
    source.shared._exact_keys(item, ('path', 'bytes', 'sha256'), label)
    identity = {key: item[key] for key in ('bytes', 'sha256')}
    source._digest_shape(identity, label)
    equal(item['sha256'], _sha(digest, label + ' independent review anchor'), label + ' anchor')
    path = ledger._portable(class_path.parent, item['path'])
    equal(ledger._remember(path), identity, label + ' bytes')
    return _external_descriptor(ledger._json(path))


def _read_gpu_cpu_class(ledger, class_path, extension):
    """Disabled scaffold. Native-review ingestion needs its own reviewed change."""
    _external_descriptor(extension)
    source.shared._exact_keys(extension, ('schema', 'class_id', 'status', 'batching_class',
                                         'source_variants', 'native_comparison', 'acceptance_verdict'),
                              'GPU/CPU descriptor')
    equal(extension['schema'], GPU_CPU_SCHEMA, 'GPU/CPU descriptor schema')
    equal(extension['class_id'], GPU_CPU_CLASS, 'GPU/CPU descriptor class')
    require(extension['status'] == 'reviewed', 'GPU/CPU review pending; variant disabled')
    equal(extension['acceptance_verdict'], None, 'GPU/CPU descriptor verdict')
    equal(extension['source_variants'], GPU_CPU_VARIANTS, 'exact coherent GPU/CPU source variants')
    batching = _read_class_reference(ledger, class_path, extension['batching_class'],
                                     PASS_BATCHING_CLASS_SHA256, 'reviewed batching class')
    equal(batching.get('schema'), PASS_BATCHING_SCHEMA, 'reviewed batching schema')
    batching_path = ledger._portable(class_path.parent, extension['batching_class']['path'])
    reviewed = _read_pass_batching_class(ledger, batching_path, batching)
    # Check the entire declared baseline against the independently pinned parent.
    for name, identity in GPU_CPU_VARIANTS['baseline']['production'].items():
        equal(identity, PASS_BATCHING_PAIRS['candidate'].get(name,
              reviewed['equivalence']['production'].get(name)), 'GPU/CPU baseline production: ' + name)
    equal(GPU_CPU_VARIANTS['baseline']['reviewed_additions']['src/render/mod.rs'],
          reviewed['equivalence']['reviewed_additions']['src/render/mod.rs'],
          'GPU/CPU baseline diagnostic suffix')
    require(GPU_CPU_NATIVE_REVIEW_SHA256 is not None,
            'GPU/CPU native review anchor unavailable; variant disabled')
    # A replaced constant or candidate-refreshed digest cannot activate this scaffold.
    raise ValueError('GPU/CPU native receipt ingestion not activated; variant disabled')


def _gpu_cpu_variant(read, reviewed, actual):
    """One complete variant, including absence, never independent per-file choices.

    This helper is exercised by adversarial fixtures only while the public
    loader is disabled. The historical class inventory is never rewritten.
    """
    if '_gpu_cpu' not in reviewed:
        return None
    names = GPU_CPU_VARIANTS['baseline']['production']
    observed = {name: (_identity(_production_bytes(name, read(name))) if name in actual else None)
                for name in names}
    matches = [value for value in GPU_CPU_VARIANTS.values() if value['production'] == observed]
    require(len(matches) == 1, 'mixed or unreviewed GPU/CPU source variant')
    return matches[0]


def _read_pass_batching_class(ledger, class_path, extension):
    """Extend the unchanged original descriptor, never rewrite its proof."""
    _external_descriptor(extension)
    source.shared._exact_keys(extension, ('schema', 'class_id', 'status', 'original_class',
                                         'source_pairs', 'native_comparison', 'acceptance_verdict'),
                              'pass-batching descriptor')
    require(extension['class_id'] == PASS_BATCHING_CLASS, 'unknown pass-batching class')
    require(extension['status'] == 'reviewed', 'pass-batching review pending; variant unavailable')
    equal(extension['acceptance_verdict'], None, 'pass-batching descriptor verdict')
    equal(extension['source_pairs'], PASS_BATCHING_PAIRS, 'exact paired source mapping')

    original = _read_class_reference(ledger, class_path, extension['original_class'],
                                     ORIGINAL_CLASS_SHA256, 'original finite class')
    require(original.get('schema') == SCHEMA and original.get('status') == 'reviewed' and
            original.get('class_id') == 'ads-offset-8f571464-finite-v1', 'original finite class differs')
    for name, identity in PASS_BATCHING_PAIRS['baseline'].items():
        equal(original['equivalence']['production'][name], identity, 'original paired source anchor')
    require(PASS_BATCHING_NATIVE_REVIEW_SHA256 is not None,
            'pass-batching native review anchor unavailable; variant disabled')
    comparison = _read_class_reference(ledger, class_path, extension['native_comparison'],
                                       PASS_BATCHING_NATIVE_REVIEW_SHA256,
                                       'pass-batching native comparison')
    reviewed = deepcopy(original)
    reviewed['class_id'] = PASS_BATCHING_CLASS
    reviewed['_pass_batching'] = {'comparison': comparison,
                                 'sha256': extension['native_comparison']['sha256']}
    return reviewed


def _pass_batching_evidence(reviewed, native_identity):
    """Validate a compact, independently anchored review of the actual artifact.

    The reviewer must run the existing fixed renderer-contract validator and
    decode/compare all PNGs before retaining this receipt. This is not a new
    native execution, nor can a candidate's refreshed digest establish review.
    """
    if '_pass_batching' not in reviewed:
        return
    report = reviewed['_pass_batching']['comparison']
    equal(report.get('schema'), 'rust-duty-pass-batching-native-review/v1', 'native comparison schema')
    for key, value in {'status': 'passed', 'native_execution': True,
                       'original_class_sha256': ORIGINAL_CLASS_SHA256,
                       'original_profile_flags_modified': False, 'acceptance_complete': False,
                       'acceptance_verdict': None}.items():
        equal(report.get(key, 'missing'), value, 'native comparison ' + key)
    equal(report.get('commits'), PASS_BATCHING_COMMITS, 'native comparison revisions')
    artifact = report.get('artifact', {})
    source.shared._exact_keys(artifact, ('run_id', 'run_attempt', 'artifact_id', 'archive_sha256'),
                              'native comparison artifact')
    for key in ('run_id', 'run_attempt', 'artifact_id'):
        require(type(artifact[key]) is str and re.fullmatch('[1-9][0-9]*', artifact[key]),
                'native comparison artifact context missing: ' + key)
    _sha(artifact['archive_sha256'], 'native comparison artifact archive')
    for name in ('summary', 'build_receipts', 'exact_pixels'):
        source._digest_shape(report.get(name), 'native comparison ' + name)
    equal(report.get('comparison'), {'channels': 'RGBA', 'channel_tolerance': 0, 'capture_count': 21},
          'native zero-tolerance comparison')
    variants = report.get('variants', {})
    source.shared._exact_keys(variants, ('baseline', 'candidate'), 'native comparison variants')
    names = {case[0] for case in renderer_contract.cases()}
    require(len(names) == 21, 'fixed production renderer contract inventory changed')
    device_fields = (*DEVICE_FIELDS, 'adapter', 'backend', 'compiler')
    expected_device = {key: native_identity[key] for key in device_fields}
    for label, variant in variants.items():
        equal(variant.get('source_pair'), PASS_BATCHING_PAIRS[label], 'native paired source ' + label)
        equal(variant.get('compiler_sha256'), reviewed['equivalence']['compiler_sha256'],
              'native comparison compiler ' + label)
        equal(variant.get('runtime_identity'), expected_device, 'native comparison adapter/compiler ' + label)
        equal(variant.get('process_exit_code'), 0, 'native comparison exit code ' + label)
        for name in ('source_receipt', 'contract_executable', 'contract_report', 'contract_log'):
            source._digest_shape(variant.get(name), 'native comparison ' + label + '/' + name)
        validation = variant.get('fixed_contract_validation', {})
        for key, value in {'schema': 'rust-duty-renderer-contract-validation/v1', 'passed': True,
                           'backend': 'Dx12', 'adapter': 'Microsoft Basic Render Driver',
                           'captures': 21, 'scope': renderer_contract.SCOPE}.items():
            equal(validation.get(key, 'missing'), value, 'fixed renderer expectations ' + label + '/' + key)
        for key in ('build_version', 'build_number'):
            require(type(validation.get(key)) is str and validation[key].strip(),
                    'fixed renderer validation missing build identity')
        for key in ('rgba_sha256', 'png_sha256'):
            mapping = variant.get(key, {})
            source.shared._exact_keys(mapping, names, 'complete native capture inventory ' + label)
            for name, digest in mapping.items():
                _sha(digest, 'native capture ' + label + '/' + name)
    equal(variants['baseline']['rgba_sha256'], variants['candidate']['rgba_sha256'],
          'all 21 native captures must match exactly in RGBA')


def _pass_batching_pair(read, reviewed):
    if '_pass_batching' not in reviewed:
        return {}
    actual = {name: _identity(_lf(read(name))) for name in PASS_BATCHING_PAIRS['baseline']}
    require(actual in PASS_BATCHING_PAIRS.values(), 'mixed or unreviewed pass-batching source pair')
    return actual


def _canonical(value):
    """Type-tag numbers, preserving exact decimal values without float rounding."""
    if type(value) is Decimal:
        sign, digits, exponent = value.as_tuple()
        digits = list(digits)
        while digits and digits[-1] == 0:
            digits.pop()
            exponent += 1
        return ['decimal', sign if digits else 0, digits, exponent if digits else 0]
    if type(value) is dict:
        return ['object', [[key, _canonical(value[key])] for key in sorted(value)]]
    if type(value) is list:
        return ['array', [_canonical(item) for item in value]]
    require(value is None or type(value) in (str, bool, int), 'unsupported canonical value')
    return [type(value).__name__, value]


def _state_sha(header, rows, root):
    """Only verified root prefixes of the explicit companion-path fields map."""
    header, rows = deepcopy(header), deepcopy(rows)
    def companion(value):
        path, prefix = source._recorded_path(value), source._recorded_path(root) + '/'
        require(path.startswith(prefix), 'companion path escapes verified source root')
        name = path[len(prefix):]
        require(name in source.COMPANIONS and name.endswith('.vra'), 'unknown companion path')
        return name
    for entry in header['sources']:
        entry['vra'] = companion(entry['vra'])
    require(len(rows) == source.FRAME_COUNT and
            [row.get('frame') for row in rows] == list(range(source.FRAME_COUNT)),
            'full 553-frame source state required')
    for row in rows:
        row['companion_catalog_vra'] = companion(row['companion_catalog_vra'])
    return hashlib.sha256(json.dumps(_canonical([header, rows]), separators=(',', ':'),
                                     ensure_ascii=True).encode()).hexdigest()


def _lf(raw):
    result = raw.replace(b'\r\n', b'\n')
    require(b'\r' not in result, 'only CRLF/LF source mapping is reviewed')
    return result


def _production_name(name):
    return name.startswith(('src/', 'updater/src/')) or name in preparation.ROOT_PRODUCTION


def _bridge_base(raw):
    if b'/// Read-only evaluated source pose for independent CPU diagnostics.' not in raw:
        return raw
    original = raw
    for start, end in (
        (b'/// Read-only evaluated source pose for independent CPU diagnostics.', b'impl AuthoredViewmodel {'),
        (b'    /// Snapshot the same effective pose selected by `draw_checked`, before',
         b'    /// Loads CPU mesh and texture descriptors without requiring a render context.')):
        require(original.count(start) == original.count(end) == 1, 'ambiguous source bridge markers')
        original = original[:original.index(start)] + original[original.index(end):]
    fixture = b'\n\n    fn layered_contact_fixture() -> AuthoredViewmodel {'
    require(original.count(fixture) == 1, 'source bridge test fixture missing')
    original = original[:original.index(fixture)] + original[original.rfind(b'\n}'): ]
    producer.reviewed_bridge(original, raw)
    return original


def _production_bytes(name, raw):
    if Path(name).suffix in ('.rs', '.toml', '.lock', '.wgsl'):
        raw = _lf(raw)
    if name == 'src/authored_viewmodel.rs':
        return _bridge_base(raw)
    if name == 'src/render/mesh.rs' and preparation.MESH_START in raw:
        require(raw.count(preparation.MESH_START) == raw.count(preparation.MESH_END) == 1,
                'ambiguous diagnostic mesh overlay')
        old = raw[:raw.index(preparation.MESH_START)] + raw[raw.index(preparation.MESH_END):]
        preparation.checked_overlay(name, old, raw)
        return old
    if name == 'src/render/mod.rs' and raw.endswith(preparation.MOD_SUFFIX):
        old = raw[:-len(preparation.MOD_SUFFIX)]
        preparation.checked_overlay(name, old, raw)
        return old
    return raw


def _input_equivalent(name, raw, expected):
    identity = _identity(raw)
    mapping = expected.get('config_newlines', {}).get(name)
    if mapping is None:
        equal(identity, expected['inputs'][name], 'reviewed input: ' + name)
        return
    require(name in ('assets/animations.cfg', 'settings.cfg', 'ads-offset.cfg'),
            'newline mapping is restricted to three parsed text configs')
    equal(mapping['original'], expected['inputs'][name], 'original config review anchor')
    equal(mapping['transform'], 'whole-file CRLF/LF only', 'config mapping transform')
    canonical = _lf(raw)
    equal(_identity(canonical), mapping['lf'], 'reviewed config LF bytes: ' + name)
    equal(_identity(canonical.replace(b'\n', b'\r\n')), mapping['crlf'], 'reviewed config CRLF bytes: ' + name)
    require(identity in (mapping['lf'], mapping['crlf']), 'mixed or unreviewed config line endings: ' + name)


def _gl_reference_equivalent(manifest, native_binding, expected):
    """Compare every runtime member; only two reviewed lock/receipt pairs vary."""
    equal(manifest.get('binding'), native_binding, 'raw current GL input-manifest binding')
    reference = manifest.get('gl_reference')
    require(type(reference) is dict and source.shared.gl_reference_digest(reference) ==
            native_binding['gl_reference_sha256'], 'current raw GL reference digest differs')
    original = expected['original_gl_reference']
    equal(source.shared.gl_reference_digest(original), expected['capture_configuration']['gl_reference_sha256'],
          'original reviewed GL aggregate identity')
    variants = expected['gl_metadata_pairs']
    require(type(variants) is list and len(variants) == 2, 'exact two reviewed GL metadata pairs required')
    require(variants[0] == {'manifest_sha256': original['manifest_sha256'],
                           'staging_receipt_sha256': original['files']['staging-receipt.json']},
            'original GL metadata pair missing')
    for pair in variants:
        source.shared._exact_keys(pair, ('manifest_sha256', 'staging_receipt_sha256'), 'GL metadata mapping')
        permitted = deepcopy(original)
        permitted['manifest_sha256'] = _sha(pair['manifest_sha256'], 'GL lock identity')
        permitted['files']['windows_gl_reference_lock.json'] = pair['manifest_sha256']
        permitted['files']['staging-receipt.json'] = _sha(pair['staging_receipt_sha256'], 'GL staging identity')
        if _canonical(reference) == _canonical(permitted):
            return
    raise ValueError('current GL DLL/license/runtime components or reviewed metadata mapping differ')


def _packet_class(bound, packet_path, reviewed):
    require(type(bound) is source.BoundSourcePacket, 'complete source packet must already be bound')
    packet_path = Path(packet_path).absolute()
    require(packet_path in bound._snapshots, 'packet path was not validated by the source binder')
    packet = bound._json(packet_path)
    root = packet_path.parent
    receipt = bound._json(bound._portable(root, packet['receipt']))
    equal(packet['capture_binding'], bound.capture_binding, 'current capture boundary')
    equal(receipt['inputs_and_implementation_before'], receipt['inputs_and_implementation_after'],
          'current immutable source inventory')
    entries = receipt['inputs_and_implementation_before']
    require(set(packet['files']) == set(entries), 'current source inventory changed')
    # All mappings are relative, distinct and already hash-bound by the source binder.
    def read(name):
        require(name in entries and name in packet['files'], 'missing current source/input: ' + name)
        path = bound._portable(root, packet['files'][name])
        equal(bound._remember(path), entries[name], 'current source/input: ' + name)
        return bound._read(path)
    expected = reviewed['equivalence']
    equal(set(packet['input_files']), set(source.INPUTS), 'complete consumed inputs')
    for name in source.INPUTS:
        _input_equivalent(name, read(packet['input_files'][name]), expected)
    if 'oracle-output/original-authored_viewmodel.rs' in entries:
        bridge = _lf(read('oracle-output/original-authored_viewmodel.rs'))
        equal(_identity(bridge), expected['production']['src/authored_viewmodel.rs'], 'original bridge production')
    actual = {name for name in entries if _production_name(name)}
    # The historical diagnostic overlay adds only this module.
    addition = 'src/render/finite_warp_probe.rs'
    allowed_additions = {addition}
    if '_gpu_cpu' in reviewed:
        allowed_additions.add('src/graphics_device.rs')
    require(actual - set(expected['production']) <= allowed_additions, 'unreviewed production file added')
    require(set(expected['production']) <= actual, 'reviewed production file missing')
    variant = _gpu_cpu_variant(read, reviewed, actual)
    if variant is None:
        source_pair = _pass_batching_pair(read, reviewed)
    else:
        source_pair = {**PASS_BATCHING_PAIRS['candidate'],
                       **{name: value for name, value in variant['production'].items() if value is not None}}
    for name in sorted(actual):
        raw = read(name)
        canonical = _lf(raw) if Path(name).suffix in ('.rs', '.toml', '.lock', '.wgsl') else raw
        identity = source_pair.get(name, expected['production'].get(name))
        if _identity(canonical) != identity:
            # The additive bodies must themselves be the reviewed versions;
            # marker-shaped arbitrary Rust is not a source-equivalence proof.
            additions = variant['reviewed_additions'] if variant is not None else {}
            equal(_identity(canonical), additions.get(name, expected.get('reviewed_additions', {}).get(name)),
                  'unreviewed additive/source bytes: ' + name)
        if name == addition and name not in expected['production']:
            preparation.checked_overlay(name, None, canonical)
        else:
            equal(_identity(_production_bytes(name, raw)), identity,
                  'reviewed production source: ' + name)
    native_manifest_key = PurePosixPath(receipt['oracle_execution']['rustc_vv']).with_name('native-input-manifest.json').as_posix()
    _gl_reference_equivalent(source._parse(read(native_manifest_key), 'current native input manifest'),
                             bound.capture_binding, expected)
    for name in ('cargo_manifest_sha256', 'cargo_lock_sha256'):
        equal(bound.capture_binding[name], expected['capture_configuration'][name], 'reviewed ' + name)
    equal(receipt['capture_rustc_sha256'], expected['compiler_sha256'], 'reviewed compiler')
    equal(_identity(read(receipt['oracle_execution']['rustc_vv']))['sha256'], expected['compiler_sha256'],
          'actual compiler bytes')
    for name in ('platform', 'host', 'target', 'profile', 'features'):
        equal(receipt['oracle_execution'][name], expected['oracle'][name], 'reviewed build ' + name)
    for role in source.ROLES:
        header, rows = bound.headers_by_role[role], bound.rows_by_role[role]
        for flag in gl.SOURCE_FALSE_FLAGS:
            equal(header.get(flag), False, 'original source flag ' + flag)
        equal(header.get('acceptance_verdict', 'missing'), None, 'original source verdict')
        equal(_state_sha(header, rows, packet['recorded_root']), expected['state_sha256'][role],
              role + ': complete reviewed masks/gameplay/time/source state')
    return packet


def _read_evidence(ledger, class_path, reviewed):
    source.shared._exact_keys(reviewed['evidence'], EVIDENCE_KEYS, 'reviewed evidence inventory')
    result = {}
    for name in EVIDENCE_KEYS:
        item = reviewed['evidence'][name]
        source.shared._exact_keys(item, ('path', 'bytes', 'sha256'), 'reviewed evidence ' + name)
        expected = {'bytes': item['bytes'], 'sha256': item['sha256']}
        source._digest_shape(expected, name)
        path = ledger._portable(class_path.parent, item['path'])
        equal(ledger._remember(path), expected, 'independent reviewed evidence ' + name)
        result[name] = ledger._read(path) if name.startswith('compiler_') else ledger._json(path)
    return result


def _comparison(report, role, frames, empty, original_sha):
    backend = source.BACKENDS[role][0]
    for key, expected in {'backend': backend, 'empty': empty, 'frame_count': len(frames),
                          'later_corroboration': True, 'original_profile_flags_modified': False,
                          'profile_native_verified': False, 'acceptance_verdict': None}.items():
        equal(report.get(key, 'missing'), expected, 'comparison/' + key)
    require(report.get('original_source', {}).get('sha256') == original_sha,
            'comparison does not bind the reviewed original source')
    source._digest_shape(report.get('trace'), 'comparison trace')
    rows = gl._frames(report.get('frames'), frames, 'comparison frames')
    for frame in frames:
        row = rows[frame]
        require(row.get('full_original_state_equal') is True and
                row.get('empty_support_separated') is empty and
                type(row.get('unsupported_domain_nodes')) is int and row['unsupported_domain_nodes'] == 0,
                'incomplete state/empty/domain proof')
        require(gl._integer(row.get('minimum_nonzero_dyadic_exponent'), 'domain exponent', -126) >= -126 and
                0 <= gl._number(row.get('maximum_rounded_magnitude_upper'), 'domain magnitude') < 2**128,
                'unresolved normal finite arithmetic domain')
    return rows


def _native_build(evidence, reviewed):
    """Verify the reviewed run's compiler/build/executable and immutable inputs."""
    before, after, prepared = (evidence[name] for name in ('before', 'after', 'preparation'))
    expected_compiler = reviewed['equivalence']['compiler_sha256']
    for key in ('compiler_before', 'compiler_after'):
        equal(_identity(evidence[key])['sha256'], expected_compiler, 'independent native compiler bytes')
    for key in ('compiler_output_sha256', 'implementation', 'prepared_files', 'receipt_sha256'):
        equal(before.get(key), after.get(key), 'native before/after ' + key)
    equal(before.get('compiler_output_sha256'), expected_compiler, 'native build compiler')
    equal(before.get('executables'), {}, 'native build must start without diagnostic executables')
    equal(before.get('derived_inputs'), {}, 'native build must start without derived evidence')
    equal(after.get('executables'), evidence['executables'], 'native compiled executable inventory')
    equal(after.get('prepared_files'), prepared.get('files'), 'native immutable prepared files')
    equal(before.get('receipt_sha256'), reviewed['evidence']['preparation']['sha256'], 'native preparation receipt')
    equal(prepared.get('caller_context'), reviewed['native_context'], 'native preparation caller')
    equal(prepared.get('capture_context'), extraction.CAPTURE_CONTEXT, 'native preparation original capture')
    equal(prepared.get('source_execution_context'), extraction.SOURCE_CONTEXT, 'native preparation original source')
    equal(prepared.get('capture_rustc_sha256'), expected_compiler, 'prepared compiler identity')
    require(prepared.get('new_native_execution') is False and prepared.get('profile_native_verified') is False and
            prepared.get('acceptance_verdict', 'missing') is None, 'preparation is not an execution verdict')
    equal(evidence['native'].get('executable_sha256'), evidence['executables']['finite_warp_probe']['sha256'],
          'actual native executable')
    for backend in ('opengl', 'dx12'):
        for kind in ('empty', 'visible'):
            equal(after['derived_inputs'].get(f'traces/{backend}-{kind}.jsonl'),
                  evidence[f'{backend}_{kind}']['trace'], 'native immutable trace')
    runner = evidence['runner']
    for key, name in (('build_invocation', 'build-two-diagnostics-once'), ('native_invocation', 'finite-warp-native')):
        receipt = evidence[key]
        require(type(receipt.get('exit_code')) is int and receipt['exit_code'] == 0, 'native build/execution failed')
        equal(receipt.get('environment'), source.ORACLE_ENVIRONMENT, 'native arithmetic compiler environment')
        equal(receipt, runner.get('executions', {}).get(name), 'native original process receipt')
    command = evidence['build_invocation']['command']
    require(Path(command[0].replace('\\', '/')).name.casefold() == 'cargo.exe' and command[1:] ==
            ['build', '--locked', '--release', '--no-default-features', '--features',
             'legacy-macroquad,wgpu-runtime', '--target', source.ORACLE_TARGET, '--example',
             'source_visibility_geometry_probe', '--example', 'finite_warp_probe'], 'native build configuration differs')
    root = source._recorded_path(evidence['build_invocation']['cwd'])
    command = evidence['native_invocation']['command']
    require(source._recorded_path(evidence['native_invocation']['cwd']) == root and
            source._recorded_path(command[0]) == root + '/target/' + source.ORACLE_TARGET + '/release/examples/finite_warp_probe.exe' and
            command[1:2] == ['--native'] and len(command) == 12 and
            command[2::2] == ['--trace', '--original-jsonl', '--source-receipt', '--source-root', '--output-dir'] and
            source._recorded_path(command[9]) == root, 'native executable/invocation scope differs')


def _native_evidence(evidence, reviewed, bound):
    runner, native = evidence['runner'], evidence['native']
    require(runner.get('schema') == 'rust-duty-finite-warp-profile-runner/v1' and
            runner.get('status') == 'bounded_later_corroboration_passed' and
            runner.get('phase') == 'completed' and runner.get('reviewed_gl_hashes_match') is True,
            'native runner incomplete or reviewed GL hashes differ')
    require(not runner.get('final_integrity_error'), 'native runner final integrity failed')
    equal(runner.get('caller_context'), reviewed['native_context'], 'independent native execution context')
    equal(runner.get('capture_context'), extraction.CAPTURE_CONTEXT, 'reviewed original capture')
    equal(runner.get('original_source_context'), extraction.SOURCE_CONTEXT, 'reviewed original source')
    for obj, keys in ((runner, FALSE_FLAGS[1:]), (native, ('original_capture_reproduced',
            'original_native_upload_identity_verified', 'original_profile_flags_modified', 'universal_profile_verified'))):
        for key in keys:
            equal(obj.get(key, 'missing'), False, 'original native flag ' + key)
        equal(obj.get('acceptance_verdict', 'missing'), None, 'native verdict')
    require(native.get('schema') == 'rust-duty-finite-warp-corroboration/v1' and
            native.get('status') == 'passed' and native.get('native_execution') is True and
            native.get('later_corroboration') is True, 'native execution required; plans are insufficient')
    equal(native.get('source_receipt_sha256'), gl._REVIEWED_SHA256['source_receipt'], 'native original receipt')
    equal(native.get('original_dx12_jsonl_sha256'), reviewed['original_outputs_sha256']['dx12'], 'native original source')
    equal(native.get('trace_sha256'), evidence['dx12_visible']['trace']['sha256'], 'native exact trace')
    equal(runner.get('native_corroboration', {}).get('native_report'),
          {key: reviewed['evidence']['native'][key] for key in ('bytes', 'sha256')}, 'runner/native report')
    equal(native.get('build_configuration'), reviewed['native_build_configuration'], 'native arithmetic build')
    for name, value in {'viewport': [0, 0, 960, 540], 'target_format': 'Rgba8Unorm', 'sample_count': 1,
                        'depth_enabled': False, 'fragment_entry_point': 'fs_straight',
                        'required_mask_changed': False, 'possible_mask_changed': False,
                        'frame_witness_excluded': [0, 0, 64, 22],
                        'blend_modes': ['disabled', 'production_alpha_over_opaque_black',
                                        'production_alpha_over_opaque_white']}.items():
        equal(native.get(name), value, 'native configuration ' + name)
    rows = gl._frames(native.get('frames'), gl.FRAME_IDS, 'native complete fifty frames')
    for frame, row in rows.items():
        current = bound.rows_by_role['dx12'][frame]
        required = gl._mask(current['required_contrast_runs'], 'native required mask')
        mask = bytearray(960 * 540)
        for sample in required:
            mask[sample] = 1
        equal(row.get('checked_required_mask_sha256'), hashlib.sha256(mask).hexdigest(), 'complete native required mask')
        equal(row.get('required_samples'), len(required), 'native sample count')
        equal(row.get('negative_controls'), {name: 'rejected' for name in CONTROLS}, 'native negative controls')
        require(row.get('per_triangle_support_guard_passed') is True and
                row.get('production_alpha_blend_endpoints_verified') is True,
                'complete native triangle and blend proof required')
        for key in ('source_triangles', 'color_probe_triangles', 'color_probe_covered_sample_memberships'):
            gl._integer(row.get(key), key, 1)
        for key in ('source_frame_sha256', 'draws_sha256', 'color_observations_sha256', 'coverage_sha256'):
            _sha(row.get(key), key)
    equal(native.get('source_triangle_count'), sum(row['source_triangles'] for row in rows.values()), 'native triangle inventory')
    equal(native.get('support_guard_draw_count'), native['source_triangle_count'], 'native all-triangle guard inventory')
    equal(native.get('color_probe_triangle_count'), sum(row['color_probe_triangles'] for row in rows.values()), 'native fragment inventory')
    identity = native.get('native_identity')
    require(type(identity) is dict and identity.get('adapter') == 'Microsoft Basic Render Driver' and
            identity.get('device_type') == 'Cpu' and identity.get('backend') == 'Dx12' and
            identity.get('compiler') == 'Fxc', 'independent native WARP/FXC identity missing')
    for name in DEVICE_FIELDS:
        require(name in identity, 'independent native device evidence missing: ' + name)
    return identity


def _gl_rows(reviewed, report, current_rows):
    compact = reviewed['gl_export']
    equal(compact.get('schema'), 'rust-duty-reviewed-gl-compact-export/v1', 'compact GL schema')
    equal(compact.get('artifact_sha256'), gl._REVIEWED_SHA256, 'fixed reviewed GL evidence identity')
    equal(compact.get('complete_triangle_fragment_inventory_checked'), True, 'complete GL proof inventory')
    for name in ('native_profile_binding_verified', 'native_geometry_profile_verified', 'native_fragment_profile_verified', 'acceptance_complete'):
        equal(compact.get(name, 'missing'), False, 'original GL flag ' + name)
        equal(report.get(name, 'missing'), False, 'reviewed binding flag ' + name)
    equal(compact.get('acceptance_verdict', 'missing'), None, 'compact GL verdict')
    require(report.get('schema') == 'rust-duty-reviewed-gl-supplement-binding/v1' and
            report.get('status') == 'reviewed_conditional_evidence_bound', 'real reviewed GL binding required')
    equal(dict(report.get('artifact_sha256', [])), gl._REVIEWED_SHA256, 'reviewed GL binding anchors')
    equal(report.get('frame_ids'), list(gl.FRAME_IDS), 'reviewed GL frame scope')
    rows = gl._frames(compact.get('frames'), gl.FRAME_IDS, 'compact GL frames')
    counts = (sum(row['required_before_fragment'] for row in rows.values()),
              sum(row['required_after_fragment'] for row in rows.values()),
              min(row['required_after_fragment'] for row in rows.values()),
              sum(row['examined_overlapping_subtriangles'] for row in rows.values()),
              sum(row['unsafe_subtriangles'] for row in rows.values()))
    equal(counts, gl._REVIEWED_COUNTS, 'complete reviewed GL totals')
    for key, value in zip(('required_samples', 'minimum_required_samples', 'examined_overlapping_subtriangles', 'unsafe_subtriangles'), counts[1:]):
        equal(report.get(key), value, 'reviewed GL report ' + key)
    for frame, row in rows.items():
        original = current_rows[frame]
        required = gl._mask(row['required_runs'], 'reviewed narrowed required')
        possible = gl._mask(row['possible_runs'], 'reviewed expanded possible')
        require(required and required <= gl._mask(original['required_contrast_runs'], 'original required') and
                gl._mask(original['possible_support_runs'], 'original possible') <= possible and required <= possible,
                'reviewed GL masks escape their bounded relation')
        equal(len(required), row['required_after_fragment'], 'reviewed required count')
    return rows


def _runtime_identity(ledger, logs, native_identity, bound):
    source.shared._exact_keys(logs, source.ROLES, 'current original runtime logs')
    records = {}
    for role, path in logs.items():
        text = ledger._read(Path(path).absolute()).decode('utf-8')
        records[role] = text.splitlines()
    dx = records['dx12']
    devices = [source._parse(line.removeprefix('renderer device_evidence='), 'device evidence')
               for line in dx if line.startswith('renderer device_evidence=')]
    require(len(devices) == 1, 'missing or ambiguous current renderer device evidence')
    device = devices[0]
    # The game owns a FIFO window surface even when capturing an independent
    # RGBA8 target. Only the diagnostic probe has no surface/present mode.
    # The source binder separately requires the original fallback/viewport argv.
    require(device.get('force_fallback_requested') is True and device.get('present_mode') == 'Fifo',
            'current runtime is not the windowed fallback game capture')
    require(dx.count('renderer dx12_shader_compiler=Fxc') == 1 and
            dx.count('renderer requested=dx12 backend=Dx12 adapter=Microsoft Basic Render Driver') == 1,
            'current adapter/FXC identity differs')
    identity = {name: device.get(name) for name in DEVICE_FIELDS}
    equal(identity, {name: native_identity[name] for name in DEVICE_FIELDS}, 'current versus independent WARP device')
    # Existing caller validates precision, target and the sealed Mesa runtime.
    # Verify all capture sidecars use the same actual adapter as that evidence.
    adapters = {}
    for role in source.ROLES:
        seen = set()
        for image in bound._frames[role]:
            metadata = bound._json(Path(str(image) + '.json'))
            seen.add(metadata.get('adapter'))
        require(len(seen) == 1 and None not in seen, 'capture adapter is missing or changes within replay')
        adapters[role] = next(iter(seen))
    equal(adapters['dx12'], native_identity['adapter'], 'current capture/native adapter')
    require(adapters['windows-legacy'].startswith('llvmpipe'), 'current GL adapter outside reviewed Mesa profile')
    return {'dx12': {**identity, 'adapter': adapters['dx12'], 'backend': 'Dx12', 'compiler': 'Fxc'},
            'windows-legacy': {'adapter': adapters['windows-legacy'],
                               'gl_reference_sha256': bound.capture_binding['gl_reference_sha256']}}


@dataclass(frozen=True)
class BoundFiniteAdsProfile:
    """A finite profile, never an original receipt or complete migration verdict."""
    source_packet: source.BoundSourcePacket = field(repr=False)
    _ledger: source.BoundSourcePacket = field(repr=False)
    _reviewed: dict = field(repr=False)
    _class_sha256: str
    _runtime: dict = field(repr=False)
    _rows: dict = field(repr=False)
    _state: dict = field(repr=False)
    _recorded_root: str = field(repr=False)
    _capture_binding: dict = field(default_factory=dict, repr=False)
    bounded_ads_profile_established: bool = field(default=True, init=False)
    native_profile_binding_verified: bool = field(default=False, init=False)
    profile_native_verified: bool = field(default=False, init=False)
    acceptance_complete: bool = field(default=False, init=False)
    acceptance_verdict: None = field(default=None, init=False)

    def __bool__(self):
        raise TypeError('finite profile is not a migration acceptance boolean')

    def summary(self):
        summary = {'schema': 'rust-duty-bound-finite-ads-profile/v1',
                         'class_id': self._reviewed['class_id'], 'reviewed_class_sha256': self._class_sha256,
                         'evidence_sha256': {key: value['sha256'] for key, value in self._reviewed['evidence'].items()},
                         'capture_binding': self._capture_binding, 'runtime_identity': self._runtime,
                         'fallback_frames': self._reviewed['fallback_frames'],
                         'bounded_ads_profile_established': True, **{key: False for key in FALSE_FLAGS},
                         'acceptance_verdict': None}
        if '_pass_batching' in self._reviewed:
            summary['source_equivalence'] = {
                'original_class_sha256': ORIGINAL_CLASS_SHA256,
                'native_comparison_sha256': self._reviewed['_pass_batching']['sha256'],
                'source_pairs': PASS_BATCHING_PAIRS,
            }
        return deepcopy(summary)

    def verify_frame_binding(self, path, role, index):
        require(role in source.ROLES and type(index) is int and index in self._rows[role],
                'fallback outside reviewed finite ADS scope')
        original = self.source_packet.verify_frame_binding(path, role, index)
        equal(_canonical(original), self._state[role][index], 'late current source row mutation')
        return deepcopy(self._rows[role][index])

    def verify_unchanged(self):
        equal(self.source_packet.capture_binding, self._capture_binding, 'late capture boundary mutation')
        self.source_packet.verify_unchanged()
        self._ledger.verify_unchanged()
        for role in source.ROLES:
            equal(_state_sha(self.source_packet.headers_by_role[role], self.source_packet.rows_by_role[role],
                             self._recorded_root), self._reviewed['equivalence']['state_sha256'][role],
                  'late source state mutation')


def bind_finite_ads_profile(*, source_packet, source_packet_path, reviewed_class,
                            expected_class_sha256, native_runtime_logs):
    """Bind an independently reviewed descriptor; pending descriptors fail closed.

    Runtime log paths must be the original, inventory-validated ADS capture logs.
    This helper retains their bytes but does not replace the caller's closed
    shard inventory or the complete PNG/witness/invocation validators.
    """
    ledger = source.BoundSourcePacket()
    class_path = Path(reviewed_class).absolute()
    require(ledger._remember(class_path)['sha256'] == _sha(expected_class_sha256, 'independent class anchor'),
            'reviewed class differs from independent SHA-256')
    reviewed = _external_descriptor(ledger._json(class_path))
    if reviewed.get('schema') == GPU_CPU_SCHEMA:
        reviewed = _read_gpu_cpu_class(ledger, class_path, reviewed)
    pass_batching = reviewed.get('schema') == PASS_BATCHING_SCHEMA
    if pass_batching:
        reviewed = _read_pass_batching_class(ledger, class_path, reviewed)
    require(reviewed.get('schema') == SCHEMA, 'unsupported finite profile class')
    require(reviewed.get('status') == 'reviewed', 'finite ADS profile review pending; no accepting class is available')
    require(reviewed.get('class_id') == (PASS_BATCHING_CLASS if pass_batching
                                       else 'ads-offset-8f571464-finite-v1'), 'unknown reviewed equivalence class')
    equal(reviewed.get('acceptance_verdict', 'missing'), None, 'descriptor verdict')
    equal(reviewed.get('visible_frames'), list(gl.FRAME_IDS), 'finite visible scope')
    empty = reviewed['empty_frames']
    require(type(empty) is list and len(empty) == 160 and empty == sorted(set(empty)) and
            all(type(i) is int and 0 <= i < 553 for i in empty) and not set(empty).intersection(gl.FRAME_IDS),
            'complete 160 empty frame scope required')
    equal(reviewed.get('fallback_frames'), sorted([*empty, *gl.FRAME_IDS]), 'exact 210 fallback scope')
    packet = _packet_class(source_packet, source_packet_path, reviewed)
    evidence = _read_evidence(ledger, class_path, reviewed)
    for role in source.ROLES:
        backend = source.BACKENDS[role][0]
        _comparison(evidence[backend + '_empty'], role, empty, True, reviewed['original_outputs_sha256'][role])
        for index in empty:
            row = source_packet.rows_by_role[role][index]
            require(row['classification'] == 'expected_empty_under_profile' and
                    row['required_contrast_runs'] == row['possible_support_runs'] == [] and
                    row['required_contrast_samples'] == row['possible_samples'] == row['unclassified_triangles'] == 0,
                    'empty fallback has unresolved source support')
            require(row['source_triangles'] == row['outside_bottom'] + row['hidden_source_triangles'],
                    'empty source triangle partition incomplete')
            for mesh in row['meshes']:
                require(mesh['state'] == 'source_actor_hidden' or
                        (mesh['state'] == 'enumerated' and mesh['unclassified'] == 0 and
                         mesh['outside_bottom'] == mesh['triangles'] and mesh['maximum_bottom_upper'] < 0),
                        'empty source mesh lacks strict separator')
    for role in source.ROLES:
        backend = source.BACKENDS[role][0]
        _comparison(evidence[backend + '_visible'], role, list(gl.FRAME_IDS), False, reviewed['original_outputs_sha256'][role])
    _native_build(evidence, reviewed)
    native = _native_evidence(evidence, reviewed, source_packet)
    _pass_batching_evidence(reviewed, native)
    gl_rows = _gl_rows(reviewed, evidence['gl_binding'], source_packet.rows_by_role['windows-legacy'])
    runtime = _runtime_identity(ledger, native_runtime_logs, native, source_packet)
    rows, state = {}, {}
    for role in source.ROLES:
        rows[role], state[role] = {}, {}
        for index in reviewed['fallback_frames']:
            original = source_packet.rows_by_role[role][index]
            equal(original.get('acceptance_verdict', 'missing'), None, 'original frame verdict')
            row = deepcopy(original)
            if role == 'windows-legacy' and index in gl_rows:
                narrowed = gl_rows[index]
                row.update(required_contrast_runs=deepcopy(narrowed['required_runs']),
                           possible_support_runs=deepcopy(narrowed['possible_runs']),
                           required_contrast_samples=narrowed['required_after_fragment'],
                           possible_samples=sum(count for _, count in narrowed['possible_runs']))
            row.update(bounded_ads_profile_established=True, profile_class_id=reviewed['class_id'])
            rows[role][index], state[role][index] = row, _canonical(original)
    result = BoundFiniteAdsProfile(source_packet, ledger, reviewed, expected_class_sha256,
                                  runtime, rows, state, packet['recorded_root'], deepcopy(source_packet.capture_binding))
    result.verify_unchanged()
    return result


def export_reviewed_gl(bound):
    """Compact export only after the fixed-anchor, complete GL proof validator."""
    require(type(bound) is gl.BoundReviewedGlSupplement, 'requires fixed reviewed GL binding')
    bound.verify_unchanged()
    equal(dict(bound.artifact_sha256), gl._REVIEWED_SHA256, 'export reviewed GL anchors')
    from dataclasses import asdict
    return {'schema': 'rust-duty-reviewed-gl-compact-export/v1',
            'artifact_sha256': dict(bound.artifact_sha256), 'complete_triangle_fragment_inventory_checked': True,
            'frames': [asdict(row) for row in bound.frames],
            'native_profile_binding_verified': False, 'native_geometry_profile_verified': False,
            'native_fragment_profile_verified': False, 'acceptance_complete': False, 'acceptance_verdict': None}

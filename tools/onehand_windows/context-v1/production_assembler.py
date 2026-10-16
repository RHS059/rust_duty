"""Strict generated-source Windows caller for the unchanged streaming assembler.

The caller is inert on import. Its production entry point requires an actual
Windows host, externally pinned inputs, target-native prerequisites and exact
original caps. No reduced-fixture or skip-admission option exists here.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import uuid
import json
import math
import os
from pathlib import Path
import shutil
import struct
import sys
from candidate_context import (ACTION, APPROVED_SHA, CANONICAL_SHA, GIB, FOCUS,
    FilePin, ProofContext, canonical, digest, exact, exact_keys, file_sha,
    ordinary, require, sha, strict_json)
from addon_resolver import official_pins, resolve_addon, PIN_FILE_SHA
from pinned_assembler import PINS, load_assembler
from pinned_transport import load_verifier, require_production_transport, TRANSPORT_SHA

NATIVE_HELPER_MANIFEST_SHA = 'ebf3e1868fc2ea8c6e729bcbd351aa283a259822b19cdb06fb605cdaac2f7aed'

FOCUS_CHECKS = (
    'bone_inventory', 'hierarchy', 'animated_camera_bound', 'animated_rig_bound',
    'single_exact_take', 'bounded_window_admitted', 'bone_deformation_world_matrix',
    'bone_head_world_m', 'actor_world_matrix', 'actor_camera_relative_matrix',
    'camera_world_matrix', 'rig_world_matrix', 'skin_world_m', 'skin_camera_relative_m',
    'finite_bones', 'finite_all_measured_transforms', 'skin_topology',
    'camera_projection_rays', 'camera_type', 'single_native_clock', 'fps',
    'source_unchanged', 'fbx_unchanged')
MAXIMA = ('bone_deformation_world_matrix', 'bone_head_world_m', 'actor_world_matrix',
          'actor_camera_relative_matrix', 'camera_world_matrix', 'rig_world_matrix',
          'skin_world_m', 'skin_camera_relative_m')


def production_contract(context, assembler):
    """The only production layout; intentionally no caller-supplied overrides."""
    require(isinstance(context, ProofContext), 'typed candidate context required')
    return assembler.StreamContract(
        clip_name=ACTION, bone_count=72, actor_count=3, ticks_per_second=15360,
        last_tick=24320, block_ticks=2048,
        source_sha256=context.pin('generated_source').sha256,
        fbx_sha256=context.pin('actual_fbx').sha256, canonical_sha256=CANONICAL_SHA,
        max_transforms=2000000, max_file_bytes=128 * 1024**2)


def _pinned_record(value, role, root):
    pin = FilePin.parse(role, value)
    require(pin.path.is_relative_to(root), 'foreign candidate evidence: ' + role)
    pin.verify()
    return strict_json(pin.path)


def _pe(path):
    with ordinary(path, existing=True).open('rb') as stream:
        header = stream.read(64)
        require(len(header) == 64 and header[:2] == b'MZ', 'x64 PE tool required')
        offset = struct.unpack_from('<I', header, 60)[0]
        require(64 <= offset <= 16 * 1024**2, 'bounded PE offset required')
        stream.seek(offset)
        raw = stream.read(24)
        require(len(raw) == 24 and raw[:4] == b'PE\0\0' and struct.unpack_from('<H', raw, 4)[0] == 0x8664,
                'x64 PE tool identity required')


def verify_host_build(context):
    """Verify recorded tool bytes; neither hashes nor this function attest a host."""
    value = strict_json(context.pin('host_binding').verify())
    exact_keys(value, ('schema', 'candidate_id', 'session_id', 'runner_id', 'run_id',
                      'observed_host', 'tools', 'blender_version', 'blender_build_hash',
                      'blender_libraries', 'addon_relative', 'addon_pins_sha256',
                      'implementation_pins', 'source_package_pins_sha256'), 'host build')
    exact(value['schema'], 'rust-duty-windows-source-production-host/v1', 'host build schema')
    for key in ('candidate_id', 'session_id'):
        exact(value[key], getattr(context, key), 'host ' + key)
    for key in ('runner_id', 'run_id'):
        exact(value[key], getattr(context.host, key), 'host ' + key)
    exact(value['observed_host'], context.host.expected_host, 'host observation')
    exact(value['blender_version'], [4, 3, 2], 'audited Blender version')
    require(type(value['blender_build_hash']) is str and 1 <= len(value['blender_build_hash']) <= 128,
            'observed Blender build hash required')
    exact(value['implementation_pins'], PINS, 'implementation source pins')
    exact(value['source_package_pins_sha256'], context.record()['lineage']['source_package_pins_sha256'], 'source package pin')
    exact(value['addon_pins_sha256'], PIN_FILE_SHA, 'official logical addon pin')
    exact_keys(value['tools'], ('python', 'python_runtime', 'blender'), 'host tools')
    tool_paths = []
    for name, item in value['tools'].items():
        pin = FilePin.parse(name, item)
        pin.verify()
        _pe(pin.path)
        tool_paths.append(pin.path)
        if name == 'python':
            require(pin.path == ordinary(sys.executable), 'recorded Python differs from actual interpreter')
        if name == 'blender':
            require(pin.path.is_relative_to(context.root('blender_bundle')), 'Blender executable outside inspected bundle')
    require(len(set(tool_paths)) == 3, 'host tool roles alias')
    libraries = value['blender_libraries']
    require(type(libraries) is list and 1 <= len(libraries) <= 128, 'bounded relevant Blender libraries required')
    for item in libraries:
        pin = FilePin.parse('blender_library', item)
        require(pin.path.is_relative_to(context.root('blender_bundle')), 'Blender library outside inspected bundle')
        pin.verify()
    helper_manifest = Path(__file__).absolute().parent / 'NATIVE_HELPER_PINS.json'
    require(file_sha(helper_manifest) == NATIVE_HELPER_MANIFEST_SHA, 'native helper manifest differs')
    for role, pins in strict_json(helper_manifest).items():
        for name, expected in pins.items():
            require(Path(name).name == name, 'unsafe native helper filename')
            require(file_sha(context.root(role) / name) == expected, 'unchanged native helper differs: ' + name)
    resolve_addon(context.root('blender_bundle'), value['addon_relative'])
    return value


def _process_receipt(context, value):
    """Transport terminal record bound by caller-trusted digest and host/run IDs.

    Process context_sha256 identifies that earlier stage's immutable snapshot,
    not this later assembler snapshot (which includes outputs not yet known then).
    The native gate envelope additionally binds those outputs to this candidate.
    """
    exact_keys(value, ('receipt', 'argv', 'context_sha256', 'executable_sha256'), 'native process reference')
    require(type(value['argv']) is list and value['argv'] and
            all(type(x) is str and '\0' not in x for x in value['argv']), 'exact native argv required')
    sha(value['context_sha256'], 'stage context')
    sha(value['executable_sha256'], 'native executable')
    host = strict_json(context.pin('host_binding').verify())
    blender = FilePin.parse('native_blender', host['tools']['blender'])
    blender.verify()
    exact(value['executable_sha256'], blender.sha256, 'native process must use pinned Blender')
    require(ordinary(value['argv'][0]) == blender.path, 'native process executable path differs')
    exact(value['argv'][1:9], ['--background', '--factory-startup', '--disable-autoexec',
                             '--threads', '1', '--python-exit-code', '1', '--python'], 'safe native argv prefix')
    receipt_pin = FilePin.parse('native_process', value['receipt'])
    require(receipt_pin.path.is_relative_to(context.candidate_root) and receipt_pin.path.name == 'terminal.json',
            'candidate-owned terminal process receipt required')
    receipt_pin.verify()
    verifier = load_verifier(context.root('process_adapter'))
    result = verifier(receipt_pin.path.parent, require_completed=True)
    receipt_pin.verify()
    # The transport contract is versioned separately; no old Linux receipt schema is accepted.
    exact(result.get('schema'), 'rust-duty-owned-process/v1', 'process schema')
    exact(result.get('state'), 'completed', 'process status')
    exact(result.get('started'), True, 'process started')
    require(type(result.get('sample_count')) is int and result['sample_count'] > 0, 'actual resource samples required')
    for name in ('attempt', 'started_record', 'transport_record'):
        require(type(result.get(name)) is dict, 'complete process predecessor evidence required')
    exact(result.get('exit_code'), 0, 'process return code')
    for name in ('completed', 'cleanup_complete', 'consumer_complete', 'windows_job_empty_verified'):
        exact(result.get(name), True, 'process ' + name)
    exact(result.get('timed_out'), False, 'process timeout')
    require(result.get('resource_stop_reason') is None, 'process resource failure')
    require(result.get('executable_before') == result.get('executable_after'), 'process executable changed')
    exact(result.get('command'), value['argv'], 'process exact argv')
    binding = result.get('host_binding')
    require(type(binding) is dict, 'process host binding missing')
    for key, expected in {'runner_id': context.host.runner_id, 'run_id': context.host.run_id,
                          'build_sha256': context.host.build_sha256,
                          'context_sha256': value['context_sha256'],
                          'observed_host': context.host.expected_host}.items():
        exact(binding.get(key), expected, 'process ' + key)
    for name in ('executable_before', 'executable_after'):
        record = result.get(name)
        require(type(record) is dict, 'process executable pin missing')
        exact(record.get('sha256'), value['executable_sha256'], 'process executable bytes')
        exact(record.get('path'), value['argv'][0], 'process executable path')
    return result


def verify_prerequisites(context, value):
    """Fail closed on missing target-native control/focus or mixed candidate roots.

    This admission checks externally trusted native evidence summaries, without
    reimplementing geometry/math. The future native producer must supply these
    hash-only envelopes; none are fabricated by this package.
    """
    exact_keys(value, ('schema', 'candidate_binding_sha256', 'same_platform_only',
                      'cross_platform_float64_equality_proved', 'control', 'focus'), 'native prerequisites')
    exact(value['schema'], 'rust-duty-windows-production-prerequisites/v1', 'native prerequisites schema')
    exact(value['candidate_binding_sha256'], context.binding_sha256, 'candidate binding')
    exact(value['same_platform_only'], True, 'same target platform')
    exact(value['cross_platform_float64_equality_proved'], False, 'no cross-platform equality assertion')
    control = value['control']
    exact_keys(control, ('target_full_oracle', 'target_bounded_report', 'full_process', 'bounded_process',
                         'control_fbx', 'sample_frames', 'bones', 'matrix_components_checked',
                         'matrix_component_bit_mismatch_count', 'focus_channel_bit_mismatch_count'), 'control')
    for name in ('target_full_oracle', 'target_bounded_report', 'control_fbx'):
        pin = FilePin.parse(name, control[name])
        require(pin.path.is_relative_to(context.candidate_root), 'foreign control input/evidence')
        pin.verify()
    for name in ('full_process', 'bounded_process'):
        _process_receipt(context, control[name])
    for key, expected in {'sample_frames': list(FOCUS), 'bones': 148, 'matrix_components_checked': 21312,
                          'matrix_component_bit_mismatch_count': 0, 'focus_channel_bit_mismatch_count': 0}.items():
        exact(control[key], expected, 'target-native control ' + key)
    # Compare the actual stored control report's counters, input pins and oracle.
    report = strict_json(control['target_bounded_report']['path'], cap=32 * 1024**2)
    exact(report.get('schema'), 'rust-duty-fbx-bounded-full-import-control/v1', 'bounded control schema')
    exact(report.get('passed'), True, 'bounded control pass')
    for key in ('bones', 'matrix_components_checked', 'matrix_component_bit_mismatch_count', 'focus_channel_bit_mismatch_count'):
        exact(report.get(key), control[key], 'control report ' + key)
    exact(report.get('source_frames'), list(FOCUS), 'control source times')
    exact(report.get('fbx_sha256'), control['control_fbx']['sha256'], 'same permitted control FBX')
    exact(report.get('full_import_control_sha256'), control['target_full_oracle']['sha256'], 'target-native full oracle')
    require(report.get('mismatches') == [] and report.get('maximum_component_difference') == 0.0,
            'target-native control mismatched')
    focus = value['focus']
    exact_keys(focus, ('report', 'source_process', 'import_process'), 'focus')
    for name in ('source_process', 'import_process'):
        _process_receipt(context, focus[name])
    report = _pinned_record(focus['report'], 'native_focus_report', context.candidate_root)
    verify_focus_report(context, report)
    return value


def verify_focus_report(context, report):
    """Validate a target-native focus summary; no host or runtime proof is implied."""
    for key, expected in {'source_sha256': context.pin('generated_source').sha256,
                          'fbx_sha256': context.pin('actual_fbx').sha256,
                          'sample_frames': list(FOCUS), 'samples': 9, 'skin_vertex_samples': 92106,
                          'sample_grid_sha256': '5ca9e5d361df01ceb384450cf1ef5d3602aaae98a173d24a996ef5675fb37b11',
                          'independent_grid_sha256': context.pin('source_grid').sha256,
                          'passed': True}.items():
        exact(report.get(key), expected, 'target-native focus ' + key)
    exact_keys(report.get('checks'), FOCUS_CHECKS, 'focus checks')
    require(all(x is True for x in report['checks'].values()), 'focus check failed')
    exact_keys(report.get('maxima'), MAXIMA, 'focus maxima')
    for name, maximum in report['maxima'].items():
        require(type(maximum) in (int, float) and math.isfinite(maximum) and 0 <= maximum < 1e-4,
                'focus strict matrix/position threshold: ' + name)
    ray = report.get('camera_projection_ray_error')
    require(type(ray) in (int, float) and math.isfinite(ray) and 0 <= ray < 1e-5,
            'focus strict projection threshold')
    return report


def _assemble_owned(context):
    """One strict production call; all original blocks/bytes/caps are unchanged."""
    require(isinstance(context, ProofContext), 'typed candidate context required')
    context = ProofContext.parse(context.record())
    context.host.require_current_host()
    context.verify_files()
    context.validate_authored_receipt(strict_json(context.pin('authored_admission').path))
    verify_host_build(context)
    verify_prerequisites(context, strict_json(context.pin('prerequisites').path))
    assembler = load_assembler(context.root('assembler_package'), context.root('tools'))
    contract = production_contract(context, assembler)
    require(contract.block_count == 12 and contract.frame_bytes == 3007, 'original production layout differs')
    output = context.runtime_output
    require(output.parent.is_dir() and not output.exists(), 'existing private output directory and fresh filename required')
    require(shutil.disk_usage(output.parent).free >= GIB + 80 * 1024**2, '1 GiB floor plus 80 MiB assembly reserve required')
    before = context.context_sha256
    # This is the unchanged public streaming API, never the Linux-fixed assemble().
    report = assembler.assemble_stream(context.pin('geometry').path, context.pin('vrs').path,
        context.pin('vrm').path, [context.pin(f'block_{i:02d}_receipt').path for i in range(12)],
        output, contract=contract)
    for pin in context.files:
        pin.verify()
    require(context.context_sha256 == before, 'context changed during assembly')
    require(shutil.disk_usage(output.parent).free >= GIB, 'post-assembly disk floor crossed')
    return {'schema': 'rust-duty-windows-production-assembly/v1', 'assembly_validated': True,
            'candidate_binding': context.binding, 'candidate_binding_sha256': context.binding_sha256,
            'context_sha256': before, 'roles': {p.role: p.record() for p in context.files},
            'runtime': {'role': 'actual_runtime', 'path': str(output), 'sha256': report['sha256'], 'bytes': report['bytes']},
            'assembler_sha256': PINS['assemble_runtime'], 'transport_verifier_sha256': TRANSPORT_SHA,
            'caller_sha256': file_sha(Path(__file__).absolute()), 'assembly_report': report,
            'source_material_sha256': context.pin('generated_source').sha256,
            'approved_source_lineage_sha256': APPROVED_SHA,
            'runtime_parity_verified': False, 'all_grid_windows_proof_verified': False,
            'cross_platform_float64_equality_proved': False, 'activation_authorized': False,
            'limits': ['Native evidence authenticity is an external trust requirement.',
                       'Assembly success is not Rust/native parity, capture, or art acceptance.']}



@contextmanager
def exclusive_owner(context):
    """Exclusive-create only; never steal or remove a foreign replacement lock."""
    lock = ordinary(context.owner_lock)
    require(lock.parent.is_dir(), 'private session root must already exist')
    payload = canonical({'schema': 'rust-duty-windows-assembly-owner/v1',
                         'context_sha256': context.context_sha256, 'pid': os.getpid(),
                         'token': uuid.uuid4().hex}) + b'\n'
    with lock.open('xb') as stream:
        stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        identity = os.fstat(stream.fileno())
    try:
        yield
    finally:
        ordinary(lock, existing=True)
        info = lock.stat()
        require((info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino) and lock.read_bytes() == payload,
                'owner lock changed; foreign replacement preserved')
        lock.unlink()


def assemble_production(context):
    """Acquire the same serialized session owner before production assembly."""
    require(isinstance(context, ProofContext), 'typed candidate context required')
    context = ProofContext.parse(context.record())
    context.host.require_current_host()
    require_production_transport()
    with exclusive_owner(context):
        return _assemble_owned(context)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', type=Path, required=True)
    parser.add_argument('--context-sha256', required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args(argv)
    require(file_sha(args.context) == sha(args.context_sha256, 'externally selected context'), 'context file pin differs')
    context = ProofContext.parse(strict_json(args.context))
    receipt = ordinary(args.receipt)
    require(receipt.is_relative_to(context.candidate_root) and receipt != context.runtime_output and not receipt.exists(),
            'fresh candidate-owned receipt required')
    started = receipt.with_name(receipt.name + '.started.json')
    protected = {p.path for p in context.files} | {context.runtime_output, args.context, context.owner_lock}
    require(receipt not in protected and started not in protected and not started.exists(), 'receipt aliases input/existing evidence')
    def durable(path, data):
        with ordinary(path).open('xb') as stream:
            stream.write(canonical(data) + b'\n'); stream.flush(); os.fsync(stream.fileno())
    durable(started, {'schema': 'rust-duty-windows-production-assembly-attempt/v1',
                      'context_sha256': context.context_sha256, 'candidate_binding': context.binding,
                      'assembly_validated': False, 'runtime_parity_verified': False})
    try:
        result = assemble_production(context)
    except Exception as error:
        durable(receipt, {'schema': 'rust-duty-windows-production-assembly-failure/v1',
            'context_sha256': context.context_sha256, 'candidate_binding': context.binding,
            'assembly_validated': False, 'runtime_parity_verified': False,
            'error_type': type(error).__name__, 'error': str(error)[:2048],
            'partial_runtime_retained': context.runtime_output.exists(),
            'started_receipt_sha256': file_sha(started)})
        raise
    result['started_receipt_sha256'] = file_sha(started)
    durable(receipt, result)
    print(json.dumps({'receipt': str(receipt), 'sha256': file_sha(receipt),
                      'assembly_validated': True, 'runtime_parity_verified': False}, sort_keys=True))


if __name__ == '__main__':
    main()

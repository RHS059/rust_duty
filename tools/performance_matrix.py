#!/usr/bin/env python3
"""Prepare, run sequential desktop game instances, and analyze real present traces.

Preparation/analysis never launch the game. Run is opt-in and needs an existing
dedicated desktop and packaged native-runtime game. No GPU is provisioned here.
"""
import argparse
import contextlib
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import time

from exclusive_output import write_bytes_exclusive, write_text_exclusive
import summarize_frame_performance as frames
from performance_matrix_driver import DriverError, create_driver, exit_snapshot, replay, tap, wait_until

PLAN_SCHEMA = 'rust-duty-real-game-performance-matrix/v1'
# Inventory audited at 49c3bf9. A new support surface needs review, not a guessed
# mapping of settings merely because two familiar source tokens still exist.
AUDITED_RUNTIME_MANIFEST = 'abdd0c3dff03f4d0f5b8b823d2274938946fe4b424d3468091d745035039ac7e'
SOURCE_PATHS = ('src/main.rs', 'src/app.rs', 'src/settings.rs', 'src/world_draw.rs',
                'src/viewmodel_draw.rs', 'src/platform/launch.rs', 'src/platform/window.rs',
                'src/render/device.rs', 'src/render/mesh.rs', 'src/render/target.rs',
                'src/render/runtime.rs', 'src/frame_performance.rs',
                'src/frame_performance_session.rs', 'src/graphics_device.rs',
                'src/telemetry_export.rs', 'src/control.rs', 'src/asset_path.rs')
BACKENDS = {'dx12': 'Dx12', 'vulkan': 'Vulkan', 'metal': 'Metal', 'gl-harness': 'Gl'}
UNAVAILABLE = {
    'fps_cap': 'No application FPS limiter or CLI selector. Fifo may pace at display refresh; it is not a 60 FPS cap.',
    'vsync_choices': 'Native surface configuration hard-codes Fifo; no supported off/mailbox/immediate selector.',
    'antialiasing_choices': 'Native targets/pipelines are single-sample. No AA selector. Legacy requests 4x window MSAA with single-sample viewmodel target.',
    'lod': 'No LOD selector or runtime LOD implementation in this inventory.',
    'offscreen_mesh_hiding': 'No user-selectable visibility/frustum/occlusion-culling mode; native mesh cull_mode is None.',
    'record_off_overhead': 'F8 couples CPU trace to CSV/GPU-counter recording. Record-off emits no frame trace; an independent observer is needed to measure its overhead.',
    'hud_off': 'F1 controls the debug panel only. The main HUD and recording indicator remain on.',
    'gpu_frame_duration': 'No GPU timestamp queries. GPU occupancy/memory counters are not frame duration.',
    'draw_pass_triangle_counts': 'Not emitted by actual-game frame telemetry. Synthetic example counts are not substituted.',
    'legacy_end_to_end': '--renderer=gl selects legacy Macroquad, whose Record export has no present-return trace.',
}


def require(value, message):
    if not value:
        raise ValueError(message)


def json_read(path, limit=2 * 1024 * 1024):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'Expected regular nonsymlink JSON: ' + str(path))
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    require(len(data) <= limit, 'JSON exceeds bound: ' + path.name)
    result = json.loads(data.decode('utf-8'), object_pairs_hook=frames._unique,
                        parse_constant=frames._constant)
    frames._finite_tree(result)
    require(isinstance(result, dict), 'Expected JSON object: ' + path.name)
    return result


def write_json(path, value):
    write_text_exclusive(path, json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def sha256(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'Expected regular nonsymlink file: ' + str(path))
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while data := stream.read(1024 * 1024):
            result.update(data)
    return result.hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def source_identity(repository):
    repository = Path(repository)
    commit = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
    result = {}
    for name in SOURCE_PATHS:
        data = (repository / name).read_bytes()
        committed = subprocess.check_output(['git', '-C', str(repository), 'show', commit + ':' + name])
        require(data == committed, 'Uncommitted runtime source: ' + name)
        result[name] = hashlib.sha256(data).hexdigest()
    require(canonical_hash(result) == AUDITED_RUNTIME_MANIFEST,
            'Audited runtime support changed; review the matrix inventory before updating its source binding')
    return {'commit': commit, 'runtime_files_sha256': result}


def export_witness(repository, output, harness=None):
    """Export only already verified source bytes, never manufacture a Git tree."""
    source = source_identity(repository)
    output = Path(output)
    output.mkdir()
    for name, digest in source['runtime_files_sha256'].items():
        data = (Path(repository) / name).read_bytes()
        require(hashlib.sha256(data).hexdigest() == digest, 'Source changed during witness export')
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        write_bytes_exclusive(destination, data)
    entrypoint = None
    if harness is not None:
        digest = sha256(harness)
        data = Path(harness).read_bytes()
        require(hashlib.sha256(data).hexdigest() == digest, 'Harness changed during witness export')
        name = 'examples/linux_actual_game_gl.rs'
        (output / 'examples').mkdir()
        write_bytes_exclusive(output / name, data)
        entrypoint = {'source_path': name, 'source_sha256': digest}
    require(source_identity(repository) == source, 'Git/source identity changed during witness export')
    witness = {'schema': 'rust-duty-matrix-source-witness/v1', 'source': source,
               'origin': 'Exported from a live Git checkout; every runtime file matched its committed blob.',
               'audited_runtime_manifest_sha256': AUDITED_RUNTIME_MANIFEST, 'harness': entrypoint}
    write_json(output / 'SOURCE_WITNESS.json', witness)
    return sha256(output / 'SOURCE_WITNESS.json')


def artifact_source(directory, expected_digest):
    directory = Path(directory)
    require(directory.is_dir() and not directory.is_symlink(), 'Expected real source-witness directory')
    require(isinstance(expected_digest, str) and re.fullmatch('[0-9a-f]{64}', expected_digest),
            'Artifact witness requires a separate expected --witness-sha256')
    path = directory / 'SOURCE_WITNESS.json'
    require(sha256(path) == expected_digest, 'Source witness digest differs from separately supplied value')
    witness = json_read(path)
    require(set(witness) == {'schema', 'source', 'origin', 'audited_runtime_manifest_sha256', 'harness'}
            and witness['schema'] == 'rust-duty-matrix-source-witness/v1'
            and witness['origin'] == 'Exported from a live Git checkout; every runtime file matched its committed blob.'
            and witness['audited_runtime_manifest_sha256'] == AUDITED_RUNTIME_MANIFEST,
            'Invalid source witness schema/provenance')
    source = witness['source']
    require(isinstance(source, dict) and set(source) == {'commit', 'runtime_files_sha256'}
            and isinstance(source['commit'], str) and re.fullmatch('[0-9a-f]{40}', source['commit']),
            'Invalid witnessed source identity')
    recorded = source['runtime_files_sha256']
    require(isinstance(recorded, dict) and set(recorded) == set(SOURCE_PATHS)
            and canonical_hash(recorded) == AUDITED_RUNTIME_MANIFEST,
            'Witness does not contain exactly the audited runtime support inventory')
    allowed = {'SOURCE_WITNESS.json', *SOURCE_PATHS}
    harness = witness['harness']
    if harness is not None:
        require(isinstance(harness, dict) and set(harness) == {'source_path', 'source_sha256'}
                and harness['source_path'] == 'examples/linux_actual_game_gl.rs', 'Invalid witnessed harness identity')
        allowed.add(harness['source_path'])
    found = set()
    for entry in directory.rglob('*'):
        require(not entry.is_symlink(), 'Witness must not contain symbolic links')
        if entry.is_file():
            found.add(entry.relative_to(directory).as_posix())
    require(found == allowed, 'Unexpected or missing source-witness files')
    # Reject linked ancestor directories before reading any source through them.
    for name, digest in recorded.items():
        require(sha256(directory / name) == digest, 'Witnessed source bytes differ: ' + name)
    if harness is not None:
        require(sha256(directory / harness['source_path']) == harness['source_sha256'], 'Witnessed harness bytes differ')
    return source


def resolve_source(args):
    if args.source_witness is not None:
        require(args.repository is None, 'Choose live Git or artifact witness, not both')
        source = artifact_source(args.source_witness, args.witness_sha256)
        return source, {'mode': 'artifact-witness', 'witness_sha256': args.witness_sha256}, args.source_witness
    require(args.repository is not None and args.witness_sha256 is None,
            '--witness-sha256 is only valid with --source-witness')
    return source_identity(args.repository), {'mode': 'live-git'}, args.repository


def make_plan(source, renderer='dx12', repeats=3, warmup=15, seconds=45, smoke=False, pilot=False, source_origin=None,
              static_diagnostics=False):
    require(renderer in BACKENDS, 'Only native runtime exports real present-return intervals')
    require(type(repeats) is int and 1 <= repeats <= 5, 'repeats must be 1..5')
    require(type(warmup) is int and 10 <= warmup <= 60, 'warmup must be 10..60 seconds')
    require(type(seconds) is int and 10 <= seconds <= 120, 'sample must be 10..120 seconds')
    source_origin = {'mode': 'live-git'} if source_origin is None else source_origin
    require(source_origin == {'mode': 'live-git'} or
            (isinstance(source_origin, dict) and set(source_origin) == {'mode', 'witness_sha256'}
             and source_origin['mode'] == 'artifact-witness' and isinstance(source_origin['witness_sha256'], str)
             and re.fullmatch('[0-9a-f]{64}', source_origin['witness_sha256'])), 'Invalid source origin')
    baseline = {'surface_extent': [1920, 1080], 'action': 'stationary',
                'debug_hud': False, 'presentation': 'packaged', 'record': True}
    cases = []
    def add(name, changes, rationale, kind='one_variable'):
        cases.append({'id': name, 'kind': kind, 'settings': {**baseline, **changes},
                      'changed_axes': sorted(changes), 'rationale': rationale})
    add('baseline', {}, '1080p real-game reference, fixed Fifo, Record on.', 'baseline')
    for name, size in [('720p', [1280, 720]), ('1440p', [2560, 1440]), ('4k', [3840, 2160])]:
        add(name, {'surface_extent': size}, 'World/HUD pixel-load diagnostic; fixed 1440x900 viewmodel target.')
    add('ads', {'action': 'ads'}, 'Held RMB with hold controls; ADS changes presentation and world FOV.')
    add('movement', {'action': 'movement'}, 'Repeat W/S every two wall-clock seconds in the default range.')
    add('debug-hud', {'debug_hud': True}, 'Measure added F1 debug panel while ordinary HUD stays enabled.')
    add('procedural', {'presentation': 'procedural'}, 'Existing procedural weapon path reduces presentation complexity; world unchanged.')
    add('1440p-movement', {'surface_extent': [2560, 1440], 'action': 'movement'},
        'Check whether resolution cost changes with moving presentation.', 'interaction')
    add('1440p-debug-hud', {'surface_extent': [2560, 1440], 'debug_hud': True},
        'Check pixel-load interaction with extra debug text.', 'interaction')
    require(type(smoke) is bool, 'smoke must be boolean')
    require(type(pilot) is bool and not (smoke and pilot), 'Choose at most one of smoke/pilot')
    require(type(static_diagnostics) is bool and not (static_diagnostics and (smoke or pilot)),
            'Static diagnostics cannot be combined with smoke/pilot')
    if smoke:
        cases = cases[:1]
        repeats = 1
    elif pilot:
        cases = [case for case in cases if case['id'] in ('baseline', '720p', '1440p', 'ads')]
        repeats = 1
    elif static_diagnostics:
        cases = [case for case in cases if case['id'] in ('baseline', '4k', 'debug-hud', 'procedural')]
        repeats = 1
        next(case for case in cases if case['id'] == 'debug-hud')['rationale'] = (
            'Existing F1 debug-panel command trial; current telemetry does not independently observe HUD state.')
    order = []
    varied = [case['id'] for case in cases[1:]]
    for repeat in range(repeats):
        # Rotate the finite order; baseline brackets diagnose clock/thermal drift.
        rotated = varied[repeat:] + varied[:repeat]
        for index, name in enumerate(['baseline'] if smoke else ['baseline', *rotated, 'baseline']):
            order.append({'run_id': f'r{repeat + 1:02d}-{index + 1:02d}-{name}',
                          'repeat': repeat + 1, 'case_id': name})
    result = {'schema': PLAN_SCHEMA, 'source': source, 'source_origin': source_origin, 'renderer': renderer,
            'repeats': repeats, 'warmup_seconds': warmup, 'sample_seconds': seconds, 'smoke': smoke, 'pilot': pilot,
            'cases': cases, 'order': order, 'unavailable_axes': UNAVAILABLE,
            'fixed_runtime': {'present_mode': 'Fifo', 'application_fps_cap': None,
                              'native_sample_count': 1, 'viewmodel_extent': [1440, 900],
                              'reference_viewport': False, 'scene': 'vector_range_default_range',
                              'profile': 'm4a1', 'weapon_id': 'hk416a5',
                              'validation': 'unchanged', 'timed_png_readbacks': 0},
            'goal': {'surface_extent': [1920, 1080], 'present_hz': 60,
                     'requested_gpu': 'RTX 3080 Ti', 'acceptance_proven': False},
            'entrypoint_scope': ('Experimental Linux native-GL harness importing unchanged production application. Not the shipped legacy-GL entrypoint or RTX evidence.'
                                 if renderer == 'gl-harness' else 'Packaged production game native-runtime entrypoint.'),
            'execution': 'Sequential fresh processes on one dedicated desktop. Never concurrent game instances.'}
    if static_diagnostics:
        # Keep historical plans byte/schema-compatible. Only the new selection
        # carries this optional discriminator and its narrower evidence scope.
        result['static_diagnostics'] = True
        result['unavailable_axes'] = {**UNAVAILABLE,
            'evolving_ads_movement': 'Unproven by this static selection. Prior WARP ADS remained at ADS=0 with no simulation-time progression; movement/ADS require a host where simulation advances.'}
    return result


def validate_plan(plan):
    expected = make_plan(plan['source'], plan['renderer'], plan['repeats'],
                         plan['warmup_seconds'], plan['sample_seconds'], plan['smoke'], plan['pilot'], plan['source_origin'],
                         plan.get('static_diagnostics', False))
    require(plan == expected, 'Plan changed or contains unsupported settings; regenerate it')


def package_identity(executable, source, renderer=None):
    executable = Path(executable)
    build = json_read(executable.parent / 'BUILD_IDENTITY.json', 16 * 1024)
    require(build.get('schema') == 'rust-duty-build-identity/v1', 'Missing packaged build schema')
    require(build.get('source', {}).get('commit') == source['commit'], 'Package and plan source commits differ')
    digest = sha256(executable)
    require(build.get('executable', {}).get('sha256') == digest, 'Packaged executable digest mismatch')
    files = {}
    for directory in ('assets', 'ui'):
        root = executable.parent / directory
        if root.exists():
            require(root.is_dir() and not root.is_symlink(), 'Unsafe package directory')
            for path in sorted(root.rglob('*')):
                require(not path.is_symlink(), 'Package symlink not supported')
                if path.is_file():
                    files[path.relative_to(executable.parent).as_posix()] = sha256(path)
    require('ui/theme.css' in files, 'Package needs its shipped ui/theme.css')
    result = {'build': build, 'executable_sha256': digest,
              'adjacent_files_sha256': files, 'adjacent_files_digest': canonical_hash(files)}
    entry = build.get('benchmark_entrypoint')
    if renderer == 'gl-harness':
        require(isinstance(entry, dict) and entry.get('kind') == 'linux_native_gl_actual_game_harness'
                and entry.get('source_path') == 'examples/linux_actual_game_gl.rs'
                and entry.get('receipt_file') == 'ACTUAL_GAME_HARNESS_RECEIPT.json', 'Missing isolated native-GL harness identity')
        receipt_path = executable.parent / entry['receipt_file']
        require(sha256(receipt_path) == entry.get('receipt_sha256'), 'Harness receipt hash differs')
        harness = json_read(receipt_path)
        require(harness.get('executable_sha256') == digest, 'Harness receipt executable differs')
        result['harness_receipt'] = harness
    else:
        require(entry is None, 'Harness cannot be presented as a production game entrypoint')
    return result


def validate_graphics(value, renderer):
    require(value.get('schema') == 'rust-duty-graphics-device/v1', 'Invalid graphics preference schema')
    adapter = value.get('adapter')
    require(isinstance(adapter, dict), 'Hardware tests require an exact selected GPU, not Auto')
    require(set(adapter) == {'backend', 'name', 'vendor_id', 'device_id', 'device_type'},
            'GPU fingerprint fields differ')
    require(adapter['backend'] == ('gl' if renderer == 'gl-harness' else renderer), 'Selected GPU backend differs from requested renderer')
    for name in ('name', 'device_type'):
        require(isinstance(adapter[name], str) and adapter[name] and
                not any(ord(c) < 32 for c in adapter[name]), 'Invalid GPU fingerprint ' + name)
    for name in ('vendor_id', 'device_id'):
        require(type(adapter[name]) is int and 0 <= adapter[name] < 2**32, 'Invalid GPU identifier')
    require(adapter['device_type'] != 'Cpu', 'CPU adapters require explicit forced-fallback mode')
    return adapter


@contextlib.contextmanager
def desktop_lock(path):
    # Shared across output folders/backends. A stale lock is never auto-deleted.
    path = Path(path)
    write_json(path, {'pid': os.getpid(), 'purpose': 'exclusive real-game performance desktop'})
    try:
        yield
    finally:
        path.unlink()


def case_command(executable, renderer, folder, case, fallback):
    command = [str(executable), '--no-update', '--hold-controls', '--renderer=' + ('gl' if renderer == 'gl-harness' else renderer),
               '--settings=' + str(folder / 'settings.cfg'),
               '--graphics-settings=' + str(folder / 'graphics-device.json'),
               '--ui-theme=' + str(executable.parent / 'ui/theme.css'), '--weapon-id=hk416a5']
    if renderer == 'gl-harness':
        require(not fallback, 'Native-GL harness does not support forced fallback')
        command.append('--graphics-device=auto')
    if fallback:
        command.append('--force-fallback-adapter')
    if case['settings']['presentation'] == 'procedural':
        command.append('--procedural-weapon')
    return command


def sole_session(folder, complete=False):
    root = folder / 'telemetry-sessions'
    sessions = list(root.iterdir()) if root.is_dir() else []
    require(len(sessions) <= 1, 'More than one Record session in a fresh process')
    if not sessions:
        return None
    session = sessions[0]
    require(session.is_dir() and not session.is_symlink(), 'Invalid session directory')
    if complete:
        for name in ('frames.json', 'IDENTITY.json', 'CSV_STATUS.json', 'GPU_STATUS.json'):
            if not (session / name).is_file():
                return None
        # A created file can still be being written. Wait for complete JSON before
        # closing the process; semantic validity is checked by analyze_run.
        try:
            for name in ('CSV_STATUS.json', 'GPU_STATUS.json'):
                json_read(session / name)
            frames.read_report(session / 'frames.json')
        except (OSError, ValueError):
            return None
    return session


def cleanup_owned_process(process):
    """Verify exit using only the Popen handle; never search for or kill a PID."""
    result = {'process_id': process.pid, 'process_exit_verified': False,
              'termination_requested': False, 'kill_requested': False}
    try:
        code = process.poll()
        if code is None:
            result['termination_requested'] = True
            process.terminate()
            try:
                code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                result['kill_requested'] = True
                process.kill()
                code = process.wait(timeout=5)
        observed = process.poll()
        result.update(returncode=observed,
                      process_exit_verified=type(code) is int and observed == code)
    except (OSError, subprocess.SubprocessError) as error:
        result['error'] = str(error)
    return result


def measurement_file_hashes(session):
    """Bind every session file consumed by the measurement analyzer."""
    names = ('frames.json', 'IDENTITY.json', 'CSV_STATUS.json', 'gameplay.csv',
             'GPU_STATUS.json', 'GPU_METADATA.json', 'gpu.jsonl')
    result = {}
    for name in names:
        path = session / name
        require(path.is_file() and not path.is_symlink(), 'Unsafe or missing measurement file: ' + name)
        result[name] = sha256(path)
    return result


def run_case(plan, item, case, executable, output, settings, graphics, fallback, driver_name,
             *, manifest=None, continue_after_exit_timeout=False):
    require(not continue_after_exit_timeout or manifest is not None,
            'Exit-timeout continuation requires the bound execution manifest')
    folder = output / item['run_id']
    folder.mkdir()
    write_bytes_exclusive(folder / 'settings.cfg', settings)
    write_json(folder / 'graphics-device.json', graphics)
    command = case_command(executable, plan['renderer'], folder, case, fallback)
    started = time.time_ns()
    receipt = {'schema': 'rust-duty-matrix-run/v1', 'run': item, 'case': case,
               'command': command, 'driver': driver_name, 'started_unix_ns': started,
               'settings_before_sha256': sha256(folder / 'settings.cfg'),
               'graphics_before_sha256': sha256(folder / 'graphics-device.json'),
               'completed': False, 'graceful_shutdown': False}
    write_json(folder / 'START.json', receipt)
    driver = create_driver(driver_name)
    env = dict(os.environ)
    if driver_name == 'x11':
        env['WINIT_UNIX_BACKEND'] = 'x11'
    process = None
    recovered_timeout = False
    try:
        with (folder / 'game.log').open('xb') as log:
            process = subprocess.Popen(command, cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT)
            receipt['process_id'] = process.pid
            driver.bind(process.pid)
            size = case['settings']['surface_extent']
            driver.configure(size)
            # Asset loading is outside measurement. Repeated Enter only resumes;
            # it does not pause already active gameplay (SessionController).
            for _ in range(3):
                time.sleep(1)
                driver.check(size)
                tap(driver, 'Return')
            tap(driver, 'F2')
            if case['settings']['debug_hud']:
                tap(driver, 'F1')
                receipt['debug_hud_command'] = {'key': 'F1', 'issued': True, 'actual_state_verified': False}
            replay(driver, process, size, 'stationary', plan['warmup_seconds'])
            if case['settings']['action'] == 'ads':
                driver.aim(True)
                time.sleep(1)  # Settle ADS before starting the recorder.
            driver.check(size)
            tap(driver, 'F8')
            wait_until(lambda: sole_session(folder), timeout=10, label='Record session creation')
            receipt['replay'] = replay(driver, process, size, case['settings']['action'], plan['sample_seconds'])
            driver.check(size)
            tap(driver, 'F8')
            session = wait_until(lambda: sole_session(folder, complete=True), timeout=30,
                                 label='frame, CSV and GPU export completion')
            receipt['session'] = session.name
            if manifest is not None:
                before_validation = measurement_file_hashes(session)
                # Validate actual exports before exit. The finished timestamp is
                # provisional here; the persisted receipt includes cleanup time.
                provisional = {**receipt, 'finished_unix_ns': time.time_ns(),
                               'settings_after_sha256': sha256(folder / 'settings.cfg'),
                               'graphics_after_sha256': sha256(folder / 'graphics-device.json')}
                observed = analyze_measurements(folder, manifest, provisional)
                require(measurement_file_hashes(session) == before_validation,
                        'Measurement exports changed during pre-exit validation')
                receipt['measurement_files_before_exit'] = before_validation
                receipt['measurement_validated_before_exit'] = True
                receipt['measurement_tail_ready_before_exit'] = observed['sample_quality']['tail_comparison_ready']
            driver.check(size)
            receipt['exit_request'] = 'application_f10'
            receipt['exit_wait_timeout_seconds'] = 15
            if driver_name == 'win32':
                receipt['exit_diagnostics'] = {
                    'schema': 'rust-duty-process-exit-diagnostics/v1',
                    'before_request': exit_snapshot(driver, process)}
            driver.close()
            try:
                receipt['returncode'] = process.wait(timeout=15)
            except subprocess.TimeoutExpired as error:
                receipt['normal_exit_timed_out'] = True
                receipt['error'] = str(error)
                if driver_name == 'win32':
                    receipt['exit_diagnostics']['after_timeout'] = exit_snapshot(
                        driver, process, probe_responsiveness=True)
                if not (continue_after_exit_timeout and receipt.get('measurement_validated_before_exit')
                        and receipt.get('measurement_tail_ready_before_exit')):
                    raise
                recovered_timeout = True
            if not recovered_timeout:
                require(receipt['returncode'] == 0, 'Game exited unsuccessfully')
                receipt['graceful_shutdown'] = True
                receipt['completed'] = True
    except (OSError, ValueError, DriverError, subprocess.SubprocessError) as error:
        receipt['error'] = str(error)
        raise
    finally:
        receipt['input_cleanup_errors'] = driver.release_inputs()
        if receipt['input_cleanup_errors']:
            receipt['completed'] = False
        if process is not None:
            receipt['cleanup'] = cleanup_owned_process(process)
            if not receipt['cleanup']['process_exit_verified']:
                receipt['completed'] = False
        if recovered_timeout and receipt.get('cleanup', {}).get('process_exit_verified') and not receipt['input_cleanup_errors']:
            receipt['outcome'] = 'measurements_valid_shutdown_failed'
        else:
            receipt['outcome'] = 'complete' if receipt['completed'] else 'incomplete'
        receipt['finished_unix_ns'] = time.time_ns()
        receipt['settings_after_sha256'] = sha256(folder / 'settings.cfg')
        receipt['graphics_after_sha256'] = sha256(folder / 'graphics-device.json')
        write_json(folder / 'RESULT.json', receipt)
    require(receipt['settings_before_sha256'] == receipt['settings_after_sha256'], 'Gameplay settings changed during run')
    require(receipt['graphics_before_sha256'] == receipt['graphics_after_sha256'], 'GPU selection changed during run')
    require(not receipt['input_cleanup_errors'], 'Injected input cleanup failed; inspect the dedicated desktop')
    require(receipt.get('cleanup', {}).get('process_exit_verified') is True,
            'Owned game process cleanup was not verified; no further case may start')
    return receipt


def run_matrix(args):
    require(args.execute, 'Execution requires --execute; prepare/analyze do not launch anything')
    plan = json_read(args.plan)
    validate_plan(plan)
    source, origin, source_root = resolve_source(args)
    require(source == plan['source'] and origin == plan['source_origin'], 'Plan source identity/origin changed')
    executable = args.executable.resolve()
    package = package_identity(executable, plan['source'], plan['renderer'])
    if plan['renderer'] == 'gl-harness':
        require(args.driver == 'x11' and not args.force_fallback, 'Native-GL harness requires x11 and exact hardware')
        entry = package['build']['benchmark_entrypoint']
        require(sha256(source_root / entry['source_path']) == entry.get('source_sha256'), 'Harness source hash differs')
    settings = args.settings.read_bytes()
    require(0 < len(settings) <= 64 * 1024, 'Settings file must be 1..65536 bytes')
    if args.force_fallback:
        require(args.graphics_settings is None, 'Do not combine explicit GPU selection and forced fallback')
        graphics = {'schema': 'rust-duty-graphics-device/v1', 'adapter': None}
    else:
        require(args.graphics_settings is not None, 'Supply the exact selected GPU preference, or --force-fallback')
        graphics = json_read(args.graphics_settings, 16 * 1024)
        validate_graphics(graphics, plan['renderer'])
    # Driver preflight before creating output or acquiring the desktop.
    create_driver(args.driver)
    output = args.output.absolute()
    output.mkdir()
    manifest = {'schema': 'rust-duty-matrix-execution/v1', 'plan': plan, 'package': package,
                'continue_after_exit_timeout': getattr(args, 'continue_after_exit_timeout', False),
                'source_origin': origin,
                'settings_sha256': hashlib.sha256(settings).hexdigest(),
                'graphics': graphics, 'force_fallback': args.force_fallback,
                'host_observed': {'system': platform.system(), 'release': platform.release(),
                                  'machine': platform.machine(), 'processor': platform.processor()},
                'operator_hardware': json_read(args.hardware) if args.hardware else None,
                'hardware_identity_scope': 'Runtime adapter fingerprint is observed; CPU/display details are operator claims when supplied.'}
    write_json(output / 'MANIFEST.json', manifest)
    with desktop_lock(args.lock_file):
        cases = {case['id']: case for case in plan['cases']}
        for item in plan['order']:
            print('Running ' + item['run_id'], flush=True)
            run_case(plan, item, cases[item['case_id']], executable, output, settings,
                     graphics, args.force_fallback, args.driver, manifest=manifest,
                     continue_after_exit_timeout=manifest['continue_after_exit_timeout'])
            # Fail on a bad capture before spending a full matrix on invalid setup.
            analyze_run(output / item['run_id'], manifest,
                        allow_forced_cleanup=manifest['continue_after_exit_timeout'])
        require(package_identity(executable, plan['source'], plan['renderer']) == package, 'Package changed during matrix')
        after_source, after_origin, _ = resolve_source(args)
        require((after_source, after_origin) == (source, origin), 'Source witness changed during matrix')
    write_json(output / 'SUMMARY.json', analyze_matrix(output))
    return output


def gameplay_summary(path):
    require(path.is_file() and not path.is_symlink(), 'Missing gameplay.csv')
    speeds, ads, positions, times = [], [], [], []
    with path.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames == 'time,x,y,z,speed,grounded,crouched,sprinting,ads,recoil_pitch_deg,ammo,shots,hits,kills,render_fps'.split(','),
                'Gameplay CSV header mismatch')
        for index, row in enumerate(reader):
            require(index < 250000 and None not in row and all(value is not None for value in row.values()), 'Malformed or oversized gameplay CSV')
            values = [float(row[key]) for key in ('speed', 'ads', 'x', 'y', 'z', 'time')]
            require(all(math.isfinite(value) for value in values), 'Nonfinite gameplay observation')
            require(values[5] >= 0 and (not times or values[5] >= times[-1]),
                    'Simulation time is negative or regresses within the recording')
            speeds.append(values[0]); ads.append(values[1]); positions.append(values[2:5]); times.append(values[5])
    require(speeds, 'No gameplay rows; startup/menu capture is not a game test')
    advancing = sum(right > left for left, right in zip(times, times[1:]))
    pairs = len(times) - 1
    progression = ('unavailable_single_row' if not pairs else 'stalled' if not advancing
                   else 'advancing' if advancing == pairs else 'intermittent_progress')
    return {'rows': len(speeds), 'speed_min': min(speeds), 'speed_max': max(speeds),
            'moving_fraction': sum(value > 0.1 for value in speeds) / len(speeds),
            'ads_min': min(ads), 'ads_max': max(ads),
            'aimed_fraction': sum(value >= 0.99 for value in ads) / len(ads),
            'first_position': positions[0], 'last_position': positions[-1],
            'simulation_time': {'first_seconds': times[0], 'last_seconds': times[-1],
                                'span_seconds': times[-1] - times[0], 'csv_pair_count': pairs,
                                'advancing_pairs': advancing, 'unchanged_pairs': pairs - advancing,
                                'advancing_pair_fraction': advancing / pairs if pairs else None,
                                'progression': progression,
                                'scope': 'Actual simulation time from CSV rounded to four decimals; not wall-clock or render FPS.'},
            'render_fps_column_used_for_timing': False}


def gpu_export_summary(session):
    status = json_read(session / 'GPU_STATUS.json')
    require(status.get('schema') == 'rust-duty-gpu-status/v1'
            and status.get('state') == 'stopped' and status.get('error') is None
            and status.get('gpu_frame_duration_available') is False,
            'GPU counter export is incomplete or has invalid timing/status metadata')
    written, available = status.get('samples_written'), status.get('samples_with_game_process_utilization')
    require(type(written) is int and type(available) is int and 0 <= available <= written <= 86400,
            'Invalid GPU counter sample counts')
    metadata = json_read(session / 'GPU_METADATA.json')
    duration = metadata.get('gpu_frame_duration_ms', {})
    require(metadata.get('schema') == 'rust-duty-gpu-telemetry/v1' and
            isinstance(duration, dict) and duration.get('value') is None and bool(duration.get('unavailable_reason')),
            'GPU duration must retain its explicit unavailable reason')
    path = session / 'gpu.jsonl'
    require(path.is_file() and not path.is_symlink(), 'Missing GPU counter stream')
    count = observed_available = byte_count = 0
    previous_end = 0
    with path.open('rb') as stream:
        while raw := stream.readline(2 * 1024 * 1024 + 1):
            byte_count += len(raw)
            require(len(raw) <= 2 * 1024 * 1024 and byte_count <= 64 * 1024 * 1024 and count < 86400,
                    'GPU counter stream exceeds matrix bounds')
            row = json.loads(raw, object_pairs_hook=frames._unique, parse_constant=frames._constant)
            frames._finite_tree(row)
            require(isinstance(row, dict), 'GPU counter sample must be an object')
            start, end = row.get('sample_started_ms'), row.get('sample_finished_ms')
            require(type(start) in (int, float) and type(end) in (int, float)
                    and previous_end <= start <= end and row.get('sample') == count,
                    'Invalid GPU counter timeline')
            previous_end = end
            data = row.get('data')
            require(isinstance(data, dict) and isinstance(data.get('adapters'), list), 'Invalid GPU counter data')
            require(all(isinstance(adapter, dict) and isinstance(adapter.get('process_busiest_engine_pct'), dict)
                        for adapter in data['adapters']), 'Malformed GPU counter adapter metric')
            observed_available += any(type(adapter.get('process_busiest_engine_pct', {}).get('value')) in (int, float)
                                      for adapter in data['adapters'])
            count += 1
    require(count == written and observed_available == available, 'GPU counter stream/status counts differ')
    return {'status': status, 'metadata': metadata, 'gpu_jsonl_sha256': sha256(path),
            'metric_scope': 'OS occupancy/memory counters, never GPU frame duration'}


def analyze_run(folder, manifest, *, allow_forced_cleanup=False):
    receipt = json_read(folder / 'RESULT.json')
    cleanup = receipt.get('cleanup', {})
    verified_cleanup = (cleanup.get('process_exit_verified') is True
                        and type(receipt.get('process_id')) is int and receipt['process_id'] > 0
                        and cleanup.get('process_id') == receipt['process_id']
                        and type(cleanup.get('returncode')) is int and not cleanup.get('error'))
    graceful = (receipt.get('completed') is True and receipt.get('returncode') == 0
                and receipt.get('graceful_shutdown', True) is True
                and not receipt.get('normal_exit_timed_out', False)
                and not receipt.get('input_cleanup_errors')
                and ('cleanup' not in receipt or (verified_cleanup and cleanup['returncode'] == 0)))
    recovered = (manifest.get('continue_after_exit_timeout') is True
                 and receipt.get('outcome') == 'measurements_valid_shutdown_failed'
                 and receipt.get('completed') is False and receipt.get('graceful_shutdown') is False
                 and receipt.get('normal_exit_timed_out') is True
                 and receipt.get('exit_wait_timeout_seconds') == 15
                 and receipt.get('measurement_validated_before_exit') is True
                 and receipt.get('measurement_tail_ready_before_exit') is True
                 and receipt.get('input_cleanup_errors') == []
                 and bool(receipt.get('error'))
                 and verified_cleanup)
    require(graceful or (allow_forced_cleanup and recovered),
            'Run did not complete with its requested case and verified process exit')
    if recovered:
        session = sole_session(folder, complete=True)
        require(session is not None and
                receipt.get('measurement_files_before_exit') == measurement_file_hashes(session),
                'Measurement exports changed after pre-exit validation')
    result = analyze_measurements(folder, manifest, receipt)
    require(not recovered or result['sample_quality']['tail_comparison_ready'],
            'Exit-timeout continuation requires at least 100 intervals')
    result.update(graceful_shutdown=graceful, process_exit_verified=True,
                  outcome='complete' if graceful else 'measurements_valid_shutdown_failed',
                  shutdown_error=None if graceful else receipt['error'])
    return result


def analyze_measurements(folder, manifest, receipt):
    """Independently validate exports without interpreting process shutdown."""
    plan = manifest['plan']
    item = next((item for item in plan['order'] if item['run_id'] == folder.name), None)
    require(item is not None and receipt.get('run') == item, 'Unexpected run identity')
    case = next(case for case in plan['cases'] if case['id'] == item['case_id'])
    require(receipt.get('case') == case, 'Run requested case differs from its plan')
    require(type(receipt.get('started_unix_ns')) is int and type(receipt.get('finished_unix_ns')) is int
            and 0 < receipt['started_unix_ns'] < receipt['finished_unix_ns'], 'Invalid run wall-clock bounds')
    require(receipt['settings_before_sha256'] == receipt['settings_after_sha256'] == manifest['settings_sha256'] == sha256(folder / 'settings.cfg'),
            'Settings hash mismatch')
    require(receipt['graphics_before_sha256'] == receipt['graphics_after_sha256'] == sha256(folder / 'graphics-device.json'), 'Graphics preference changed')
    require(json_read(folder / 'graphics-device.json') == manifest['graphics'], 'Graphics preference differs from manifest')
    session = sole_session(folder, complete=True)
    require(session is not None and session.name == receipt.get('session'), 'Missing or ambiguous completed session')
    report = frames.read_report(session / 'frames.json')
    require(report['status']['state'] == 'complete', 'Incomplete frame trace')
    require(report['ineligible_present_count'] == 0, 'Trace includes ineligible gameplay')
    require(not any(row['kind'] == 'boundary' or row['kind'] == 'window_context' for row in report['records']),
            'Trace contains focus/pause/resize/capture or other segment boundary')
    runtime = report['identity']['runtime_observed']
    require(runtime['actual_backend'] == BACKENDS[plan['renderer']], 'Observed backend differs from request')
    adapter = runtime['actual_adapter']
    require(isinstance(adapter, dict) and adapter.get('present_mode') == 'Fifo', 'Missing actual Fifo evidence')
    require(adapter.get('force_fallback_requested') is manifest['force_fallback'], 'Fallback evidence differs')
    if manifest['force_fallback']:
        require(adapter.get('device_type') == 'Cpu', 'Forced-fallback experiment did not observe a CPU adapter')
    else:
        wanted = validate_graphics(manifest['graphics'], plan['renderer'])
        require(adapter.get('selection_mode') == 'explicit_fingerprint' and
                adapter.get('actual_fingerprint') == wanted and adapter.get('requested_fingerprint') == wanted,
                'Actual/requested selected GPU fingerprints do not match')
        require(all(adapter.get(key) == wanted[key] for key in ('name', 'vendor_id', 'device_id', 'device_type')),
                'Adapter fields contradict its fingerprint')
    require(all(key in adapter for key in ('name', 'backend', 'device_type', 'vendor_id', 'device_id', 'driver', 'driver_info')),
            'Incomplete runtime device identity')
    require(adapter['backend'] == runtime['actual_backend'], 'Adapter backend contradicts runtime')
    window = runtime['initial_window']
    size = case['settings']['surface_extent']
    require([window['physical_width'], window['physical_height']] == size, 'Observed surface extent differs from requested resolution')
    require(window['mode'] == 'windowed', 'Matrix requires windowed presentation')
    stage = report.get('cpu_frame_stages')
    require(stage is not None, 'CPU-stage extension unavailable on this build')
    require(all([row['physical_width'], row['physical_height']] == size for row in stage['samples']), 'CPU-stage sample extent mismatch')
    scene = runtime['scene']
    require(isinstance(scene, dict) and scene.get('name') == 'vector_range_default_range'
            and scene.get('reference_viewport') is False and scene.get('diagnostic_capture') is False
            and scene.get('demo') is False and scene.get('capture_sequence') is None,
            'Diagnostic/demo scene cannot be used as real gameplay')
    require(scene.get('profile_base') == 'm4a1' and scene.get('weapon_id') == 'hk416a5', 'Gameplay identity mismatch')
    if case['settings']['presentation'] == 'procedural':
        require(scene.get('presentation') == 'procedural', 'Procedural case did not use procedural presentation')
    else:
        require(scene.get('presentation') in ('authored_viewmodel', 'static_weapon_model'), 'Packaged presentation unavailable')
    identity = json_read(session / 'IDENTITY.json')
    require(identity.get('schema') == 'rust-duty-local-playtest-session/v1', 'Invalid session identity')
    require(identity.get('executable_sha256') == manifest['package']['executable_sha256'], 'Recorded executable digest differs')
    require(identity.get('source', {}).get('state') == 'bound_to_executable_hash_and_label'
            and identity['source'].get('commit') == plan['source']['commit'], 'Session source identity is not bound')
    require(identity.get('build') == runtime['build'] and runtime['build'].get('label') == manifest['package']['build']['display_version'], 'Recorded build differs')
    require(identity.get('graphics_device') == adapter, 'Session/frame adapter evidence differs')
    status = json_read(session / 'CSV_STATUS.json')
    require(status.get('state') == 'stopped' and status.get('error') is None, 'Gameplay CSV recording is incomplete')
    values = [row['interval_ns'] for row in report['records']
              if row['kind'] == 'successful_present_return' and row['interval_ns'] is not None]
    require(sum(values) >= plan['sample_seconds'] * 0.90 * 1e9, 'Insufficient retained eligible duration')
    tail_ready = len(values) >= 100
    # A setup smoke establishes input/window/export/exit behavior independently
    # of statistical sufficiency. Pilot/full retain their existing sample gate.
    require(plan['smoke'] or tail_ready, 'Fewer than 100 intervals; tail estimate not useful')
    gameplay = gameplay_summary(session / 'gameplay.csv')
    action = case['settings']['action']
    if action in ('ads', 'movement'):
        require(gameplay['simulation_time']['span_seconds'] > 0,
                'Simulation time did not advance; evolving ADS/movement is unproven')
    require((gameplay['moving_fraction'] > 0.50) if action == 'movement' else (gameplay['speed_max'] < 0.1),
            'Observed movement does not match the input case')
    require((gameplay['aimed_fraction'] > 0.90) if action == 'ads' else (gameplay['ads_max'] < 0.01),
            'Observed ADS does not match the input case')
    if plan.get('static_diagnostics') and case['settings']['debug_hud']:
        require(receipt.get('debug_hud_command') == {'key': 'F1', 'issued': True, 'actual_state_verified': False},
                'Static F1 trial needs its issued-command receipt; HUD state is not observable')
    progression = gameplay['simulation_time']['progression']
    long_intervals = sum(value > 250_000_000 for value in values)
    condition = ('static_scene_with_stalled_simulation' if progression == 'stalled'
                 else 'scene_with_intermittent_simulation' if progression == 'intermittent_progress'
                 else 'scene_with_advancing_simulation' if progression == 'advancing'
                 else 'simulation_progression_unavailable')
    summary = report['summary']
    result = {'run': item, 'settings_requested': case['settings'], 'runtime_observed': runtime,
              'started_unix_ns': receipt['started_unix_ns'], 'finished_unix_ns': receipt['finished_unix_ns'],
              'frame_summary_ns': summary, 'effective_present_hz': len(values) * 1e9 / sum(values),
              'sample_quality': {'purpose': ('setup_smoke' if plan['smoke'] else 'static_render_diagnostics'
                                            if plan.get('static_diagnostics') else 'statistical_matrix'),
                                 'observed_intervals': len(values), 'required_intervals_for_tail_comparison': 100,
                                 'tail_comparison_ready': tail_ready,
                                 'percentile_scope': 'Descriptive retained-sample quantiles; fewer than 100 intervals do not establish a useful tail comparison.'},
              'interval_fraction_over_60hz_budget': sum(value * 60 > 1e9 for value in values) / len(values),
              'interval_fraction_over_two_60hz_budgets': sum(value * 30 > 1e9 for value in values) / len(values),
              'cpu_stages': frames._cpu_stage_summary(stage, report['records']),
              'gameplay_observed': gameplay, 'skipped_frames': report['skipped_frame_count'],
              'simulation_condition': {'classification': condition,
                                       'simulation_seconds_per_present_wall_second': gameplay['simulation_time']['span_seconds'] / (sum(values) / 1e9),
                                       'present_intervals_over_250ms': long_intervals,
                                       'present_interval_fraction_over_250ms': long_intervals / len(values),
                                       'evolving_gameplay_acceptance_proven': False,
                                       'scope': 'CSV progression and retained present intervals have different sampling endpoints. At source49, application dt above250ms discards simulation time; long present intervals are supporting hitch evidence, not direct per-frame dt instrumentation.'},
              'gpu_counter_export': gpu_export_summary(session),
              'gpu_frame_duration_ns': None, 'draw_pass_triangle_counts': None,
              'debug_hud_evidence': {'requested_debug_panel': case['settings']['debug_hud'],
                                     'command_receipt': receipt.get('debug_hud_command'),
                                     'actual_state_verified': False,
                                     'scope': 'An issued F1 command is not proof of actual HUD state; older receipts may omit the command field.'},
              'scope': 'Real-game CPU present-return intervals, not GPU time or display scan-out.',
              'acceptance_proven': False}
    result['trace_sha256'] = sha256(session / 'frames.json')
    return result


def analyze_matrix(output):
    output = Path(output)
    manifest = json_read(output / 'MANIFEST.json')
    require(manifest.get('schema') == 'rust-duty-matrix-execution/v1', 'Invalid matrix execution manifest')
    plan = manifest['plan']
    validate_plan(plan)
    require(manifest.get('source_origin') == plan['source_origin'], 'Execution source origin differs from plan')
    runs, failures, measurement_failures = [], [], []
    for item in plan['order']:
        try:
            run = analyze_run(output / item['run_id'], manifest, allow_forced_cleanup=True)
            runs.append(run)
            if not run['graceful_shutdown']:
                failures.append({'run_id': item['run_id'], 'kind': 'graceful_shutdown',
                                 'error': run['shutdown_error']})
        except (OSError, ValueError, KeyError, TypeError) as error:
            failure = {'run_id': item['run_id'], 'error': str(error)}
            failures.append(failure)
            measurement_failures.append(failure)
    if runs:
        first = runs[0]['runtime_observed']
        require(all(left['finished_unix_ns'] <= right['started_unix_ns'] for left, right in zip(runs, runs[1:])),
                'Overlapping or out-of-order game processes cannot be compared')
        for run in runs:
            actual = run['runtime_observed']
            require(actual['actual_adapter'] == first['actual_adapter'] and actual['build'] == first['build'],
                    'Do not pool different adapters/drivers/builds')
            require(actual['initial_window']['scale_factor'] == first['initial_window']['scale_factor'], 'Display DPI changed between cases')
            if run['settings_requested']['presentation'] == 'packaged':
                require(actual['scene']['presentation'] == first['scene']['presentation'], 'Packaged presentation changed')
    groups = []
    for case in plan['cases']:
        selected = [run for run in runs if run['run']['case_id'] == case['id']]
        groups.append({'case_id': case['id'], 'completed_runs': sum(run['graceful_shutdown'] for run in selected),
                       'measured_runs': len(selected),
                       'p50_ms_by_run': [run['frame_summary_ns']['p50_ns'] / 1e6 for run in selected],
                       'p95_ms_by_run': [run['frame_summary_ns']['p95_ns'] / 1e6 for run in selected],
                       'p99_ms_by_run': [run['frame_summary_ns']['p99_ns'] / 1e6 for run in selected],
                       'median_run_p99_ms': statistics.median(run['frame_summary_ns']['p99_ns'] / 1e6 for run in selected) if selected else None})
    pairs = []
    for repeat in range(1, plan['repeats'] + 1):
        selected = [run for run in runs if run['run']['repeat'] == repeat]
        baselines = [run for run in selected if run['run']['case_id'] == 'baseline']
        if len(baselines) == 2:
            reference = statistics.mean(run['frame_summary_ns']['p99_ns'] for run in baselines)
            for run in selected:
                if run['run']['case_id'] != 'baseline':
                    pairs.append({'run_id': run['run']['run_id'],
                                  'p99_delta_ms_from_bracketing_baseline_mean': (run['frame_summary_ns']['p99_ns'] - reference) / 1e6,
                                  'baseline_p99_drift_ms': (baselines[1]['frame_summary_ns']['p99_ns'] - baselines[0]['frame_summary_ns']['p99_ns']) / 1e6})
    pilot_ready = bool(runs) and not failures and all(run['sample_quality']['tail_comparison_ready'] for run in runs)
    measurement_ready = (len(runs) == len(plan['order']) and not measurement_failures
                         and all(run['sample_quality']['tail_comparison_ready'] for run in runs))
    return {'schema': 'rust-duty-real-game-matrix-analysis/v1',
            'state': ('setup_complete' if plan['smoke'] else 'complete') if not failures else 'incomplete',
            'analysis_purpose': ('setup_smoke' if plan['smoke'] else 'static_render_diagnostics'
                                 if plan.get('static_diagnostics') else 'statistical_matrix'),
            'graceful_shutdown': bool(runs) and not failures and all(run['graceful_shutdown'] for run in runs),
            'measurement_readiness': {'ready': measurement_ready, 'required_intervals_per_run': 100,
                                      'all_processes_exited': len(runs) == len(plan['order']) and not measurement_failures,
                                      'scope': 'Valid source/device/exports plus verified process cleanup; does not approve graceful shutdown.'},
            'pilot_sample_readiness': {'ready': pilot_ready, 'required_intervals_per_run': 100,
                                       'reason': None if pilot_ready else 'Setup/exports failed or fewer than 100 retained intervals; do not advance to statistical pilot on this evidence.'},
            'acceptance_proven': False,
            'measurement': frames.MEASUREMENT, 'percentile_method': frames.METHOD,
            'goal': plan['goal'], 'package': manifest['package'],
            'source_origin': manifest['source_origin'],
            'entrypoint_scope': plan['entrypoint_scope'],
            'host_observed': manifest['host_observed'], 'operator_hardware': manifest['operator_hardware'],
            'scope': 'Per-run CPU pacing and CPU spans only. No pooled percentiles, GPU-time estimate, display-cadence claim, or RTX inference from another adapter.',
            'runs': runs, 'failures': failures, 'case_comparisons': [] if plan['smoke'] else groups,
            'paired_baseline_comparisons': [] if plan['smoke'] else pairs, 'unavailable_axes': plan['unavailable_axes']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    export = sub.add_parser('export-witness', help='Export exact source bytes verified against a live Git checkout')
    export.add_argument('--repository', type=Path, required=True)
    export.add_argument('--harness', type=Path)
    export.add_argument('--output', type=Path, required=True)
    prepare = sub.add_parser('prepare', help='Write a finite plan; never launch the game')
    prepare.add_argument('--renderer', choices=BACKENDS, default='dx12')
    prepare.add_argument('--repeats', type=int, default=3)
    prepare.add_argument('--warmup-seconds', type=int, default=15)
    prepare.add_argument('--sample-seconds', type=int, default=45)
    prepare.add_argument('--smoke', action='store_true', help='One baseline only; gate the desktop before a full matrix')
    prepare.add_argument('--pilot', action='store_true', help='Baseline,720p,1440p,ADS,baseline before the full matrix')
    prepare.add_argument('--static-diagnostics', action='store_true',
                         help='Remaining static cases: baseline,4K,F1 command,procedural,baseline; evolving ADS/movement unproven')
    prepare.add_argument('--output', type=Path, required=True)
    run = sub.add_parser('run', help='Opt-in sequential real-game desktop execution')
    for name in ('plan', 'executable', 'settings', 'output'):
        run.add_argument('--' + name, type=Path, required=True)
    for command in (prepare, run):
        source = command.add_mutually_exclusive_group(required=True)
        source.add_argument('--repository', type=Path)
        source.add_argument('--source-witness', type=Path)
        command.add_argument('--witness-sha256')
    run.add_argument('--graphics-settings', type=Path)
    run.add_argument('--force-fallback', action='store_true')
    run.add_argument('--hardware', type=Path, help='Optional operator CPU/display/driver notes; retained as claims')
    run.add_argument('--driver', choices=('win32', 'x11'), required=True)
    run.add_argument('--lock-file', type=Path, default=Path(tempfile.gettempdir()) / 'rust-duty-performance-desktop.lock')
    run.add_argument('--execute', action='store_true')
    run.add_argument('--continue-after-exit-timeout', action='store_true',
                     help='Continue measurements after validated exports and verified owned-process cleanup; exit failure stays failed')
    analyze = sub.add_parser('analyze', help='Read existing runs, preserve missing/incomplete evidence')
    analyze.add_argument('folder', type=Path)
    analyze.add_argument('--output', type=Path)
    analyze.add_argument('--measurement-readiness', action='store_true',
                         help='Return measurement readiness only; overall correctness remains in state/graceful_shutdown')
    args = parser.parse_args(argv)
    try:
        if args.command == 'export-witness':
            print(export_witness(args.repository, args.output, args.harness))
        elif args.command == 'prepare':
            source, origin, _ = resolve_source(args)
            result = make_plan(source, args.renderer, args.repeats,
                               args.warmup_seconds, args.sample_seconds, args.smoke, args.pilot, origin,
                               args.static_diagnostics)
            write_json(args.output, result)
            print(f'Prepared {len(result["order"])} sequential runs; no game launched: {args.output}')
        elif args.command == 'run':
            folder = run_matrix(args)
            print(folder)
            result = analyze_matrix(folder)
            if result['state'] == 'incomplete':
                # Code 3 is narrowly reserved for measurement continuation.
                return 3 if result['measurement_readiness']['ready'] else 2
        else:
            result = analyze_matrix(args.folder)
            if args.output:
                write_json(args.output, result)
            print(json.dumps(result, indent=2, allow_nan=False))
            # CI callers already use successful smoke analysis to gate a pilot.
            # A valid low-sample setup therefore stays explicitly setup_complete
            # in JSON while returning nonzero so that pilot is not auto-started.
            if args.measurement_readiness:
                return 0 if result['measurement_readiness']['ready'] else 1
            return 0 if result['state'] in ('complete', 'setup_complete') and result['pilot_sample_readiness']['ready'] else 1
        return 0
    except (OSError, ValueError, DriverError, subprocess.SubprocessError, KeyError, TypeError) as error:
        print('Matrix error: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

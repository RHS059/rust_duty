#!/usr/bin/env python3
"""Bounded CPU sampling on an ephemeral Windows CI desktop using installed WPT.

This is a diagnostic capture, not a frame-rate gate. No registry changes,
profiler installation, persistent logger, or user-computer access is performed.
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

from performance_matrix_driver import DriverError, create_driver, exit_snapshot, replay, tap

BUILD = ['cargo', 'build', '--locked', '--release', '--no-default-features',
         '--features', 'wgpu-runtime', '--bin', 'vector-range']
SETTINGS = {'CARGO_INCREMENTAL': '0', 'CARGO_BUILD_JOBS': '2',
            'CARGO_PROFILE_RELEASE_DEBUG': '2', 'CARGO_PROFILE_RELEASE_STRIP': 'none'}
EXTENT = [1920, 1080]
SECONDS = 30
# These existing producers may replace committed transport metadata. Their exact
# materialized bytes are separately bound and verified by package_game.
GENERATED_ASSET_PREFIXES = tuple('assets/' + name + '/' for name in ('reload', 'walk', 'ads', 'directional', 'jump'))


class NormalShutdownFailure(ValueError):
    """Retained measurements may remain usable; normal process exit still failed."""


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def inventory(folder):
    result = {}
    for path in sorted(Path(folder).rglob('*')):
        require(not path.is_symlink(), 'Symlink in evidence input: ' + str(path))
        if path.is_file():
            result[path.relative_to(folder).as_posix()] = digest(path)
    return result


def checked_source(root):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args])
    commit = git('rev-parse', 'HEAD').decode().strip()
    require(commit == os.environ.get('GITHUB_SHA'), 'Source must be this actual CI checkout')
    changed = git('diff', '--name-only', 'HEAD').decode().splitlines()
    require(all(name.startswith(GENERATED_ASSET_PREFIXES) for name in changed), 'Tracked source changed')
    for extra in ([], ['--ignored']):
        untracked = git('ls-files', '--others', '--exclude-standard', *extra, '--',
                        'src', 'updater', 'tools', 'ui', 'Cargo.toml', 'Cargo.lock',
                        'build.rs', 'build_number.rs', 'settings.cfg', '.cargo',
                        'rust-toolchain', 'rust-toolchain.toml')
        require(not untracked.strip(), 'Untracked or ignored compile/tool inputs')
    files, generated_transports = {}, {}
    for name in git('ls-files', '-z').decode().split('\0'):
        if not name:
            continue
        if name.startswith('assets/weapons/'):
            require(not (root / name).exists(), 'Excluded weapon asset present')
            continue
        path = root / name
        require(path.is_file() and not path.is_symlink(), 'Missing/unsafe tracked input: ' + name)
        raw = path.read_bytes()
        committed = git('show', commit + ':' + name)
        if name.startswith(GENERATED_ASSET_PREFIXES):
            generated_transports[name] = {'committed_sha256': hashlib.sha256(committed).hexdigest(),
                                          'materialized_sha256': hashlib.sha256(raw).hexdigest()}
        else:
            require(raw == committed, 'Checkout bytes differ: ' + name)
            files[name] = hashlib.sha256(raw).hexdigest()
    return {'commit': commit, 'tree': git('rev-parse', 'HEAD^{tree}').decode().strip(),
            'files_sha256': files, 'generated_asset_transports': generated_transports}


def command_log(command, root, output, *, env=None, timeout=120, owned_tree=False):
    output = Path(output)
    with output.open('xb') as stream:
        if owned_tree:
            import dx12_contract_process as processes
            child = subprocess.Popen(list(map(str, command)), cwd=root, env=env, stdout=stream,
                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            try:
                code = child.wait(timeout=timeout)
            except BaseException:
                write(output.with_suffix('.cleanup.json'), processes._terminate_process_tree(child))
                raise
        else:
            code = subprocess.run(list(map(str, command)), cwd=root, env=env, stdout=stream,
                                  stderr=subprocess.STDOUT, timeout=timeout).returncode
    require(code == 0, 'Command failed; inspect ' + output.name)
    return output


def validate_scene_log(game):
    expected = 'renderer requested=dx12 backend=Dx12 adapter=Microsoft Basic Render Driver'
    identities = [line for line in game.splitlines() if line.startswith('renderer requested=')]
    require(identities and all(line == expected for line in identities), 'Actual DX12 WARP identity missing or conflicting')
    require('window physical_extent_verified=1920x1080' in game, 'No verified physical launch receipt')
    require('Loaded Blender-authored viewmodel:' in game, 'No positive authored-load receipt')
    require(not any(error in game for error in ('Authored viewmodel could not load:',
            'Authored viewmodel playback failed:', 'Action clip timings:')), 'Authored scene reported a load/playback error')


def installed_tools(env=None):
    env = os.environ if env is None else env
    windows = Path(env.get('SystemRoot', 'C:/Windows'))
    kits = Path(env.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Windows Kits/10/Windows Performance Toolkit'
    paths = {'wpr': windows / 'System32/wpr.exe', 'xperf': kits / 'xperf.exe'}
    for name, path in paths.items():
        require(path.is_file(), 'Installed Windows profiler missing: ' + str(path))
    return paths


def require_host():
    require(sys.platform == 'win32' and os.environ.get('GITHUB_ACTIONS') == 'true'
            and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted',
            'Only the explicitly scoped ephemeral GitHub-hosted Windows job is supported')


def wpr_command(path, instance, *args):
    require(instance.startswith('rust-duty-') and instance.replace('-', '').isalnum(), 'Unsafe trace instance')
    return [str(path), *map(str, args), '-instancename', instance]


def preflight(root, output):
    require_host()
    output.mkdir(parents=True, exist_ok=False)
    paths = installed_tools()
    for name, args in [('wpr', ['-profiles']), ('xperf', ['-help', 'profile'])]:
        command_log([paths[name], *args], root, output / (name + '-help.log'))
    command_log([paths['xperf'], '-help', 'stack'], root, output / 'xperf-stack-help.log')
    write(output / 'tools.json', {name: {'path': str(path), 'sha256': digest(path)} for name, path in paths.items()})
    return paths


def capture(root, output):
    require_host()
    root, output = root.resolve(), output.resolve()
    require(root == Path(__file__).resolve().parents[1], 'Runner must belong to the exact source checkout')
    tools = json.loads((output / 'tools.json').read_text(encoding='utf-8'))
    for value in tools.values():
        require(digest(value['path']) == value['sha256'], 'Profiler changed after preflight')
    require('VR_WEAPON_ASSET' not in os.environ and not (root / 'assets/weapons').exists(),
            'Private weapon asset inputs are excluded')
    from run_cpu_image_preservation import check_environment, check_cargo_configuration, toolchain_at
    check_environment(os.environ)
    check_cargo_configuration(root, os.environ)
    source = checked_source(root)
    assets = inventory(root / 'assets')
    require('animations.cfg' in assets and 'locomotion/asset.vrs' in assets,
            'Need the existing validated original authored companions')
    write(output / 'source.json', source)
    write(output / 'assets.json', assets)
    write(output / 'asset-producers.json', {'github_run_id': os.environ.get('GITHUB_RUN_ID'),
          'github_run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'), 'source_commit': source['commit'],
          'same_run_artifacts': ['generated-' + name + '-runtime'
                                 for name in ('reload', 'walk', 'ads', 'directional', 'jump')],
          'verification_receipt_sha256': digest(output / 'materialize.json'),
          'materialized_assets_sha256': digest(output / 'assets.json')})
    compiler = toolchain_at(root)
    require('release: 1.99.0\n' in compiler['rustc']
            and 'host: x86_64-pc-windows-msvc\n' in compiler['rustc'], 'Need pinned Rust1.99 MSVC')
    target = output / 'target'
    require(not target.exists(), 'Fresh profiler build target required')
    env = dict(os.environ, **SETTINGS, CARGO_TARGET_DIR=str(target))
    command_log(BUILD, root, output / 'build.log', env=env, timeout=1800, owned_tree=True)
    check_cargo_configuration(root, os.environ)
    require(toolchain_at(root) == compiler, 'Compiler changed during build')
    require(checked_source(root) == source and inventory(root / 'assets') == assets, 'Build inputs changed')
    binary = target / 'release/vector-range.exe'
    pdb = target / 'release/vector_range.pdb'
    require(binary.is_file() and pdb.is_file() and pdb.stat().st_size > 0, 'Fresh EXE and matching build PDB required')
    for path in (binary, pdb):
        shutil.copyfile(path, output / path.name)
    bound = {'exe_sha256': digest(binary), 'pdb_sha256': digest(pdb)}
    write(output / 'build.json', {'command': BUILD, 'settings': SETTINGS, 'compiler': compiler,
          'source_commit': source['commit'], **bound})
    def verify_inputs():
        require(checked_source(root) == source and inventory(root / 'assets') == assets,
                'Capture inputs changed')
    sample_build(root, output, tools, target, source, bound, env, verify_inputs)


def sample_build(root, output, tools, target, source, bound, env, verify_inputs, *, record=False,
                 source_variant=None, source_receipt_sha256=None):
    """Sample one freshly bound build; pair mode keeps each process in a new cwd."""
    binary = target / 'release/vector-range.exe'
    pdb = target / 'release/vector_range.pdb'
    require(digest(binary) == bound['exe_sha256'] and digest(pdb) == bound['pdb_sha256'],
            'Fresh sampled build changed')
    verify_inputs()
    for path in (binary, pdb):
        retained = output / path.name
        if not retained.exists():
            shutil.copyfile(path, retained)
        require(digest(retained) == digest(path), 'Retained sampled binary differs')
    runtime = output / 'runtime'
    runtime.mkdir()
    shutil.copyfile(root / 'settings.cfg', runtime / 'settings.cfg')
    command = [str(binary), '--no-update', '--hold-controls', '--renderer=dx12',
               '--force-fallback-adapter', '--physical-1080p', '--present-mode=immediate', '--weapon-id=hk416a5',
               '--settings=' + str(runtime / 'settings.cfg'),
               '--graphics-settings=' + str(runtime / 'graphics-device.json'),
               '--ui-theme=' + str(root / 'ui/theme.css'),
               '--animation-manifest=' + str(root / 'assets/animations.cfg')]
    # The production physical-size path verifies the initial client extent before
    # hooks/app polling; the driver also checks the actual extent during sampling.
    driver = create_driver('win32')
    instance = 'rust-duty-' + uuid.uuid4().hex
    wpr = tools['wpr']['path']
    process = None
    started = False
    trace_saved = False
    pending_error = None
    initial_settings = digest(runtime / 'settings.cfg')
    receipt = {'schema': 'rust-duty-windows-cpu-sampling/v1', 'command': command,
               'source_commit': source['commit'], **bound, 'passed': False,
               'sample_seconds': SECONDS, 'physical_extent': EXTENT,
               'sampling_profile': 'CPU.Verbose.Memory', 'instance': instance,
               'scope': 'Stationary authored-scene diagnostic on DX12 WARP; no RTX/FPS inference',
               'top_functions_reviewed': False, 'initial_settings_sha256': initial_settings,
               'record_enabled': record, 'source_variant': source_variant,
               'source_receipt_sha256': source_receipt_sha256,
               'counterfactual_source': source_variant == 'baseline'}
    def verify_final_inputs():
        require(digest(binary) == digest(output / binary.name) == bound['exe_sha256']
                and digest(pdb) == digest(output / pdb.name) == bound['pdb_sha256'], 'Profiled/retained binary changed')
        receipt['runtime_after_sampling'] = inventory(runtime)
        if record:
            require({name: receipt['runtime_after_sampling'].get(name)
                     for name in receipt['runtime_before_sampling']} == receipt['runtime_before_sampling'],
                    'Runtime settings changed during capture')
            require(inventory(runtime / 'telemetry-sessions') == receipt['measurement_files'],
                    'Measurement exports changed after validation')
        else:
            require(receipt['runtime_after_sampling'] == receipt['runtime_before_sampling'],
                    'Runtime settings changed during capture')
        verify_inputs()
        game = (output / 'game.log').read_text(encoding='utf-8', errors='replace')
        validate_scene_log(game)
        receipt['authored_error_log_clear'] = True
        receipt['post_capture_inputs_verified'] = True

    try:
        with (output / 'game.log').open('xb') as stream:
            process = subprocess.Popen(command, cwd=runtime if record else root, env=env,
                                       stdout=stream, stderr=subprocess.STDOUT)
            receipt['pid'] = process.pid
            driver.bind(process.pid)
            driver.configure(EXTENT)
            for _ in range(3):
                time.sleep(1)
                driver.check(EXTENT)
                tap(driver, 'Return')
            tap(driver, 'F2')
            replay(driver, process, EXTENT, 'stationary', 10)
            receipt['before'] = exit_snapshot(driver, process)
            require(receipt['before']['window'].get('owned_by_launched_process'), 'No verified renderer thread')
            receipt['renderer_window_thread_id'] = receipt['before']['window']['owner_thread_id']
            receipt['runtime_before_sampling'] = inventory(runtime)
            if record:
                receipt['record_start'] = record_request(driver, runtime, start=True)
            # Even a timed-out start may have created this unique owned logger.
            started = True
            command_log(wpr_command(wpr, instance, '-start', 'CPU'), root, output / 'wpr-start.log')
            receipt['sample_started_unix_ns'] = time.time_ns()
            receipt['replay'] = replay(driver, process, EXTENT, 'stationary', SECONDS)
            receipt['sample_finished_unix_ns'] = time.time_ns()
            command_log(wpr_command(wpr, instance, '-status', 'collectors', '-details'), root, output / 'wpr-status.log')
            command_log(wpr_command(wpr, instance, '-stop', output / 'cpu.etl', '-skipPdbGen', '-compress'),
                        root, output / 'wpr-stop.log', timeout=180)
            started = False
            trace_saved = True
            if record:
                receipt['record_stop'] = record_request(driver, runtime, start=False)
                receipt['measurements'] = recorded_measurements(runtime, bound['exe_sha256'])
                receipt['measurement_files'] = inventory(runtime / 'telemetry-sessions')
            receipt['after'] = exit_snapshot(driver, process)
            driver.check(EXTENT)
            receipt['shutdown'] = normal_shutdown(driver, process)
            if not receipt['shutdown']['normal_exit']:
                raise NormalShutdownFailure('Game did not exit normally; inspect shutdown attempts')
    except BaseException as error:
        receipt['error'] = str(error)
        pending_error = error
    pending_error = finalize_capture(root, output, driver, process, wpr, instance,
                                     started, trace_saved, tools, target, receipt, pending_error,
                                     verify_final=verify_final_inputs)
    if pending_error is not None:
        raise pending_error


def record_request(driver, runtime, *, start):
    import performance_matrix as matrix
    from summarize_cpu_substages import read_json
    result = {'key': 'F8', 'requested_unix_ns': time.time_ns()}
    tap(driver, 'F8')
    result['key_released_unix_ns'] = time.time_ns()

    def ready():
        folder = matrix.sole_session(runtime, complete=not start)
        if folder is None:
            return None
        if not start:
            try:
                for name in ('frames.cpu-substages.json', 'frames.cpu-encode-detail.json'):
                    read_json(folder / name)
            except (OSError, ValueError):
                return None
        return folder

    folder = matrix.wait_until(ready, timeout=10 if start else 30,
                               label='Record start' if start else 'complete CPU-detail export')
    result.update(observed_unix_ns=time.time_ns(), session=folder.name)
    return result


def recorded_measurements(runtime, executable_sha256):
    import performance_matrix as matrix
    import summarize_cpu_substages as cpu
    import summarize_cpu_encode_detail as encode
    folder = matrix.sole_session(runtime, complete=True)
    require(folder is not None, 'One complete Record session is required')
    primary, raw_hash = cpu.read_json(folder / 'frames.json')
    substages, _ = cpu.read_json(folder / 'frames.cpu-substages.json')
    detail, _ = cpu.read_json(folder / 'frames.cpu-encode-detail.json')
    summary = encode.summarize(detail, substages, primary, raw_hash)
    require(primary['status']['state'] == 'complete' and primary['ineligible_present_count'] == 0,
            'Record must finish with complete eligible gameplay')
    require(not any(row['kind'] in ('boundary', 'window_context') for row in primary['records']),
            'Focus/pause/resize boundary during recorded sampling')
    require(summary['diagnostic_status'] == 'complete' and summary['summarized_attempts'] > 0,
            'Complete CPU encode-detail samples are required')
    runtime_observed = primary['identity']['runtime_observed']
    adapter = runtime_observed['actual_adapter']
    require(runtime_observed['actual_backend'] == 'Dx12' and adapter['backend'] == 'Dx12'
            and adapter['name'] == 'Microsoft Basic Render Driver' and adapter['device_type'] == 'Cpu'
            and adapter['force_fallback_requested'] is True and adapter['present_mode'] == 'Immediate'
            and adapter['gpu_timestamps_requested'] is False
            and adapter['gpu_timestamp_features_enabled'] is False,
            'Record must observe the requested DX12/WARP/Immediate/default-off device')
    descriptor = adapter['instance_descriptor']
    require(descriptor['application_debug_assertions'] is False and descriptor['flags_bits'] == 32,
            'Record instance flags or app profile differ from this fixed release build')
    window = runtime_observed['initial_window']
    require([window['physical_width'], window['physical_height']] == EXTENT and window['mode'] == 'windowed'
            and all([row['physical_width'], row['physical_height']] == EXTENT
                    for row in primary['cpu_frame_stages']['samples']), 'Record physical extent differs')
    scene = runtime_observed['scene']
    require(scene.get('name') == 'vector_range_default_range' and scene.get('presentation') == 'authored_viewmodel'
            and scene.get('profile_base') == 'm4a1' and scene.get('weapon_id') == 'hk416a5'
            and scene.get('reference_viewport') is False and scene.get('diagnostic_capture') is False
            and scene.get('demo') is False and scene.get('capture_sequence') is None,
            'Record must observe the original authored range scene')
    identity = matrix.json_read(folder / 'IDENTITY.json')
    require(identity.get('schema') == 'rust-duty-local-playtest-session/v1'
            and identity.get('executable_sha256') == executable_sha256
            and identity.get('build') == runtime_observed['build']
            and identity.get('graphics_device') == adapter, 'Record executable/build/device identity differs')
    # These fresh profiler builds are bound by complete source receipts, not a
    # retail package label or fabricated counterfactual Git commit.
    require(identity.get('source', {}).get('state') == 'unavailable',
            'Unexpected adjacent retail package identity in a fresh diagnostic build')
    status = matrix.json_read(folder / 'CSV_STATUS.json')
    require(status.get('state') == 'stopped' and status.get('error') is None, 'Incomplete gameplay CSV')
    gameplay = matrix.gameplay_summary(folder / 'gameplay.csv')
    require(gameplay['speed_max'] < 0.1 and gameplay['ads_max'] < 0.01,
            'Recorded input is not stationary hip-fire')
    require(not (folder / 'frames.gpu-timing.json').exists(), 'Unexpected GPU timing opt-in')
    values = [row['interval_ns'] for row in primary['records']
              if row['kind'] == 'successful_present_return' and row['interval_ns'] is not None]
    require(values and sum(values) >= SECONDS * 0.90 * 1e9, 'Insufficient retained Record duration')
    return {'session': folder.name, 'frame_report_sha256': raw_hash, 'adapter': adapter,
            'build': runtime_observed['build'], 'scene': scene, 'initial_window': window,
            'primary_summary_ns': primary['summary'], 'present_intervals': len(values),
            'present_interval_total_ns': sum(values), 'tail_comparison_ready': len(values) >= 100,
            'cpu_stages': cpu.frames._cpu_stage_summary(primary['cpu_frame_stages'], primary['records']),
            'cpu_substages': cpu.summarize(substages, primary, raw_hash), 'cpu_encode_detail': summary,
            'upload_policy': detail.get('upload_policy'), 'gameplay': gameplay,
            'gpu_counter_export': matrix.gpu_export_summary(folder),
            'scope': 'Complete Record window, including explicit margins around WPR; no pooled quantiles or sample-count normalization'}



def normal_shutdown(driver, process):
    """Normal app/window requests only; forced cleanup remains a separate result."""
    result = {'normal_exit': False, 'method': None,
              'before': exit_snapshot(driver, process),
              'f10': {'attempted': False}, 'wm_close': {'attempted': False}}
    for method in ('f10', 'wm_close'):
        if process.poll() is not None:
            result.update(normal_exit=process.returncode == 0, method='already_exited',
                          exit_code=process.returncode)
            return result
        attempt = result[method]
        try:
            if method == 'f10':
                attempt['attempted'] = True
                driver.close()
            else:
                # Never search for another window or post to a recycled HWND.
                owner = wintypes.DWORD()
                window = driver.window
                require(window and driver.user.IsWindow(window), 'Bound game window is absent')
                thread = driver.user.GetWindowThreadProcessId(window, ctypes.byref(owner))
                require(thread and owner.value == process.pid, 'Bound window owner differs from launched PID')
                attempt.update(hwnd=window, owner_pid=owner.value, owner_thread_id=thread,
                               attempted=True, message='WM_CLOSE')
                require(driver.user.PostMessageW(window, 0x0010, 0, 0), 'Owned WM_CLOSE request failed')
            code = process.wait(timeout=20)
            attempt['exit_code'] = code
            result.update(normal_exit=code == 0, method=method, exit_code=code)
            return result
        except subprocess.TimeoutExpired as error:
            attempt.update(timed_out=True, timeout_seconds=20, error=str(error))
        except (OSError, ValueError, DriverError) as error:
            attempt['error'] = str(error)
        attempt['after'] = exit_snapshot(driver, process, probe_responsiveness=True)
    return result


def export_trace(root, output, tools, target, process, receipt):
    # Local build PDBs identify game functions. OS/driver symbols use only the
    # public Microsoft server; unresolved entries remain explicit in reports.
    symbols = str(target / 'release') + ';srv*' + str(output / 'symbols') + '*https://msdl.microsoft.com/download/symbols'
    export_env = dict(os.environ, _NT_SYMBOL_PATH=symbols, _NT_SYMCACHE_PATH=str(output / 'symcache'))
    for action, args in [('profile', ['-detail']), ('process', []), ('tracestats', []), ('stack', ['-butterfly']),
                         ('renderer-stack', ['-butterfly', '-event', 'Profile', '-pid', str(process.pid),
                                             '-tid', str(receipt['renderer_window_thread_id'])])]:
        command_log([tools['xperf']['path'], '-i', output / 'cpu.etl', '-symbols',
                     '-o', output / (action + '.txt'), '-a', 'stack' if action == 'renderer-stack' else action, *args], root,
                    output / (action + '-export.log'), env=export_env, timeout=180)
    return {'passed': True, 'trace_sha256': digest(output / 'cpu.etl'),
            'reports_sha256': {name: digest(output / (name + '.txt'))
                              for name in ('profile', 'process', 'tracestats', 'stack', 'renderer-stack')}}


def finalize_capture(root, output, driver, process, wpr, instance, started, trace_saved,
                     tools, target, receipt, pending_error, *, verify_final=None):
    observation = {}
    cleanup, code = cleanup_owned(root, output, driver, process, wpr, instance, started, observation)
    receipt.update(cleanup_errors=cleanup, cleanup=observation, exit_code=code,
                   trace_saved=trace_saved, trace_export={'passed': False})
    input_error = None
    receipt['post_capture_checks'] = {'passed': False, 'attempted': False}
    if verify_final is not None and not isinstance(pending_error, (KeyboardInterrupt, SystemExit)):
        receipt['post_capture_checks']['attempted'] = True
        try:
            require(type(code) is int, 'Cannot verify final inputs while owned process exit is unknown')
            verify_final()
            receipt['post_capture_checks']['passed'] = True
        except BaseException as error:
            input_error = error
            receipt['post_capture_inputs_verified'] = False
            receipt['post_capture_checks'].update(error=str(error) or type(error).__name__,
                                                  error_type=type(error).__name__)
    export_error = None
    # A failed normal exit does not erase a stopped trace. Explicit interrupts
    # still stop work rather than beginning additional report-export commands.
    if trace_saved and not any(isinstance(error, (KeyboardInterrupt, SystemExit))
                               for error in (pending_error, input_error)):
        try:
            receipt['trace_export'] = export_trace(root, output, tools, target, process, receipt)
        except BaseException as error:
            export_error = error
            receipt['trace_export'].update(error=str(error) or type(error).__name__,
                                           error_type=type(error).__name__)
    receipt['passed'] = (pending_error is None and input_error is None and not cleanup and not observation.get('forced', False)
                         and receipt.get('shutdown', {}).get('normal_exit') is True
                         and receipt.get('post_capture_inputs_verified') is True
                         and receipt['trace_export']['passed'])
    failure = next((error for error in (export_error, input_error)
                    if isinstance(error, (KeyboardInterrupt, SystemExit))), pending_error)
    if failure is None and input_error is not None:
        failure = input_error
    if failure is None and cleanup:
        failure = ValueError('Cleanup incomplete; inspect capture.json')
    if failure is None and export_error is not None:
        failure = export_error
    if failure is None and not receipt['passed']:
        failure = ValueError('Capture or trace export incomplete; inspect capture.json')
    if failure is not None:
        primary_error = pending_error if pending_error is not None else failure
        receipt.setdefault('error', str(primary_error) or type(primary_error).__name__)
        receipt['error_type'] = type(primary_error).__name__
    write(output / 'capture.json', receipt)
    return failure


def cleanup_owned(root, output, driver, process, wpr, instance, started, observation=None):
    observation = {} if observation is None else observation
    observation.update(forced=False, process_action='not_launched')
    cleanup = []
    if started:
        try:
            command_log(wpr_command(wpr, instance, '-cancel'), root, output / 'wpr-owned-cleanup.log')
        except Exception as error:
            cleanup.append('owned trace cleanup: ' + str(error))
    try:
        cleanup.extend(driver.release_inputs())
    except Exception as error:
        cleanup.append('input cleanup: ' + str(error))
    code = None
    try:
        if process is not None:
            observation['process_action'] = 'already_exited'
            if process.poll() is None:
                observation.update(forced=True, process_action='terminate')
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    observation['process_action'] = 'kill'
                    process.kill()
                    process.wait(timeout=5)
            code = process.poll()
            require(type(code) is int, 'Owned process exit is unverified')
    except Exception as error:
        cleanup.append('owned process cleanup: ' + str(error))
    return cleanup, code


PAIR_ORDER = ('baseline', 'candidate', 'candidate', 'baseline')


def retained_inventory(folder):
    """Exclude only nonretained compiler and public-symbol caches."""
    result = {}
    for path in sorted(Path(folder).rglob('*')):
        relative = path.relative_to(folder)
        if {'target', 'symbols', 'symcache'}.intersection(relative.parts):
            continue
        require(not path.is_symlink(), 'Symlink in retained comparison evidence')
        if path.is_file():
            result[relative.as_posix()] = digest(path)
    return result


def compare_uploads(root, output, experiment='geometry-reuse'):
    """Run one source-bound ABBA diagnostic; shutdown failures remain failures."""
    import tempfile
    import performance_matrix as matrix
    import run_cpu_image_preservation as pair
    require_host()
    root, output = root.resolve(), output.resolve()
    require(root == Path(__file__).resolve().parents[1], 'Runner and actual checkout differ')
    pair.check_environment(os.environ)
    pair.check_cargo_configuration(root, os.environ)
    require(not (root / 'assets/weapons').exists(), 'Private weapon asset inputs are excluded')
    source = checked_source(root)
    assets = inventory(root / 'assets')
    require('animations.cfg' in assets and 'locomotion/asset.vrs' in assets,
            'Need the existing validated original authored companions')
    tools = json.loads((output / 'tools.json').read_text(encoding='utf-8'))
    require(all(digest(value['path']) == value['sha256'] for value in tools.values()), 'Profiler changed')
    compiler = pair.toolchain_at(root)
    require('release: 1.99.0\n' in compiler['rustc'] and 'host: x86_64-pc-windows-msvc\n' in compiler['rustc']
            and compiler['cargo'].startswith('cargo 1.99.0 '), 'Need pinned Rust1.99 MSVC')
    production = pair.read_sources(root, source['commit'], pair.PRODUCTION_PATHS)
    require(all((root / name).read_bytes() == raw for name, raw in production.items()),
            'Committed production bytes differ')
    require(experiment in ('geometry-reuse', 'arena-serialization', 'authored-dedup'), 'Unknown profile experiment')
    variants = (pair.geometry_production_pair(production) if experiment == 'geometry-reuse' else
                pair.loader_production_pair(production, pair.read_sources(root, pair.LOADER_BASELINE_COMMIT, sorted(pair.LOADER_BASELINE)))
                if experiment == 'authored-dedup' else pair.serialization_production_pair(production,
                    pair.read_sources(root, pair.BASELINE_CPU_COMMIT, [pair.ARENA_PATH])))
    binding = {'source_commit': source['commit'], 'profile_source': source}
    receipts = pair.materialize_variants(output / 'sources', variants, binding,
        pair.experiment_metadata(experiment))
    write(output / 'pair-inputs.json', {'schema': 'rust-duty-upload-profile-pair/v1',
          'experiment': experiment, 'source': source, 'assets_sha256': assets, 'toolchain': compiler, 'build_command': BUILD,
          'build_settings': SETTINGS, 'order': list(PAIR_ORDER), 'sample_seconds': SECONDS,
          'warmup_seconds': 10, 'record_enabled': True, 'physical_extent': EXTENT,
          'materialize_receipt_sha256': digest(output / 'materialize.json'),
          'scope': 'Matched instrumented WARP upload diagnostic; no RTX or target-performance verdict'})
    retained = {output / name: digest(output / name)
                for name in ('tools.json', 'materialize.json', 'pair-inputs.json')}
    snapshots, builds, results = {}, {}, []

    def verify_all():
        require(checked_source(root) == source and inventory(root / 'assets') == assets,
                'Common source/assets changed')
        pair.verify_sources(receipts)
        require(all(digest(path) == expected for path, expected in retained.items()),
                'Retained pair input/build receipt changed')
        require(all(retained_inventory(path) == expected for path, expected in snapshots.items()),
                'Earlier retained build/capture output changed')
        require(all(digest(value['target'] / 'release/vector-range.exe') == value['bound']['exe_sha256']
                    and digest(value['target'] / 'release/vector_range.pdb') == value['bound']['pdb_sha256']
                    for value in builds.values()), 'Earlier compiled EXE/PDB changed')
        for directory in (root, *(receipt['source'] for receipt in receipts.values())):
            pair.check_cargo_configuration(directory, os.environ)
            require(pair.toolchain_at(directory) == compiler, 'Actual source-directory toolchain changed')
        require(all(digest(value['path']) == value['sha256'] for value in tools.values()), 'Profiler changed')

    try:
        for label, receipt in receipts.items():
            folder = output / (label + '-build')
            folder.mkdir(exist_ok=False)
            target = folder / 'target'
            env = dict(os.environ, **SETTINGS, CARGO_TARGET_DIR=str(target))
            verify_all()
            command_log(BUILD, receipt['source'], folder / 'build.log', env=env, timeout=1800, owned_tree=True)
            bound = {'exe_sha256': digest(target / 'release/vector-range.exe'),
                     'pdb_sha256': digest(target / 'release/vector_range.pdb')}
            require((target / 'release/vector_range.pdb').stat().st_size > 0, 'Fresh matching PDB required')
            for name in ('vector-range.exe', 'vector_range.pdb'):
                shutil.copyfile(target / 'release' / name, folder / name)
            write(folder / 'build.json', {'command': BUILD, 'settings': SETTINGS, 'compiler': compiler,
                  'source_commit': source['commit'], 'source_variant': label,
                  'source_receipt_sha256': receipt['receipt_sha256'], 'compiled_files_sha256': receipt['files'],
                  'counterfactual': label == 'baseline', **bound})
            builds[label] = {'target': target, 'bound': bound, 'env': env}
            snapshots[folder] = retained_inventory(folder)
            verify_all()
        with matrix.desktop_lock(Path(tempfile.gettempdir()) / 'rust-duty-performance-desktop.lock'):
            for ordinal, label in enumerate(PAIR_ORDER, 1):
                verify_all()
                folder = output / f'r{ordinal:02}-{label}'
                folder.mkdir(exist_ok=False)
                value = builds[label]
                capture_error = None
                try:
                    sample_build(root, folder, tools, value['target'], source, value['bound'], value['env'],
                                 verify_all, record=True, source_variant=label,
                                 source_receipt_sha256=receipts[label]['receipt_sha256'])
                except NormalShutdownFailure as error:
                    capture_error = str(error) or type(error).__name__
                require((folder / 'capture.json').is_file(), 'Capture did not retain its terminal receipt')
                capture = matrix.json_read(folder / 'capture.json')
                require(capture.get('source_variant') == label
                        and capture.get('source_receipt_sha256') == receipts[label]['receipt_sha256']
                        and capture.get('counterfactual_source') is (label == 'baseline')
                        and capture.get('source_commit') == source['commit'],
                        'Sampled source-variant receipt differs')
                if capture_error is not None:
                    require(capture['passed'] is False and capture.get('error_type') == 'NormalShutdownFailure'
                            and capture.get('shutdown', {}).get('normal_exit') is False,
                            'Only an explicit failed normal shutdown permits diagnostic continuation')
                require(capture.get('post_capture_checks', {}).get('passed') is True
                        and capture.get('post_capture_inputs_verified') is True,
                        'Post-cleanup source/assets/settings/binary checks did not pass')
                require(capture['trace_saved'] is True and capture['trace_export']['passed'] is True
                        and type(capture['exit_code']) is int and not capture['cleanup_errors'],
                        'Stopped trace/export or owned process cleanup is incomplete')
                verify_all()
                validate_scene_log((folder / 'game.log').read_text(encoding='utf-8', errors='replace'))
                after = inventory(folder / 'runtime')
                require({name: after.get(name) for name in capture['runtime_before_sampling']}
                        == capture['runtime_before_sampling'], 'Per-process runtime settings changed')
                require(all(name in capture['runtime_before_sampling'] or name == 'telemetry.csv'
                            or name.startswith('telemetry-sessions/') for name in after),
                        'Unexpected per-process runtime output')
                require(digest(folder / 'cpu.etl') == capture['trace_export']['trace_sha256']
                        and all(digest(folder / (name + '.txt')) == expected
                                for name, expected in capture['trace_export']['reports_sha256'].items()),
                        'Trace or export changed before acceptance')
                measured = recorded_measurements(folder / 'runtime', value['bound']['exe_sha256'])
                require(measured == capture.get('measurements') and inventory(folder / 'runtime/telemetry-sessions')
                        == capture.get('measurement_files'), 'Retained Record exports changed')
                require(capture['record_start']['session'] == capture['record_stop']['session'] == measured['session'],
                        'Record start/stop/export sessions differ')
                require(capture['record_start']['requested_unix_ns'] <= capture['record_start']['observed_unix_ns']
                        <= capture['sample_started_unix_ns'] < capture['sample_finished_unix_ns']
                        <= capture['record_stop']['requested_unix_ns'] <= capture['record_stop']['observed_unix_ns'],
                        'Record request window does not contain the WPR replay window')
                require(measured['upload_policy'] == pair.experiment_metadata(experiment)['upload_policies'][label],
                        'Actual measured upload policy differs from compiled source variant')
                for name in ('vector-range.exe', 'vector_range.pdb'):
                    require(digest(folder / name) == digest(value['target'] / 'release' / name),
                            'Retained sampled EXE/PDB changed')
                current = {'ordinal': ordinal, 'variant': label, 'capture_passed': capture['passed'],
                           'capture_error': capture_error, 'capture_sha256': digest(folder / 'capture.json'),
                           'measurements': measured, 'source_receipt_sha256': receipts[label]['receipt_sha256']}
                results.append(current)
                snapshots[folder] = retained_inventory(folder)
                verify_all()
        first = results[0]['measurements']
        require(all(all(item['measurements'][field] == first[field]
                        for field in ('adapter', 'build', 'scene', 'initial_window')) for item in results),
                'Actual paired device/build/scene/window identity differs')
        verify_all()
        passed = all(item['capture_passed'] for item in results)
        write(output / 'pair-summary.json', {'schema': 'rust-duty-upload-profile-pair/v1',
              'experiment': experiment, 'passed': passed, 'diagnostic_runs_complete': len(results), 'runs': results,
              'retained_files_sha256': {str(path.relative_to(output)): files for path, files in snapshots.items()},
              'target_1080p60_proven': False, 'performance_improvement': None,
              'scope': 'ABBA per-run Record summaries and separately bounded WPR traces. No pooled quantiles, parent/child percentile subtraction or RTX extrapolation.'})
        require(passed, 'All paired traces retained, but one or more normal capture exits failed')
    except BaseException as error:
        write(output / 'pair-failure.json', {'passed': False, 'completed_runs': len(results),
              'error': str(error) or type(error).__name__, 'error_type': type(error).__name__})
        raise



def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('preflight', 'capture', 'compare-uploads', 'compare-serialization', 'compare-loaders'))
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == 'preflight':
            preflight(args.root.resolve(), args.output.resolve())
        elif args.mode == 'capture':
            capture(args.root, args.output)
        else:
            compare_uploads(args.root, args.output,
                            'authored-dedup' if args.mode == 'compare-loaders' else
                            'arena-serialization' if args.mode == 'compare-serialization' else 'geometry-reuse')
        return 0
    except (ValueError, OSError, KeyError, DriverError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

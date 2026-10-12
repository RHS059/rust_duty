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


def command_log(command, root, output, *, env=None, timeout=120):
    output = Path(output)
    with output.open('xb') as stream:
        result = subprocess.run(list(map(str, command)), cwd=root, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=timeout)
    require(result.returncode == 0, 'Command failed; inspect ' + output.name)
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
    command_log(BUILD, root, output / 'build.log', env=env, timeout=1800)
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
               'top_functions_reviewed': False, 'initial_settings_sha256': initial_settings}
    try:
        with (output / 'game.log').open('xb') as stream:
            process = subprocess.Popen(command, cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT)
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
            receipt['after'] = exit_snapshot(driver, process)
            driver.check(EXTENT)
            receipt['shutdown'] = normal_shutdown(driver, process)
            require(receipt['shutdown']['normal_exit'], 'Game did not exit normally; inspect shutdown attempts')
        require(digest(binary) == digest(output / binary.name) == bound['exe_sha256']
                and digest(pdb) == digest(output / pdb.name) == bound['pdb_sha256'], 'Profiled/retained binary changed')
        receipt['runtime_after_sampling'] = inventory(runtime)
        require(receipt['runtime_after_sampling'] == receipt['runtime_before_sampling'], 'Runtime settings changed during capture')
        require(checked_source(root) == source and inventory(root / 'assets') == assets, 'Capture inputs changed')
        game = (output / 'game.log').read_text(encoding='utf-8', errors='replace')
        validate_scene_log(game)
        receipt['authored_error_log_clear'] = True
        receipt['post_capture_inputs_verified'] = True
    except BaseException as error:
        receipt['error'] = str(error)
        pending_error = error
    pending_error = finalize_capture(root, output, driver, process, wpr, instance,
                                     started, trace_saved, tools, target, receipt, pending_error)
    if pending_error is not None:
        raise pending_error


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
                     tools, target, receipt, pending_error):
    observation = {}
    cleanup, code = cleanup_owned(root, output, driver, process, wpr, instance, started, observation)
    receipt.update(cleanup_errors=cleanup, cleanup=observation, exit_code=code,
                   trace_saved=trace_saved, trace_export={'passed': False})
    export_error = None
    # A failed normal exit does not erase a stopped trace. Explicit interrupts
    # still stop work rather than beginning additional report-export commands.
    if trace_saved and not isinstance(pending_error, (KeyboardInterrupt, SystemExit)):
        try:
            receipt['trace_export'] = export_trace(root, output, tools, target, process, receipt)
        except BaseException as error:
            export_error = error
            receipt['trace_export'].update(error=str(error) or type(error).__name__,
                                           error_type=type(error).__name__)
    receipt['passed'] = (pending_error is None and not cleanup and not observation.get('forced', False)
                         and receipt.get('shutdown', {}).get('normal_exit') is True
                         and receipt.get('post_capture_inputs_verified') is True
                         and receipt['trace_export']['passed'])
    failure = export_error if isinstance(export_error, (KeyboardInterrupt, SystemExit)) else pending_error
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('preflight', 'capture'))
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == 'preflight':
            preflight(args.root.resolve(), args.output.resolve())
        else:
            capture(args.root, args.output)
        return 0
    except (ValueError, OSError, KeyError, DriverError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

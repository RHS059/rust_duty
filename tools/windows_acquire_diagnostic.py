#!/usr/bin/env python3
"""Bounded observer-only derivative of the pinned Windows game and DX12 HAL.

This is deliberately separate from the production performance matrix. No timing,
physics, presentation, wait-result handling or acceptance threshold is changed.
"""
import argparse
import difflib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib

import performance_matrix as matrix
from performance_matrix_driver import create_driver, exit_snapshot, replay, tap, wait_until

SOURCE = '49c3bf9b3d0482ce81a7d50683904bda28468d7d'
HAL_VERSION = '30.0.1'
HAL_SHA256 = 'b6b7fb58561a792bc237628ba0792e332de418fefe145f13b5ed8201e6d52f58'
HAL_FILE_SHA256 = 'aea978a714e2427df87458bcb36d66f9195cff6ad521c5bab2ca2806a56d94dc'
ORIGINALS = {
    'Cargo.lock': '2aa35ed5561b7e40f515520ec36cb7eaa5c4175f12f0fcf9c764dd0ae6cbdeef',
    'Cargo.toml': 'ec02a76fb9e8eb29178d707c0f6cfea8206b0299d81f6594fd3cfe0707f55584',
    'src/app.rs': 'c282e402b35b0edee452eff30741251b729a936e90431c94387eb14c3cb918da',
    'src/platform/window.rs': '485b038b385a5a2f6ff74ee1f57c6a94a902c32bf6ab954a5f86bccd85e085d8',
    'src/render/device.rs': 'fe742b814bcc55ab3b5d13ad70a03dcef54e5369a7b3a82665a016eec16a6763',
}
PREFIX = 'rd_acquire_exit_v1 '
SCOPE = ('Instrumented derivative, native Windows DX12 WARP CPU software diagnostic only. '
         'Not the original production binary, GPU frame time, full matrix, or RTX acceptance.')
MARKER = '''
// Observer-only acquire/exit diagnostic; this file belongs to a derived build.
fn rd_acquire_exit_mark(event: &str, elapsed_ns: u128) {
    std::eprintln!(
        "rd_acquire_exit_v1 event={} unix_ns={} elapsed_ns={}",
        event,
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |value| value.as_nanos()),
        elapsed_ns
    );
}
'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def replace_once(text, old, new):
    matrix.require(text.count(old) == 1, 'Instrumentation anchor differs or is ambiguous')
    return text.replace(old, new, 1)


def instrument(name, data):
    """Exact hashes plus exact anchors reject source drift before any patching."""
    expected = HAL_FILE_SHA256 if name == 'hal/src/dx12/mod.rs' else ORIGINALS[name]
    matrix.require(digest(data) == expected, 'Original source hash differs: ' + name)
    text = data.decode('utf-8')
    if name == 'src/platform/window.rs':
        text = replace_once(text,
            '    let result = event_loop.run_app(&mut runtime).map_err(|e| e.to_string());',
            '    rd_acquire_exit_mark("run_app_enter", 0);\n'
            '    let diagnostic_run_start = std::time::Instant::now();\n'
            '    let result = event_loop.run_app(&mut runtime).map_err(|e| e.to_string());\n'
            '    rd_acquire_exit_mark("run_app_exit", diagnostic_run_start.elapsed().as_nanos());')
        text = replace_once(text, '    runtime.hooks.take();',
            '    rd_acquire_exit_mark("hooks_drop_enter", 0);\n'
            '    let diagnostic_drop_start = std::time::Instant::now();\n'
            '    runtime.hooks.take();\n'
            '    rd_acquire_exit_mark("hooks_drop_exit", diagnostic_drop_start.elapsed().as_nanos());')
        text = replace_once(text,
            '            WindowEvent::CloseRequested | WindowEvent::Destroyed => event_loop.exit(),',
            '            event @ (WindowEvent::CloseRequested | WindowEvent::Destroyed) => {\n'
            '                let kind = if matches!(event, WindowEvent::CloseRequested) { "native_close" } else { "native_destroyed" };\n'
            '                rd_acquire_exit_mark(&format!("{kind}_enter"), 0);\n'
            '                let diagnostic_exit_start = std::time::Instant::now();\n'
            '                event_loop.exit();\n'
            '                rd_acquire_exit_mark(&format!("{kind}_exit"), diagnostic_exit_start.elapsed().as_nanos());\n'
            '            }')
    elif name == 'src/app.rs':
        text = replace_once(text, '        if focus_input.is_key_pressed(KeyCode::F10) {',
            '        if focus_input.is_key_pressed(KeyCode::F10) {\n'
            '            rd_acquire_exit_mark("f10_enter", 0);\n'
            '            let diagnostic_f10_start = std::time::Instant::now();')
        text = replace_once(text, '                BoundaryReason::Shutdown,\n            )));\n            break;',
            '                BoundaryReason::Shutdown,\n            )));\n'
            '            rd_acquire_exit_mark("f10_exit", diagnostic_f10_start.elapsed().as_nanos());\n'
            '            break;')
    elif name == 'src/render/device.rs':
        text = replace_once(text, '            let status = surface.surface.get_current_texture();',
            '            rd_acquire_exit_mark("surface_acquire_enter", 0);\n'
            '            let diagnostic_acquire_start = std::time::Instant::now();\n'
            '            let status = surface.surface.get_current_texture();\n'
            '            rd_acquire_exit_mark("surface_acquire_exit", diagnostic_acquire_start.elapsed().as_nanos());')
    elif name == 'hal/src/dx12/mod.rs':
        text = replace_once(text, '                unsafe { sc.wait(timeout) }?;',
            '                static DIAGNOSTIC_WAIT: core::sync::atomic::AtomicU64 = core::sync::atomic::AtomicU64::new(0);\n'
            '                let sequence = DIAGNOSTIC_WAIT.fetch_add(1, core::sync::atomic::Ordering::Relaxed);\n'
            '                rd_acquire_exit_mark("hal_wait_enter", 0);\n'
            '                let diagnostic_wait_start = std::time::Instant::now();\n'
            '                let diagnostic_wait_result = unsafe { sc.wait(timeout) };\n'
            '                let elapsed_ns = diagnostic_wait_start.elapsed().as_nanos();\n'
            '                std::eprintln!("rd_acquire_exit_v1 event=hal_wait_result sequence={} elapsed_ns={} wait_ok={} timeout_ns={} waitable={}",\n'
            '                    sequence, elapsed_ns,\n'
            '                    match &diagnostic_wait_result { Ok(true) => "true", Ok(false) => "false", Err(_) => "error" },\n'
            '                    timeout.map_or(u128::MAX, |value| value.as_nanos()), sc.waitable.is_some());\n'
            '                rd_acquire_exit_mark("hal_wait_exit", elapsed_ns);\n'
            '                diagnostic_wait_result?;')
    else:
        raise ValueError('Unsupported instrumentation target')
    return (text + MARKER).encode('utf-8')


def extract_regular(archive, target, prefix=''):
    """Archive inputs are immutable; still reject links and path traversal."""
    for member in archive.getmembers():
        path = Path(member.name)
        matrix.require(not path.is_absolute() and '..' not in path.parts and
                       '\\' not in member.name and ':' not in member.name,
                       'Unsafe archive member')
        if prefix:
            matrix.require(path.parts[0] == prefix, 'Unexpected dependency root')
            path = Path(*path.parts[1:])
        if member.isdir():
            (target / path).mkdir(parents=True, exist_ok=True)
            continue
        matrix.require(member.isfile(), 'Archive links are unsupported')
        destination = target / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        with archive.extractfile(member) as stream, destination.open('xb') as output:
            shutil.copyfileobj(stream, output)


def tree_hashes(root):
    result = {}
    for path in sorted(root.rglob('*')):
        matrix.require(not path.is_symlink(), 'Symlink in diagnostic inputs')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = matrix.sha256(path)
    return result


def prepare(repository, crate, output):
    matrix.require(matrix.sha256(crate) == HAL_SHA256, 'Pinned HAL crate checksum differs')
    matrix.require(subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'],
                                         text=True).strip() == SOURCE, 'Wrong production source commit')
    # Export committed blobs; untracked files and working-tree edits cannot enter the derivative.
    exported = subprocess.check_output(['git', '-C', str(repository), 'archive', '--format=tar', SOURCE])
    output.mkdir()
    source, hal = output / 'source', output / 'hal'
    source.mkdir()
    hal.mkdir()
    with tarfile.open(fileobj=io.BytesIO(exported)) as archive:
        extract_regular(archive, source)
    with tarfile.open(crate, 'r:gz') as archive:
        extract_regular(archive, hal, 'wgpu-hal-' + HAL_VERSION)
    for name, expected in ORIGINALS.items():
        matrix.require(matrix.sha256(source / name) == expected, 'Wrong pinned file: ' + name)
    lock = tomllib.loads((source / 'Cargo.lock').read_text('utf-8'))
    selected = [p for p in lock['package'] if p['name'] == 'wgpu-hal']
    matrix.require(len(selected) == 1 and selected[0]['version'] == HAL_VERSION and
                   selected[0]['checksum'] == HAL_SHA256, 'Pinned Cargo dependency differs')
    receipt = {'schema': 'rust-duty-acquire-exit-derivative/v1', 'scope': SCOPE,
               'production_source_commit': SOURCE, 'production_source_archive_sha256': digest(exported),
               'production_files_sha256': tree_hashes(source),
               'hal_crate_sha256': HAL_SHA256, 'hal_version': HAL_VERSION,
               'hal_original_files_sha256': tree_hashes(hal), 'patches': {},
               'acceptance_proven': False, 'full_matrix_passed': False}
    patches = output / 'patches'
    patches.mkdir()
    for name, path in [(n, source / n) for n in ORIGINALS if n.startswith('src/')] + [
            ('hal/src/dx12/mod.rs', hal / 'src/dx12/mod.rs')]:
        old = path.read_bytes()
        new = instrument(name, old)
        path.write_bytes(new)
        patch = ''.join(difflib.unified_diff(old.decode().splitlines(True), new.decode().splitlines(True),
                                            fromfile='original/' + name, tofile='derived/' + name))
        patch_path = patches / (name.replace('/', '_') + '.patch')
        patch_path.write_text(patch, encoding='utf-8', newline='\n')
        receipt['patches'][name] = {'original_sha256': digest(old), 'derived_sha256': digest(new),
                                   'patch_file': patch_path.relative_to(output).as_posix(),
                                   'patch_sha256': digest(patch.encode())}
    # Rewrite just the locked registry entry to an identical-version local patch.
    # Other dependency versions/checksums stay exactly locked. Cargo then uses --locked.
    lock_path = source / 'Cargo.lock'
    old = lock_path.read_bytes()
    header = ('name = "wgpu-hal"\nversion = "30.0.1"\n'
              'source = "registry+https://github.com/rust-lang/crates.io-index"\n'
              'checksum = "' + HAL_SHA256 + '"\n')
    new = replace_once(old.decode(), header, 'name = "wgpu-hal"\nversion = "30.0.1"\n').encode()
    lock_path.write_bytes(new)
    patch = ''.join(difflib.unified_diff(old.decode().splitlines(True), new.decode().splitlines(True),
                                        fromfile='original/Cargo.lock', tofile='derived/Cargo.lock'))
    (patches / 'Cargo.lock.patch').write_text(patch, encoding='utf-8', newline='\n')
    receipt['patches']['Cargo.lock'] = {'original_sha256': digest(old), 'derived_sha256': digest(new),
        'patch_file': 'patches/Cargo.lock.patch', 'patch_sha256': digest(patch.encode())}
    config = '[patch.crates-io]\nwgpu-hal = { path = ' + json.dumps(hal.resolve().as_posix()) + ' }\n'
    (source / 'diagnostic-cargo.toml').write_text(config, encoding='utf-8', newline='\n')
    receipt['cargo_config_sha256'] = digest(config.encode())
    receipt['derived_files_sha256'] = tree_hashes(source)
    receipt['hal_derived_files_sha256'] = tree_hashes(hal)
    matrix.write_json(output / 'DERIVATION.json', receipt)
    return receipt


def stage(prepared, package, executable, output):
    """Keep the provider's original identity separate from the new executable."""
    derivation = matrix.json_read(prepared / 'DERIVATION.json', 16 * 1024 * 1024)
    matrix.require(derivation['production_source_commit'] == SOURCE, 'Wrong derivation')
    original = matrix.package_identity(package / 'vector-range.exe', {'commit': SOURCE}, 'dx12')
    build = original['build']
    matrix.require(build.get('repository') == 'RHS059/rust_duty' and
                   build.get('target') == 'x86_64-pc-windows-msvc' and
                   build.get('display_version') == '0.1.11+build.37505927104.1' and
                   build['source'].get('run_id') == 37505927104 and
                   build['source'].get('run_attempt') == 1 and build['source'].get('branch') == 'main',
                   'Wrong original package identity')
    preview = matrix.json_read(package / 'DX12_PREVIEW.json')
    matrix.require(preview.get('source') == build['source'] and
                   preview.get('executable_sha256') == original['executable_sha256'] and
                   preview.get('dx12_shader_compiler') == 'Fxc', 'Wrong original preview identity')
    # Only output binaries may be added by Cargo; verify every declared source/dependency input.
    for directory, key in [(prepared / 'source', 'derived_files_sha256'),
                           (prepared / 'hal', 'hal_derived_files_sha256')]:
        for name, expected in derivation[key].items():
            matrix.require(matrix.sha256(directory / name) == expected, 'Derived input changed: ' + name)
    output.mkdir()
    for directory in ('assets', 'ui'):
        shutil.copytree(package / directory, output / directory)
    shutil.copyfile(package / 'settings.cfg', output / 'settings.cfg')
    destination = output / 'Rust-Duty-acquire-exit-DIAGNOSTIC.exe'
    shutil.copyfile(executable, destination)
    matrix.require(matrix.sha256(destination) != original['executable_sha256'],
                   'Diagnostic must not be the original binary')
    receipt = {'schema': 'rust-duty-acquire-exit-build/v1', 'scope': SCOPE,
               'derivation_sha256': matrix.sha256(prepared / 'DERIVATION.json'),
               'original_package': original, 'diagnostic_executable_sha256': matrix.sha256(destination),
               'diagnostic_executable': destination.name,
               'rustc_vv': subprocess.check_output(['rustc', '-Vv'], text=True),
               'cargo_version': subprocess.check_output(['cargo', '-V'], text=True),
               'cargo_command': ['cargo', '--config', 'diagnostic-cargo.toml', 'build', '--locked',
                                 '--release', '--features', 'wgpu-runtime', '--bin', 'vector-range'],
               'runtime_files_sha256': tree_hashes(output),
               'acceptance_proven': False, 'full_matrix_passed': False}
    # No BUILD_IDENTITY.json is copied: production's packaged-source attribution
    # correctly reports unavailable for the derivative; this receipt binds it instead.
    matrix.write_json(output / 'DIAGNOSTIC_BUILD.json', receipt)
    return receipt


def parse_log(text):
    records = []
    for line in text.splitlines():
        if line.startswith(PREFIX):
            fields = dict(item.split('=', 1) for item in line[len(PREFIX):].split())
            matrix.require('event' in fields, 'Malformed observer marker')
            for key in ('sequence', 'elapsed_ns', 'unix_ns', 'timeout_ns'):
                if key in fields:
                    matrix.require(fields[key].isdigit(), 'Invalid observer integer')
                    fields[key] = int(fields[key])
            records.append(fields)
    waits = [r for r in records if r['event'] == 'hal_wait_result']
    matrix.require([r.get('sequence') for r in waits] == list(range(len(waits))),
                   'Missing or reordered HAL wait records')
    matrix.require(all(r.get('wait_ok') in ('true', 'false', 'error') and
                       r.get('waitable') in ('true', 'false') and 'elapsed_ns' in r for r in waits),
                   'Missing wait result or duration')
    lifecycle = {}
    for phase in ('f10', 'native_close', 'native_destroyed', 'run_app', 'hooks_drop'):
        entries = [r for r in records if r['event'] == phase + '_enter']
        exits = [r for r in records if r['event'] == phase + '_exit']
        lifecycle[phase] = {'entered': bool(entries), 'returned': bool(exits),
                            'entries': entries, 'exits': exits}
    return {'records': records, 'waits': waits, 'lifecycle': lifecycle,
            'wait_false_count': sum(r['wait_ok'] == 'false' for r in waits),
            'wait_true_count': sum(r['wait_ok'] == 'true' for r in waits)}


def request_exit(driver, process, method):
    driver.check([1920, 1080])
    snapshot = exit_snapshot(driver, process)
    window = snapshot.get('window', {})
    matrix.require(window.get('owned_by_launched_process') is True and snapshot.get('process_alive'),
                   'Exit request requires a live PID-owned window')
    if method == 'f10':
        tap(driver, 'F10')
    else:
        matrix.require(method == 'native-close', 'Unknown exit method')
        matrix.require(driver.user.PostMessageW(driver.window, 0x0010, 0, 0),
                       'Could not queue WM_CLOSE to the owned game window')
    return snapshot


def run(package, output, method='f10', seconds=25):
    matrix.require(sys.platform == 'win32', 'This diagnostic requires native Windows')
    matrix.require(type(seconds) is int and 20 <= seconds <= 30, 'Diagnostic sample must be 20..30 seconds')
    build = matrix.json_read(package / 'DIAGNOSTIC_BUILD.json', 16 * 1024 * 1024)
    executable = package / build['diagnostic_executable']
    matrix.require(matrix.sha256(executable) == build['diagnostic_executable_sha256'], 'Diagnostic binary changed')
    for name, expected in build['runtime_files_sha256'].items():
        matrix.require(matrix.sha256(package / name) == expected, 'Runtime file changed: ' + name)
    output.mkdir()
    shutil.copyfile(package / 'settings.cfg', output / 'settings.cfg')
    matrix.write_json(output / 'graphics-device.json', {'schema': 'rust-duty-graphics-device/v1', 'adapter': None})
    case = {'settings': {'presentation': 'packaged'}}
    command = matrix.case_command(executable.resolve(), 'dx12', output.resolve(), case, True)
    receipt = {'schema': 'rust-duty-acquire-exit-run/v1', 'scope': SCOPE, 'command': command,
               'build_receipt_sha256': matrix.sha256(package / 'DIAGNOSTIC_BUILD.json'),
               'sample_seconds': seconds, 'exit_method': method, 'started_unix_ns': time.time_ns(),
               'graceful_shutdown': False, 'acceptance_proven': False, 'full_matrix_passed': False}
    driver = create_driver('win32')
    process = None
    try:
        with matrix.desktop_lock(output.parent / 'acquire-exit-desktop.lock'), (output / 'game.log').open('xb') as log:
            process = subprocess.Popen(command, cwd=output, stdout=log, stderr=subprocess.STDOUT)
            receipt['pid'] = process.pid
            driver.bind(process.pid)
            driver.configure([1920, 1080])
            for _ in range(3):
                time.sleep(1)
                driver.check([1920, 1080])
                tap(driver, 'Return')
            tap(driver, 'F2')
            replay(driver, process, [1920, 1080], 'stationary', 3)
            tap(driver, 'F8')
            wait_until(lambda: matrix.sole_session(output), timeout=10, label='diagnostic Record session')
            receipt['sample'] = replay(driver, process, [1920, 1080], 'stationary', seconds)
            tap(driver, 'F8')
            session = wait_until(lambda: matrix.sole_session(output, complete=True), timeout=30,
                                 label='diagnostic telemetry export')
            receipt['session'] = session.name
            receipt['telemetry_files_sha256'] = matrix.measurement_file_hashes(session)
            receipt['exit_request_unix_ns'] = time.time_ns()
            exit_start = time.monotonic_ns()
            receipt['before_exit'] = request_exit(driver, process, method)
            try:
                receipt['returncode'] = process.wait(timeout=15)
                receipt['graceful_shutdown'] = receipt['returncode'] == 0
            except subprocess.TimeoutExpired:
                receipt['exit_timed_out'] = True
                receipt['after_timeout'] = exit_snapshot(driver, process, probe_responsiveness=True)
            receipt['exit_request_to_observed_end_ns'] = time.monotonic_ns() - exit_start
    except Exception as error:
        receipt['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        try:
            receipt['input_cleanup_errors'] = driver.release_inputs()
        finally:
            # This runs on export, focus, timeout, control and unexpected Python errors.
            # It only acts on the Popen handle; no PID search or broad taskkill.
            if process is not None:
                receipt['cleanup'] = matrix.cleanup_owned_process(process)
            receipt['finished_unix_ns'] = time.time_ns()
            matrix.write_json(output / 'RUN.json', receipt)
    summary = summarize(output)
    matrix.write_json(output / 'SUMMARY.json', summary)
    return summary


def summarize(output):
    receipt = matrix.json_read(output / 'RUN.json')
    log = (output / 'game.log').read_text('utf-8', errors='replace') if (output / 'game.log').exists() else ''
    parsed = parse_log(log)
    errors = []
    session = matrix.sole_session(output, complete=True)
    runtime = None
    interval_count = None
    if session:
        report = matrix.frames.read_report(session / 'frames.json')
        if report['status']['state'] != 'complete':
            errors.append('Frame export is incomplete')
        runtime = report['identity']['runtime_observed']
        adapter = runtime.get('actual_adapter', {})
        window = runtime.get('initial_window', {})
        if not (runtime.get('actual_backend') == 'Dx12' and adapter.get('device_type') == 'Cpu'
                and adapter.get('force_fallback_requested') is True
                and window.get('physical_width') == 1920 and window.get('physical_height') == 1080
                and adapter.get('present_mode') == 'Fifo'):
            errors.append('Observed runtime does not establish Windows CPU DX12/Fifo/1080p')
        interval_count = (report.get('summary') or {}).get('interval_count')
    else:
        errors.append('Complete telemetry export unavailable')
    if len(parsed['waits']) < 3:
        errors.append('Fewer than three HAL wait observations')
    if not receipt.get('cleanup', {}).get('process_exit_verified'):
        errors.append('Owned process cleanup was not verified')
    if not receipt.get('graceful_shutdown'):
        errors.append('Graceful shutdown failed or was not reached')
    chosen = 'f10' if receipt['exit_method'] == 'f10' else 'native_close'
    for phase in (chosen, 'run_app', 'hooks_drop'):
        if not (parsed['lifecycle'][phase]['entered'] and parsed['lifecycle'][phase]['returned']):
            errors.append(phase + ' paired lifecycle markers missing')
    if receipt.get('error'):
        errors.append(receipt['error'])
    if receipt.get('input_cleanup_errors'):
        errors.append('Injected input cleanup failed')
    return {'schema': 'rust-duty-acquire-exit-summary/v1', 'scope': SCOPE,
            'state': 'diagnostic_complete' if not errors else 'diagnostic_incomplete', 'errors': errors,
            'run': receipt, 'observer': parsed, 'runtime_observed': runtime,
            'retained_interval_count': interval_count, 'acceptance_proven': False,
            'full_matrix_passed': False,
            'matrix_gate': 'Unchanged: this short diagnostic does not run or satisfy the 100-interval matrix gate.',
            'timing_scope': 'Observer logging adds overhead. Renderer submit is CPU encoding, never GPU time.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    prepare_parser = sub.add_parser('prepare')
    for name in ('repository', 'crate', 'output'):
        prepare_parser.add_argument('--' + name, type=Path, required=True)
    stage_parser = sub.add_parser('stage')
    for name in ('prepared', 'package', 'executable', 'output'):
        stage_parser.add_argument('--' + name, type=Path, required=True)
    run_parser = sub.add_parser('run')
    for name in ('package', 'output'):
        run_parser.add_argument('--' + name, type=Path, required=True)
    run_parser.add_argument('--exit-method', choices=('f10', 'native-close'), default='f10')
    run_parser.add_argument('--seconds', type=int, default=25)
    args = parser.parse_args(argv)
    if args.action == 'prepare':
        prepare(args.repository, args.crate, args.output)
    elif args.action == 'stage':
        stage(args.prepared, args.package, args.executable, args.output)
    else:
        result = run(args.package, args.output, args.exit_method, args.seconds)
        return 0 if result['state'] == 'diagnostic_complete' else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

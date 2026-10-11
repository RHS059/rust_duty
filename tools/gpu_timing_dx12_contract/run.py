"""Bounded Windows DX12 correctness evidence; never initializes another backend."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).resolve().parent
EVIDENCE = ROOT / 'evidence' / 'gpu-timing-dx12-contract'
HELPER_COMMIT = 'f5a7493302842a2b7bbd1c19e244d325d67a21b5'
HELPER_GIT_BLOB = 'e03a31b2062cb44c41b95a261cae00391ed37997'
SCENARIOS = ('disabled', 'missing_features', 'ring_and_verdict',
             'real_validation_rejection', 'synthetic_rejection',
             'abandon', 'stop_restart')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(name, args, timeout, *, input_bytes=None):
    log = EVIDENCE / f'{name}.log'
    started = time.monotonic()
    supervision_errors = []
    process = None
    timed_out = False
    with log.open('wb') as output:
        try:
            process = subprocess.Popen(args, cwd=ROOT, stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT)
            try:
                process.communicate(input=input_bytes, timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    subprocess.run(['taskkill', '/T', '/F', '/PID', str(process.pid)],
                                   stdout=output, stderr=subprocess.STDOUT, timeout=10, check=False)
                except (OSError, subprocess.TimeoutExpired) as error:
                    supervision_errors.append(f'taskkill: {error}')
                try:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=10)
                except (OSError, subprocess.TimeoutExpired) as error:
                    supervision_errors.append(f'process termination: {error}')
        except OSError as error:
            supervision_errors.append(f'process launch: {error}')
        finally:
            alive = process is not None and process.poll() is None
            result = {'name': name, 'command': list(map(str, args)),
                      'exit_code': process.returncode if process else None,
                      'timed_out': timed_out, 'timeout_seconds': timeout,
                      'elapsed_seconds': time.monotonic() - started, 'log': log.name,
                      'supervision_errors': supervision_errors, 'process_still_alive': alive}
            (EVIDENCE / f'{name}-process.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
            print(json.dumps(result), flush=True)
    print(log.read_text(encoding='utf-8', errors='replace'), flush=True)
    if alive:
        # Do not create more GPU/build work beside an uncontained process.
        (EVIDENCE / 'result.json').write_text(json.dumps({
            'status': 'failed', 'reason': 'supervisor could not confirm termination',
            'process': result, 'remaining_scenarios': 'untested', 'fps_verdict': None}, indent=2) + '\n', encoding='utf-8')
        raise RuntimeError('process termination unconfirmed; remaining work not started')
    return result



def witness_error(name, events):
    def of(kind):
        return [e for e in events if e.get('event') == kind]
    if of('uncaptured_error') or of('device_lost') or of('poll_deadline'):
        return 'unexpected GPU error or deadline anywhere in native stream'
    for kind in ('scenario_start', 'instance', 'adapter', 'device'):
        if len(of(kind)) != 1:
            return f'missing or duplicate {kind} witness'
    if of('scenario_start')[0].get('name') != name:
        return 'wrong scenario start'
    instance, adapter, device = of('instance')[0], of('adapter')[0], of('device')[0]
    if (instance.get('configured_backends') != 'DX12' or
            instance.get('force_fallback_adapter') is not True or
            instance.get('validation_requested') is not True or adapter.get('backend') != 'Dx12' or
            adapter.get('device_type') != 'Cpu'):
        return 'missing exact validated DX12 selection witness'
    for field in ('name', 'vendor', 'device', 'device_type', 'driver', 'driver_info', 'available_features', 'requested_features'):
        if field not in adapter:
            return f'missing adapter {field}'
    if 'enabled_features' not in device:
        return 'missing enabled-device feature witness'
    timing = name not in ('disabled', 'missing_features')
    if adapter.get('requested_timestamp_pair') is not timing or device.get('enabled_timestamp_pair') is not timing:
        return 'incorrect requested or enabled timestamp-pair evidence'
    if name != 'disabled' and adapter.get('adapter_supports_timestamp_pair') is not True:
        return 'required supported-adapter path was not observed'
    expected = {
        'disabled': [('1', '1', 'disabled')],
        'missing_features': [('1', '1', 'device_features_not_enabled')],
        'ring_and_verdict': [('2', '5', 'ring_full')] + [('2', str(i), 'measured') for i in (1, 2, 3, 4, 6)],
        'real_validation_rejection': [('3', '1', 'measured'), ('3', '2', 'submission_rejected'), ('3', '3', 'measured')],
        'synthetic_rejection': [('3', '1', 'measured'), ('3', '2', 'submission_rejected'), ('3', '3', 'measured')],
        'abandon': [('4', '1', 'abandoned_before_submit'), ('4', '2', 'measured')],
        'stop_restart': [('5', '1', 'validation_unconfirmed_at_stop'), ('5', '2', 'stopped'), ('6', '1', 'measured')],
    }[name]
    samples = of('sample')
    if [(e.get('session'), e.get('attempt'), e.get('status')) for e in samples] != expected:
        return 'missing, duplicated, mis-keyed or unexpected native sample'
    for e in samples:
        fields = ('start_ticks', 'end_ticks', 'timestamp_period_ns', 'elapsed_ns')
        if any(k not in e for k in fields):
            return 'sample missing explicit numeric fields'
        if e['status'] != 'measured':
            if any(e[k] is not None for k in fields):
                return 'unavailable sample contains numeric values'
        else:
            for k in ('start_ticks', 'end_ticks'):
                value = e[k]
                if not isinstance(value, str) or not value.isascii() or not value.isdigit() or int(value) > 2**64-1:
                    return 'measured ticks are not lossless u64 decimal strings'
            if int(e['end_ticks']) < int(e['start_ticks']):
                return 'measured timestamp order reversed'
            for k in ('timestamp_period_ns', 'elapsed_ns'):
                value = e[k]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    return 'invalid measured period/duration'
            if e['timestamp_period_ns'] == 0:
                return 'zero timestamp period'
            expected_ns = (int(e['end_ticks']) - int(e['start_ticks'])) * e['timestamp_period_ns']
            if not math.isclose(e['elapsed_ns'], expected_ns, rel_tol=1e-12, abs_tol=0.0):
                return 'raw ticks and elapsed value disagree'
    if timing and not of('work_done_witness'):
        return 'missing native callback completion witness'
    if name in ('real_validation_rejection', 'synthetic_rejection'):
        verdicts = of('verdict_origin')
        synthetic = name == 'synthetic_rejection'
        if len(verdicts) != 1 or verdicts[0].get('synthetic') is not synthetic:
            return 'missing real versus synthetic verdict distinction'
        rejected = [e for e in of('submission_validation') if e.get('session') == '3' and e.get('attempt') == '2']
        if len(rejected) != 1 or rejected[0].get('deliberate_invalid_clear') is not (not synthetic):
            return 'missing rejected submission identity'
        if bool(rejected[0].get('error')) is synthetic:
            return 'real validation error evidence does not match rejection method'
    if name == 'stop_restart':
        if not of('restart_coverage') or not of('pre_stop') or not of('cross_owner_ticket_rejected'):
            return 'missing stop/restart owner isolation witness'
    return None


def scenario_result(name, process, lines):
    events = []
    for line in lines.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue  # All non-JSON driver/panic text remains in the raw log.
        if isinstance(value, dict) and 'event' in value:
            events.append(value)
    terminal = [e for e in events if e.get('event') == 'scenario_result']
    status = 'failed'
    reason = None
    if process.get('supervision_errors') or process.get('process_still_alive'):
        reason = 'process supervision failure'
    elif process['timed_out']:
        reason = 'process deadline exceeded'
    elif len(terminal) != 1 or terminal[0].get('name') != name:
        reason = 'missing, duplicate or mismatched terminal native receipt'
    elif terminal[0].get('status') not in ('passed', 'failed', 'unsupported'):
        reason = 'invalid terminal status'
    else:
        status = terminal[0]['status']
        reason = terminal[0].get('error')
        expected_exit = {'passed': 0, 'failed': 1, 'unsupported': 2}[status]
        if process['exit_code'] != expected_exit:
            status, reason = 'failed', 'terminal status/exit mismatch'
        if status == 'passed':
            gap = witness_error(name, events)
            if gap:
                status, reason = 'failed', gap
    return {'name': name, 'status': status, 'reason': reason, 'process': process, 'events': events}


def main():
    if sys.platform != 'win32':
        raise SystemExit('Windows DX12-only harness: execution on another OS is forbidden')
    EVIDENCE.mkdir(parents=True, exist_ok=False)
    source = ROOT / '.gpu-helper-source'
    actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != HELPER_COMMIT:
        raise SystemExit(f'Wrong pinned helper revision: {actual}')
    helper_bytes = subprocess.check_output(['git', '-C', str(source), 'show', 'HEAD:src/render/gpu_timing.rs'])
    actual_blob = hashlib.sha1(b'blob ' + str(len(helper_bytes)).encode('ascii') + b'\0' + helper_bytes).hexdigest()
    if actual_blob != HELPER_GIT_BLOB:
        raise SystemExit(f'Wrong pinned helper bytes: {actual_blob}')
    pinned = HARNESS / 'pinned_gpu_timing.rs'
    if pinned.exists():
        raise SystemExit('Refusing to overwrite an existing pinned helper copy')
    pinned.write_bytes(helper_bytes)
    (EVIDENCE / 'pinned_gpu_timing.rs').write_bytes(helper_bytes)
    paths = (HARNESS / 'src' / 'main.rs', HARNESS / 'Cargo.toml', HARNESS / 'Cargo.lock', Path(__file__))
    identity = {'schema': 'rust_duty_gpu_timing_dx12_contract_v1',
                'harness_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                'helper_commit': actual, 'helper_git_blob': actual_blob,
                'helper_sha256': digest(pinned), 'wgpu_version': '30.0.1',
                'run_id': os.environ.get('GITHUB_RUN_ID'), 'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
                'host': platform.platform(), 'python': sys.version,
                'source_sha256': {str(p.relative_to(ROOT)): digest(p) for p in paths},
                'configured_backends': ['DX12'], 'force_fallback_adapter': True,
                'purpose': 'isolated headless correctness only; not gameplay, presentation, FPS or hardware performance',
                'scenario_process_timeout_seconds': 45, 'internal_callback_deadline_seconds': 15}
    (EVIDENCE / 'identity.json').write_text(json.dumps(identity, indent=2) + '\n', encoding='utf-8')
    failures = []
    command('rustc-version', ['rustc', '--version', '--verbose'], 30)
    command('cargo-version', ['cargo', '--version'], 30)
    for name, path in [('harness', HARNESS / 'src' / 'main.rs'), ('pinned-helper', pinned)]:
        result = command(f'{name}-formatted', ['rustfmt', '--edition', '2021', '--config', 'skip_children=true', '--emit', 'stdout'], 30, input_bytes=path.read_bytes())
        print('FORMATTED_SOURCE_JSON=' + json.dumps({str(path.relative_to(ROOT)): base64.b64encode((EVIDENCE / result['log']).read_bytes()).decode('ascii')}), flush=True)
        checked = command(f'{name}-format-check', ['rustfmt', '--edition', '2021', '--config', 'skip_children=true', '--check', str(path)], 30)
        if checked['exit_code'] != 0 or checked['timed_out']:
            failures.append(checked['name'])
    lock = HARNESS / 'Cargo.lock'
    before = lock.read_bytes()
    normalized = command('lock-normalization', ['cargo', 'metadata', '--manifest-path', str(HARNESS / 'Cargo.toml'), '--format-version', '1'], 300)
    if normalized['exit_code'] != 0 or normalized['timed_out']:
        failures.append('lock-normalization')
    after = lock.read_bytes()
    if after != before:
        failures.append('lockfile_changed_requires_commit')
    (EVIDENCE / 'normalized-Cargo.lock').write_bytes(after)
    print('NORMALIZED_LOCK_BASE64=' + base64.b64encode(after).decode('ascii'), flush=True)
    manifest = ['--manifest-path', str(HARNESS / 'Cargo.toml'), '--locked']
    for name, args in [('clippy', ['cargo', 'clippy', *manifest, '--all-targets', '--', '-D', 'warnings']),
                       ('cpu-tests', ['cargo', 'test', *manifest]),
                       ('build', ['cargo', 'build', *manifest])]:
        result = command(name, args, 600)
        if result['exit_code'] != 0 or result['timed_out']:
            failures.append(name)
    binary = HARNESS / 'target' / 'debug' / 'rust-duty-gpu-timing-dx12-contract.exe'
    results = []
    if 'build' not in failures:
        identity['executable_sha256'] = digest(binary)
        (EVIDENCE / 'identity.json').write_text(json.dumps(identity, indent=2) + '\n', encoding='utf-8')
        for name in SCENARIOS:
            process = command(name, [str(binary), name], 45)
            result = scenario_result(name, process, (EVIDENCE / process['log']).read_text(encoding='utf-8', errors='replace'))
            (EVIDENCE / f'{name}.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
            results.append(result)
    else:
        results = [{'name': name, 'status': 'untested', 'reason': 'current executable did not build'} for name in SCENARIOS]
    status = ('failed' if failures or any(r['status'] == 'failed' for r in results)
              else 'incomplete' if any(r['status'] != 'passed' for r in results) else 'passed')
    summary = {'status': status, 'failed_checks': failures,
               'scenarios': [{'name': r['name'], 'status': r['status'], 'reason': r.get('reason')} for r in results],
               'not_tested': ['game integration', 'presentation', 'hardware FPS', 'instrumentation overhead',
                              'forced device loss', 'deterministic map failure', 'old helper map callback proven delivered after restart'],
               'fps_verdict': None, 'hardware_performance_verdict': None}
    (EVIDENCE / 'result.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print('DX12_CONTRACT_RESULT=' + json.dumps(summary), flush=True)
    return status != 'passed'


if __name__ == '__main__':
    raise SystemExit(main())

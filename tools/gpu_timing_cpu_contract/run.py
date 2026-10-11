"""Windows CPU-only source/API contracts; never creates a renderer or device."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).resolve().parent
EVIDENCE = ROOT / 'evidence' / 'gpu-timing-cpu-contract'
PRESENT_SHA = 'f97c878f63a72c979ed6033fa72689490cbfd024'


def run(name, command, *, input_bytes=None):
    result = subprocess.run(command, cwd=ROOT, input=input_bytes,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            check=False)
    (EVIDENCE / f'{name}.log').write_bytes(result.stdout)
    print(f'\n=== {name}: {command!r} (exit {result.returncode}) ===', flush=True)
    print(result.stdout.decode('utf-8', errors='replace'), flush=True)
    return result


def main():
    if sys.platform != 'win32':
        raise SystemExit('This workflow contract is Windows CPU-only; no alternate runtime is allowed.')
    EVIDENCE.mkdir(parents=True, exist_ok=False)
    present_checkout = ROOT / '.present-policy-source'
    actual = subprocess.check_output(['git', '-C', str(present_checkout), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != PRESENT_SHA:
        raise SystemExit(f'Wrong present-policy source: {actual}')
    present = ROOT / 'src' / 'render' / 'present_policy.rs'
    if present.exists():
        raise SystemExit('Refusing to replace an existing present-policy implementation')
    shutil.copyfile(present_checkout / 'src' / 'render' / 'present_policy.rs', present)
    gpu = ROOT / 'src' / 'render' / 'gpu_timing.rs'
    identity = {
        'schema': 'rust_duty_isolated_gpu_helpers_cpu_contract_v1',
        'scope': 'Windows compile, lint, format and pure CPU unit tests only; no instance, adapter, device, surface, window, game or GPU execution',
        'timing_source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'present_policy_source_commit': actual,
        'github_sha': os.environ.get('GITHUB_SHA'),
        'run_id': os.environ.get('GITHUB_RUN_ID'),
        'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
        'host': platform.platform(),
        'source_sha256': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (gpu, present, HARNESS / 'Cargo.toml', HARNESS / 'Cargo.lock', HARNESS / 'src' / 'lib.rs')},
    }
    (EVIDENCE / 'identity.json').write_text(json.dumps(identity, indent=2) + '\n', encoding='utf-8')
    failures = []
    run('rustc-version', ['rustc', '--version', '--verbose'])
    run('cargo-version', ['cargo', '--version'])
    formatted = {}
    for path in (gpu, present, HARNESS / 'src' / 'lib.rs'):
        name = path.stem if path.name != 'lib.rs' else 'harness'
        output = run(f'{name}-formatted', ['rustfmt', '--edition', '2021', '--config', 'skip_children=true', '--emit', 'stdout'], input_bytes=path.read_bytes())
        formatted[str(path.relative_to(ROOT))] = base64.b64encode(output.stdout).decode('ascii')
        result = run(f'{name}-format-check', ['rustfmt', '--edition', '2021', '--config', 'skip_children=true', '--check', str(path)])
        if result.returncode != 0:
            failures.append(f'{name}-format-check')
    # Exact formatter output can be recovered from read-only logs when artifact
    # downloads are unavailable. These are public project source bytes, no secrets.
    print('FORMATTED_SOURCE_JSON=' + json.dumps(formatted, separators=(',', ':')), flush=True)
    lock = HARNESS / 'Cargo.lock'
    committed_lock = lock.read_bytes()
    if run('lock-normalization', ['cargo', 'metadata', '--manifest-path', str(HARNESS / 'Cargo.toml'), '--format-version', '1']).returncode != 0:
        failures.append('lock-normalization')
    normalized_lock = lock.read_bytes()
    if normalized_lock != committed_lock:
        failures.append('lockfile_changed_requires_commit')
    print('NORMALIZED_LOCK_BASE64=' + base64.b64encode(normalized_lock).decode('ascii'), flush=True)
    (EVIDENCE / 'Cargo.lock').write_bytes(normalized_lock)
    for name, command in [
        ('clippy', ['cargo', 'clippy', '--manifest-path', str(HARNESS / 'Cargo.toml'), '--locked', '--all-targets', '--', '-D', 'warnings']),
        ('unit-tests', ['cargo', 'test', '--manifest-path', str(HARNESS / 'Cargo.toml'), '--locked', '--', '--nocapture']),
    ]:
        if run(name, command).returncode != 0:
            failures.append(name)
    result = {'status': 'failed' if failures else 'passed', 'failed_checks': failures,
              'native_gpu_execution': 'not_run', 'runtime_integration': 'not_tested',
              'performance_or_fps_verdict': None}
    (EVIDENCE / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result), flush=True)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())

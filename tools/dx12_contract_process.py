"""Run an already-built DX12 fixture and publish only validated fresh evidence.

Fixture wrappers own platform gating and output/report schemas. Their callback
receives the resolved output Path and must return a dict with passed=True, or
raise on any validation failure, including a mismatched CI build identity. The
callback cannot supply process-owned provenance fields. No build is performed.
"""

import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys

from run_dx12_smoke import validate_renderer_log


CLEANUP_TIMEOUT = 10
PROCESS_FIELDS = {'fixture', 'exit_code', 'renderer_logs', 'dx12_shader_compiler',
                  'executable_sha256', 'source_commit', 'run_id', 'run_attempt',
                  'command', 'cwd', 'timeout_seconds'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def command(executable, output):
    return [str(executable), '--renderer=dx12', '--force-fallback-adapter',
            '--output-dir', str(output)]


def _write_json(path, record):
    # Serialize first, then atomically publish. NaN or a callback's unserializable
    # value must not leave a success-looking partial summary behind.
    data = json.dumps(record, indent=2, allow_nan=False) + '\n'
    temporary = path.with_name(path.name + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as target:
            target.write(data)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _terminate_process_tree(process):
    """Best-effort bounded cleanup; retain every failure in the failure record."""
    result = {'method': 'taskkill' if sys.platform == 'win32' else 'killpg',
              'pid': process.pid, 'errors': []}
    try:
        if sys.platform == 'win32':
            argv = ['taskkill', '/PID', str(process.pid), '/T', '/F']
            result['command'] = argv
            killed = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=CLEANUP_TIMEOUT, check=False)
            result.update(exit_code=killed.returncode,
                          stdout=killed.stdout.decode('utf-8', errors='replace'),
                          stderr=killed.stderr.decode('utf-8', errors='replace'))
            if killed.returncode != 0:
                result['errors'].append(f'taskkill exited with code {killed.returncode}')
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                # It can exit between the timeout and the cleanup request.
                result['already_exited'] = True
    except (OSError, subprocess.SubprocessError) as error:
        result['errors'].append(f'{type(error).__name__}: {error}')

    if result['errors']:
        # A failed tree cleanup stays a failure even if killing its root works.
        try:
            process.kill()
        except OSError as error:
            result['errors'].append(f'root process kill failed: {error}')
    try:
        result['process_exit_code'] = process.wait(timeout=CLEANUP_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as error:
        result['errors'].append(f'process reap failed: {error}')
    result['succeeded'] = not result['errors']
    return result


def run(executable, root, evidence, output, timeout, fixture, validate_outputs):
    """Return the callback summary plus verified process provenance.

    Invalid preflight inputs are rejected without creating or altering evidence.
    Once the evidence directory is claimed, every exception records failure.json
    and is re-raised. Existing evidence/output directories are never reused.
    """
    raw_evidence, raw_output = Path(evidence), Path(output)
    executable, root, evidence, output = (
        Path(path).resolve() for path in (executable, root, evidence, output))
    require(executable.is_file(), f'fixture executable missing: {executable}')
    require(sys.platform == 'win32' or os.access(executable, os.X_OK),
            f'fixture file is not executable: {executable}')
    require(root.is_dir(), f'fixture working directory missing: {root}')
    require(isinstance(timeout, (int, float)) and not isinstance(timeout, bool),
            'timeout must be finite and positive')
    try:
        timeout = float(timeout)
    except OverflowError as error:
        raise ValueError('timeout must be finite and positive') from error
    require(math.isfinite(timeout) and timeout > 0, 'timeout must be finite and positive')
    require(isinstance(fixture, str) and bool(fixture.strip()), 'fixture name must not be empty')
    require(callable(validate_outputs), 'output validator must be callable')
    require(evidence != output and evidence not in output.parents and output not in evidence.parents,
            'fixture outputs and process evidence must be separate nonoverlapping directories')
    require(not evidence.exists() and not output.exists()
            and not raw_evidence.is_symlink() and not raw_output.is_symlink(),
            'refusing stale fixture evidence/output')

    evidence.mkdir(parents=True, exist_ok=False)
    process = None
    cleanup = None
    try:
        output.mkdir(parents=True, exist_ok=False)
        with executable.open('rb') as source:
            executable_sha256 = hashlib.file_digest(source, 'sha256').hexdigest()
        argv = command(executable, output)
        invocation = {
            'fixture': fixture, 'command': argv, 'cwd': str(root),
            'timeout_seconds': timeout, 'executable_sha256': executable_sha256,
            'source_commit': os.environ.get('GITHUB_SHA'),
            'run_id': os.environ.get('GITHUB_RUN_ID'),
            'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
        }
        _write_json(evidence / 'invocation.json', invocation)
        process_options = {'creationflags': getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x00000200)} if sys.platform == 'win32' else {
            'start_new_session': True}
        with (evidence / 'stdout.log').open('wb') as stdout, (evidence / 'stderr.log').open('wb') as stderr:
            process = subprocess.Popen(argv, cwd=root, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, shell=False, **process_options)
            try:
                exit_code = process.wait(timeout=timeout)
            except BaseException:
                cleanup = _terminate_process_tree(process)
                raise
        require(exit_code == 0, f'{fixture} exited with code {exit_code}; inspect stdout.log/stderr.log')
        renderer_logs = validate_renderer_log(evidence)
        stderr_lines = (evidence / 'stderr.log').read_text(encoding='utf-8', errors='replace').splitlines()
        require('renderer dx12_shader_compiler=Fxc' in stderr_lines,
                'expected actual FXC initialization in stderr.log')
        report = validate_outputs(output)
        require(isinstance(report, dict), 'output validator must return a summary dict')
        require(report.get('passed') is True, 'output validator summary must have passed strictly True')
        require(not PROCESS_FIELDS.intersection(report),
                f'output validator summary contains process-owned fields: {sorted(PROCESS_FIELDS.intersection(report))}')
        with executable.open('rb') as source:
            require(hashlib.file_digest(source, 'sha256').hexdigest() == executable_sha256,
                    'fixture executable changed during execution or validation')
        # Do not mutate the validator's object or assume any fixture/report keys.
        report = dict(report, fixture=fixture, exit_code=exit_code,
                      renderer_logs=renderer_logs, dx12_shader_compiler='Fxc',
                      executable_sha256=executable_sha256,
                      **{key: invocation[key] for key in ('source_commit', 'run_id', 'run_attempt')})
        _write_json(evidence / 'summary.json', report)
        return report
    except BaseException as error:
        failure = {'passed': False, 'fixture': fixture,
                   'error': str(error), 'error_type': type(error).__name__}
        if process is not None:
            failure['exit_code'] = process.returncode
        if cleanup is not None:
            failure['cleanup'] = cleanup
        _write_json(evidence / 'failure.json', failure)
        raise

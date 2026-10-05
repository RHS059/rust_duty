#!/usr/bin/env python3
"""Run production UI through pinned app-local Windows Mesa; retain failures."""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

from run_dx12_authored import execute, write_json
from run_windows_gl_reference_probe import digest, validate_runtime
from run_dx12_game_ui_fixture import validate_outputs
from verify_capture_telemetry import read_record


def check_identity(output, process):
    report = read_record(Path(output) / 'game-ui-contract-report.json')
    adapter = report.get('adapter')
    if report.get('requested') != 'gl' or report.get('backend') != 'OpenGl' or not isinstance(adapter, str) or not adapter.lower().startswith('llvmpipe'):
        raise ValueError('actual Windows OpenGl llvmpipe UI identity required')
    lines = []
    for name in ('stdout.log', 'stderr.log'):
        lines.extend((Path(process) / name).read_text(encoding='utf-8', errors='replace').splitlines())
    identities = [line for line in lines if line.startswith('renderer requested=')]
    expected = f'renderer requested=gl backend=OpenGl adapter={adapter}'
    if not identities or any(line != expected for line in identities):
        raise ValueError('UI startup renderer identity does not match output')
    return adapter


def run(executable, runtime, manifest, root, evidence, output, timeout=600):
    if sys.platform != 'win32':
        raise ValueError('this native UI reference requires Windows')
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout must be finite and positive')
    raw = [Path(p) for p in (executable, runtime, manifest, root, evidence, output)]
    if any(p.is_symlink() for p in raw):
        raise ValueError('symlink inputs/evidence are unsupported')
    executable, runtime, manifest, root, evidence, output = [p.resolve() for p in raw]
    if not executable.is_file() or not root.is_dir():
        raise ValueError('fixture executable and source root are required')
    if evidence.exists() or output.exists() or evidence == output or evidence in output.parents or output in evidence.parents:
        raise ValueError('fresh separate evidence/output directories required')
    pinned = validate_runtime(runtime, manifest)
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    if os.environ.get('GITHUB_SHA', source) != source:
        raise ValueError('source revision differs from workflow identity')
    evidence.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'rust-duty-windows-gl-game-ui/v1', 'passed': False,
              'native_execution': False, 'pixel_checks_passed': False,
              'loaded_modules_verified': False, 'source_commit': source,
              'run_id': os.environ.get('GITHUB_RUN_ID'), 'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
              'runtime': pinned, 'executable_sha256': digest(executable)}
    try:
        staged = runtime / 'game_ui_contract.exe'
        with executable.open('rb') as src, staged.open('xb') as dst:
            shutil.copyfileobj(src, dst)
        if digest(staged) != report['executable_sha256']:
            raise ValueError('staged fixture executable differs from source')
        argv = [str(staged), '--renderer=gl', '--output-dir', str(output)]
        report['command'] = argv
        variables = {'GALLIUM_DRIVER': 'llvmpipe', 'LIBGL_ALWAYS_SOFTWARE': 'true'}
        previous = {k: os.environ.get(k) for k in variables}
        try:
            os.environ.update(variables)
            execute(argv, root, evidence / 'process', timeout)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        adapter = check_identity(output, evidence / 'process')
        pixels = validate_outputs(output, 'gl')
        if pixels.get('passed') is not True:
            raise ValueError('UI pixel validator did not pass')
        if digest(executable) != report['executable_sha256'] or digest(staged) != report['executable_sha256']:
            raise ValueError('executable changed during UI run')
        if validate_runtime(runtime, manifest) != pinned:
            raise ValueError('runtime changed during UI run')
        report.update(passed=True, native_execution=True, pixel_checks_passed=True,
                      adapter=adapter, backend='OpenGl', pixels=pixels)
    except BaseException as error:
        report['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        process = evidence / 'process' / 'process.json'
        if process.is_file():
            record = read_record(process)
            report['process_status'] = record.get('status')
            report['native_execution'] = type(record.get('pid')) is int and record['pid'] > 0
        write_json(evidence / 'windows-gl-game-ui-report.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('executable', 'runtime', 'manifest', 'root', 'evidence', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=600)
    try:
        print(json.dumps(run(**vars(parser.parse_args(argv))), indent=2, allow_nan=False))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f'Windows GL UI failed: {error}\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())

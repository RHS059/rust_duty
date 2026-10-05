#!/usr/bin/env python3
"""Bounded native Windows OpenGL feasibility probe; not authored parity."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from run_dx12_authored import execute, write_json
from verify_capture_telemetry import read_record
from verify_render_capture import verify


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_runtime(runtime, manifest):
    runtime, manifest = Path(runtime), Path(manifest)
    lock = read_record(manifest)
    receipt = read_record(runtime / 'staging-receipt.json')
    if receipt.get('schema') != 'rust-duty-windows-gl-reference-staging/v1' or receipt.get('manifest_sha256') != digest(manifest):
        raise ValueError('staging receipt does not bind the requested runtime manifest')
    if lock.get('schema') != 'rust-duty-windows-gl-reference/v1':
        raise ValueError('unsupported runtime manifest')
    expected = {entry['dll'] for entry in lock['dlls']}
    actual = {path.name for path in runtime.iterdir() if path.suffix.lower() == '.dll'}
    if actual != expected or 'opengl32.dll' not in {name.lower() for name in expected}:
        raise ValueError('runtime DLL inventory differs from pinned closure')
    for entry in lock['dlls']:
        path = runtime / entry['dll']
        if path.is_symlink() or not path.is_file() or path.stat().st_size != entry['size'] or digest(path) != entry['sha256']:
            raise ValueError(f'runtime DLL differs from pin: {entry["dll"]}')
    return {'manifest_sha256': digest(manifest), 'dll_count': len(expected)}


def validate_capture(evidence):
    evidence = Path(evidence)
    png = evidence / 'gl.png'
    sidecar = Path(str(png) + '.json')
    if any(path.is_symlink() or not path.is_file() for path in (png, sidecar)):
        raise ValueError('capture and sidecar must be regular files')
    metadata = read_record(sidecar)
    adapter = metadata.get('adapter')
    if metadata.get('backend') != 'OpenGl' or metadata.get('requested') != 'gl' or not isinstance(adapter, str) or not adapter.lower().startswith('llvmpipe'):
        raise ValueError('actual OpenGl llvmpipe identity is required')
    if any(type(metadata.get(key)) is not int for key in ('width', 'height')) or (metadata['width'], metadata['height']) != (960, 540):
        raise ValueError('capture extent must be 960x540')
    lines = []
    for name in ('stdout.log', 'stderr.log'):
        lines.extend((evidence / 'process' / name).read_text(encoding='utf-8', errors='replace').splitlines())
    identities = [line for line in lines if line.startswith('renderer requested=')]
    expected = f'renderer requested=gl backend=OpenGl adapter={adapter}'
    if not identities or any(line != expected for line in identities):
        raise ValueError('renderer startup log does not match captured OpenGl identity')
    image = verify(png, (960, 540), (36, 48, 61, 255), 0.01, 8, None)
    return {'backend': 'OpenGl', 'adapter': adapter, 'image': image,
            'png_sha256': digest(png), 'sidecar_sha256': digest(sidecar)}


def run(executable, runtime, manifest, root, evidence, timeout=180):
    if os.name != 'nt':
        raise ValueError('native probe must run on Windows')
    executable, runtime, manifest, root, evidence = [Path(p).resolve() for p in (executable, runtime, manifest, root, evidence)]
    if not executable.is_file():
        raise ValueError('combined-backend executable is missing')
    pinned = validate_runtime(runtime, manifest)
    evidence.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'rust-duty-windows-gl-reference-probe/v1', 'passed': False,
              'native_execution': False, 'execution_attempted': False, 'capture_verified': False,
              'loaded_modules_verified': False, 'runtime': pinned,
              'scope': 'procedural Windows GL feasibility; not authored or cross-renderer parity',
              'executable_sha256': digest(executable),
              'run_id': os.environ.get('GITHUB_RUN_ID'), 'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT')}
    try:
        source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
        if os.environ.get('GITHUB_SHA', source) != source:
            raise ValueError('checked-out source differs from workflow revision')
        report['source_commit'] = source
        local_executable = runtime / 'vector-range.exe'
        with executable.open('rb') as source_file, local_executable.open('xb') as destination:
            shutil.copyfileobj(source_file, destination)
        if digest(local_executable) != report['executable_sha256']:
            raise ValueError('staged executable differs from built binary')
        command = [str(local_executable), '--renderer=gl', '--no-update', '--procedural-weapon',
                   '--reference-viewport', '--capture', f'--output={evidence / "gl.png"}']
        # Child process only: no installed driver, registry, or persistent settings.
        variables = {'GALLIUM_DRIVER': 'llvmpipe', 'LIBGL_ALWAYS_SOFTWARE': 'true'}
        previous = {name: os.environ.get(name) for name in variables}
        try:
            os.environ.update(variables)
            report['execution_attempted'] = True
            execute(command, root, evidence / 'process', timeout)
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        report.update(validate_capture(evidence))
        report.update(passed=True, native_execution=True, capture_verified=True)
    except Exception as error:
        report['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        process_path = evidence / 'process' / 'process.json'
        if process_path.is_file():
            try:
                process = read_record(process_path)
                report['process_status'] = process.get('status')
                pid = process.get('pid')
                report['native_execution'] = type(pid) is int and pid > 0
            except (OSError, ValueError) as error:
                report['process_evidence_error'] = str(error)
        write_json(evidence / 'windows-gl-reference-report.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('executable', 'runtime', 'manifest', 'root', 'evidence'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--timeout', type=float, default=180)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run(**vars(args)), indent=2))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

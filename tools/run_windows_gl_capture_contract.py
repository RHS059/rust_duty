#!/usr/bin/env python3
"""Verify screenshot neutrality through the production Windows GL renderer."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image
import run_dx12_authored as authored
from run_windows_gl_reference_probe import validate_runtime
from run_windows_same_platform_return import (
    positive_timeout, process_record, regular, require, runtime_environment, stage_runtime,
)
from verify_capture_telemetry import read_record

EXPECTED = {
    'baseline.png': [128, 128, 128, 255],
    'warm-world.png': [204, 51, 26, 255],
    'warm-after.png': [128, 128, 128, 255],
    'cool-world.png': [26, 102, 204, 255],
    'cool-after.png': [128, 128, 128, 255],
}


def validate_outputs(output):
    output = Path(output)
    require(output.is_dir() and not output.is_symlink(), 'capture output must be a real directory')
    require({p.name for p in output.iterdir()} == set(EXPECTED) | {'report.json'},
            'capture output must contain exactly five expected PNGs and report.json')
    report = read_record(regular(output / 'report.json'))
    require(report.get('schema') == 'rust-duty-legacy-capture-neutrality/v1'
            and report.get('status') == 'passed', 'capture neutrality report did not pass')
    adapter = report.get('adapter')
    require(report.get('backend') == 'OpenGl' and isinstance(adapter, str)
            and adapter.lower().startswith('llvmpipe'), 'actual OpenGl llvmpipe identity required')
    require(report.get('extent') == [256, 256] and type(report.get('channel_tolerance')) is int
            and report['channel_tolerance'] == 0
            and type(report.get('interior_pixels_per_capture')) is int
            and report['interior_pixels_per_capture'] == 248 * 248, 'capture probe contract changed')
    require(report.get('captures') == [str(output / name) for name in EXPECTED],
            'reported capture paths or order differ from this output')
    hashes = {}
    for name, expected in EXPECTED.items():
        path = regular(output / name)
        require(0 < path.stat().st_size <= 1024 * 1024, f'{name}: invalid PNG size')
        with Image.open(path) as image:
            require(image.format == 'PNG' and image.mode == 'RGBA' and image.size == (256, 256),
                    f'{name}: expected 256x256 RGBA PNG')
            pixels = image.load()
            for y in range(4, 252):
                for x in range(4, 252):
                    require(list(pixels[x, y]) == expected,
                            f'{name}: pixel ({x},{y}) differs from fixed expected {expected}')
        hashes[name] = authored.sha256(path)
    return {'passed': True, 'backend': 'OpenGl', 'adapter': adapter,
            'captures': 5, 'interior_pixels_checked': 5 * 248 * 248,
            'channel_tolerance': 0, 'png_sha256': hashes,
            'report_sha256': authored.sha256(output / 'report.json')}


def run(executable, root, runtime, evidence, timeout=180):
    require(sys.platform == 'win32', 'capture neutrality requires native Windows execution')
    positive_timeout(timeout, 'timeout')
    raw = [Path(p) for p in (executable, root, runtime, evidence)]
    require(not any(p.is_symlink() for p in raw), 'symlink inputs/evidence are unsupported')
    executable, root, runtime, evidence = [p.resolve() for p in raw]
    regular(executable)
    require(0 < executable.stat().st_size <= 512 * 1024 * 1024, 'invalid fixture executable size')
    require(root.is_dir() and not evidence.exists(), 'source root and fresh evidence are required')
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    require(os.environ.get('GITHUB_SHA', source) == source, 'source differs from workflow identity')
    subprocess.run(['git', 'diff', '--exit-code', '--', 'src', 'examples', 'Cargo.toml', 'Cargo.lock', 'tools'],
                   cwd=root, check=True, capture_output=True)
    evidence.mkdir(parents=True)
    report = {'schema': 'rust-duty-windows-gl-capture-contract/v1', 'passed': False,
              'source_commit': source, 'run_id': os.environ.get('GITHUB_RUN_ID'),
              'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
              'native_execution': False, 'pixel_checks_passed': False,
              'loaded_modules_verified': False, 'executable_sha256': authored.sha256(executable)}
    try:
        staged = evidence / 'runtime'
        pinned = stage_runtime(executable, runtime, root / 'tools/windows_gl_reference_lock.json', staged)
        report['runtime'] = pinned
        staged_exe = staged / 'vector-range.exe'
        require(authored.sha256(staged_exe) == report['executable_sha256'], 'staged executable differs')
        output = evidence / 'captures'
        command = [str(staged_exe), '--output-dir', str(output)]
        report['command'] = command
        with runtime_environment():
            authored.execute(command, root, evidence / 'process', timeout)
        report['process'] = process_record(evidence / 'process', command, root)
        report['native_execution'] = True
        pixels = validate_outputs(output)
        stdout = (evidence / 'process/stdout.log').read_text(encoding='utf-8', errors='replace')
        require(f"Legacy capture neutrality passed on {pixels['adapter']}" in stdout.splitlines(),
                'native success identity differs from capture report')
        require(authored.sha256(executable) == report['executable_sha256']
                and authored.sha256(staged_exe) == report['executable_sha256'], 'executable changed during capture')
        validate_runtime(staged, root / 'tools/windows_gl_reference_lock.json')
        report.update(passed=True, pixel_checks_passed=True, pixels=pixels)
    except BaseException as error:
        report['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        process_path = evidence / 'process/process.json'
        if process_path.is_file():
            try:
                state = read_record(process_path)
                report['native_execution'] = type(state.get('pid')) is int and state['pid'] > 0
                report['process_status'] = state.get('status')
            except ValueError as error:
                report.update(passed=False, process_receipt_error=str(error))
        authored.write_json(evidence / 'summary.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('executable', 'root', 'runtime', 'evidence'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=180)
    try:
        result = run(**vars(parser.parse_args(argv)))
        print(json.dumps(result, indent=2, allow_nan=False))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f'Windows GL capture neutrality failed: {error}\n')
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

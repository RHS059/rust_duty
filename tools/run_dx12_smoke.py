#!/usr/bin/env python3
"""Run the real Windows game on DX12 WARP and fail closed on capture breakage.

This is a runtime smoke, not visual parity or authored-animation acceptance.
The 127-frame contract follows traversal_replay::duration (4 s), capture.rs's
0.2 s tail, and app.rs's 30 Hz zero-based capture clock. Never reuse evidence.
WARP's DXGI name is documented at:
https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/d3d10-graphics-programming-guide-dxgi
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

from verify_capture_telemetry import read_record, validate
from verify_render_capture import verify


FRAME_COUNT = 127
EXTENT = (960, 540)
# viewmodel_draw clears the reference target to (0.14, 0.19, 0.24, 1).
# It is a linear RGBA8Unorm target; the world sky is not this image's background.
BACKGROUND = (36, 48, 61, 255)
WARP_ADAPTER = 'Microsoft Basic Render Driver'
TIME_FIELDS = {'elapsed_seconds', 'normalized_phase', 'visual_duration_seconds',
               'simulation_ready_seconds', 'sampling_hz'}
GAMEPLAY_FIELDS = {'simulation_time', 'segment', 'slot', 'phase', 'normalized',
                   'weight', 'placeholder', 'left_hand', 'right_hand', 'left_owner',
                   'right_owner', 'obstruction', 'obstruction_raw', 'fire_blocked',
                   'mounted', 'position', 'eye_height', 'speed', 'grounded',
                   'look_sway_degrees', 'shots'}


def game_command(executable, captures):
    return [str(executable), '--renderer=dx12', '--force-fallback-adapter',
            '--no-update', '--procedural-weapon', '--reference-viewport',
            '--capture-sequence=gameplay-sway', '--capture-hz=30',
            f'--output={captures}']


def number(record, field, path):
    value = record.get(field)
    if isinstance(value, bool) or value is None:
        raise ValueError(f'{path}: missing or invalid {field}')
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f'{path}: invalid {field}') from error
    if isinstance(record[field], str) or not math.isfinite(value):
        raise ValueError(f'{path}: nonnumeric/nonfinite {field}')
    return value


def validate_renderer_log(evidence):
    identities = []
    compilers = []
    for name in ('stdout.log', 'stderr.log'):
        for line in (Path(evidence) / name).read_text(encoding='utf-8', errors='replace').splitlines():
            if line.startswith('renderer requested='):
                identities.append(line)
            if line.startswith('renderer dx12_shader_compiler='):
                compilers.append(line)
    expected = f'renderer requested=dx12 backend=Dx12 adapter={WARP_ADAPTER}'
    if not identities or any(line.casefold() != expected.casefold() for line in identities):
        raise ValueError(f'expected actual DX12 WARP renderer identity in logs, got {identities!r}')
    if not compilers or any(line != 'renderer dx12_shader_compiler=Fxc' for line in compilers):
        raise ValueError(f'expected explicitly pinned FXC shader compiler in logs, got {compilers!r}')
    return identities


def validate_captures(captures):
    captures = Path(captures)
    # Reject duplicate JSON keys, NaN, Infinity, missing renderer metadata,
    # symlinks, and any non-DX12 renderer before interpreting the records.
    telemetry = validate(captures, expected_backend='Dx12')
    expected = {f'{index:04}.png{suffix}' for index in range(FRAME_COUNT)
                for suffix in ('', '.json', '.time.json', '.gameplay.json')}
    actual = {path.relative_to(captures).as_posix() for path in captures.rglob('*')}
    if actual != expected:
        raise ValueError(f'incomplete/unexpected capture set: '
                         f'missing={sorted(expected - actual)[:10]}, '
                         f'extra={sorted(actual - expected)[:10]}')
    adapters = set()
    images = []
    for index in range(FRAME_COUNT):
        png = captures / f'{index:04}.png'
        metadata = read_record(Path(f'{png}.json'))
        adapter = metadata['adapter']
        if adapter.casefold() != WARP_ADAPTER.casefold():
            raise ValueError(f'{png}: expected WARP Microsoft Basic Render Driver, got {adapter!r}')
        adapters.add(adapter)
        if metadata.get('requested') != 'dx12':
            raise ValueError(f'{png}: expected explicitly requested dx12 renderer')
        if any(type(metadata.get(field)) is not int for field in ('width', 'height')) or (
                metadata.get('width'), metadata.get('height')) != EXTENT:
            raise ValueError(f'{png}: metadata extent must be {EXTENT}')
        timing_path = Path(f'{png}.time.json')
        timing = read_record(timing_path)
        if timing.keys() != TIME_FIELDS:
            raise ValueError(f'{timing_path}: gameplay-sway timing fields changed or incomplete')
        for field, expected_value in [('elapsed_seconds', index / 30),
                                      ('normalized_phase', min(index / 120, 1)),
                                      ('sampling_hz', 30),
                                      ('visual_duration_seconds', 4)]:
            if abs(number(timing, field, timing_path) - expected_value) > 0.00001:
                raise ValueError(f'{timing_path}: incorrect {field}')
        if number(timing, 'simulation_ready_seconds', timing_path) <= 0:
            raise ValueError(f'{timing_path}: invalid simulation_ready_seconds')
        gameplay_path = Path(f'{png}.gameplay.json')
        gameplay = read_record(gameplay_path)
        if gameplay.keys() != GAMEPLAY_FIELDS:
            raise ValueError(f'{gameplay_path}: gameplay-sway fields changed or incomplete')
        if abs(number(gameplay, 'simulation_time', gameplay_path) - index / 30) > 0.00001:
            raise ValueError(f'{gameplay_path}: incorrect simulation_time')
        if not isinstance(gameplay.get('segment'), str) or not gameplay['segment'].strip():
            raise ValueError(f'{gameplay_path}: missing gameplay segment')
        # Every image must have visible structure, including between samples.
        # This deliberately makes no orientation or pixel-parity claim.
        images.append(verify(png, EXTENT, BACKGROUND, 0.01, 8, None))
    samples = [images[index] for index in (0, 63, 126)]
    return {'schema': 'rust-duty-dx12-warp-smoke/v1', 'passed': True,
            'backend': 'Dx12', 'adapters': sorted(adapters),
            'frames': FRAME_COUNT, 'telemetry': telemetry, 'image_samples': samples,
            'minimum_foreground_coverage': min(image['foreground_coverage'] for image in images),
            'scope': 'DX12 WARP runtime smoke; not visual parity or authored asset acceptance'}


def run(executable, root, evidence, timeout):
    executable, root, evidence = map(lambda p: Path(p).resolve(), (executable, root, evidence))
    if not executable.is_file():
        raise ValueError(f'game executable missing: {executable}')
    if not root.is_dir():
        raise ValueError(f'game working directory missing: {root}')
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout must be finite and positive')
    # Refuse an existing directory so stale successful frames cannot pass.
    evidence.mkdir(parents=True, exist_ok=False)
    captures = evidence / 'captures'
    command = game_command(executable, captures)
    with executable.open('rb') as source:
        executable_sha256 = hashlib.file_digest(source, 'sha256').hexdigest()
    (evidence / 'invocation.json').write_text(
        json.dumps({'command': command, 'cwd': str(root), 'timeout_seconds': timeout,
                    'executable_sha256': executable_sha256,
                    'source_commit': os.environ.get('GITHUB_SHA'),
                    'run_id': os.environ.get('GITHUB_RUN_ID'),
                    'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT')}, indent=2),
        encoding='utf-8')
    try:
        with (evidence / 'stdout.log').open('wb') as stdout, (evidence / 'stderr.log').open('wb') as stderr:
            result = subprocess.run(command, cwd=root, stdout=stdout, stderr=stderr,
                                    timeout=timeout, check=False)
        if result.returncode != 0:
            raise ValueError(f'game exited with code {result.returncode}; inspect stdout.log/stderr.log')
        renderer_logs = validate_renderer_log(evidence)
        report = validate_captures(captures)
        report.update(exit_code=result.returncode, renderer_logs=renderer_logs,
                      executable_sha256=executable_sha256)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        (evidence / 'failure.json').write_text(json.dumps({'passed': False, 'error': str(error)}, indent=2),
                                             encoding='utf-8')
        raise
    (evidence / 'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=600)
    args = parser.parse_args(argv)
    try:
        if sys.platform != 'win32':
            raise ValueError('the actual DX12 WARP smoke requires Windows')
        report = run(args.executable, args.root, args.evidence, args.timeout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f'DX12 smoke failed: {error}', file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())

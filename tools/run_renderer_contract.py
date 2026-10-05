#!/usr/bin/env python3
"""Run and independently verify the renderer-owned Windows DX12/FXC contract.

The case inventory and pixel constants come from examples/renderer_contract.rs,
published at428cd2a417e172f6081d9369032bba2ef13f1ac7. This additionally requires
the later explicit FXC initialization log. Synthetic tests are not native proof.
"""

import argparse
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image

import run_dx12_smoke as smoke
from verify_capture_telemetry import read_record, validate
from verify_render_capture import load_png, near_color


OPAQUE = 'opaque-rgba8-rgb-preserved-over-black'
ASSOCIATED = 'raw-associated-emissive-rgba8'
REPORT = 'renderer-contract-report.json'
FAILURES = ['create capture directory', 'write capture', 'capture path must not be empty', 'non-finite']
BLOCKED_CONTENT = b'This regular file intentionally blocks PNG parent creation.\n'
SCOPE = 'headless DX12 renderer contract; not window presentation, native DPI, gameplay, performance or artistic approval'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def equal(actual, expected, location):
    require(type(actual) is type(expected), f'{location}: JSON type differs')
    if isinstance(expected, dict):
        require(actual.keys() == expected.keys(), f'{location}: JSON fields differ')
        for key in expected:
            equal(actual[key], expected[key], f'{location}.{key}')
    elif isinstance(expected, list):
        require(len(actual) == len(expected), f'{location}: JSON array length differs')
        for index, value in enumerate(expected):
            equal(actual[index], value, f'{location}[{index}]')
    else:
        require(actual == expected, f'{location}: expected {expected!r}, got {actual!r}')


def literal(actual, expected, location):
    equal(actual, json.loads(json.dumps(expected), parse_float=Decimal), location)


def solid(color):
    return [('solid interior', [0.1, 0.9, 0.1, 0.9], color)]


def cases():
    quadrants = [('top-left red', [0.1, 0.4, 0.1, 0.4], [255, 0, 0, 255]),
                 ('top-right green', [0.6, 0.9, 0.1, 0.4], [0, 255, 0, 255]),
                 ('bottom-left blue', [0.1, 0.4, 0.6, 0.9], [0, 0, 255, 255]),
                 ('bottom-right yellow', [0.6, 0.9, 0.6, 0.9], [255, 255, 0, 255])]
    result = [
        ('quadrant.png', 'orientation-quadrants', (96, 64), OPAQUE, quadrants, {'row_padding_required': False}),
        ('readback-width-65.png', 'readback-width-65', (65, 49), OPAQUE, quadrants, {'row_padding_required': True}),
        ('ordered-a-red.png', 'same-submission-checkpoint-a', (96, 64), OPAQUE,
         solid([255, 0, 0, 255]), {'submission_group': 'red-then-green', 'checkpoint': 0}),
        ('ordered-b-green.png', 'same-submission-checkpoint-b', (96, 64), OPAQUE,
         solid([0, 255, 0, 255]), {'submission_group': 'red-then-green', 'checkpoint': 1}),
    ]
    for filename, case, alpha, color in [
        ('depth-main-near.png', 'near-surface-occludes-far', OPAQUE, [255, 0, 0, 255]),
        ('depth-target-near.png', 'camera-selects-named-target', ASSOCIATED, [0, 0, 255, 255]),
        ('depth-target-reset.png', 'named-target-clear-resets-depth', ASSOCIATED, [255, 255, 0, 255]),
        ('depth-main-preserved.png', 'named-target-clear-preserves-main', OPAQUE, [255, 0, 0, 255]),
        ('depth-main-reset.png', 'main-clear-resets-depth', OPAQUE, [0, 255, 0, 255]),
        ('depth-disabled.png', 'screen-camera-disables-depth', OPAQUE, [0, 0, 255, 255]),
    ]:
        result.append((filename, case, (96, 64), alpha, solid(color), None))
    for filename, case, alpha, colors in [
        ('alpha-target.png', 'raw-associated-and-emissive-target', ASSOCIATED,
         [[127, 127, 127, 127], [127, 0, 0, 0], [0, 0, 0, 0]]),
        ('alpha-main-display.png', 'main-capture-flattens-coverage-preserving-emission', OPAQUE,
         [[127, 127, 127, 255], [127, 0, 0, 255], [0, 0, 0, 255]]),
        ('alpha-composite.png', 'target-composited-over-opaque-black', OPAQUE,
         [[127, 127, 127, 255], [127, 0, 0, 255], [0, 0, 0, 255]]),
        ('alpha-tinted-composite.png', 'target-tint-opacity-scales-associated-rgb', OPAQUE,
         [[32, 16, 63, 255], [32, 0, 0, 255], [0, 0, 0, 255]]),
    ]:
        probes = [(name, bounds, color) for (name, bounds), color in zip([
            ('half-alpha white', [0.1, 0.25, 0.1, 0.9]),
            ('red emission with zero coverage', [0.4, 0.6, 0.1, 0.9]),
            ('transparent untouched region', [0.75, 0.9, 0.1, 0.9])], colors)]
        result.append((filename, case, (96, 64), alpha, probes, {'vertex_alpha_u8': 127}))
    result += [
        ('alpha-clear.png', 'clear-associates-straight-color', (96, 64), ASSOCIATED, solid([128, 128, 128, 128]), None),
        ('alpha-opaque-source.png', 'opaque-replacement-associates-straight-source', (96, 64), ASSOCIATED, solid([127, 127, 127, 127]), None),
    ]
    for scale in (1, 2):
        result.append((f'text-{100 * scale}-percent.png', 'physical-pixel-text-rasterization',
                       (64 * scale, 48 * scale), OPAQUE, [],
                       {'dpi_percent': 100 * scale, 'font_size_physical_px': float(16 * scale),
                        'text': 'Ag', 'measured_with_trailing_space': 'Ag ',
                        'metrics': {'width': float(21 * scale), 'height': float(11 * scale), 'offset_y': float(8 * scale)},
                        'ink_bounds_exclusive': [11 * scale, 12 * scale, 23 * scale, 23 * scale],
                        'claim': 'raster dimensions only; no font-style or OS-DPI claim'}))
    result.append(('after-errors.png', 'renderer-recovers-after-rejected-captures', (16, 16),
                   OPAQUE, solid([0, 255, 0, 255]), None))
    return result


def verify_fraction(record, key, actual, location):
    require(abs(smoke.number(record, key, location) - actual) <= 1e-12, f'{location}: incorrect {key}')


def verify_case(output, spec, metadata, renderer):
    filename, case, size, alpha, probes, extra = spec
    path = output / filename
    with Image.open(path) as original:
        require(original.mode == 'RGBA', f'{filename}: expected RGBA8 PNG')
    image = load_png(path, size)
    expected = {'schema_version': 1, 'fixture_case': case, 'filename': filename,
                **renderer, 'renderer': renderer, 'force_fallback_adapter': True,
                'alpha_representation': alpha, 'diagnostic_raw_target': alpha == ASSOCIATED,
                'row_origin': 'top-left', 'size': {'width': size[0], 'height': size[1]},
                'width': size[0], 'height': size[1], 'extra': extra}
    require(metadata.keys() == set(expected) | {'coverage', 'probes'}, f'{filename}: metadata fields differ')
    literal({key: metadata[key] for key in expected}, expected, filename)
    pixels = list(image.getdata())
    total, nonblack = len(pixels), sum(any(channel != 0 for channel in p[:3]) for p in pixels)
    require(nonblack > 0, f'{filename}: empty RGB coverage')
    if alpha == OPAQUE:
        require(all(pixel[3] == 255 for pixel in pixels), f'{filename}: main capture alpha is not opaque')
    coverage = metadata['coverage']
    require(isinstance(coverage, dict) and coverage.keys() == {'nonblack_pixels', 'total_pixels', 'nonblack_fraction'},
            f'{filename}: invalid coverage schema')
    literal([coverage['nonblack_pixels'], coverage['total_pixels']], [nonblack, total], filename + '.coverage')
    verify_fraction(coverage, 'nonblack_fraction', nonblack / total, filename)
    require(isinstance(metadata['probes'], list) and len(metadata['probes']) == len(probes), f'{filename}: probes differ')
    for observed, (label, bounds, color) in zip(metadata['probes'], probes):
        x0, x1, y0, y1 = bounds
        box = [math.floor(x0 * size[0]), math.floor(x1 * size[0]),
               math.floor(y0 * size[1]), math.floor(y1 * size[1])]
        region = image.crop((box[0], box[2], box[1], box[3]))
        count = region.width * region.height
        matching = sum(near_color(pixel, color, 8) for pixel in region.getdata())
        require(count > 0 and matching / count >= 0.9, f'{filename}: pixel probe {label} failed')
        fields = {'label': label, 'normalized_bounds': bounds, 'pixel_bounds': box,
                  'expected_rgba': color, 'matching_pixels': matching, 'total_pixels': count,
                  'minimum_match_fraction': 0.9, 'channel_tolerance': 8}
        require(isinstance(observed, dict) and observed.keys() == set(fields) | {'match_fraction'}, f'{filename}: probe fields differ')
        literal({key: observed[key] for key in fields}, fields, filename + '.' + label)
        verify_fraction(observed, 'match_fraction', matching / count, filename)
    if filename.startswith('text-'):
        ink = [(x, y) for y in range(size[1]) for x in range(size[0]) if any(v > 8 for v in image.getpixel((x, y))[:3])]
        require(ink, f'{filename}: no text ink')
        bounds = [min(x for x, _ in ink), min(y for _, y in ink), max(x for x, _ in ink) + 1, max(y for _, y in ink) + 1]
        require(bounds == extra['ink_bounds_exclusive'], f'{filename}: text ink bounds differ')


def validate_outputs(output):
    output = Path(output)
    validate(output, expected_backend='Dx12')
    specifications = cases()
    expected = {REPORT, 'blocked-parent', 'capture-is-directory.png'} | {
        name + suffix for name, *_ in specifications for suffix in ('', '.json')}
    actual = {path.relative_to(output).as_posix() for path in output.rglob('*')}
    require(actual == expected, f'fixture output set differs: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}')
    require((output / 'blocked-parent').is_file() and (output / 'blocked-parent').read_bytes() == BLOCKED_CONTENT,
            'invalid intentional blocked-parent fixture')
    require((output / 'capture-is-directory.png').is_dir(), 'missing intentional PNG-directory fixture')
    report = read_record(output / REPORT)
    fields = {'schema_version', 'status', 'native_execution', 'requested', 'backend', 'adapter',
              'force_fallback_adapter', 'platform', 'build_version', 'build_number', 'captures', 'expected_failures', 'scope'}
    require(report.keys() == fields, 'renderer report fields differ')
    literal({key: report[key] for key in ('schema_version', 'status', 'native_execution', 'requested', 'backend',
                                        'force_fallback_adapter', 'platform', 'scope')},
            {'schema_version': 1, 'status': 'passed', 'native_execution': True, 'requested': 'dx12', 'backend': 'Dx12',
             'force_fallback_adapter': True, 'platform': 'windows', 'scope': SCOPE}, 'renderer report')
    require(isinstance(report['adapter'], str) and report['adapter'].casefold() == smoke.WARP_ADAPTER.casefold(),
            'renderer report must identify WARP')
    for key in ('build_version', 'build_number'):
        require(isinstance(report[key], str) and report[key].strip(), f'renderer report missing {key}')
    require(isinstance(report['captures'], list) and len(report['captures']) == 19, 'renderer report must contain all19 captures')
    renderer = {key: report[key] for key in ('requested', 'backend', 'adapter')}
    for spec, reported in zip(specifications, report['captures']):
        metadata = read_record(output / (spec[0] + '.json'))
        equal(reported, metadata, spec[0] + ': report/sidecar')
        verify_case(output, spec, metadata, renderer)
    failures = report['expected_failures']
    require(isinstance(failures, list) and len(failures) == len(FAILURES), 'renderer report expected failures incomplete')
    for failure, expected_error in zip(failures, FAILURES):
        require(isinstance(failure, dict) and failure.keys() == {'expected_error', 'actual_error'}
                and failure['expected_error'] == expected_error and isinstance(failure['actual_error'], str)
                and expected_error in failure['actual_error'], 'renderer report has wrong expected failure')
    return {'schema': 'rust-duty-renderer-contract-validation/v1', 'passed': True,
            'backend': 'Dx12', 'adapter': report['adapter'], 'captures': 19,
            'build_version': report['build_version'], 'build_number': report['build_number'], 'scope': SCOPE}


def command(output):
    return ['cargo', 'run', '--locked', '--no-default-features', '--features', 'wgpu-runtime',
            '--example', 'renderer_contract', '--', '--renderer=dx12', '--force-fallback-adapter', '--output-dir', str(output)]


def run(root, evidence, output, timeout):
    root, evidence, output = (Path(path).resolve() for path in (root, evidence, output))
    require(root.is_dir(), 'missing renderer-contract working directory')
    require(math.isfinite(timeout) and timeout > 0, 'timeout must be finite and positive')
    require(output != evidence and output not in evidence.parents and evidence not in output.parents,
            'fixture outputs and process evidence must be separate directories')
    require(not evidence.exists() and not output.exists(), 'refusing stale renderer-contract evidence/output')
    evidence.mkdir(parents=True)
    output.mkdir(parents=True)
    argv = command(output)
    invocation = {'command': argv, 'cwd': str(root), 'timeout_seconds': timeout,
                  'source_commit': os.environ.get('GITHUB_SHA'), 'run_id': os.environ.get('GITHUB_RUN_ID'),
                  'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT')}
    (evidence / 'invocation.json').write_text(json.dumps(invocation, indent=2), encoding='utf-8')
    try:
        with (evidence / 'stdout.log').open('wb') as stdout, (evidence / 'stderr.log').open('wb') as stderr:
            process = subprocess.run(argv, cwd=root, stdout=stdout, stderr=stderr, timeout=timeout, check=False)
        require(process.returncode == 0, f'renderer contract exited with code {process.returncode}')
        identities = smoke.validate_renderer_log(evidence)
        report = validate_outputs(output)
        if os.environ.get('GITHUB_ACTIONS') == 'true':
            import build_identity
            identity = build_identity.context()
            require(report['build_version'] == identity['version'] and report['build_number'] == identity['build_number'],
                    'renderer report build identity does not match this CI attempt')
        report.update(exit_code=0, renderer_logs=identities, dx12_shader_compiler='Fxc')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        (evidence / 'failure.json').write_text(json.dumps({'passed': False, 'error': str(error)}, indent=2), encoding='utf-8')
        raise
    (evidence / 'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=1200)
    args = parser.parse_args(argv)
    try:
        require(sys.platform == 'win32', 'the actual renderer contract requires Windows')
        report = run(args.root, args.evidence, args.output, args.timeout)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f'Renderer contract validation failed: {error}\n')
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

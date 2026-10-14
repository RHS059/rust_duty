#!/usr/bin/env python3
"""Independently validate world_primitives_contract's fixed output contract.

Constants are transcribed from examples/world_primitives_contract.rs (SHA256
d1b0addd12d88e1ea374e73aa9f4afe7ff42741376cd134d8d3bd82983e22d64), not read
from producer metadata or fitted to its images. This read-only checker never
launches a renderer. Synthetic passing inputs prove these guards, not native
execution; the process runner separately owns freshness and runtime provenance.
"""

import argparse
import json
import os
from pathlib import Path

from PIL import Image

from run_renderer_contract import equal, literal, require
from verify_capture_telemetry import read_record, validate
from verify_render_capture import load_png, near_color


REPORT = 'world-primitives-contract-report.json'
EXTENT = (160, 120)
TOLERANCE = 8
WARP = 'Microsoft Basic Render Driver'
SCOPE = ('headless public-facade world primitive projection, model transforms, '
         'clipping and depth; not window presentation, gameplay, performance or artistic approval')
BLACK = [0, 0, 0, 255]
RED = [255, 0, 0, 255]
GREEN = [0, 255, 0, 255]
BLUE = [0, 0, 255, 255]
CYAN = [0, 255, 255, 255]
YELLOW = [255, 255, 0, 255]
MAGENTA = [255, 0, 255, 255]
MINIMUM = {'area': 0.95, 'horizontal': 0.9, 'vertical': 0.9, 'any': 1.0}


def cases():
    """Ordered, literal filename/case/probes/envelopes/palette/forbidden specs."""
    return [
        ('world-lines-perspective.png', 'facade-lines-perspective-model-and-clipping', [
            ('near red perspective line', 'horizontal', [23, 57, 39, 42], RED),
            ('far green perspective line', 'horizontal', [53, 67, 49, 52], GREEN),
            ('cyan vertical world line', 'vertical', [139, 142, 43, 77], CYAN),
            ('rotated translated blue model line', 'vertical', [79, 82, 63, 97], BLUE),
            ('clear background', 'area', [5, 15, 5, 15], BLACK),
        ], [[18, 62, 38, 42], [48, 72, 48, 52], [138, 142, 38, 82], [78, 82, 58, 102]],
         [RED, GREEN, CYAN, BLUE], [MAGENTA, YELLOW]),
        ('world-wires-perspective.png', 'facade-wire-box-twelve-edges-and-model', [
            ('green near top', 'horizontal', [23, 57, 39, 42], GREEN),
            ('green near bottom', 'horizontal', [23, 57, 79, 82], GREEN),
            ('green near left', 'vertical', [19, 22, 43, 77], GREEN),
            ('green near right', 'vertical', [59, 62, 43, 77], GREEN),
            ('green far top', 'horizontal', [47, 65, 47, 50], GREEN),
            ('green far bottom', 'horizontal', [47, 65, 71, 74], GREEN),
            ('green far left', 'vertical', [43, 46, 51, 69], GREEN),
            ('green far right', 'vertical', [67, 70, 51, 69], GREEN),
            ('green upper left connector', 'any', [30, 35, 42, 47], GREEN),
            ('green upper right connector', 'any', [62, 67, 42, 47], GREEN),
            ('green lower left connector', 'any', [30, 35, 74, 79], GREEN),
            ('green lower right connector', 'any', [62, 67, 74, 79], GREEN),
            ('yellow model near top', 'horizontal', [103, 137, 49, 52], YELLOW),
            ('yellow model near bottom', 'horizontal', [103, 137, 69, 72], YELLOW),
            ('yellow model near left', 'vertical', [99, 102, 53, 67], YELLOW),
            ('yellow model near right', 'vertical', [139, 142, 53, 67], YELLOW),
            ('yellow model far top', 'horizontal', [95, 113, 53, 56], YELLOW),
            ('yellow model far bottom', 'horizontal', [95, 113, 65, 68], YELLOW),
            ('yellow model far left', 'vertical', [91, 94, 57, 63], YELLOW),
            ('yellow model far right', 'vertical', [115, 118, 57, 63], YELLOW),
            ('yellow upper left connector', 'any', [94, 99, 51, 54], YELLOW),
            ('yellow upper right connector', 'any', [125, 131, 51, 54], YELLOW),
            ('yellow lower left connector', 'any', [94, 99, 67, 70], YELLOW),
            ('yellow lower right connector', 'any', [125, 131, 67, 70], YELLOW),
            ('wire interior is unfilled', 'area', [25, 35, 50, 70], BLACK),
            ('transformed wire interior is unfilled', 'area', [123, 133, 57, 63], BLACK),
            ('clear background', 'area', [5, 15, 5, 15], BLACK),
        ], [[18, 70, 38, 82], [90, 142, 48, 72]], [GREEN, YELLOW], []),
        ('world-spheres-depth.png', 'facade-sphere-perspective-model-and-occluded-lines', [
            ('near sphere occludes later far sphere and line', 'area', [40, 58, 56, 65], RED),
            ('near sphere upper interior', 'area', [45, 55, 49, 54], RED),
            ('near sphere lower interior', 'area', [45, 55, 67, 72], RED),
            ('near cyan line in front of sphere', 'horizontal', [29, 71, 44, 47], CYAN),
            ('far yellow line exposed left', 'horizontal', [21, 28, 59, 62], YELLOW),
            ('far yellow line exposed right', 'horizontal', [69, 77, 59, 62], YELLOW),
            ('scaled sphere upper interior', 'area', [107, 113, 50, 55], GREEN),
            ('scaled sphere lower interior', 'area', [107, 113, 65, 70], GREEN),
            ('clear background', 'area', [5, 15, 5, 15], BLACK),
            ('sphere gap remains clear', 'area', [85, 95, 50, 70], BLACK),
        ], [[18, 82, 39, 81], [98, 122, 42, 78]], [RED, CYAN, YELLOW, GREEN], [BLUE]),
    ]


def _probe_statistics(image, mode, bounds, color):
    left, right, top, bottom = bounds
    matches = lambda x, y: near_color(image.getpixel((x, y)), color, TOLERANCE)
    if mode == 'horizontal':
        return sum(any(matches(x, y) for y in range(top, bottom))
                   for x in range(left, right)), right - left
    if mode == 'vertical':
        return sum(any(matches(x, y) for x in range(left, right))
                   for y in range(top, bottom)), bottom - top
    if mode == 'any':
        return int(any(matches(x, y) for y in range(top, bottom)
                       for x in range(left, right))), 1
    return (sum(matches(x, y) for y in range(top, bottom) for x in range(left, right)),
            (right - left) * (bottom - top))


def _verify_image(output, spec, metadata, renderer):
    filename, case, probes, envelopes, palette, forbidden = spec
    location = filename
    fields = {'schema_version': 1, 'fixture_case': case, 'filename': filename,
              **renderer, 'renderer': renderer, 'force_fallback_adapter': True,
              'alpha_representation': 'opaque-rgba8-rgb-preserved-over-black',
              'diagnostic_raw_target': False, 'row_origin': 'top-left',
              'width': 160, 'height': 120, 'size': {'width': 160, 'height': 120}}
    require(metadata.keys() == set(fields) | {'evidence'}, f'{location}: metadata fields differ')
    literal({key: metadata[key] for key in fields}, fields, location)
    evidence = metadata['evidence']
    evidence_fields = {'coverage', 'probes', 'projection_envelopes', 'palette', 'palette_pixel_counts',
                       'forbidden_colors', 'forbidden_color_pixels', 'outside_envelope_pixels',
                       'channel_tolerance'}
    require(type(evidence) is dict and evidence.keys() == evidence_fields,
            f'{location}: evidence fields differ')
    fixed = {'projection_envelopes': envelopes, 'palette': palette,
             'forbidden_colors': forbidden, 'forbidden_color_pixels': 0,
             'outside_envelope_pixels': 0, 'channel_tolerance': TOLERANCE}
    literal({key: evidence[key] for key in fixed}, fixed, location + '.evidence')
    require(type(evidence['probes']) is list and len(evidence['probes']) == len(probes),
            f'{location}: probes differ')
    # Authenticate every probe before examining pixels. None of these bounds,
    # expected colors, modes, or tolerances are chosen by the report.
    for observed, (label, mode, bounds, color) in zip(evidence['probes'], probes):
        fixed_probe = {'label': label, 'mode': mode, 'pixel_bounds': bounds,
                       'expected_rgba': color, 'minimum_match_fraction': MINIMUM[mode],
                       'channel_tolerance': TOLERANCE}
        require(type(observed) is dict and observed.keys() == set(fixed_probe) | {
            'matching_samples', 'total_samples', 'match_fraction'}, f'{location}: probe fields differ')
        literal({key: observed[key] for key in fixed_probe}, fixed_probe, location + '.' + label)

    path = output / filename
    image = load_png(path, EXTENT)
    # load_png deliberately converts modes for its general callers; this fixture
    # additionally requires RGBA8 on disk (PNG color type 6, bit depth 8).
    with Image.open(path) as source:
        require(source.mode == 'RGBA', f'{location}: expected RGBA8 PNG')
    with path.open('rb') as source:
        header = source.read(29)
    require(header[12:16] == b'IHDR' and header[24:26] == bytes([8, 6]),
            f'{location}: expected RGBA8 PNG')
    counts = [0] * len(palette)
    nonblack = 0
    for y in range(120):
        for x in range(160):
            pixel = image.getpixel((x, y))
            require(pixel[3] == 255, f'{location}: main capture alpha is not opaque at ({x},{y})')
            if near_color(pixel, BLACK, TOLERANCE):
                continue
            require(not any(near_color(pixel, color, TOLERANCE) for color in forbidden),
                    f'{location}: forbidden clipped/occluded color at ({x},{y})')
            require(any(left <= x < right and top <= y < bottom
                        for left, right, top, bottom in envelopes),
                    f'{location}: nonblack pixel outside fixed projection envelopes at ({x},{y})')
            index = next((i for i, color in enumerate(palette)
                          if near_color(pixel, color, TOLERANCE)), None)
            require(index is not None, f'{location}: unexpected color at ({x},{y})')
            counts[index] += 1
            nonblack += 1
    require(nonblack > 0 and all(counts), f'{location}: capture is missing a required primitive color')
    literal(evidence['palette_pixel_counts'], counts, location + '.palette_pixel_counts')
    literal(evidence['coverage'], {'nonblack_pixels': nonblack, 'total_pixels': 19200,
                                  'nonblack_fraction': nonblack / 19200}, location + '.coverage')
    for observed, (label, mode, bounds, color) in zip(evidence['probes'], probes):
        matched, total = _probe_statistics(image, mode, bounds, color)
        require(matched / total >= MINIMUM[mode], f'{location}: pixel probe {label} failed')
        literal({key: observed[key] for key in ('matching_samples', 'total_samples', 'match_fraction')},
                {'matching_samples': matched, 'total_samples': total, 'match_fraction': matched / total},
                location + '.' + label + '.statistics')


def validate_outputs(output):
    """Validate all seven files; return content evidence without process claims."""
    output = Path(output)
    validate(output, expected_backend='Dx12')
    specifications = cases()
    expected = {REPORT} | {spec[0] + suffix for spec in specifications for suffix in ('', '.json')}
    entries = list(output.rglob('*'))
    actual = {path.relative_to(output).as_posix() for path in entries}
    require(actual == expected,
            f'fixture output set differs: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}')
    require(all(path.is_file() and not path.is_symlink() for path in entries),
            'fixture outputs must be regular files, not directories or symbolic links')
    report = read_record(output / REPORT)
    fixed = {'schema_version': 1, 'status': 'passed', 'native_execution': True,
             'requested': 'dx12', 'backend': 'Dx12', 'adapter': WARP,
             'force_fallback_adapter': True, 'platform': 'windows', 'scope': SCOPE}
    require(report.keys() == set(fixed) | {'build_version', 'build_number', 'captures'},
            'world primitives report fields differ')
    literal({key: report[key] for key in fixed}, fixed, 'world primitives report')
    for key in ('build_version', 'build_number'):
        require(type(report[key]) is str and bool(report[key].strip()),
                f'world primitives report missing {key}')
    require(type(report['captures']) is list and len(report['captures']) == 3,
            'world primitives report must contain all 3 ordered captures')
    renderer = {key: report[key] for key in ('requested', 'backend', 'adapter')}
    for spec, reported in zip(specifications, report['captures']):
        metadata = read_record(output / (spec[0] + '.json'))
        equal(reported, metadata, spec[0] + ': report/sidecar')
        _verify_image(output, spec, metadata, renderer)
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        import build_identity
        identity = build_identity.context()
        require(report['build_version'] == identity['version']
                and report['build_number'] == identity['build_number'],
                'world primitives report build identity does not match this CI attempt')
    return {'schema': 'rust-duty-world-primitives-contract-validation/v1', 'passed': True,
            'backend': 'Dx12', 'adapter': WARP, 'captures': 3,
            'build_version': report['build_version'], 'build_number': report['build_number'], 'scope': SCOPE}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args(argv)
    try:
        result = validate_outputs(args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f'World primitives output validation failed: {error}\n')
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

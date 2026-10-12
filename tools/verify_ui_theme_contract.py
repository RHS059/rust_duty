#!/usr/bin/env python3
"""Check the finalized UI-theme example's fixed evidence, without launching it.

The literals below are independently transcribed from ui_theme_contract.rs,
SHA256 23596041cb73a56b7f8797c72b56afb6d49bec327972d42ef261ec0382418873.
Neither a producer report nor its pixels choose expectations or tolerances.
Synthetic passes qualify this checker, not native Windows execution. Freshness,
executable identity, process success and compiler logs belong to the runner.
"""

import argparse
from functools import lru_cache
import json
import math
import os
from pathlib import Path

from PIL import Image, ImageChops

from run_renderer_contract import equal, literal, require
from verify_capture_telemetry import read_record, validate
from verify_render_capture import load_png


REPORT = 'ui-theme-contract-report.json'
SCALES = (100, 125, 150, 175, 200)
PHASES = ('initial', 'reloaded', 'invalid-last-good')
WARP = 'Microsoft Basic Render Driver'
SCOPE = 'headless native DX12 UiTheme-to-facade-to-PNG contract'
TOLERANCE = 4
ORACLE = 'independent fixed ProggyClean H/I design-grid area coverage, including negative-space pixels'
INITIAL_CSS = (
    '#pause-menu .panel { background-color:#204060; border-color:#e0c020; border-width:4px; }\n'
    '#pause-menu .label { color:#40e080; font-size:16px; }\n'
    '#pause-menu .button { background-color:#8040c0; border-color:#20c0e0; border-width:8px; opacity:0.5; }\n'
)
RELOADED_CSS = (
    '#pause-menu .panel { background-color:#502080; border-color:#20c080; border-width:8px; }\n'
    '#pause-menu .label { color:#e08040; font-size:32px; opacity:0.5; }\n'
    '#pause-menu .button { background-color:#4080c0; border-color:#e08020; border-width:4px; opacity:0.75; }\n'
)
INVALID_CSS = (
    '#pause-menu .panel { background-color:#ff0000; border-width:1px; }\n'
    '#pause-menu .label { opacity:NaN; }\n'
)
CSS_FILES = {'initial-theme.css': INITIAL_CSS, 'reloaded-theme.css': RELOADED_CSS,
             'rejected-theme.css': INVALID_CSS, 'active-theme.css': INVALID_CSS}
GLYPHS = (
    ('100001', '100001', '100001', '111111', '100001', '100001', '100001', '100001'),
    ('011100', '001000', '001000', '001000', '001000', '001000', '001000', '011100'),
)


def _colors(reloaded):
    if reloaded:
        return ((80, 32, 128, 255), (32, 192, 128, 255), (32, 192, 128, 255),
                (48, 96, 144, 255), (180, 120, 60, 255), (48, 96, 144, 255),
                (224, 128, 64), 127, 32)
    return ((32, 64, 96, 255), (224, 192, 32, 255), (32, 64, 96, 255),
            (64, 32, 96, 255), (48, 112, 160, 255), (48, 112, 160, 255),
            (64, 224, 128), 255, 16)


def _probes(reloaded):
    background, border, strip, button, button_border, button_strip, *_ = _colors(reloaded)
    return (
        ('panel background', [96., 36., 184., 68.], background),
        ('panel top border', [32., 21., 192., 23.], border),
        ('panel bottom border', [32., 81., 192., 83.], border),
        ('panel left border', [25., 32., 27., 72.], border),
        ('panel right border', [197., 32., 199., 72.], border),
        ('panel border width', [32., 25., 192., 27.], strip),
        ('button background opacity', [40., 124., 184., 148.], button),
        ('button top border opacity', [32., 109., 192., 111.], button_border),
        ('button bottom border opacity', [32., 161., 192., 163.], button_border),
        ('button left border opacity', [25., 120., 27., 152.], button_border),
        ('button right border opacity', [197., 120., 199., 152.], button_border),
        ('button border width', [32., 113., 192., 115.], button_strip),
        ('inward panel left guard', [20., 20., 23., 84.], (0, 0, 0, 255)),
        ('inward panel right guard', [201., 20., 204., 84.], (0, 0, 0, 255)),
        ('inward button top guard', [24., 104., 200., 107.], (0, 0, 0, 255)),
        ('inward button bottom guard', [24., 165., 200., 168.], (0, 0, 0, 255)),
    )


def _bounds(logical, percent):
    scale = percent / 100.
    return [math.ceil(logical[0] * scale), math.ceil(logical[1] * scale),
            math.floor(logical[2] * scale), math.floor(logical[3] * scale)]


def _round_positive(value):
    # Rust f64::round is half-away-from-zero; all source color values are >= 0.
    return math.floor(value + 0.5)


@lru_cache(maxsize=10)
def _text_expectation(reloaded, percent):
    """Fixed design-grid area coverage; cached immutable bytes, never test pixels.

    Accumulate each on-cell's geometric overlap in physical pixels. Quarter-step
    scales make all cell edges/overlaps exactly binary representable. Blend only
    after summing coverage, including the unpainted negative-space background.
    """
    background, _, _, _, _, _, rgb, alpha_byte, font_size = _colors(reloaded)
    scale = percent / 100.
    unit = font_size / 16. * scale
    left, top, right, bottom = _bounds([36., 36., 80., 68.], percent)
    size = (right - left, bottom - top)
    coverage = {}
    for glyph, rows in enumerate(GLYPHS):
        for row, cells in enumerate(rows):
            for column, cell in enumerate(cells):
                if cell != '1':
                    continue
                x0 = (40. + 24. * glyph) * scale + (1. + column) * unit
                y0 = 60. * scale + (-8. + row) * unit
                for y in range(max(top, math.floor(y0)), min(bottom, math.ceil(y0 + unit))):
                    dy = max(0., min(y0 + unit, y + 1.) - max(y0, y))
                    for x in range(max(left, math.floor(x0)), min(right, math.ceil(x0 + unit))):
                        dx = max(0., min(x0 + unit, x + 1.) - max(x0, x))
                        coverage[x, y] = coverage.get((x, y), 0.) + dx * dy
    image = Image.new('RGBA', size, background)
    ink = 0
    for (x, y), area in coverage.items():
        alpha = min(max(area, 0.), 1.) * alpha_byte / 255.
        color = tuple(_round_positive(rgb[i] * alpha + background[i] * (1. - alpha))
                      for i in range(3)) + (255,)
        image.putpixel((x - left, y - top), color)
        ink += color != background
    require(ink > 0, 'fixed text expectation has no ink')
    return size, image.tobytes(), ink


def _maximum_error(actual, expected):
    return max(high for _, high in ImageChops.difference(actual, expected).getextrema())


def _verify_image(output, phase, percent, metadata):
    filename = f'theme-{phase}-{percent}.png'
    reloaded = phase != 'initial'
    size = (320 * percent // 100, 192 * percent // 100)
    fixed = {'schema_version': 1, 'filename': filename, 'phase': phase,
             'requested': 'dx12', 'backend': 'Dx12', 'adapter': WARP,
             'scale_percent': percent, 'logical_size': [320, 192], 'physical_size': list(size),
             'row_origin': 'top-left', 'alpha_representation': 'opaque-rgba8-rgb-preserved-over-black',
             'last_good_identical_to_successful_reload': True if phase == 'invalid-last-good' else None}
    require(metadata.keys() == set(fixed) | {'probes', 'styled_text'}, f'{filename}: metadata fields differ')
    literal({key: metadata[key] for key in fixed}, fixed, filename)
    probes = _probes(reloaded)
    require(type(metadata['probes']) is list and len(metadata['probes']) == 16,
            f'{filename}: expected 16 ordered probes')
    # Authenticate all declarations before loading pixels. Reports cannot move
    # probe rectangles, relax thresholds, substitute colors or hide text holes.
    for observed, (label, logical, rgba) in zip(metadata['probes'], probes):
        bounds = _bounds(logical, percent)
        record = {'label': label, 'logical_bounds': logical, 'pixel_bounds': bounds,
                  'expected_rgba': list(rgba),
                  'checked_pixels': (bounds[2] - bounds[0]) * (bounds[3] - bounds[1]),
                  'channel_tolerance': TOLERANCE, 'required_match_fraction': 1.0}
        require(type(observed) is dict and observed.keys() == set(record) | {'maximum_channel_error'},
                f'{filename}: probe fields differ')
        literal({key: observed[key] for key in record}, record, f'{filename}.{label}')
    text_bounds = _bounds([36., 36., 80., 68.], percent)
    text_size, text_bytes, ink = _text_expectation(reloaded, percent)
    font_size = 32 if reloaded else 16
    styled = {'glyphs': [{'text': 'H', 'baseline_logical': [40, 60]},
                         {'text': 'I', 'baseline_logical': [64, 60]}],
              'font_size_css_px': font_size, 'font_size_physical_px': font_size * (percent / 100.),
              'pixel_bounds': text_bounds, 'expected_ink_pixels': ink,
              'checked_pixels': text_size[0] * text_size[1], 'channel_tolerance': TOLERANCE,
              'required_match_fraction': 1.0, 'oracle': ORACLE, 'human_legibility_approved': False}
    observed_text = metadata['styled_text']
    require(type(observed_text) is dict and observed_text.keys() == set(styled) | {'maximum_channel_error'},
            f'{filename}: styled_text fields differ')
    literal({key: observed_text[key] for key in styled}, styled, f'{filename}.styled_text')

    path = output / filename
    image = load_png(path, size)
    with Image.open(path) as source:
        require(source.mode == 'RGBA', f'{filename}: expected RGBA8 PNG')
    with path.open('rb') as source:
        header = source.read(29)
    require(header[12:16] == b'IHDR' and header[24:26] == bytes([8, 6]),
            f'{filename}: expected RGBA8 PNG')
    require(image.getchannel('A').getextrema() == (255, 255), f'{filename}: main PNG alpha must be opaque everywhere')
    for observed, (label, logical, rgba) in zip(metadata['probes'], probes):
        region = image.crop(_bounds(logical, percent))
        error = _maximum_error(region, Image.new('RGBA', region.size, rgba))
        require(error <= TOLERANCE, f'{filename}: pixel probe {label} failed (error {error} > {TOLERANCE})')
        literal(observed['maximum_channel_error'], error, f'{filename}.{label}.maximum_channel_error')
    error = _maximum_error(image.crop(text_bounds), Image.frombytes('RGBA', text_size, text_bytes))
    require(error <= TOLERANCE, f'{filename}: styled H/I raster failed (error {error} > {TOLERANCE})')
    literal(observed_text['maximum_channel_error'], error, f'{filename}.styled_text.maximum_channel_error')
    return image.tobytes()


def _reload_checks(report, output):
    checks = report['reload_checks']
    require(type(checks) is list and len(checks) == 3, 'expected three ordered reload_checks')
    literal(checks[:2], [{'phase': 'initial', 'api': 'load_theme', 'status': 'loaded'},
                        {'phase': 'reloaded', 'api': 'reload_theme', 'status': 'reloaded'}], 'reload_checks')
    rejected = checks[2]
    fixed = {'phase': 'invalid-last-good', 'api': 'reload_theme', 'status': 'expected-error'}
    require(type(rejected) is dict and rejected.keys() == set(fixed) | {'error', 'file', 'line', 'column'},
            'invalid-theme diagnostic fields differ')
    literal({key: rejected[key] for key in fixed}, fixed, 'invalid-theme diagnostic')
    for key in ('error', 'file'):
        require(type(rejected[key]) is str and bool(rejected[key].strip()),
                f'invalid-theme diagnostic {key} must be nonblank text')
    for key in ('line', 'column'):
        require(type(rejected[key]) is int and rejected[key] > 0,
                f'invalid-theme diagnostic {key} must be a positive integer')
    # The source does not pin parser message wording. Validate the typed location
    # and Display framing without inventing or accepting a fixed fake message.
    declared_path = Path(rejected['file'].replace('\\', '/'))
    require(declared_path.resolve() == (output / 'active-theme.css').resolve(),
            'invalid-theme diagnostic file must identify this active-theme.css path')
    lines = INVALID_CSS.splitlines()
    require(rejected['line'] <= len(lines)
            and rejected['column'] <= len(lines[rejected['line'] - 1]) + 1,
            'invalid-theme diagnostic position is outside active CSS')
    prefix = f"{rejected['file']}:{rejected['line']}:{rejected['column']}: "
    require(rejected['error'].startswith(prefix) and bool(rejected['error'][len(prefix):].strip()),
            'invalid-theme diagnostic error must contain matching file:line:column and nonblank detail')


def validate_outputs(output):
    """Validate all 35 evidence files, returning no process/provenance claims."""
    output = Path(output)
    validate(output, expected_backend='Dx12')
    expected = {REPORT, *CSS_FILES} | {
        f'theme-{phase}-{percent}.png{suffix}' for phase in PHASES for percent in SCALES
        for suffix in ('', '.json')}
    entries = list(output.rglob('*'))
    actual = {path.relative_to(output).as_posix() for path in entries}
    require(actual == expected,
            f'fixture output set differs: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}')
    require(all(path.is_file() and not path.is_symlink() for path in entries),
            'fixture outputs must be regular files, not directories or symbolic links')
    for filename, css in CSS_FILES.items():
        require((output / filename).read_bytes() == css.encode('utf-8'), f'{filename}: CSS bytes differ from fixed source')
    report = read_record(output / REPORT)
    fixed = {'schema_version': 1, 'status': 'passed', 'native_execution': True,
             'requested': 'dx12', 'backend': 'Dx12', 'adapter': WARP,
             'force_fallback_adapter': True, 'platform': 'windows', 'scales_percent': list(SCALES),
             'compiler_identity_source': 'external captured renderer startup log; not inferred by this fixture',
             'scope': SCOPE,
             'boundaries': {'os_dpi_events_verified': False, 'window_presentation_verified': False,
                            'native_pointer_or_click_verified': False, 'human_legibility_approved': False,
                            'private_assets_loaded': False},
             'cpu_hit_geometry': {
                 'evidence': 'CPU only; Rect::contains at the logical draw rectangle',
                 'button_logical_xywh': [24, 108, 176, 56],
                 'samples': [{'point': [24., 108.], 'inside': True},
                             {'point': [200., 164.], 'inside': True},
                             {'point': [112., 136.], 'inside': True},
                             {'point': [23.75, 136.], 'inside': False},
                             {'point': [200.25, 136.], 'inside': False}],
                 'native_pointer_or_click_verified': False}}
    require(report.keys() == set(fixed) | {'build_version', 'build_number', 'captures', 'reload_checks'},
            'UI theme report fields differ')
    literal({key: report[key] for key in fixed}, fixed, 'UI theme report')
    for key in ('build_version', 'build_number'):
        require(type(report[key]) is str and bool(report[key].strip()), f'UI theme report missing {key}')
    require(type(report['captures']) is list and len(report['captures']) == 15,
            'UI theme report must contain all 15 ordered captures')
    _reload_checks(report, output)
    reloaded_pixels = {}
    for index, (phase, percent) in enumerate((p, s) for p in PHASES for s in SCALES):
        filename = f'theme-{phase}-{percent}.png'
        metadata = read_record(output / (filename + '.json'))
        equal(report['captures'][index], metadata, filename + ': report/sidecar')
        pixels = _verify_image(output, phase, percent, metadata)
        if phase == 'reloaded':
            reloaded_pixels[percent] = pixels
        elif phase == 'invalid-last-good':
            require(pixels == reloaded_pixels[percent], f'{filename}: last-good pixels differ from successful reload')
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        import build_identity
        identity = build_identity.context()
        require(report['build_version'] == identity['version']
                and report['build_number'] == identity['build_number'],
                'UI theme report build identity does not match this CI attempt')
    return {'schema': 'rust-duty-ui-theme-contract-validation/v1', 'passed': True,
            'backend': 'Dx12', 'adapter': WARP, 'captures': 15,
            'build_version': report['build_version'], 'build_number': report['build_number'], 'scope': SCOPE}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args(argv)
    try:
        result = validate_outputs(args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f'UI theme output validation failed: {error}\n')
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run the built game_ui_contract example on Windows DX12 and verify its evidence.

Process provenance (fresh directories, exit code, executable hash, actual
Dx12/WARP and FXC startup logs) is owned by dx12_contract_process. This module
only checks the fixture's own outputs: an exact file inventory with no links,
exact typed report and sidecar metadata, and every PNG re-decoded and
re-measured independently of the producer. Expectations are transcribed from
the documented hint behaviour, never read from the report under test.
"""

import argparse
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image

import dx12_contract_process
from verify_capture_telemetry import read_record
from verify_render_capture import load_png

REPORT = 'game-ui-contract-report.json'
WARP = 'Microsoft Basic Render Driver'
SCALES = (100, 200)
LOGICAL_SIZE = (480, 270)
ANCHOR = (240, 120)
INK_WINDOW = (90, 80, 390, 190)
# Logical regions for the white key glyph and the caption (or AMMO FULL text).
KEY_BOX = (230, 108, 250, 132)
CAPTION_BAND = (90, 140, 390, 172)
FULL_TEXT_BAND = (90, 100, 390, 128)
CASES = (('idle', '0', False), ('half', '0.5', False), ('complete', '1', False), ('ammo-full', '0', True))
INK_KEYS = {'lit_pixels', 'lit_bounds', 'gold_left', 'gold_right', 'key_white', 'caption_white'}
SIDECAR_KEYS = {'schema_version', 'filename', 'element', 'case', 'progress', 'ammo_full', 'requested',
                'backend', 'adapter', 'scale_percent', 'logical_size', 'physical_size', 'anchor_logical', 'ink'}
REPORT_KEYS = {'schema_version', 'status', 'native_execution', 'requested', 'backend', 'adapter',
               'force_fallback_adapter', 'platform', 'build_version', 'build_number', 'scales_percent',
               'captures', 'elements_covered', 'elements_pending', 'compiler_identity_source', 'scope', 'boundaries'}
SCOPE = 'headless native DX12 production game-UI draw paths to PNG'
COMPILER_SOURCE = 'external captured renderer startup log; not inferred by this fixture'
BOUNDARIES = {'os_dpi_events_verified': False, 'window_presentation_verified': False,
              'native_pointer_or_click_verified': False, 'human_legibility_approved': False}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def is_int(value):
    return type(value) is int


def is_gold(p):
    return p[0] >= 235 and 170 <= p[1] <= 215 and p[2] <= 95


def is_white(p):
    return min(p[0], p[1], p[2]) >= 200 and not is_gold(p)


def inside(x, y, region, scale):
    return (region[0] * scale <= x + 0.5 < region[2] * scale
            and region[1] * scale <= y + 0.5 < region[3] * scale)


def measure(image, scale, full):
    """Lit pixels, bounds, gold left/right of the anchor, and white key/caption pixels."""
    axis = ANCHOR[0] * scale
    width, height = image.size
    pixels = image.load()
    ink = dict.fromkeys(('lit_pixels', 'gold_left', 'gold_right', 'key_white', 'caption_white'), 0)
    bounds = None
    caption = FULL_TEXT_BAND if full else CAPTION_BAND
    for y in range(height):
        for x in range(width):
            p = pixels[x, y]
            if p[0] == 0 and p[1] == 0 and p[2] == 0:
                continue
            ink['lit_pixels'] += 1
            bounds = [x, y, x, y] if bounds is None else [
                min(bounds[0], x), min(bounds[1], y), max(bounds[2], x), max(bounds[3], y)]
            if is_gold(p):
                ink['gold_left' if x + 0.5 < axis else 'gold_right'] += 1
            elif is_white(p):
                if not full and inside(x, y, KEY_BOX, scale):
                    ink['key_white'] += 1
                if inside(x, y, caption, scale):
                    ink['caption_white'] += 1
    ink['lit_bounds'] = bounds
    return ink


def check_case(case, ink, scale):
    bounds = ink['lit_bounds']
    require(bounds is not None and ink['lit_pixels'] > 0, f'{case}: capture is empty')
    window = [value * scale for value in INK_WINDOW]
    require(bounds[0] >= window[0] and bounds[1] >= window[1] and bounds[2] <= window[2] and bounds[3] <= window[3],
            f'{case}: lit bounds {bounds} escape {window}')
    area = scale * scale
    gold = ink['gold_left'] + ink['gold_right']
    require(ink['caption_white'] >= 60 * area, f'{case}: caption text is missing')
    if case == 'ammo-full':
        require(bounds[1] >= FULL_TEXT_BAND[1] * scale and bounds[3] < FULL_TEXT_BAND[3] * scale,
                'ammo-full: only the AMMO FULL text may be drawn')
        require(gold == 0 and ink['key_white'] == 0, 'ammo-full: no hold circle or key may be drawn')
        return
    require(ink['key_white'] >= 8 * area, f'{case}: the F key glyph is missing')
    if case == 'idle':
        require(gold == 0, f'idle: no hold circle may be drawn, found {gold} gold pixels')
    elif case == 'half':
        require(ink['gold_right'] > 0 and ink['gold_left'] <= ink['gold_right'] // 50,
                f"half: gold sweep must sit right of the anchor, got {ink['gold_left']}/{ink['gold_right']}")
    elif case == 'complete':
        require(ink['gold_left'] > 0 and ink['gold_right'] > 0, 'complete: gold sweep must cover both halves')


def check_scale(inks, images):
    half = inks['half']['gold_left'] + inks['half']['gold_right']
    complete = inks['complete']['gold_left'] + inks['complete']['gold_right']
    ratio = complete / max(half, 1)
    require(1.6 <= ratio <= 2.4, f'full sweep should be about twice the half sweep, got {ratio:.2f}')
    names = list(images)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            require(images[a] != images[b], f'{a} and {b} rendered identical pixels')


def check_scaling(one, two):
    a, b = one['lit_bounds'], two['lit_bounds']
    area = two['lit_pixels'] / max(one['lit_pixels'], 1)
    width = (b[2] - b[0] + 1) / (a[2] - a[0] + 1)
    require(3.0 <= area <= 5.0 and 1.8 <= width <= 2.2,
            f'200% capture is not a 2x rendering: area x{area:.2f}, width x{width:.2f}')


def opaque_rgba(path, extent):
    """Integrity/extent via load_png, then the file's own encoding must be opaque RGBA8."""
    load_png(path, extent)
    with Image.open(path) as image:
        require(image.mode == 'RGBA', f'{path.name}: PNG must be stored as RGBA8, got {image.mode}')
        require(image.getextrema()[3] == (255, 255), f'{path.name}: PNG alpha must be opaque everywhere')
        return image.copy()


def check_ink_record(name, recorded, measured):
    require(isinstance(recorded, dict) and set(recorded) == INK_KEYS, f'{name}: ink record has wrong fields')
    for key in INK_KEYS - {'lit_bounds'}:
        require(is_int(recorded[key]), f'{name}: ink {key} must be an integer')
    bounds = recorded['lit_bounds']
    require(bounds is None or (isinstance(bounds, list) and len(bounds) == 4 and all(map(is_int, bounds))),
            f'{name}: ink lit_bounds must be four integers')
    require(recorded == measured, f'{name}: recorded ink differs from independent measurement')


def validate_outputs(output):
    output = Path(output)
    require(output.is_dir() and not output.is_symlink(), 'fixture output must be a real directory')
    expected = [f'ammo-{case}-{percent}.png' for percent in SCALES for case, _, _ in CASES]
    entries = list(output.iterdir())
    require(not any(entry.is_symlink() or not entry.is_file() for entry in entries),
            'fixture output may contain only regular files, no links')
    require({entry.name for entry in entries} == set(expected) | {f'{n}.json' for n in expected} | {REPORT},
            'fixture output has missing or unexpected files')

    report = read_record(output / REPORT)
    require(set(report) == REPORT_KEYS, 'fixture report has missing or unexpected fields')
    require(report['schema_version'] == 1 and is_int(report['schema_version'])
            and report['status'] == 'passed' and report['native_execution'] is True,
            'fixture report is not a native pass')
    require(report['requested'] == 'dx12' and report['backend'] == 'Dx12'
            and isinstance(report['adapter'], str) and report['adapter'].casefold() == WARP.casefold()
            and report['force_fallback_adapter'] is True and report['platform'] == 'windows',
            'fixture report is not a Windows DX12 WARP run')
    require(isinstance(report['build_version'], str) and report['build_version'].count('.') == 2
            and isinstance(report['build_number'], str) and report['build_number'].strip(),
            'fixture report build identity is malformed')
    require(report['scales_percent'] == list(SCALES) and all(map(is_int, report['scales_percent'])),
            'fixture report scales are wrong')
    require(report['elements_covered'] == ['ammo-hint'] and isinstance(report['elements_pending'], dict),
            'fixture report element coverage is wrong')
    require(report['compiler_identity_source'] == COMPILER_SOURCE and report['scope'] == SCOPE
            and report['boundaries'] == BOUNDARIES, 'fixture report scope or boundaries changed')
    captures = report['captures']
    require(isinstance(captures, list) and len(captures) == len(expected), 'report must list every capture')

    per_scale = {}
    index = 0
    for percent in SCALES:
        scale = percent // 100
        extent = (LOGICAL_SIZE[0] * scale, LOGICAL_SIZE[1] * scale)
        inks, images = {}, {}
        for case, progress, full in CASES:
            name = f'ammo-{case}-{percent}.png'
            sidecar = read_record(output / f'{name}.json')
            require(captures[index] == sidecar, f'{name}: report capture entry differs from its sidecar')
            index += 1
            require(set(sidecar) == SIDECAR_KEYS, f'{name}: sidecar has missing or unexpected fields')
            anchor = sidecar['anchor_logical']
            require(sidecar['schema_version'] == 1 and is_int(sidecar['schema_version'])
                    and sidecar['filename'] == name and sidecar['element'] == 'ammo-hint'
                    and sidecar['case'] == case and sidecar['ammo_full'] is full
                    and type(sidecar['progress']) in (int, Decimal)
                    and Decimal(sidecar['progress']) == Decimal(progress)
                    and sidecar['requested'] == 'dx12' and sidecar['backend'] == 'Dx12'
                    and sidecar['adapter'] == report['adapter']
                    and is_int(sidecar['scale_percent']) and sidecar['scale_percent'] == percent
                    and sidecar['logical_size'] == list(LOGICAL_SIZE) and all(map(is_int, sidecar['logical_size']))
                    and sidecar['physical_size'] == list(extent) and all(map(is_int, sidecar['physical_size']))
                    and isinstance(anchor, list) and len(anchor) == 2
                    and all(type(v) in (int, Decimal) for v in anchor)
                    and [Decimal(v) for v in anchor] == [Decimal(v) for v in ANCHOR],
                    f'{name}: sidecar identity mismatch')
            image = opaque_rgba(output / name, extent)
            ink = measure(image, scale, full)
            check_ink_record(name, sidecar['ink'], ink)
            check_case(case, ink, scale)
            inks[case], images[case] = ink, image.tobytes()
        check_scale(inks, images)
        per_scale[percent] = inks
    for case, _, _ in CASES:
        check_scaling(per_scale[100][case], per_scale[200][case])
    return {'passed': True, 'captures': len(expected), 'elements_covered': ['ammo-hint'],
            'adapter': report['adapter'],
            'scope': 'Production ammo hint draw path on DX12 WARP; menu and updater cases follow.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True, type=Path)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--timeout', type=float, default=180)
    args = parser.parse_args(argv)
    try:
        if sys.platform != 'win32':
            raise ValueError('the game UI fixture requires actual Windows DX12')
        report = dx12_contract_process.run(args.executable, args.root, args.evidence, args.output,
                                           args.timeout, 'game-ui', validate_outputs)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f'DX12 game UI fixture failed: {error}\n')
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

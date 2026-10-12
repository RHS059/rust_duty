#!/usr/bin/env python3
"""Run the built game_ui_contract example on Windows DX12 and verify its evidence.

The fixture draws the production pause menu, updater panel, HUD/telemetry and
ammo hint inside the live winit window runtime, into offscreen targets at 1x
and 2x of the 960x540 logical viewport.

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
import os
from pathlib import Path
import re
import subprocess
import sys

from PIL import Image, ImageChops

import build_identity
import dx12_contract_process
from run_renderer_contract import equal, literal
from verify_capture_telemetry import read_record
from verify_render_capture import load_png

REPORT = 'game-ui-contract-report.json'
WARP = 'Microsoft Basic Render Driver'
SCALES = (100, 200)
LOGICAL_SIZE = (960, 540)
ANCHOR = (240, 120)
INK_WINDOW = (90, 80, 390, 190)
# Logical regions for the white key glyph and the caption (or AMMO FULL text).
KEY_BOX = (230, 108, 250, 132)
CAPTION_BAND = (90, 140, 390, 172)
FULL_TEXT_BAND = (90, 100, 390, 128)
# HUD corner panels (title, score, stance, weapon), telemetry panel, menu band.
CORNERS = ((24, 24, 312, 105), (685, 24, 936, 105), (24, 435, 272, 516), (710, 415, 936, 516))
DEBUG_PANEL = (24, 119, 334, 326)
MENU_BAND = (200, 0, 760, 540)
CASES = ('pause-menu', 'updater-current', 'updater-unavailable', 'hud', 'hud-telemetry',
         'ammo-idle', 'ammo-half', 'ammo-complete', 'ammo-full')
ELEMENTS = {'pause-menu': 'pause-menu', 'updater-current': 'updater-panel', 'updater-unavailable': 'updater-panel',
            'hud': 'hud', 'hud-telemetry': 'telemetry'}
AMMO = {'ammo-idle': ('idle', '0', False), 'ammo-half': ('half', '0.5', False),
        'ammo-complete': ('complete', '1', False), 'ammo-full': ('ammo-full', '0', True)}
PARAMETERS = {
    'pause-menu': {'weapon': 'hk416a5', 'initial': False, 'control_mode': 'toggle', 'status': None},
    'updater-current': {'phase': 'current', 'message': 'Version is current.', 'menu': True},
    'updater-unavailable': {'phase': 'unavailable', 'message': "Can't reach GitHub. Retry, or play this version.",
                            'menu': True},
    'hud': {'debug': False, 'recording': False, 'weapon_label': 'M4 / CANDIDATE'},
    'hud-telemetry': {'debug': True, 'recording': False, 'weapon_label': 'M4 / CANDIDATE'},
}
AMMO_INK_KEYS = {'lit_pixels', 'lit_bounds', 'gold_left', 'gold_right', 'key_white', 'caption_white'}
UI_INK_KEYS = {'lit_pixels', 'lit_bounds', 'warm', 'warm_menu_band', 'white', 'corner_white', 'debug_lit'}
SIDECAR_KEYS = {'schema_version', 'filename', 'element', 'case', 'parameters', 'requested', 'backend', 'adapter',
                'scale_percent', 'logical_size', 'physical_size', 'ink'}
REPORT_KEYS = {'schema_version', 'status', 'native_execution', 'requested', 'backend', 'adapter',
               'force_fallback_adapter', 'platform', 'build_version', 'build_number', 'live_logical_viewport',
               'scales_percent', 'cases', 'captures', 'elements_covered', 'compiler_identity_source', 'scope',
               'boundaries'}
ELEMENTS_COVERED = ['pause-menu', 'updater-panel', 'hud', 'telemetry', 'ammo-hint']
SCOPE = 'live game window runtime, native production game-UI draw paths to offscreen PNG'
COMPILER_SOURCE = 'external captured renderer startup log; not inferred by this fixture'
BOUNDARIES = {'os_dpi_events_verified': False, 'window_presentation_verified': False,
              'native_pointer_or_click_verified': False, 'human_legibility_approved': False}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def is_int(value):
    return type(value) is int


# Reference per-pixel predicates; masks() must agree with them exactly.
def is_gold(p):
    return p[0] >= 235 and 170 <= p[1] <= 215 and p[2] <= 95


def is_white(p):
    return min(p[0], p[1], p[2]) >= 200 and not is_gold(p)


def is_warm(p):
    """HUD/menu accent #FA9E38, GOLD #FFCB00 and supply gold; not white, cyan or grey."""
    return p[0] >= 200 and 100 <= p[1] <= 215 and p[2] <= 110


def masks(image):
    """Per-pixel 255/0 masks equal to is_gold/is_white/is_warm and 'not the black clear'."""
    r, g, b, _ = image.convert('RGBA').split()

    def band(channel, low, high):
        return channel.point(lambda v: 255 if low <= v <= high else 0)
    return {
        'lit': ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda v: 255 if v else 0),
        'white': ImageChops.darker(ImageChops.darker(r, g), b).point(lambda v: 255 if v >= 200 else 0),
        'gold': ImageChops.multiply(ImageChops.multiply(band(r, 235, 255), band(g, 170, 215)), band(b, 0, 95)),
        'warm': ImageChops.multiply(ImageChops.multiply(band(r, 200, 255), band(g, 100, 215)), band(b, 0, 110)),
    }


def count(mask, region=None, scale=1):
    """Set pixels whose centre lies in the logical region (integer bounds, so exact)."""
    if region is not None:
        mask = mask.crop(tuple(int(v * scale) for v in region))
    return mask.histogram()[255]


def bounds(mask):
    box = mask.getbbox()
    return None if box is None else [box[0], box[1], box[2] - 1, box[3] - 1]


def measure(image, scale, full):
    """Lit pixels, bounds, gold left/right of the anchor, and white key/caption pixels."""
    m = masks(image)
    width, height = image.size
    axis = ANCHOR[0] * scale
    # Gold and white are disjoint (blue <= 95 versus >= 200).
    return {
        'lit_pixels': count(m['lit']), 'lit_bounds': bounds(m['lit']),
        'gold_left': count(m['gold'], (0, 0, axis, height)),
        'gold_right': count(m['gold'], (axis, 0, width, height)),
        'key_white': 0 if full else count(m['white'], KEY_BOX, scale),
        'caption_white': count(m['white'], FULL_TEXT_BAND if full else CAPTION_BAND, scale),
    }


def check_case(case, ink, scale):
    bounds = ink['lit_bounds']
    require(bounds is not None and ink['lit_pixels'] > 0, f'{case}: capture is empty')
    window = [value * scale for value in INK_WINDOW]
    require(bounds[0] >= window[0] and bounds[1] >= window[1] and bounds[2] <= window[2] and bounds[3] <= window[3],
            f'{case}: lit bounds {bounds} escape {window}')
    area = scale * scale
    gold = ink['gold_left'] + ink['gold_right']
    require(ink['caption_white'] >= (20 if case == 'ammo-full' else 60) * area, f'{case}: caption text is missing')
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


def measure_ui(image, scale):
    """Lit pixels and bounds, warm pixels (all, menu band), white (all, per HUD corner), telemetry-panel ink."""
    m = masks(image)
    # Warm and white are disjoint (blue <= 110 versus >= 200).
    return {
        'lit_pixels': count(m['lit']), 'lit_bounds': bounds(m['lit']),
        'warm': count(m['warm']), 'warm_menu_band': count(m['warm'], MENU_BAND, scale),
        'white': count(m['white']), 'corner_white': [count(m['white'], c, scale) for c in CORNERS],
        'debug_lit': count(m['lit'], DEBUG_PANEL, scale),
    }


def check_ui_case(case, ink, scale):
    area = scale * scale
    require(ink['lit_bounds'] is not None and ink['lit_pixels'] > 0, f'{case}: capture is empty')
    if case == 'pause-menu':
        require(ink['warm_menu_band'] >= 500 * area and ink['white'] >= 75 * area,
                f"pause-menu: expected accent and white text in the centred menu, got warm "
                f"{ink['warm_menu_band']} white {ink['white']}")
    elif case.startswith('updater-'):
        require(ink['warm'] >= 50 * area and ink['white'] >= 50 * area,
                f"{case}: expected gold title/frame and white message, got warm {ink['warm']} white {ink['white']}")
    else:
        require(all(n >= 20 * area for n in ink['corner_white']),
                f"{case}: every HUD corner needs white text, got {ink['corner_white']}")


def check_ui_text(case, image, scale):
    """Default production-font layout markers, independent of recorded ink.

    The opaque dark panels cannot satisfy this mask. Muted HUD text is
    (158,176,184), so the white-only mask would discard all telemetry rows.
    These markers detect missing rows/messages and swapped updater states;
    they do not establish exact wording or human legibility.
    """
    if case != 'hud-telemetry' and not case.startswith('updater-'):
        return
    r, g, b, _ = image.split()
    foreground = ImageChops.darker(ImageChops.darker(r, g), b).point(lambda v: 255 if v >= 100 else 0)
    area = scale * scale
    if case == 'hud-telemetry':
        # Production rows start at x=40, baseline 145 + row*23, size 16.
        # ProggyClean's 16px glyph bounds fit baseline-12 through baseline+4.
        for row in range(8):
            band = (40, 133 + row * 23, 334, 149 + row * 23)
            require(count(foreground, band, scale) >= 20 * area,
                    f'hud-telemetry: text missing from row {row + 1}')
        return
    # The default updater panel starts at (18,18); message baseline is (34,71).
    # At 16px ProggyClean advances 7px: "Version is current." ends before x=180,
    # while the unavailable message extends beyond x=300. The title and buttons
    # lie outside this band, so they cannot stand in for the message.
    require(count(foreground, (34, 59, 600, 77), scale) >= 40 * area,
            f'{case}: message text is missing')
    tail = count(foreground, (180, 59, 600, 77), scale)
    require(tail == 0 if case == 'updater-current' else tail >= 40 * area,
            f'{case}: message layout does not match its state')


def check_scale(inks, images, scale):
    half = inks['ammo-half']['gold_left'] + inks['ammo-half']['gold_right']
    complete = inks['ammo-complete']['gold_left'] + inks['ammo-complete']['gold_right']
    ratio = complete / max(half, 1)
    require(1.6 <= ratio <= 2.4, f'full sweep should be about twice the half sweep, got {ratio:.2f}')
    require(inks['hud-telemetry']['debug_lit'] >= inks['hud']['debug_lit'] + 300 * scale * scale,
            'hud-telemetry: telemetry panel missing')
    names = list(images)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            require(images[a] != images[b], f'{a} and {b} rendered identical pixels')


def integrated_intensity(image):
    """Coverage proxy over the fixed black clear: sum max(R, G, B), not lit support.

    A faint antialias fringe contributes proportionally instead of counting as
    one full pixel. Each pair uses the same colors and opaque RGBA8 encoding.
    This value is measured from pixels and is never trusted from a sidecar.
    """
    r, g, b, _ = image.split()
    histogram = ImageChops.lighter(ImageChops.lighter(r, g), b).histogram()
    return sum(level * pixels for level, pixels in enumerate(histogram))


def check_scaling(one, two, one_intensity, two_intensity):
    a, b = one['lit_bounds'], two['lit_bounds']
    require(a is not None and b is not None and one_intensity > 0 and two_intensity > 0,
            'scaling comparison requires nonempty pixel coverage')
    area = two_intensity / one_intensity
    width = (b[2] - b[0] + 1) / (a[2] - a[0] + 1)
    require(3.0 <= area <= 5.0 and 1.8 <= width <= 2.2,
            f'200% capture is not a 2x rendering: area x{area:.2f}, width x{width:.2f}')


def opaque_rgba(path, extent):
    """Integrity/extent via load_png, then the file's own encoding must be opaque RGBA8."""
    load_png(path, extent)
    with path.open('rb') as source:
        header = source.read(26)
    # IHDR bit depth 8 and colour type 6 (RGBA); Pillow also reports RGBA16 as RGBA.
    require(len(header) == 26 and header[12:16] == b'IHDR' and header[24:26] == bytes([8, 6]),
            f'{path.name}: PNG must be 8-bit RGBA (IHDR bit depth 8, colour type 6)')
    with Image.open(path) as image:
        require(image.mode == 'RGBA', f'{path.name}: PNG must be stored as RGBA8, got {image.mode}')
        require(image.getextrema()[3] == (255, 255), f'{path.name}: PNG alpha must be opaque everywhere')
        return image.copy()


def check_ink_record(name, recorded, measured, keys):
    require(isinstance(recorded, dict) and set(recorded) == keys, f'{name}: ink record has wrong fields')
    for key in keys - {'lit_bounds', 'corner_white'}:
        require(is_int(recorded[key]), f'{name}: ink {key} must be an integer')
    if 'corner_white' in keys:
        corners = recorded['corner_white']
        require(isinstance(corners, list) and len(corners) == 4 and all(map(is_int, corners)),
                f'{name}: ink corner_white must be four integers')
    bounds = recorded['lit_bounds']
    require(bounds is None or (isinstance(bounds, list) and len(bounds) == 4 and all(map(is_int, bounds))),
            f'{name}: ink lit_bounds must be four integers')
    require(recorded == measured, f'{name}: recorded ink differs from independent measurement')


def check_parameters(name, case, parameters):
    if case not in AMMO:
        literal(parameters, PARAMETERS[case], f'{name}: parameters')
        return
    _, progress, full = AMMO[case]
    anchor = parameters.get('anchor_logical') if isinstance(parameters, dict) else None
    require(isinstance(parameters, dict) and set(parameters) == {'progress', 'ammo_full', 'anchor_logical'}
            and parameters['ammo_full'] is full
            and type(parameters['progress']) in (int, Decimal)
            and Decimal(parameters['progress']) == Decimal(progress)
            and isinstance(anchor, list) and len(anchor) == 2
            and all(type(v) in (int, Decimal) for v in anchor)
            and [Decimal(v) for v in anchor] == [Decimal(v) for v in ANCHOR],
            f'{name}: ammo parameters mismatch')


def validate_outputs(output, renderer='dx12'):
    """DX12 evidence must come from Windows WARP; GL evidence from any named OpenGL adapter."""
    require(renderer in ('dx12', 'gl'), f'unknown renderer {renderer!r}')
    backend = 'Dx12' if renderer == 'dx12' else 'OpenGl'
    output = Path(output)
    require(output.is_dir() and not output.is_symlink(), 'fixture output must be a real directory')
    expected = [f'{case}-{percent}.png' for percent in SCALES for case in CASES]
    entries = list(output.iterdir())
    require(not any(entry.is_symlink() or not entry.is_file() for entry in entries),
            'fixture output may contain only regular files, no links')
    require({entry.name for entry in entries} == set(expected) | {f'{n}.json' for n in expected} | {REPORT},
            'fixture output has missing or unexpected files')

    report = read_record(output / REPORT)
    require(set(report) == REPORT_KEYS, 'fixture report has missing or unexpected fields')
    require(report['schema_version'] == 2 and is_int(report['schema_version'])
            and report['status'] == 'passed' and report['native_execution'] is True,
            'fixture report is not a native pass')
    if renderer == 'dx12':
        require(report['requested'] == 'dx12' and report['backend'] == 'Dx12'
                and isinstance(report['adapter'], str) and report['adapter'].casefold() == WARP.casefold()
                and report['force_fallback_adapter'] is True and report['platform'] == 'windows',
                'fixture report is not a Windows DX12 WARP run')
    else:
        require(report['requested'] == 'gl' and report['backend'] == 'OpenGl'
                and isinstance(report['adapter'], str) and report['adapter'].strip()
                and report['force_fallback_adapter'] is False and report['platform'] in ('windows', 'linux'),
                'fixture report is not a native OpenGL run')
    require(isinstance(report['build_version'], str) and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', report['build_version'])
            and report['build_version'] == build_identity.package_version()
            and isinstance(report['build_number'], str) and report['build_number'].strip(),
            'fixture report build identity is malformed or not this package version')
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        identity = build_identity.context()
        require(report['build_version'] == identity['version'] and report['build_number'] == identity['build_number'],
                'fixture report build identity does not match this CI attempt')
    literal(report['live_logical_viewport'], list(LOGICAL_SIZE), 'report.live_logical_viewport')
    literal(report['scales_percent'], list(SCALES), 'report.scales_percent')
    literal(report['cases'], list(CASES), 'report.cases')
    literal(report['elements_covered'], ELEMENTS_COVERED, 'report.elements_covered')
    literal(report['compiler_identity_source'], COMPILER_SOURCE, 'report.compiler_identity_source')
    literal(report['scope'], SCOPE, 'report.scope')
    literal(report['boundaries'], BOUNDARIES, 'report.boundaries')
    captures = report['captures']
    require(isinstance(captures, list) and len(captures) == len(expected), 'report must list every capture')

    per_scale = {}
    intensities = {}
    index = 0
    for percent in SCALES:
        scale = percent // 100
        extent = (LOGICAL_SIZE[0] * scale, LOGICAL_SIZE[1] * scale)
        inks, images = {}, {}
        for case in CASES:
            name = f'{case}-{percent}.png'
            sidecar = read_record(output / f'{name}.json')
            equal(captures[index], sidecar, f'{name}: report capture entry vs sidecar')
            index += 1
            require(set(sidecar) == SIDECAR_KEYS, f'{name}: sidecar has missing or unexpected fields')
            require(sidecar['schema_version'] == 2 and is_int(sidecar['schema_version'])
                    and sidecar['filename'] == name
                    and sidecar['element'] == ELEMENTS.get(case, 'ammo-hint') and sidecar['case'] == case
                    and sidecar['requested'] == renderer and sidecar['backend'] == backend
                    and sidecar['adapter'] == report['adapter']
                    and is_int(sidecar['scale_percent']) and sidecar['scale_percent'] == percent
                    and sidecar['logical_size'] == list(LOGICAL_SIZE) and all(map(is_int, sidecar['logical_size']))
                    and sidecar['physical_size'] == list(extent) and all(map(is_int, sidecar['physical_size'])),
                    f'{name}: sidecar identity mismatch')
            check_parameters(name, case, sidecar['parameters'])
            image = opaque_rgba(output / name, extent)
            intensities[percent, case] = integrated_intensity(image)
            if case in AMMO:
                ammo, _, full = AMMO[case]
                ink = measure(image, scale, full)
                check_ink_record(name, sidecar['ink'], ink, AMMO_INK_KEYS)
                check_case(ammo, ink, scale)
            else:
                ink = measure_ui(image, scale)
                check_ink_record(name, sidecar['ink'], ink, UI_INK_KEYS)
                check_ui_case(case, ink, scale)
            inks[case], images[case] = ink, image.tobytes()
        check_scale(inks, images, scale)
        for case in ('hud-telemetry', 'updater-current', 'updater-unavailable'):
            check_ui_text(case, Image.frombytes('RGBA', extent, images[case]), scale)
        per_scale[percent] = inks
    for case in CASES:
        check_scaling(per_scale[100][case], per_scale[200][case],
                      intensities[100, case], intensities[200, case])
    return {'passed': True, 'captures': len(expected), 'elements_covered': ELEMENTS_COVERED,
            'adapter': report['adapter'],
            'scope': f'Production pause menu, updater, HUD/telemetry and ammo hint in the live window on {backend}.'}


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

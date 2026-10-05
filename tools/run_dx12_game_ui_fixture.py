#!/usr/bin/env python3
"""Run the built game_ui_contract example on Windows DX12 and verify its evidence.

Process provenance (fresh directories, exit code, executable hash, actual
Dx12/WARP and FXC startup logs) is owned by dx12_contract_process. This module
only checks the fixture's own outputs, re-measuring every PNG independently of
the producer's report. Expectations are transcribed from the documented hint
behaviour, never read from the report under test.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys

import dx12_contract_process
from verify_capture_telemetry import read_record
from verify_render_capture import load_png

REPORT = 'game-ui-contract-report.json'
WARP = 'Microsoft Basic Render Driver'
SCALES = (100, 200)
LOGICAL_SIZE = (480, 270)
ANCHOR = (240.0, 120.0)
INK_WINDOW = (90.0, 80.0, 390.0, 190.0)
CASES = (('idle', 0.0, False), ('half', 0.5, False), ('complete', 1.0, False), ('ammo-full', 0.0, True))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def is_gold(pixel):
    r, g, b = pixel[:3]
    return r >= 235 and 170 <= g <= 215 and b <= 95


def measure(image, scale):
    """Lit pixels, their bounds and gold sweep pixels left/right of the anchor."""
    axis = ANCHOR[0] * scale
    width, height = image.size
    pixels = image.load()
    lit = gold_left = gold_right = 0
    bounds = None
    for y in range(height):
        for x in range(width):
            p = pixels[x, y]
            if p[0] == 0 and p[1] == 0 and p[2] == 0:
                continue
            lit += 1
            if bounds is None:
                bounds = [x, y, x, y]
            else:
                bounds = [min(bounds[0], x), min(bounds[1], y), max(bounds[2], x), max(bounds[3], y)]
            if is_gold(p):
                if x + 0.5 < axis:
                    gold_left += 1
                else:
                    gold_right += 1
    return {'lit_pixels': lit, 'lit_bounds': bounds, 'gold_left': gold_left, 'gold_right': gold_right}


def check_case(case, ink, scale):
    bounds = ink['lit_bounds']
    require(bounds is not None and ink['lit_pixels'] > 0, f'{case}: capture is empty')
    window = [value * scale for value in INK_WINDOW]
    require(bounds[0] >= window[0] and bounds[1] >= window[1] and bounds[2] <= window[2] and bounds[3] <= window[3],
            f'{case}: lit bounds {bounds} escape {window}')
    gold = ink['gold_left'] + ink['gold_right']
    if case in ('idle', 'ammo-full'):
        require(gold == 0, f'{case}: no hold circle may be drawn, found {gold} gold pixels')
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
            require(images[a].tobytes() != images[b].tobytes(), f'{a} and {b} rendered identical pixels')


def check_scaling(one, two):
    a, b = one['lit_bounds'], two['lit_bounds']
    area = two['lit_pixels'] / max(one['lit_pixels'], 1)
    width = (b[2] - b[0] + 1) / (a[2] - a[0] + 1)
    require(3.0 <= area <= 5.0 and 1.8 <= width <= 2.2,
            f'200% capture is not a 2x rendering: area x{area:.2f}, width x{width:.2f}')


def validate_outputs(output):
    output = Path(output)
    report = read_record(output / REPORT)
    require(report.get('status') == 'passed' and report.get('native_execution') is True,
            'fixture report is not a native pass')
    require(report.get('requested') == 'dx12' and report.get('backend') == 'Dx12'
            and isinstance(report.get('adapter'), str) and report['adapter'].casefold() == WARP.casefold()
            and report.get('force_fallback_adapter') is True,
            'fixture report is not a DX12 WARP run')
    expected = {f'ammo-{case}-{percent}.png' for percent in SCALES for case, _, _ in CASES}
    files = {path.name for path in output.iterdir()}
    require(files == expected | {f'{name}.json' for name in expected} | {REPORT},
            'fixture output has missing or unexpected files')
    require(len(report.get('captures', [])) == len(expected), 'report must list every capture')
    per_scale = {}
    for percent in SCALES:
        scale = percent / 100
        extent = (LOGICAL_SIZE[0] * percent // 100, LOGICAL_SIZE[1] * percent // 100)
        inks, images = {}, {}
        for case, progress, full in CASES:
            name = f'ammo-{case}-{percent}.png'
            sidecar = read_record(output / f'{name}.json')
            require(sidecar.get('backend') == 'Dx12' and sidecar.get('case') == case
                    and sidecar.get('scale_percent') == percent and sidecar.get('ammo_full') is full,
                    f'{name}: sidecar identity mismatch')
            image = load_png(output / name, extent)
            ink = measure(image, scale)
            require(sidecar.get('ink') == ink, f'{name}: recorded ink differs from independent measurement')
            check_case(case, ink, scale)
            inks[case], images[case] = ink, image
        check_scale(inks, images)
        per_scale[percent] = inks
    for case, _, _ in CASES:
        check_scaling(per_scale[100][case], per_scale[200][case])
    return {'passed': True, 'captures': len(expected), 'elements_covered': ['ammo-hint'],
            'adapter': report['adapter'],
            'scope': 'Production ammo hint draw path on DX12 WARP; pause menu and updater panel pending export.'}


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

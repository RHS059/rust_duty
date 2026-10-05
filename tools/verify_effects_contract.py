#!/usr/bin/env python3
"""Independently validate the finalized effects_contract output evidence.

The fixed regions, fields and thresholds are transcribed from
examples/effects_contract.rs (SHA256
9baf9d95b2abe979048b95e7b6f1de37d39f17114323bff0b8dd4eeeeab57d9f).
No producer-selected probe bounds or statistics are trusted. This checker does
not execute a renderer: synthetic passing controls prove its discrimination,
not native DX12 execution. The runner owns freshness and process provenance.
"""

import argparse
import json
import os
from pathlib import Path

from run_renderer_contract import equal, literal, require
from verify_capture_telemetry import read_record
from verify_render_capture import load_png, near_color


REPORT = 'effects-contract-report.json'
EXTENT = (800, 600)
WARP = 'Microsoft Basic Render Driver'
TOLERANCE = 3
FLASH = (380, 250, 485, 350)
HALO = (445, 270, 480, 330)
SMOKE = (400, 255, 470, 315)
CASING = (150, 160, 290, 285)
MARKER = (610, 460, 730, 530)
CLEAR = (30, 30, 100, 100)
MARKER_RGBA = (32, 128, 224, 255)
BRASS_RGBA = (193, 140, 61, 255)
SCOPE = ('actual muzzle_fx public draw API through facade and headless DX12; '
         'effect visibility, additive emission, expiration and subsequent '
         'normal-geometry state; not window presentation, gameplay, artistic '
         'approval or cross-backend depth parity')
# json! converts f32 through serde_json::Value::from -> Number::from_f32.
# With pinned serde_json 1.0.151's default features, Number stores f as f64,
# then serializes that f64. This is the shortest f64 serialization of 0.1_f32,
# not a directly serialized f32's "0.1". SHELL_LIFE is exactly 5.0_f32.
AGED_SECONDS = 0.10000000149011612
CAPTURES = (
    ('barrel.png', 'barrel', 0.0),
    ('barrel-twice.png', 'barrel', 0.0),
    ('barrel-after-markers.png', 'barrel', 0.0),
    ('world-live.png', 'world-live', 0.0),
    ('world-live-after-markers.png', 'world-live', 0.0),
    ('world-aged.png', 'world-aged', AGED_SECONDS),
    ('world-aged-after-markers.png', 'world-aged', AGED_SECONDS),
    ('world-expired.png', 'world-expired', 5.0),
    ('world-expired-after-markers.png', 'world-expired', 5.0),
)


def _load_rgba8(path):
    image = load_png(path, EXTENT)  # Full decode, static frame, framing and CRCs.
    # General load_png converts modes; inspect the actual on-disk IHDR as well.
    with path.open('rb') as source:
        header = source.read(26)
    require(header[8:16] == b'\x00\x00\x00\x0dIHDR'
            and header[24:26] == b'\x08\x06',
            f'{path.name}: expected raw RGBA8 PNG')
    return image


def _exact(image, bounds, rgba, label):
    region = image.crop(bounds)
    require(all(near_color(p, rgba, TOLERANCE) for p in region.getdata()),
            f'{label}: fixed pixel probe failed')
    return {'label': label, 'pixel_bounds': list(bounds), 'expected_rgba': list(rgba),
            'matching_pixels': region.width * region.height, 'channel_tolerance': TOLERANCE}


def _emission(image, bounds, minimum):
    count = sum(p[0] >= 16 and p[3] == 0 for p in image.crop(bounds).getdata())
    require(count >= minimum,
            f'real effect emission: {count} zero-coverage red-emitting pixels; require {minimum}')
    return {'label': 'real-effect-zero-coverage-emission', 'pixel_bounds': list(bounds),
            'minimum_red': 16, 'expected_alpha': 0, 'matching_pixels': count,
            'minimum_pixels': minimum}


def _repeated(single, twice):
    unsaturated = 0
    checked = 0
    for before, after in zip(single.crop(FLASH).getdata(), twice.crop(FLASH).getdata()):
        require(before[3] == 0 and after[3] == 0,
                'barrel-only emission changed coverage alpha')
        unsaturated += 8 <= before[0] <= 100
        require(all(abs(after[c] - min(255, 2 * before[c])) <= TOLERANCE for c in range(3)),
                f'repeated real flash did not add radiance: first {before}, second {after}')
        checked += 1
    require(unsaturated >= 32,
            f'repeat invariant needs 32 nontrivial unsaturated pixels; got {unsaturated}')
    return {'label': 'repeat-real-flash-adds-radiance', 'pixel_bounds': list(FLASH),
            'equation': 'twice.rgb = min(255, 2 * once.rgb); both alpha = 0',
            'channel_tolerance': TOLERANCE, 'checked_pixels': checked,
            'unsaturated_pixels': unsaturated, 'minimum_unsaturated_pixels': 32}


def _smoke(image):
    count = 0
    for pixel in image.crop(SMOKE).getdata():
        expected = [(channel * pixel[3] + 127) // 255 for channel in (147, 158, 163)]
        if (20 <= pixel[3] <= 230 and pixel[2] > pixel[0]
                and all(abs(a - b) <= TOLERANCE for a, b in zip(pixel[:3], expected))):
            count += 1
    require(count >= 100, f'aged smoke: {count} translucent tint/coverage pixels; require 100')
    return {'label': 'unlit-aged-smoke-associated-tint', 'pixel_bounds': list(SMOKE),
            'source_rgb': [147, 158, 163], 'alpha_range': [20, 230],
            'matching_pixels': count, 'minimum_pixels': 100, 'channel_tolerance': TOLERANCE}


def _casing(image):
    count = sum(near_color(p, BRASS_RGBA, TOLERANCE) for p in image.crop(CASING).getdata())
    require(count >= 8, f'aged casing: {count} opaque brass pixels; require 8')
    return {'label': 'unlit-aged-casing-visible', 'pixel_bounds': list(CASING),
            'expected_rgba': list(BRASS_RGBA), 'matching_pixels': count,
            'minimum_pixels': 8, 'channel_tolerance': TOLERANCE}


def _expired(image):
    # Source exception is x=599..=740, y=449..=540 (inclusive); use exclusive
    # crop boundaries here. All four channels outside it must be exactly zero.
    # Pillow channel extrema inspect raw zero-alpha emission too, unlike an
    # alpha-composited view or RGBA getbbox's alpha-only default.
    checked = 0
    for bounds in ((0, 0, 800, 449), (0, 541, 800, 600),
                   (0, 449, 599, 541), (741, 449, 800, 541)):
        region = image.crop(bounds)
        require(all(extrema == (0, 0) for extrema in region.getextrema()),
                'expired effects leave pixels outside the fixed marker exception')
        checked += region.width * region.height
    return {'label': 'expired-effects-leave-no-pixels', 'checked_pixels': checked,
            'expected_rgba': [0, 0, 0, 0]}


def _verify_probes(image, filename, original):
    result = [_exact(image, CLEAR, (0, 0, 0, 0), 'untouched-clear')]
    if filename.endswith('-after-markers.png'):
        result.append(_exact(image, MARKER, MARKER_RGBA,
                             'normal-opaque-marker-replaces-background-and-occludes-later-far-marker'))
    elif filename in ('barrel.png', 'barrel-twice.png'):
        result.append(_emission(image, FLASH, 100))
        if filename == 'barrel-twice.png':
            result.append(_repeated(original, image))
    elif filename == 'world-live.png':
        result.append(_emission(image, HALO, 200))
    elif filename == 'world-aged.png':
        result.extend((_smoke(image), _casing(image)))
    elif filename == 'world-expired.png':
        result.append(_expired(image))
    else:
        raise ValueError(f'unknown effects capture: {filename}')
    return result


def validate_outputs(output):
    """Check all 19 fixed files and return JSON-safe content-only evidence."""
    output = Path(output)
    require(not output.is_symlink() and output.is_dir(),
            'effects output must be a real directory')
    expected = {REPORT} | {name + suffix for name, _, _ in CAPTURES for suffix in ('', '.json')}
    paths = list(output.iterdir())
    actual = {path.name for path in paths}
    require(actual == expected,
            f'effects output set differs: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}')
    for path in paths:
        require(not path.is_symlink() and path.is_file(),
                f'effects output is not a regular file: {path.name}')
    report = read_record(output / REPORT)
    fixed = {
        'schema_version': 1, 'status': 'passed', 'native_execution': True,
        'requested': 'dx12', 'backend': 'Dx12', 'adapter': WARP,
        'platform': 'windows', 'force_fallback_adapter': True,
        'shot': {'time': 12.5, 'spread_degrees': 0.75, 'caliber_mm': 5.56,
                 'initial_effect_seed_u32': 3787887164, 'muzzle': [0, 1, 0],
                 'barrel_forward': [1, 0, 0], 'barrel_right': [0, 0, 1],
                 'barrel_up': [0, 1, 0], 'carrier_velocity': [0, 0, 0]},
        'camera': {'position': [0, 1, 1], 'target': [0, 1, 0],
                   'fovy_degrees': 90, 'z_near': 0.01, 'z_far': 10},
        'scope': SCOPE,
    }
    require(report.keys() == set(fixed) | {'build_version', 'build_number', 'captures'},
            'effects report fields differ')
    literal({key: report[key] for key in fixed}, fixed, 'effects report')
    for key in ('build_version', 'build_number'):
        require(type(report[key]) is str and bool(report[key].strip()), f'effects report missing {key}')
    require(type(report['captures']) is list and len(report['captures']) == 9,
            'effects report must contain all 9 ordered captures')
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        import build_identity
        identity = build_identity.context()
        literal([report['build_version'], report['build_number']],
                [identity['version'], identity['build_number']], 'effects report CI build identity')

    original = None
    for (filename, scene, age), reported in zip(CAPTURES, report['captures']):
        metadata = read_record(output / (filename + '.json'))
        equal(reported, metadata, filename + ': report/sidecar')
        expected_metadata = {
            'schema_version': 1, 'fixture_case': scene, 'filename': filename,
            'requested': 'dx12', 'backend': 'Dx12', 'adapter': WARP,
            'force_fallback_adapter': True, 'width': 800, 'height': 600,
            'row_origin': 'top-left', 'alpha_representation': 'raw-associated-emissive-rgba8',
            'diagnostic_raw_target': True, 'age_seconds': age,
            'caller_camera_model_restored': True,
        }
        require(metadata.keys() == set(expected_metadata) | {'probes'}, f'{filename}: metadata fields differ')
        literal({key: metadata[key] for key in expected_metadata}, expected_metadata, filename)
        image = _load_rgba8(output / filename)
        if filename == 'barrel.png':
            original = image
        probes = _verify_probes(image, filename, original)
        literal(metadata['probes'], probes, filename + '.probes')
    return {'schema': 'rust-duty-effects-contract-validation/v1', 'passed': True,
            'backend': 'Dx12', 'adapter': WARP, 'captures': 9,
            'build_version': report['build_version'], 'build_number': report['build_number'], 'scope': SCOPE}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args(argv)
    try:
        result = validate_outputs(args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f'Effects output validation failed: {error}\n')
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

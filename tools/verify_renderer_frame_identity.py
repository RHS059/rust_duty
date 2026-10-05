"""Independently validate the finalized renderer_frame_identity output contract.

The authored constants below were read from renderer_frame_identity.rs SHA256
064df4fff07c6276b34bc69b1ff66673e1f806a6c135f105abd0a629668602b7.
This module never launches a renderer. It checks files, not process provenance;
the process owner must separately require fresh Windows DX12/WARP execution and
the actual FXC initialization stderr. Synthetic controls are not native proof.
"""

import os
from pathlib import Path

from run_dx12_smoke import WARP_ADAPTER
from run_renderer_contract import equal, literal, require
from verify_capture_telemetry import read_record
from verify_render_capture import load_png


REPORT = 'renderer-frame-identity-report.json'
SCOPE = ('headless production-recorder DX12 frame identity; not authored '
         'pose-to-pixel parity, window presentation, gameplay or artistic approval')
COMPILER_PROVENANCE = ('require renderer initialization stderr: '
                       'renderer dx12_shader_compiler=Fxc')
EXTENT = (65, 49)
STAGES = ('early-target', 'late-target', 'main')
TOLERANCE = 2
CHECKED_PIXELS = 1421
# Exclusive pixel bounds, independent of the producer's reported probes.
BOUNDS = ((5, 5, 26, 19), (39, 5, 60, 19),
          (5, 30, 26, 44), (39, 30, 60, 44), (30, 0, 35, 49))
FRAMES = (
    (0, (255, 0, 0, 255), 3, (255, 255, 0, 255)),
    (2, (0, 255, 0, 255), 1, (255, 0, 255, 255)),
    (1, (0, 0, 255, 255), 2, (0, 255, 255, 255)),
    (3, (255, 255, 0, 255), 0, (0, 0, 255, 255)),
    (0, (255, 0, 255, 255), 2, (0, 255, 0, 255)),
    (2, (0, 255, 255, 255), 3, (255, 0, 0, 255)),
)


def _specifications():
    result = []
    for frame, (first_slot, first, second_slot, second) in enumerate(FRAMES):
        for stage in STAGES:
            background = (0, 0, 0, 255 if stage == 'main' else 0)
            colors = [background] * 5
            colors[first_slot] = first
            if stage != 'early-target':
                colors[second_slot] = second
            result.append({
                'filename': f'frame-{frame:02}-{stage}.png',
                'frame': frame, 'stage': stage, 'width': 65, 'height': 49,
                'row_origin': 'top-left',
                'expected_probes': [[list(bounds), list(color)]
                                    for bounds, color in zip(BOUNDS, colors)],
                'checked_pixels': CHECKED_PIXELS, 'channel_tolerance': TOLERANCE,
                'other_identities_rejected': 17,
            })
    return result


def _verify_pixels(image, specification):
    """Check all fixed probe pixels, never coordinates/colors from the report."""
    name = specification['filename']
    require(image.size == EXTENT, f'{name}: capture extent differs')
    if specification['stage'] == 'main':
        require(image.getchannel('A').getextrema() == (255, 255),
                f'{name}: main capture contains nonopaque alpha')
    checked = 0
    pixels = image.load()
    for bounds, expected in specification['expected_probes']:
        x0, y0, x1, y1 = bounds
        for y in range(y0, y1):
            for x in range(x0, x1):
                actual = pixels[x, y]
                require(all(abs(a - e) <= TOLERANCE for a, e in zip(actual, expected)),
                        f'{name}: pixel probe at ({x},{y}) expected {expected}, got {actual}')
                checked += 1
    return checked


def _load_rgba8(path):
    image = load_png(path, EXTENT)
    # Pillow converts 16-bit/channel RGBA and palette inputs while decoding.
    # Check the actual PNG IHDR as well as the CRC-verified, fully decoded bytes.
    with path.open('rb') as source:
        header = source.read(26)
    require(header[8:16] == b'\x00\x00\x00\x0dIHDR'
            and header[24:26] == b'\x08\x06',
            f'{path.name}: capture is not RGBA8 PNG')
    return image


def validate_outputs(output):
    """Return a JSON-safe output-only summary, or raise on any mismatch.

Only the fixed 18 images and producer report are accepted; there are no primary
sidecars. All images are reopened after execution, including earlier frames.
The returned counts are recomputed from independent expectations and PNG bytes.
"""
    output = Path(output)
    require(not output.is_symlink() and output.is_dir(),
            'frame identity output must be a real directory')
    specifications = _specifications()
    expected_files = {REPORT} | {item['filename'] for item in specifications}
    paths = list(output.iterdir())
    actual_files = {path.name for path in paths}
    require(actual_files == expected_files,
            f'frame identity output set differs: missing={sorted(expected_files - actual_files)}, '
            f'extra={sorted(actual_files - expected_files)}')
    for path in paths:
        require(not path.is_symlink() and path.is_file(),
                f'frame identity output is not a regular file: {path.name}')

    report = read_record(output / REPORT)
    fixed = {
        'schema_version': 1, 'status': 'passed', 'native_execution': True,
        'requested': 'dx12', 'backend': 'Dx12', 'force_fallback_adapter': True,
        'platform': 'windows', 'compiler_provenance': COMPILER_PROVENANCE,
        'frame_count': 6, 'capture_count': 18, 'cross_identity_rejections': 306,
        'rechecked_after_all_submissions': True, 'persistent_renderer': True,
        'persistent_target': True, 'scope': SCOPE,
    }
    require(report.keys() == set(fixed) | {'adapter', 'build_version', 'build_number', 'captures'},
            'frame identity report fields differ')
    literal({key: report[key] for key in fixed}, fixed, 'frame identity report')
    require(type(report['adapter']) is str
            and report['adapter'].casefold() == WARP_ADAPTER.casefold(),
            'frame identity report must identify WARP')
    for key in ('build_version', 'build_number'):
        require(type(report[key]) is str and bool(report[key].strip()),
                f'frame identity report missing {key}')
    equal(report['captures'], specifications, 'frame identity report.captures')

    if os.environ.get('GITHUB_ACTIONS') == 'true':
        import build_identity
        identity = build_identity.context()
        literal([report['build_version'], report['build_number']],
                [identity['version'], identity['build_number']],
                'frame identity report CI build identity')

    checked_pixels = 0
    cross_identity_rejections = 0
    for index, specification in enumerate(specifications):
        image = _load_rgba8(output / specification['filename'])
        checked = _verify_pixels(image, specification)
        equal(checked, CHECKED_PIXELS, specification['filename'] + '.checked_pixels')
        checked_pixels += checked
        rejected = 0
        for other_index, other in enumerate(specifications):
            if index == other_index:
                continue
            try:
                _verify_pixels(image, other)
            except ValueError:
                rejected += 1
            else:
                raise ValueError(f"{specification['filename']}: also passes as "
                                 f"{other['filename']}; identity is ambiguous")
        equal(rejected, 17, specification['filename'] + '.other_identities_rejected')
        cross_identity_rejections += rejected
    equal(cross_identity_rejections, 306, 'frame identity cross-identity rejections')
    return {
        'schema': 'rust-duty-renderer-frame-identity-validation/v1', 'passed': True,
        'backend': 'Dx12', 'adapter': report['adapter'], 'frame_count': 6,
        'capture_count': len(specifications), 'checked_pixels': checked_pixels,
        'cross_identity_rejections': cross_identity_rejections,
        'build_version': report['build_version'], 'build_number': report['build_number'],
        'scope': SCOPE,
    }

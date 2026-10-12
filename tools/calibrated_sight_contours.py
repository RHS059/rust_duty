#!/usr/bin/env python3
"""Historical/prototype contour measurements, not a native acceptance gate.

Locate background-connected sight openings over the whole neutral 960x540
reference image. Never read a calibration target during localization. A unique
large/small opening constellation gives candidate contour centers, not semantic
proof that a candidate is the requested named landmark. No source image changes.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from PIL import Image, ImageChops

BACKGROUND = (36, 48, 61)
EXTENT = (960, 540)
TOLERANCE = 8  # Existing reference-capture clear-color tolerance.


def openings(image, tolerance=TOLERANCE):
    """Find bounded background components; omit only the known witness rectangle."""
    if image.size != EXTENT:
        raise ValueError('prototype requires unscaled 960x540 pixels')
    rgb = image.convert('RGB')
    channels = ImageChops.difference(rgb, Image.new('RGB', image.size, BACKGROUND)).split()
    difference = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    background = bytearray(difference.point(lambda value: int(value <= tolerance)).tobytes())
    width, height = image.size
    # Current acceptance validates this area independently as a frame witness.
    # In historical inputs this also excludes a fixed empty corner, never a sight.
    for y in range(22):
        background[y * width:y * width + 64] = bytes(64)
    seen = bytearray(width * height)
    result = []
    for start, value in enumerate(background):
        if not value or seen[start]:
            continue
        stack = [start]
        seen[start] = 1
        area = 0
        left = right = start % width
        top = bottom = start // width
        border = False
        while stack:
            index = stack.pop()
            y, x = divmod(index, width)
            area += 1
            left, right = min(left, x), max(right, x)
            top, bottom = min(top, y), max(bottom, y)
            border |= x == 0 or y == 0 or x == width - 1 or y == height - 1
            for other in (index - width if y else -1,
                          index + width if y + 1 < height else -1,
                          index - 1 if x else -1,
                          index + 1 if x + 1 < width else -1):
                if other >= 0 and background[other] and not seen[other]:
                    seen[other] = 1
                    stack.append(other)
        if border or area < 3:
            continue
        w, h = right - left + 1, bottom - top + 1
        if min(w, h) < 2:
            continue
        # These are explicit prototype morphology filters, not calibration gates.
        # Tiny openings have coarse anisotropic pixel quantization.
        aspect_limit = 2.5 if area < 30 else 1.5
        if max(w / h, h / w) > aspect_limit or area / (w * h) < 0.4:
            continue
        result.append({'background_area_px': area, 'bounds_inclusive': [left, top, right, bottom],
                       'contour_midrange_center': [(left + right) / 2, (top + bottom) / 2],
                       'method': 'midpoint of bounded background contour extrema',
                       'quantization_only_bound_px': [0.5, 0.5]})
    return sorted(result, key=lambda row: row['background_area_px'], reverse=True)


def constellation(candidates, pose):
    if pose not in ('hip', 'ads'):
        raise ValueError('pose must be hip or ads')
    pairs = []
    for near in candidates:
        for far in candidates:
            if near is far or near['background_area_px'] < 4 * far['background_area_px']:
                continue
            n, f = near['contour_midrange_center'], far['contour_midrange_center']
            left, top, right, bottom = near['bounds_inclusive']
            if pose == 'ads':
                matches = left < f[0] < right and top < f[1] < bottom
            else:
                # The inspected unchanged right-handed source has a small far
                # opening left of the large near surround. No target X/Y used.
                matches = f[0] < left and abs(f[1] - n[1]) <= 2 * (bottom - top + 1)
            if matches:
                pairs.append({'near_surround_candidate': near, 'far_opening_candidate': far})
    return pairs


def measure(path, pose):
    path = Path(path)
    before = path.read_bytes()
    with Image.open(path) as source:
        # Inspect the decoder's header before allocating/decompressing pixels.
        if source.format != 'PNG' or source.size != EXTENT:
            raise ValueError('prototype needs a 960x540 PNG')
        source.load()
        image = source.convert('RGB')
    candidates = openings(image)
    pairs = constellation(candidates, pose)
    report = {'schema': 'rust-duty-historical-sight-contour-prototype/v1',
              'image': str(path), 'sha256': hashlib.sha256(before).hexdigest(),
              'pose': pose, 'candidate_components': candidates,
              'pair_count': len(pairs), 'semantic_identity_verified': False,
              'native_acceptance': False, 'status': 'unmeasurable' if not pairs else 'ambiguous'}
    if len(pairs) == 1:
        report.update(status='unique-constellation-candidate', candidates=pairs[0])
        sensitivity = []
        for tolerance in (6, 8, 10):
            alternative = constellation(openings(image, tolerance), pose)
            sensitivity.append({'clear_tolerance': tolerance, 'pair_count': len(alternative),
                                'centers': {key: value['contour_midrange_center']
                                            for key, value in alternative[0].items()} if len(alternative) == 1 else None})
        report['threshold_sensitivity'] = sensitivity
        report['uncertainty_note'] = ('0.5px is quantization only, not a total error guarantee. '
                                      'Threshold sensitivity, contour occlusion and semantic identity '
                                      'must be established on source-bound native controls.')
    if path.read_bytes() != before:
        raise ValueError('input changed during read-only measurement')
    return report


def calibration_comparison(measured_center, target):
    """Comparison is separate; target coordinates never enter localization."""
    if len(measured_center) != 2 or len(target) != 2 or not all(math.isfinite(v) for v in (*measured_center, *target)):
        raise ValueError('need finite measured and target X/Y')
    delta = [a - b for a, b in zip(measured_center, target)]
    return {'delta_xy': delta, 'within_original_inclusive_4px': all(abs(v) <= 4 for v in delta)}


def position_delta(first, second):
    return [a - b for a, b in zip(first, second)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--pose', required=True, choices=('hip', 'ads'))
    args = parser.parse_args()
    print(json.dumps(measure(args.image, args.pose), indent=2, allow_nan=False))


if __name__ == '__main__':
    main()

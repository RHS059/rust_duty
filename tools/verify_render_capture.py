#!/usr/bin/env python3
"""Validate PNG breakage, never pixel parity between renderers.

Example (background must match the capture's explicit clear color):
  python tools/verify_render_capture.py frame.png --width 960 --height 540 \
      --background 0,0,0,255 --min-coverage 0.01

Optional --orientation quadrants-v1 is a dedicated fixture contract, NOT an
assertion that any existing renderer/capture mode currently emits this fixture.
In top-left-origin pixel coordinates, draw opaque red, green, blue and yellow
patches respectively in the top-left, top-right, bottom-left and bottom-right.
Each patch must fill at least 90% of its inset probe rectangle: x/y ranges
[10%,40%) or [60%,90%) of the requested extent, with endpoints rounded down.
Use clear background elsewhere. Colors are RGBA (255,0,0,255), (0,255,0,255),
(0,0,255,255), (255,255,0,255). Per-channel tolerance defaults to 8 (maximum 32).
The four unique colors discriminate every rotation/reflection, even on squares.

Foreground means alpha > 0 AND at least one RGBA channel differs from the
explicit background by more than tolerance. Uniform images always fail, even
when their color is different from the declared background. Coverage alone
cannot prove scene correctness; only the optional fixture checks orientation.
No sidecars, renderer execution, authored assets, or output writes are involved.
"""

import argparse
import json
import math
from pathlib import Path
import sys

from PIL import Image


class CaptureError(ValueError):
    """A requested capture contract was not satisfied."""


def positive_integer(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('must be a positive integer')
    return number


def coverage_fraction(value):
    number = float(value)
    if not math.isfinite(number) or not 0 < number <= 1:
        raise argparse.ArgumentTypeError('must be finite and in (0, 1]')
    return number


def color_tolerance(value):
    number = int(value)
    if not 0 <= number <= 32:
        raise argparse.ArgumentTypeError('must be an integer in [0, 32]')
    return number


def rgba_color(value):
    try:
        color = tuple(int(part) for part in value.split(','))
    except ValueError as error:
        raise argparse.ArgumentTypeError('expected R,G,B,A bytes') from error
    if len(color) != 4 or any(not 0 <= channel <= 255 for channel in color):
        raise argparse.ArgumentTypeError('expected R,G,B,A bytes')
    return color


def near_color(actual, expected, tolerance):
    return all(abs(a - b) <= tolerance for a, b in zip(actual, expected))


def load_png(path, extent):
    # verify() checks PNG integrity/CRC before a separate full decode. Neither
    # filename suffix nor header alone establishes that this is a valid PNG.
    try:
        with Image.open(path) as source:
            if source.format != 'PNG':
                raise CaptureError('expected PNG format')
            if source.size != extent:
                raise CaptureError(f'wrong extent: expected {extent}, got {source.size}')
            if getattr(source, 'n_frames', 1) != 1:
                raise CaptureError('expected one static PNG frame')
            source.verify()
        with Image.open(path) as source:
            source.load()
            return source.convert('RGBA')
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as error:
        raise CaptureError(f'{path}: {error}') from error


def verify(path, extent, background, min_coverage, tolerance, orientation):
    image = load_png(path, extent)
    extrema = image.getextrema()
    if all(low == high for low, high in extrema):
        raise CaptureError('uniform image: no rendered structure')
    foreground = sum(pixel[3] > 0 and not near_color(pixel, background, tolerance)
                     for pixel in image.getdata())
    coverage = foreground / (image.width * image.height)
    if coverage < min_coverage:
        raise CaptureError(f'foreground coverage {coverage:.6f} below {min_coverage:.6f}')
    probes = []
    if orientation:
        patches = [('top-left', 1, 1, (255, 0, 0, 255)),
                   ('top-right', 6, 1, (0, 255, 0, 255)),
                   ('bottom-left', 1, 6, (0, 0, 255, 255)),
                   ('bottom-right', 6, 6, (255, 255, 0, 255))]
        for name, x, y, color in patches:
            box = (image.width * x // 10, image.height * y // 10,
                   image.width * (x + 3) // 10, image.height * (y + 3) // 10)
            if box[0] == box[2] or box[1] == box[3]:
                raise CaptureError('extent too small for orientation probe rectangles')
            region = image.crop(box)
            fraction = sum(near_color(pixel, color, tolerance)
                           for pixel in region.getdata()) / (region.width * region.height)
            if fraction < 0.9:
                raise CaptureError(f'orientation {name}: expected {color}; '
                                   f'matching coverage {fraction:.6f} below 0.9')
            probes.append({'region': name, 'matching_coverage': fraction})
    return {'schema': 'rust-duty-render-capture-verification/v1', 'passed': True,
            'capture': str(path), 'width': image.width, 'height': image.height,
            'foreground_coverage': coverage, 'orientation': orientation,
            'probes': probes}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--width', type=positive_integer, required=True)
    parser.add_argument('--height', type=positive_integer, required=True)
    parser.add_argument('--background', type=rgba_color, required=True)
    parser.add_argument('--min-coverage', type=coverage_fraction, required=True)
    parser.add_argument('--color-tolerance', type=color_tolerance, default=8)
    parser.add_argument('--orientation', choices=['quadrants-v1'])
    args = parser.parse_args(argv)
    try:
        report = verify(args.capture, (args.width, args.height), args.background,
                        args.min_coverage, args.color_tolerance, args.orientation)
    except CaptureError as error:
        print(f'render capture validation failed: {error}', file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())

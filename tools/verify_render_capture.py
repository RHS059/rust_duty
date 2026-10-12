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
when their color is different from the declared background. Near-uniform images
also fail the same coverage threshold against their own median color. Complete
PNG framing and all chunk CRCs, including IEND, are required. Coverage alone
cannot prove scene correctness; only the optional fixture checks orientation.
No sidecars, renderer execution, authored assets, or output writes are involved.
"""

import argparse
import json
import math
from pathlib import Path
import sys
import zlib

from PIL import Image, ImageChops, ImageStat


class CaptureError(ValueError):
    """A requested capture contract was not satisfied."""


class CaptureStructureError(CaptureError):
    """Decoded pixels failed only generic foreground/structure requirements."""


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


def _verify_png_framing(path):
    # Pillow permits a missing/truncated IEND CRC. Require the complete stream,
    # including every chunk's CRC and no trailing bytes after the empty IEND.
    with Path(path).open('rb') as source:
        if source.read(8) != b'\x89PNG\r\n\x1a\n':
            raise CaptureError('expected PNG format')
        while True:
            header = source.read(8)
            if len(header) != 8:
                raise CaptureError('truncated PNG chunk or missing IEND')
            length = int.from_bytes(header[:4], 'big')
            kind = header[4:]
            crc = zlib.crc32(kind)
            remaining = length
            while remaining:
                block = source.read(min(remaining, 65536))
                if not block:
                    raise CaptureError('truncated PNG chunk data')
                crc = zlib.crc32(block, crc)
                remaining -= len(block)
            checksum = source.read(4)
            if len(checksum) != 4:
                raise CaptureError('truncated PNG chunk CRC')
            if int.from_bytes(checksum, 'big') != crc:
                raise CaptureError('invalid PNG chunk CRC')
            if kind == b'IEND':
                if length != 0 or source.read(1):
                    raise CaptureError('invalid PNG IEND or trailing bytes')
                return


def load_png(path, extent):
    # verify() checks PNG integrity/CRC before a separate full decode. Neither
    # filename suffix nor header alone establishes that this is a valid PNG.
    try:
        _verify_png_framing(path)
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


def _foreground_count(image, background, tolerance):
    # The same per-channel predicate as near_color, evaluated by Pillow so a
    # complete sequence can validate every frame without Python pixel loops.
    difference = ImageChops.difference(image, Image.new('RGBA', image.size, background))
    changed = Image.new('L', image.size)
    for channel in difference.split():
        changed = ImageChops.lighter(changed, channel.point(lambda value: 255 if value > tolerance else 0))
    visible = image.getchannel('A').point(lambda value: 255 if value > 0 else 0)
    return ImageChops.multiply(changed, visible).histogram()[255]


def verify(path, extent, background, min_coverage, tolerance, orientation):
    image = load_png(path, extent)
    extrema = image.getextrema()
    if all(low == high for low, high in extrema):
        raise CaptureStructureError('uniform image: no rendered structure')
    foreground = _foreground_count(image, background, tolerance)
    coverage = foreground / (image.width * image.height)
    if coverage < min_coverage:
        raise CaptureStructureError(f'{path}: foreground coverage {coverage:.6f} below {min_coverage:.6f}')
    # Independently reject near-uniform output against its own median color.
    # This catches a changed clear encoding/color plus sparse noise, rather
    # than accepting the entire wrong-colored background as scene coverage.
    structure = _foreground_count(image, tuple(ImageStat.Stat(image).median), tolerance)
    if structure / (image.width * image.height) < min_coverage:
        raise CaptureStructureError('near-uniform image: insufficient rendered structure')
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

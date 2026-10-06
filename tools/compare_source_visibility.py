#!/usr/bin/env python3
"""Compare conditional source obligations; never grants migration acceptance.

The caller must independently bind the certificate implementation, original
companions, manifest/settings, executable and capture invocation. Arithmetic,
raster and fragment profiles in the source header remain explicit assumptions.
The existing all-frame, world/finite, identity, witness, telemetry and pair
validators are separate requirements and are not weakened or called here.
"""
from PIL import Image, ImageChops

EXTENT = (960, 540)
BACKGROUND = (36, 48, 61, 255)
TOLERANCE = 8


def decode_runs(runs, count):
    if not isinstance(runs, list):
        raise ValueError('source runs must be a list')
    mask = bytearray(EXTENT[0] * EXTENT[1])
    end = -1
    for run in runs:
        if (not isinstance(run, list) or len(run) != 2
                or any(type(v) is not int for v in run)):
            raise ValueError('source run must contain two integers')
        start, length = run
        if start <= end or length <= 0 or start + length > len(mask):
            raise ValueError('source runs overlap, are noncanonical, or exceed extent')
        mask[start:start + length] = b'\xff' * length
        end = start + length
    if type(count) is not int or count != mask.count(255):
        raise ValueError('source sample count differs from runs')
    return Image.frombytes('L', EXTENT, bytes(mask))


def compare(image, frame):
    """Return only whether this image meets the supplied source obligations."""
    if image.size != EXTENT or image.mode != 'RGBA':
        raise ValueError('expected decoded RGBA image at source extent')
    required = decode_runs(frame['required_contrast_runs'], frame['required_contrast_samples'])
    possible = decode_runs(frame['possible_support_runs'], frame['possible_samples'])
    if ImageChops.subtract(required, possible).getbbox():
        raise ValueError('required source samples exceed possible support')
    if frame['unsupported_clip_triangles'] != 0 or frame['possible_support_complete'] is not True:
        raise ValueError('source clipping remains unresolved')
    if frame['unclassified_triangles'] and not required.getbbox():
        raise ValueError('source visibility remains unresolved')
    if not frame['unclassified_triangles'] and possible.getbbox():
        raise ValueError('expected-empty source has nonempty possible support')
    witness = Image.new('L', EXTENT)
    witness.paste(255, (0, 0, 64, 22))
    if ImageChops.multiply(required, witness).getbbox() or ImageChops.multiply(possible, witness).getbbox():
        raise ValueError('source samples overlap the independently checked witness')
    difference = ImageChops.difference(image, Image.new('RGBA', EXTENT, BACKGROUND))
    foreground = Image.new('L', EXTENT)
    for channel in difference.split()[:3]:
        foreground = ImageChops.lighter(foreground, channel.point(lambda v: 255 if v > TOLERANCE else 0))
    # Expected source actors and the source clear target are opaque. A lost
    # alpha channel cannot masquerade as valid contrast or valid background.
    if image.getchannel('A').getextrema() != (255, 255):
        raise ValueError('source target opacity differs')
    missing = ImageChops.subtract(required, foreground)
    if missing.getbbox():
        raise ValueError(f'missing source-derived contrast at {missing.getbbox()}')
    unexpected = ImageChops.subtract(foreground, ImageChops.lighter(possible, witness))
    if unexpected.getbbox():
        raise ValueError(f'foreground outside possible source support at {unexpected.getbbox()}')
    return {'source_obligations_match': True,
            'required_contrast_samples': frame['required_contrast_samples'],
            'possible_samples': frame['possible_samples'],
            'native_profile_binding_verified': False, 'acceptance_verdict': None}

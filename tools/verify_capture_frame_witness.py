"""Independently bind an opt-in rendered marker to a verified capture invocation.

The caller supplies the expected index and capture identity from its verified
invocation. Neither expectation may be learned from this PNG or its sidecar.
Ordinary unmarked captures are not changed by this read-only module.

The physical marker is 64x22 at (0,0): two rows of red/blue half-width header,
then 320 LSB-first bits in 32 columns of opaque 2x2 black/white cells. Payload:
little-endian u32 frame index, its u32 complement, and 32 identity bytes.
This binds the rendered witness; it does not certify scene semantics or trust
a producer that deliberately forges both the scene and its witness.
"""

import hashlib
import json
from pathlib import Path
import re

from PIL import Image

from verify_render_capture import load_png


SCHEMA = 'rust-duty-capture-frame-witness/v1'
MARKER_SIZE = (64, 22)
RGB_TOLERANCE = 8
CONTEXT_KEYS = {'source_commit', 'exe_sha256', 'run_id', 'run_attempt', 'scenario', 'backend'}
WITNESS_KEYS = {'schema', 'frame_index', 'capture_identity'}


class WitnessError(ValueError):
    """The marker, metadata, or independently supplied expectation is invalid."""


def _require(condition, message):
    if not condition:
        raise WitnessError(message)


def _index(value, label):
    _require(type(value) is int and 0 <= value <= 0xffffffff, f'{label} must be a u32 integer')
    return value


def _hex(value, size, label):
    _require(type(value) is str and re.fullmatch(f'[0-9a-f]{{{size}}}', value) is not None,
             f'{label} must be {size} lowercase hexadecimal characters')
    return value


def capture_identity(context):
    """SHA256 of canonical JSON for an independently verified invocation context.

    Exactly six fields are required. SHA strings are lowercase; run_id and
    run_attempt are canonical positive decimal u64 strings. Scenario is a
    nonempty trimmed string of at most 128 characters without control characters;
    backend is OpenGl or Dx12. Canonical bytes
    use sorted keys, compact separators, UTF-8, and unescaped Unicode.
    This function validates the shape, not the provenance, of the supplied data.
    """
    _require(type(context) is dict and set(context) == CONTEXT_KEYS,
             'capture context must contain exactly the six invocation fields')
    _hex(context['source_commit'], 40, 'source_commit')
    _hex(context['exe_sha256'], 64, 'exe_sha256')
    for key in ('run_id', 'run_attempt'):
        value = context[key]
        _require(type(value) is str and re.fullmatch('[1-9][0-9]{0,19}', value) is not None
                 and int(value) <= 0xffffffffffffffff, f'{key} must be a positive canonical decimal u64 string')
    value = context['scenario']
    _require(type(value) is str and 0 < len(value) <= 128 and value == value.strip()
             and all(ord(c) >= 32 and ord(c) != 127 for c in value),
             'scenario must be a trimmed 1–128 character string without control characters')
    _require(type(context['backend']) is str and context['backend'] in ('OpenGl', 'Dx12'),
             'backend must be OpenGl or Dx12')
    try:
        canonical = json.dumps(context, sort_keys=True, separators=(',', ':'),
                               ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, UnicodeError) as error:
        raise WitnessError(f'invalid capture context encoding: {error}') from error
    return hashlib.sha256(canonical).hexdigest()


def _image(path):
    path = Path(path)
    _require(not path.is_symlink() and path.is_file(), f'{path}: witness PNG must be a regular non-link file')
    try:
        with path.open('rb') as stream:
            header = stream.read(26)
        _require(len(header) == 26 and header[:8] == b'\x89PNG\r\n\x1a\n'
                 and header[12:16] == b'IHDR' and header[24:26] == bytes((8, 6)),
                 f'{path}: witness PNG must be stored as RGBA8')
        with Image.open(path) as source:
            extent = source.size
        _require(extent[0] >= MARKER_SIZE[0] and extent[1] >= MARKER_SIZE[1],
                 f'{path}: image is smaller than the 64x22 witness')
        image = load_png(path, extent)
        _require(image.getextrema()[3] == (255, 255), f'{path}: witness PNG alpha must be 255 everywhere')
        return image
    except WitnessError:
        raise
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as error:
        raise WitnessError(f'{path}: {error}') from error


def _near(pixel, color):
    return pixel[3] == 255 and all(abs(pixel[channel] - color[channel]) <= RGB_TOLERANCE
                                   for channel in range(3))


def decode(path):
    """Decode every marker pixel, without treating the decoded identity as trusted."""
    image = _image(path)
    pixels = image.load()
    for y in range(2):
        for x in range(64):
            expected = (255, 0, 0) if x < 32 else (0, 0, 255)
            _require(_near(pixels[x, y], expected), f'invalid witness header pixel ({x},{y})')
    payload = bytearray(40)
    for bit in range(320):
        x, y = (bit % 32) * 2, 2 + (bit // 32) * 2
        cell = [pixels[x + dx, y + dy] for dy in range(2) for dx in range(2)]
        zero = all(_near(pixel, (0, 0, 0)) for pixel in cell)
        one = all(_near(pixel, (255, 255, 255)) for pixel in cell)
        _require(zero != one, f'invalid or ambiguous witness cell {bit}')
        if one:
            payload[bit // 8] |= 1 << (bit % 8)
    index = int.from_bytes(payload[:4], 'little')
    complement = int.from_bytes(payload[4:8], 'little')
    _require(complement == index ^ 0xffffffff, 'witness frame-index complement does not match')
    return {'schema': SCHEMA, 'frame_index': index, 'capture_identity': payload[8:].hex()}


def verify(path, metadata, expected_frame_index, expected_capture_identity):
    """Require PNG and metadata to agree with independently supplied expectations."""
    expected_index = _index(expected_frame_index, 'expected_frame_index')
    expected_identity = _hex(expected_capture_identity, 64, 'expected_capture_identity')
    _require(type(metadata) is dict and type(metadata.get('frame_witness')) is dict,
             'primary metadata must contain frame_witness')
    witness = metadata['frame_witness']
    _require(set(witness) == WITNESS_KEYS and witness.get('schema') == SCHEMA,
             'frame_witness has an invalid schema or fields')
    _index(witness['frame_index'], 'metadata frame_index')
    _hex(witness['capture_identity'], 64, 'metadata capture_identity')
    _require(witness['frame_index'] == expected_index, 'metadata frame index differs from verified invocation')
    _require(witness['capture_identity'] == expected_identity, 'metadata capture identity differs from verified invocation')
    decoded = decode(path)
    _require(decoded['frame_index'] == expected_index, 'PNG frame index differs from verified invocation')
    _require(decoded['capture_identity'] == expected_identity, 'PNG capture identity differs from verified invocation')
    return {'passed': True, **decoded}

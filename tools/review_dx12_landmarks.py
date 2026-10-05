#!/usr/bin/env python3
"""Fail-closed review of explicitly measured DX12 sight-landmark pixels.

This tool never detects, projects, infers or fills in a landmark position. It
only checks coordinates a named reviewer measured by hand (or with a separately
named raw-pixel tool) on an exact raw 960x540 capture, then compares them with
the documented calibration in docs/VISUAL_REFERENCE_MATCH.md:

- ADS rear-aperture center (480,270)
- Hip front-sight guard   (526,280)

Both absolute axis deltas must be <= 4 px. Every annotation is bound to the PNG
SHA-256, its 960x540 extent, its frame identity and its landmark identity. Any
missing, non-finite, out-of-bounds, duplicated, contradictory or unknown input
is rejected and the whole review stays open; there is no partial pass.
Unmeasurable or uncertain landmarks are recorded but never accepted. Raw images
are opened read-only and their hashes are re-checked after decoding. PNG framing
(including every chunk CRC) is checked before Pillow decode. Sidecars that mark
raw render targets, or that carry wrongly typed diagnostic_raw_target / ads
fields, are rejected, whether they come from --frames or from the annotated
image's own sibling <image>.json. Type and bounds errors become invalid reports
(exit 2).

A within-tolerance result closes only the measured-pixel comparison. Human M2
capture approval and M4 hardware playtest approval always remain open here.
See docs/DX12_LANDMARK_MEASUREMENT.md.
"""
import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sys

from PIL import Image

from verify_render_capture import CaptureError, _verify_png_framing

MEASUREMENT_SCHEMA = 'rust-duty-dx12-landmark-measurements/v1'
REPORT_SCHEMA = 'rust-duty-dx12-landmark-review/v1'
EXTENT = (960, 540)
TOLERANCE_PX = 4
LANDMARKS = {
    'ads-rear-aperture-center': {'pose': 'ads', 'feature': 'rear-aperture center',
                                 'target': (480, 270)},
    'hip-front-sight-guard': {'pose': 'hip', 'feature': 'front-sight guard',
                              'target': (526, 280)},
}
# Documented confusables. Naming one of these is an identity error, not an alias.
CONFUSABLE_LANDMARKS = {
    'ads-aiming-post': 'the ADS aiming post is not the rear aperture or the hip guard',
    'ads-front-post': 'the ADS front post is not the rear aperture or the hip guard',
    'hip-rear-aperture-center': 'the hip rear aperture (~625,293) is not the hip front-sight guard',
    'crosshair': 'a displayed crosshair is not a measured sight feature',
    'near-central-post-tip': 'historical projection feature; not a calibrated landmark',
    'far-aperture': 'historical projection feature; not a calibrated landmark',
}
BACKENDS = ('dx12', 'legacy')
# Capture sidecar labels from the renderer contract. Landmark measurement accepts
# only opaque display images; raw-associated targets are never landmark inputs.
DISPLAY_ALPHA = 'opaque-rgba8-rgb-preserved-over-black'
RAW_ALPHA = 'raw-associated-emissive-rgba8'
OUTCOMES = ('measured', 'unmeasurable', 'uncertain')
ACCEPTED_METHODS = ('manual-raw-pixel', 'scripted-raw-pixel')
# Coordinates from any of these sources are never measurements.
FORBIDDEN_METHOD_WORDS = ('overlay', 'guide', 'target', 'calibrat', 'project', 'infer',
                          'default', 'expected', 'detector', 'estimate', 'copied')
HEX40 = re.compile(r'^[0-9a-f]{40}$')
HEX64 = re.compile(r'^[0-9a-f]{64}$')
FRAME_NAME = re.compile(r'^[0-9]{4,}\.png$')
DIGITS = re.compile(r'^[0-9]+$')

TOP_KEYS = {'schema', 'evidence', 'measurements'}
EVIDENCE_REQUIRED = {'repository', 'run_id', 'run_attempt', 'source_commit'}
EVIDENCE_OPTIONAL = {'artifact_id', 'artifact_name', 'artifact_zip_sha256'}
ENTRY_REQUIRED = {'image', 'image_sha256', 'image_size', 'frame', 'landmark', 'outcome',
                  'reviewer', 'provenance', 'target_values_not_used'}
ENTRY_OPTIONAL = {'measured_center', 'reason'}
FRAME_KEYS = {'source_frame', 'backend', 'pose'}
PROVENANCE_REQUIRED = {'method', 'tool', 'image_role', 'measured_at'}
PROVENANCE_OPTIONAL = {'notes'}


class ReviewError(ValueError):
    """An input that cannot be reviewed; the whole review remains open."""


def _reject_duplicates(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ReviewError(f'duplicate JSON key {key!r}')
        seen[key] = value
    return seen


def _reject_constant(name):
    raise ReviewError(f'non-finite JSON number {name}')


def load_json(path):
    try:
        text = Path(path).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as error:
        raise ReviewError(f'cannot read {path}: {error}') from error
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicates,
                          parse_constant=_reject_constant)
    except json.JSONDecodeError as error:
        raise ReviewError(f'{path}: invalid JSON: {error}') from error


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _keys(obj, required, optional, where):
    if not isinstance(obj, dict):
        raise ReviewError(f'{where} must be an object')
    missing = sorted(required - obj.keys())
    unknown = sorted(obj.keys() - required - optional)
    if missing:
        raise ReviewError(f'{where} missing {missing}')
    if unknown:
        raise ReviewError(f'{where} has unknown fields {unknown}')


def _text(value, where):
    if not isinstance(value, str) or not value.strip():
        raise ReviewError(f'{where} must be a non-empty string')
    return value


def _number(value, where):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReviewError(f'{where} must be a JSON number')
    try:
        number = float(value)
    except OverflowError as error:
        raise ReviewError(f'{where} is outside the finite float range') from error
    if not math.isfinite(number):
        raise ReviewError(f'{where} must be finite')
    return number


def parse_point(value, where):
    if (not isinstance(value, list) or len(value) != 2
            or any(isinstance(item, (list, dict)) for item in value)):
        raise ReviewError(f'{where} must be exactly one [x, y] pair; '
                          'multiple candidates are ambiguous')
    x = _number(value[0], f'{where}[0]')
    y = _number(value[1], f'{where}[1]')
    if not (0 <= x <= EXTENT[0] - 1 and 0 <= y <= EXTENT[1] - 1):
        raise ReviewError(f'{where} ({x:g},{y:g}) is outside the 960x540 pixel grid')
    return x, y


def parse_evidence(evidence):
    _keys(evidence, EVIDENCE_REQUIRED, EVIDENCE_OPTIONAL, 'evidence')
    for key in sorted(evidence):
        _text(evidence[key], f'evidence.{key}')
    if not DIGITS.match(evidence['run_id']) or not DIGITS.match(evidence['run_attempt']):
        raise ReviewError('evidence run_id and run_attempt must be decimal strings')
    if not HEX40.match(evidence['source_commit']):
        raise ReviewError('evidence.source_commit must be a full lowercase 40-hex commit')
    if 'artifact_id' in evidence and not DIGITS.match(evidence['artifact_id']):
        raise ReviewError('evidence.artifact_id must be a decimal string')
    if 'artifact_zip_sha256' in evidence and not HEX64.match(evidence['artifact_zip_sha256']):
        raise ReviewError('evidence.artifact_zip_sha256 must be lowercase 64-hex')
    return dict(evidence)


def parse_provenance(provenance, where):
    _keys(provenance, PROVENANCE_REQUIRED, PROVENANCE_OPTIONAL, where)
    method = _text(provenance['method'], f'{where}.method')
    if any(word in method.casefold() for word in FORBIDDEN_METHOD_WORDS) \
            or method not in ACCEPTED_METHODS:
        raise ReviewError(f'{where}.method {method!r} is not a raw-pixel measurement; '
                          f'accepted: {list(ACCEPTED_METHODS)}')
    _text(provenance['tool'], f'{where}.tool')
    if provenance['image_role'] != 'raw':
        raise ReviewError(f'{where}.image_role must be "raw"; guides/overlays are not measured')
    stamp = _text(provenance['measured_at'], f'{where}.measured_at')
    try:
        parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    except ValueError as error:
        raise ReviewError(f'{where}.measured_at is not ISO 8601') from error
    if parsed.tzinfo is None:
        raise ReviewError(f'{where}.measured_at needs an explicit timezone')
    if 'notes' in provenance and not isinstance(provenance['notes'], str):
        raise ReviewError(f'{where}.notes must be a string')
    return dict(provenance)


def resolve_image(root, relative, where):
    _text(relative, where)
    candidate = Path(relative)
    if candidate.is_absolute() or '..' in candidate.parts or '\\' in relative:
        raise ReviewError(f'{where} must be a relative path inside the evidence root')
    if candidate.name.casefold().endswith('-guide.png'):
        raise ReviewError(f'{where} names a guide overlay; measure the raw PNG instead')
    path = root / candidate
    current = root
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            raise ReviewError(f'{where} traverses a symlink')
    if not path.is_file():
        raise ReviewError(f'{where} is not an existing regular file')
    resolved = path.resolve()
    if root.resolve() not in resolved.parents:
        raise ReviewError(f'{where} resolves outside the evidence root')
    return path


def verify_raw_png(path, expected_sha, where):
    before = sha256_file(path)
    if before != expected_sha:
        raise ReviewError(f'{where} SHA-256 {before} does not match annotation {expected_sha}')
    # Pillow verify/load accepts a PNG missing only its final IEND CRC; reuse the
    # capture-contract framing check that rejects truncated chunk CRCs first.
    try:
        _verify_png_framing(path)
    except CaptureError as error:
        raise ReviewError(f'{where} is not a framed PNG: {error}') from error
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            if image.format != 'PNG':
                raise ReviewError(f'{where} is {image.format}, not PNG')
            size = image.size
            image.load()
    except ReviewError:
        raise
    except Exception as error:  # Pillow raises several decoder-specific types.
        raise ReviewError(f'{where} is not a decodable PNG: {error}') from error
    if size != EXTENT:
        raise ReviewError(f'{where} is {size[0]}x{size[1]}, not unscaled 960x540')
    if sha256_file(path) != before:
        raise ReviewError(f'{where} changed while being reviewed')
    return size


def load_packet_records(packet, root):
    """Index an authored packet's landmark-review.json raw records by SHA-256."""
    if not isinstance(packet, dict) or not isinstance(packet.get('records'), list):
        raise ReviewError('landmark review packet has no records list')
    raw, guides = {}, set()
    for index, record in enumerate(packet['records']):
        where = f'packet.records[{index}]'
        if not isinstance(record, dict):
            raise ReviewError(f'{where} must be an object')
        sha = record.get('raw_sha256')
        if not isinstance(sha, str) or not HEX64.match(sha):
            raise ReviewError(f'{where}.raw_sha256 must be lowercase 64-hex')
        if sha in raw:
            raise ReviewError(f'{where} repeats raw SHA-256 {sha}; frame identity is ambiguous')
        raw[sha] = record
        guide = record.get('guide')
        if isinstance(guide, str) and (root / guide).is_file():
            guides.add(sha256_file(root / guide))
    return raw, guides


def check_packet(entry, record, where):
    landmark = LANDMARKS[entry['landmark']]
    expected = {'backend': entry['frame']['backend'], 'pose': entry['frame']['pose'],
                'source_frame': entry['frame']['source_frame'], 'feature': landmark['feature'],
                'calibrated_center': list(landmark['target']), 'tolerance_px': TOLERANCE_PX}
    for key, value in expected.items():
        if record.get(key) != value:
            raise ReviewError(f'{where}: packet record {key}={record.get(key)!r} '
                              f'does not match {value!r}')


# Same frame selection the authored packet uses for its review copies.
POSE_TELEMETRY = {'hip': {'route': 'ready'},
                  'ads': {'route': 'ads.hold', 'simulation_ads': 1}}
BACKEND_SIDECAR = {'dx12': 'Dx12'}


def _sidecar_bool(metadata, key, where, path_name):
    """Require a real JSON boolean when the capture sidecar declares a typed flag."""
    if key not in metadata:
        return None
    value = metadata[key]
    if not isinstance(value, bool):
        raise ReviewError(f'{where}: {path_name} {key} must be a JSON boolean, got {value!r}')
    return value


def _sidecar_number(metadata, key, where, path_name):
    """Require a finite JSON number when the capture sidecar declares a numeric field."""
    if key not in metadata:
        return None
    return _number(metadata[key], f'{where}: {path_name} {key}')


def check_display_metadata(metadata, frame, where, path_name, require_extent):
    """Typed raw/display checks shared by --frames sidecars and sibling sidecars.

    Opaque display sidecars are accepted; raw-associated emissive targets and
    wrongly typed flags are never landmark inputs.
    """
    if not isinstance(metadata, dict):
        raise ReviewError(f'{where}: {path_name} must be an object')
    extent = (metadata.get('width'), metadata.get('height'))
    if (require_extent or 'width' in metadata or 'height' in metadata) and extent != EXTENT:
        raise ReviewError(f'{where}: {path_name} does not report 960x540')
    expected_backend = BACKEND_SIDECAR.get(frame['backend'])
    if (expected_backend is not None and (require_extent or 'backend' in metadata)
            and metadata.get('backend') != expected_backend):
        raise ReviewError(f'{where}: {path_name} backend is '
                          f'{metadata.get("backend")!r}, not {expected_backend!r}')
    raw_flag = _sidecar_bool(metadata, 'diagnostic_raw_target', where, path_name)
    if raw_flag is True:
        raise ReviewError(f'{where}: {path_name} marks diagnostic_raw_target=true; '
                          'raw render-target readbacks are not landmark inputs')
    alpha = metadata.get('alpha_representation')
    if alpha is not None and not isinstance(alpha, str):
        raise ReviewError(f'{where}: {path_name} alpha_representation must be a string, '
                          f'got {alpha!r}')
    if alpha == RAW_ALPHA:
        raise ReviewError(f'{where}: {path_name} alpha_representation is {RAW_ALPHA!r}; '
                          'raw-associated targets are not landmark inputs')
    if alpha is not None and alpha != DISPLAY_ALPHA:
        raise ReviewError(f'{where}: {path_name} alpha_representation {alpha!r} is not '
                          f'the opaque display label {DISPLAY_ALPHA!r}')
    ads = _sidecar_number(metadata, 'ads', where, path_name)
    expected_ads = 1.0 if frame['pose'] == 'ads' else 0.0
    if ads is not None and ads != expected_ads:
        raise ReviewError(f'{where}: {path_name} ads={ads!r} does not match pose '
                          f'{frame["pose"]!r} (expected {expected_ads:g})')


def check_sibling_sidecar(item, root, where):
    """Apply the display checks to the annotated image's own <image>.json, if present.

    Runs with or without --frames, so a standalone annotated PNG cannot bypass a
    sibling sidecar that marks it as a raw render target.
    """
    sibling = Path(root) / f'{item["image"]}.json'
    if sibling.is_symlink():
        raise ReviewError(f'{where}: sibling sidecar {sibling.name} is a symlink')
    if not sibling.exists():
        return
    if not sibling.is_file():
        raise ReviewError(f'{where}: sibling sidecar {sibling.name} is not a regular file')
    check_display_metadata(load_json(sibling), item['frame'], where, sibling.name,
                           require_extent=False)


def check_frame_source(item, frames_dir, where):
    """Tie the annotation to the original capture sequence frame and its sidecars."""
    frame = item['frame']
    original = Path(frames_dir) / frame['source_frame']
    if original.is_symlink() or not original.is_file():
        raise ReviewError(f'{where}: source frame {original} is not a regular file')
    if sha256_file(original) != item['image_sha256']:
        raise ReviewError(f'{where}: annotated image is not byte-identical to {original}')
    metadata_path = Path(f'{original}.json')
    gameplay_path = Path(f'{original}.gameplay.json')
    for path in (metadata_path, gameplay_path):
        if not path.is_file():
            raise ReviewError(f'{where}: missing sidecar {path.name}')
    metadata = load_json(metadata_path)
    check_display_metadata(metadata, frame, where, metadata_path.name, require_extent=True)
    gameplay = load_json(gameplay_path)
    if not isinstance(gameplay, dict):
        raise ReviewError(f'{where}: {gameplay_path.name} must be an object')
    for key, value in POSE_TELEMETRY[frame['pose']].items():
        actual = gameplay.get(key)
        if key == 'simulation_ads':
            # Reject string "1" / bools; pose binding needs a real JSON number.
            if isinstance(actual, bool) or not isinstance(actual, (int, float)):
                raise ReviewError(f'{where}: {gameplay_path.name} {key}={actual!r} does not '
                                  f'identify a {frame["pose"]} review frame ({value!r})')
            try:
                numeric = float(actual)
            except OverflowError as error:
                raise ReviewError(f'{where}: {gameplay_path.name} {key} is outside the finite '
                                  'float range') from error
            if not math.isfinite(numeric) or numeric != value:
                raise ReviewError(f'{where}: {gameplay_path.name} {key}={actual!r} does not '
                                  f'identify a {frame["pose"]} review frame ({value!r})')
            continue
        if isinstance(actual, bool) or actual != value:
            raise ReviewError(f'{where}: {gameplay_path.name} {key}={actual!r} does not '
                              f'identify a {frame["pose"]} review frame ({value!r})')


def parse_entry(entry, index, root):
    where = f'measurements[{index}]'
    _keys(entry, ENTRY_REQUIRED, ENTRY_OPTIONAL, where)
    landmark = entry['landmark']
    if not isinstance(landmark, str):
        raise ReviewError(f'{where}.landmark must be a string landmark id, got {landmark!r}')
    if landmark in CONFUSABLE_LANDMARKS:
        raise ReviewError(f'{where}.landmark {landmark!r}: {CONFUSABLE_LANDMARKS[landmark]}')
    if landmark not in LANDMARKS:
        raise ReviewError(f'{where}.landmark {landmark!r} is unknown; '
                          f'expected one of {sorted(LANDMARKS)}')
    frame = entry['frame']
    _keys(frame, FRAME_KEYS, set(), f'{where}.frame')
    if not isinstance(frame['source_frame'], str) or not FRAME_NAME.match(frame['source_frame']):
        raise ReviewError(f'{where}.frame.source_frame must be a capture name like 0042.png')
    if frame['backend'] not in BACKENDS:
        raise ReviewError(f'{where}.frame.backend must be one of {list(BACKENDS)}')
    if frame['pose'] != LANDMARKS[landmark]['pose']:
        raise ReviewError(f'{where}: landmark {landmark} belongs to pose '
                          f'{LANDMARKS[landmark]["pose"]!r}, frame says {frame["pose"]!r}')
    if not isinstance(entry['image_sha256'], str) or not HEX64.match(entry['image_sha256']):
        raise ReviewError(f'{where}.image_sha256 must be lowercase 64-hex')
    size = entry['image_size']
    if (not isinstance(size, list) or len(size) != 2
            or any(isinstance(v, bool) or not isinstance(v, int) for v in size)
            or tuple(size) != EXTENT):
        raise ReviewError(f'{where}.image_size must be [960, 540]')
    _text(entry['reviewer'], f'{where}.reviewer')
    provenance = parse_provenance(entry['provenance'], f'{where}.provenance')
    if entry['target_values_not_used'] is not True:
        raise ReviewError(f'{where}.target_values_not_used must be true')
    outcome = entry['outcome']
    if outcome not in OUTCOMES:
        raise ReviewError(f'{where}.outcome must be one of {list(OUTCOMES)}')
    point = None
    if outcome == 'measured':
        if 'measured_center' not in entry or entry['measured_center'] is None:
            raise ReviewError(f'{where}: a measured outcome needs measured_center; '
                              'the calibration target is never substituted')
        point = parse_point(entry['measured_center'], f'{where}.measured_center')
        if 'reason' in entry:
            _text(entry['reason'], f'{where}.reason')
    else:
        if entry.get('measured_center') is not None:
            raise ReviewError(f'{where}: {outcome} entries must not carry coordinates')
        _text(entry.get('reason'), f'{where}.reason')
    path = resolve_image(root, entry['image'], f'{where}.image')
    verify_raw_png(path, entry['image_sha256'], f'{where}.image')
    return {'index': index, 'image': entry['image'], 'image_sha256': entry['image_sha256'],
            'image_size': list(EXTENT), 'frame': dict(frame), 'landmark': landmark,
            'feature': LANDMARKS[landmark]['feature'], 'outcome': outcome, 'point': point,
            'reason': entry.get('reason'), 'reviewer': entry['reviewer'],
            'provenance': provenance}


def compare(parsed):
    target = LANDMARKS[parsed['landmark']]['target']
    result = {key: parsed[key] for key in ('index', 'image', 'image_sha256', 'image_size',
                                           'frame', 'landmark', 'feature', 'outcome',
                                           'reviewer', 'provenance')}
    result.update({'calibrated_center': list(target), 'tolerance_px': TOLERANCE_PX,
                   'measured_center': None, 'delta': None, 'accepted': False})
    if parsed['outcome'] != 'measured':
        result['status'] = f'unaccepted-{parsed["outcome"]}'
        result['reason'] = parsed['reason']
        return result
    x, y = parsed['point']
    dx, dy = x - target[0], y - target[1]
    result['measured_center'] = [x, y]
    result['delta'] = {'dx': dx, 'dy': dy, 'euclidean': math.hypot(dx, dy)}
    if (x, y) == (float(target[0]), float(target[1])):
        result['status'] = 'unaccepted-coincides-with-target'
        result['reason'] = ('measured value equals the calibration target exactly and cannot '
                            'be distinguished from a copied target; needs explicit human '
                            'confirmation in the review record')
    elif abs(dx) <= TOLERANCE_PX and abs(dy) <= TOLERANCE_PX:
        result['status'] = 'within-tolerance'
        result['accepted'] = True
    else:
        result['status'] = 'outside-tolerance'
    return result


def open_report(errors, evidence=None, results=()):
    return {'schema': REPORT_SCHEMA, 'evidence': evidence, 'results': list(results),
            'errors': errors, 'status': 'invalid', 'automated_landmark_gate': 'open',
            'human_m2_approval': 'open', 'human_m4_approval': 'open',
            'acceptance_complete': False}


def review(measurements, root, packet=None, require_backends=('dx12',), frames=None):
    """Return a report; any input error yields status 'invalid' with the gate open."""
    root = Path(root)
    if not root.is_dir():
        return open_report([f'evidence root {root} is not a directory'])
    try:
        _keys(measurements, TOP_KEYS, set(), 'measurement file')
        if measurements['schema'] != MEASUREMENT_SCHEMA:
            raise ReviewError(f'measurement schema must be {MEASUREMENT_SCHEMA!r}')
        evidence = parse_evidence(measurements['evidence'])
        entries = measurements['measurements']
        if not isinstance(entries, list) or not entries:
            raise ReviewError('measurements must be a non-empty list')
        packet_raw, packet_guides = (load_packet_records(packet, root) if packet is not None
                                     else ({}, set()))
    except ReviewError as error:
        return open_report([str(error)])
    errors, parsed = [], []
    for index, entry in enumerate(entries):
        try:
            item = parse_entry(entry, index, root)
            if item['image_sha256'] in packet_guides:
                raise ReviewError(f'measurements[{index}] is a guide overlay, not a raw PNG')
            if packet is not None:
                record = packet_raw.get(item['image_sha256'])
                if record is None:
                    raise ReviewError(f'measurements[{index}] image is not a raw record '
                                      'in the landmark review packet')
                check_packet(item, record, f'measurements[{index}]')
            check_sibling_sidecar(item, root, f'measurements[{index}]')
            frames_dir = (frames or {}).get(item['frame']['backend'])
            if frames_dir is not None:
                check_frame_source(item, frames_dir, f'measurements[{index}]')
            parsed.append(item)
        except ReviewError as error:
            errors.append(str(error))
    by_slot, by_image = {}, {}
    for item in parsed:
        slot = (item['frame']['backend'], item['landmark'])
        by_slot.setdefault(slot, []).append(item['index'])
        identity = (item['frame']['backend'], item['frame']['pose'], item['frame']['source_frame'])
        by_image.setdefault(item['image_sha256'], set()).add(identity)
    for (backend, landmark), indexes in sorted(by_slot.items()):
        if len(indexes) > 1:
            errors.append(f'ambiguous: {backend} {landmark} annotated by entries {indexes}')
    for sha, identities in sorted(by_image.items()):
        if len(identities) > 1:
            errors.append(f'ambiguous: image {sha} claims frame identities {sorted(identities)}')
    results = [compare(item) for item in parsed]
    if errors:
        return open_report(errors, evidence, results)
    report = open_report([], evidence, results)
    missing = [f'{backend} {landmark}' for backend in require_backends for landmark in LANDMARKS
               if (backend, landmark) not in by_slot]
    required = [r for r in results if r['frame']['backend'] in require_backends]
    report['required'] = [f'{backend} {landmark}' for backend in require_backends
                          for landmark in sorted(LANDMARKS)]
    report['missing'] = missing
    if any(r['status'] == 'outside-tolerance' for r in required):
        report['status'], report['automated_landmark_gate'] = 'outside-tolerance', 'failed'
    elif missing or not all(r['accepted'] for r in required):
        report['status'] = 'open'
    else:
        report['status'] = 'within-tolerance'
        report['automated_landmark_gate'] = 'measured-within-tolerance'
    report['note'] = ('Only explicit reviewer-measured raw pixels were compared. Human M2 '
                      'capture approval and M4 hardware playtest approval remain open.')
    return report


def template(packet, root):
    """Skeleton entries from a packet; coordinates and outcome are deliberately blank."""
    raw, _ = load_packet_records(packet, Path(root))
    entries = []
    for sha, record in raw.items():
        landmark = next((name for name, spec in LANDMARKS.items()
                         if spec['pose'] == record.get('pose')), None)
        entries.append({'image': record.get('raw'), 'image_sha256': sha,
                        'image_size': list(EXTENT),
                        'frame': {'source_frame': record.get('source_frame'),
                                  'backend': record.get('backend'), 'pose': record.get('pose')},
                        'landmark': landmark, 'outcome': None, 'measured_center': None,
                        'reviewer': None,
                        'provenance': {'method': None, 'tool': None, 'image_role': 'raw',
                                       'measured_at': None},
                        'target_values_not_used': None})
    return {'schema': MEASUREMENT_SCHEMA,
            'evidence': {'repository': None, 'run_id': None, 'run_attempt': None,
                         'source_commit': None},
            'measurements': entries}


def _write(document, output):
    text = json.dumps(document, indent=2, sort_keys=True) + '\n'
    if output is None:
        sys.stdout.write(text)
        return
    with open(output, 'x', encoding='utf-8') as handle:  # never overwrite evidence
        handle.write(text)


EXIT_CODES = {'within-tolerance': 0, 'open': 1, 'outside-tolerance': 1, 'invalid': 2}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('review', help='compare explicit measurements with calibration')
    check.add_argument('measurements', type=Path)
    check.add_argument('--root', type=Path, required=True,
                       help='evidence directory that annotation image paths are relative to')
    check.add_argument('--packet', type=Path,
                       help='optional landmark-review.json from the authored DX12 packet')
    check.add_argument('--frames', action='append', default=[], metavar='BACKEND=DIR',
                       help='original capture sequence for a backend (dx12=... legacy=...); '
                            'ties each annotation to its frame bytes and telemetry sidecars')
    check.add_argument('--require-backend', action='append', choices=BACKENDS,
                       help='backends that must have both landmarks (default: dx12)')
    check.add_argument('--output', type=Path, help='new report path (refuses to overwrite)')
    skeleton = sub.add_parser('template', help='blank measurement skeleton from a packet')
    skeleton.add_argument('--packet', type=Path, required=True)
    skeleton.add_argument('--root', type=Path, required=True)
    skeleton.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'template':
            try:
                _write(template(load_json(args.packet), args.root), args.output)
            except FileExistsError:
                sys.stderr.write(f'refusing to overwrite existing file {args.output}\n')
                return 2
            return 0
        measurements = load_json(args.measurements)
        packet = load_json(args.packet) if args.packet else None
        frames = {}
        for value in args.frames:
            backend, separator, folder = value.partition('=')
            if not separator or backend not in BACKENDS or not folder or backend in frames:
                raise ReviewError(f'--frames {value!r} must be a unique dx12=DIR or legacy=DIR')
            frames[backend] = Path(folder)
    except ReviewError as error:
        report = open_report([str(error)])
        try:
            _write(report, None if args.command == 'template' else args.output)
        except FileExistsError:
            # Parse/load failures still go through the protected writer: never
            # clobber an existing file, and still exit 2 with the invalid report
            # on stdout when --output cannot be created.
            sys.stderr.write(f'refusing to overwrite existing report {args.output}\n')
            _write(report, None)
            return 2
        return 2
    report = review(measurements, args.root, packet,
                    tuple(args.require_backend or ('dx12',)), frames)
    try:
        _write(report, args.output)
    except FileExistsError:
        sys.stderr.write(f'refusing to overwrite existing report {args.output}\n')
        return 2
    return EXIT_CODES[report['status']]


if __name__ == '__main__':
    sys.exit(main())

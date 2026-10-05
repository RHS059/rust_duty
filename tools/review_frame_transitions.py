#!/usr/bin/env python3
"""Compare frame-to-frame change patterns of a candidate and a legacy capture.

Diagnostic only. Each frame's decoded RGBA pixels are hashed; transition i is
"changed" when frame i differs from frame i-1. A one-frame-late readback, a
duplicated frame or a swap near a static/moving boundary shifts the candidate
pattern relative to legacy. Pattern "edges" (where changed flips to unchanged
or back) are where such faults become visible. Continuously moving or fully
static sequences have no edges and are reported as insufficient signal.

A matching pattern is NOT proof that the GPU returned each frame's pixels, and
cross-backend rasterization can legitimately move an edge. Every report keeps
pixel_binding_proven=false and human_review=open; mismatches are review
findings, never silently accepted parity.

Exit codes: 0 pattern match, 1 pattern mismatch (review finding),
2 invalid input, 3 insufficient signal.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from exclusive_output import write_text_exclusive

from verify_capture_telemetry import read_record
from verify_render_capture import load_png

SCHEMA = 'rust-duty-frame-transition-review/v1'
FRAME = re.compile(r'[0-9]{4,}\.png')
LIMITATIONS = [
    'A matching change/no-change pattern does not prove frame identity; continuous motion can hide lag or swaps.',
    'Cross-backend rasterization may change one frame but not the other; treat any mismatch as a review finding.',
    'A match does not prove the GPU returned the pixels of the frame each sidecar describes.',
    'This diagnostic does not validate gameplay/time telemetry or replace authored acceptance checks.',
]


def frame_digests(folder, backend):
    """Decode every NNNN.png in order; validate identity, extent and names."""
    folder = Path(folder)
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError(f'{folder}: capture directory missing or a symbolic link')
    entries = list(folder.iterdir())
    for path in entries:
        if path.is_symlink():
            raise ValueError(f'{path}: capture entry is a symbolic link')
        if path.suffix.lower() == '.png' and not FRAME.fullmatch(path.name):
            raise ValueError(f'{path}: noncanonical capture filename')
    # The producer uses a minimum width of four digits, not a 9999-frame cap.
    names = sorted((p.name for p in entries if FRAME.fullmatch(p.name)),
                   key=lambda name: int(name.removesuffix('.png')))
    if not names or names != [f'{i:04}.png' for i in range(len(names))]:
        raise ValueError(f'{folder}: missing or noncontiguous zero-based frames')
    expected_sidecars = {f'{name}.json' for name in names}
    if any(p.name.lower().endswith('.png.json') and p.name not in expected_sidecars for p in entries):
        raise ValueError(f'{folder}: orphan or noncanonical primary capture sidecar')
    identity = extent = None
    digests = []
    witnessed = 0
    for name in names:
        for path in (folder / name, folder / f'{name}.json'):
            if not path.is_file() or path.is_symlink():
                raise ValueError(f'{path}: capture input must be a regular non-symlink file')
        record = read_record(folder / f'{name}.json')
        if record.get('backend') != backend:
            raise ValueError(f'{folder / name}: backend {record.get("backend")!r} != {backend!r}')
        adapter = record.get('adapter')
        if not isinstance(adapter, str) or not adapter.strip():
            raise ValueError(f'{folder / name}: adapter must be a nonblank string')
        size = (record.get('width'), record.get('height'))
        if any(type(value) is not int or value <= 0 for value in size):
            raise ValueError(f'{folder / name}: width/height must be positive integers')
        if identity is None:
            identity, extent = (backend, adapter), size
        elif (backend, adapter) != identity or size != extent:
            raise ValueError(f'{folder / name}: renderer identity or extent changed mid-sequence')
        digest = hashlib.sha256(load_png(folder / name, size).tobytes()).hexdigest()
        # Optional completed-readback witness: when the capture path records the
        # SHA-256 of the RGBA it read back, the saved PNG must decode to it.
        witness = record.get('readback_rgba_sha256')
        if witness is not None:
            if witness != digest:
                raise ValueError(f'{folder / name}: decoded pixels differ from readback_rgba_sha256')
            witnessed += 1
        digests.append(digest)
    return names, extent, identity, digests, witnessed


def transitions(digests):
    """changed[i-1] says whether frame i differs from frame i-1."""
    return [after != before for before, after in zip(digests, digests[1:])]


def edges(changed):
    """Transition indices where the changed/unchanged state flips."""
    return [i for i in range(1, len(changed)) if changed[i] != changed[i - 1]]


def review(legacy, candidate, legacy_backend='OpenGl', candidate_backend='Dx12'):
    report = {'schema': SCHEMA, 'status': 'invalid-input',
              'pixel_binding_proven': False, 'human_review': 'open',
              'legacy': str(legacy), 'candidate': str(candidate),
              'limitations': list(LIMITATIONS)}
    try:
        before = frame_digests(legacy, legacy_backend)
        after = frame_digests(candidate, candidate_backend)
    except (OSError, ValueError) as error:
        report['error'] = str(error)
        return report
    names, extent = before[0], before[1]
    if after[0] != names:
        report['error'] = f'frame names differ: legacy {len(names)} frames, candidate {len(after[0])}'
        return report
    if after[1] != extent:
        report['error'] = f'extent differs: legacy {extent}, candidate {after[1]}'
        return report
    legacy_changed, candidate_changed = transitions(before[3]), transitions(after[3])
    legacy_edges, candidate_edges = edges(legacy_changed), edges(candidate_changed)
    mismatches = [{'transition': f'{names[i]}->{names[i + 1]}',
                   'legacy_changed': legacy_changed[i], 'candidate_changed': candidate_changed[i]}
                  for i in range(len(legacy_changed)) if legacy_changed[i] != candidate_changed[i]]
    if mismatches:
        status = 'pattern-mismatch'
    elif not legacy_edges:
        status = 'insufficient-signal'
    else:
        status = 'pattern-match'
    report.update({
        'status': status,
        'frames': len(names), 'extent': list(extent),
        'legacy_identity': list(before[2]), 'candidate_identity': list(after[2]),
        'readback_witnessed_frames': {'legacy': before[4], 'candidate': after[4]},
        'legacy_unchanged_transitions': legacy_changed.count(False),
        'candidate_unchanged_transitions': candidate_changed.count(False),
        'legacy_edges': len(legacy_edges), 'candidate_edges': len(candidate_edges),
        'mismatched_transitions': mismatches,
        'frame_digests': [{'frame': name, 'legacy_rgba_sha256': a, 'candidate_rgba_sha256': b}
                          for name, a, b in zip(names, before[3], after[3])],
    })
    return report


EXIT = {'pattern-match': 0, 'pattern-mismatch': 1, 'invalid-input': 2, 'insufficient-signal': 3}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('legacy', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--legacy-backend', default='OpenGl')
    parser.add_argument('--candidate-backend', default='Dx12')
    parser.add_argument('--report', type=Path, help='write the JSON report here (must not exist)')
    args = parser.parse_args(argv)
    report = review(args.legacy, args.candidate, args.legacy_backend, args.candidate_backend)
    text = json.dumps(report, indent=2) + '\n'
    if args.report is not None:
        try:
            write_text_exclusive(args.report, text)
        except OSError as error:
            print(f'cannot write report: {error}', file=sys.stderr)
            return 2
    print(text, end='')
    return EXIT[report['status']]


if __name__ == '__main__':
    sys.exit(main())

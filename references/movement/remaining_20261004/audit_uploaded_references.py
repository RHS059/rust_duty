#!/usr/bin/env python3
"""Reproduce native PTS and exact decoded-pixel overlap checks, without downloads.

Output is source evidence only. Zero exact matches does not rule out re-encoded
footage and does not establish motion uniqueness or candidate animation quality.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from cut_reference import frame_hashes, inspect, sha256, validate_pts


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--uploaded-dir', type=Path, required=True)
    for key in ('r1', 'r2', 'r3'):
        ap.add_argument('--' + key, type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    here = Path(__file__).parent
    catalog = json.loads((here / 'uploaded_references_inventory.json').read_text())
    prior = json.loads((here / 'source_map.json').read_text())['sources']
    entries = {s['id']: (args.uploaded_dir / Path(s['path']).name, s['sha256'],
                        s['decoded_frame_count']) for s in catalog['sources']}
    entries.update({sid: (getattr(args, sid.lower()), spec['sha256'], spec['frame_count'])
                    for sid, spec in prior.items()})
    args.out.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for sid, (source, pin, count) in entries.items():
        if sha256(source) != pin:
            raise ValueError(f'{sid}: source SHA-256 mismatch')
        probe = inspect(source)
        pts = validate_pts(probe, count)
        hashes[sid] = frame_hashes(source)
        if len(hashes[sid]) != count:
            raise ValueError(f'{sid}: wrong decoded pixel-frame count')
        raw = ('\n'.join(hashes[sid]) + '\n').encode()
        (args.out / f'{sid}_frame_md5.txt').write_bytes(raw)
        if sid.startswith('U'):
            with (args.out / f'{sid}_frame_pts.csv').open('w') as f:
                writer = csv.writer(f, lineterminator="\n")
                writer.writerow(['source_frame', 'pts_ticks', 'time_base'])
                writer.writerows((i, t, '1/15360') for i, t in enumerate(pts))
            write_json(args.out / f'{sid}_native_probe.json', {
                'stream': probe['streams'][0], 'decoded_frame_count': count,
                'first_pts': pts[0], 'last_pts': pts[-1],
                'all_pts_equal_index_times_256': True,
                'frame_md5_list_sha256': hashlib.sha256(raw).hexdigest()})
        print(f'{sid}: verified {count} native frames', flush=True)
    comparisons = []
    for sid in entries:
        if not sid.startswith('U'):
            continue
        for rid in prior:
            lookup = {}
            for i, digest in enumerate(hashes[rid]):
                lookup.setdefault(digest, []).append(i)
            pairs = [[i, j] for i, digest in enumerate(hashes[sid])
                     for j in lookup.get(digest, [])]
            comparisons.append({'uploaded_source_id': sid, 'prior_source_id': rid,
                'exact_equal_decoded_frame_count': len({i for i, _ in pairs}),
                'matching_frame_pairs': pairs})
    write_json(args.out / 'decoded_pixel_overlap.json', {
        'method': 'Every decoded native YUV420P frame hashed with FFmpeg framemd5. '
                  'Equal decoded pixels only; no visual-footage exclusion inferred from unequal encoding.',
        'comparisons': comparisons})


if __name__ == '__main__':
    main()

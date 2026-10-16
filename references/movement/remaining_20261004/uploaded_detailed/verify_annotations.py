#!/usr/bin/env python3
"""Check the six detailed timelines against pinned sources and native PTS.

Structural/source integrity only: this does not certify semantic boundaries,
reviewer observations, animation matching, or artistic approval.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(source_dir):
    here = Path(__file__).resolve().parent
    catalog = json.loads((here.parent / 'uploaded_references_inventory.json').read_text())
    results = []
    for pin in catalog['sources']:
        sid = pin['id']
        path = here / f'{sid}_annotations.json'
        doc = json.loads(path.read_text())
        count = pin['decoded_frame_count']
        require(doc['source_id'] == sid and doc['sha256'] == pin['sha256'], f'{sid}: identity')
        require(doc['frame_count'] == count and doc['fps'] == pin['fps']
                and doc['time_base'] == pin['time_base'], f'{sid}: timing identity')
        source = source_dir / Path(pin['path']).name
        require(digest(source) == pin['sha256'], f'{sid}: original source hash')
        with (here.parent / pin['frame_pts_csv']).open() as stream:
            rows = list(csv.DictReader(stream))
        require(len(rows) == count, f'{sid}: PTS count')
        require(all(int(r['source_frame']) == n and int(r['pts_ticks']) == n * 256
                    and r['time_base'] == pin['time_base'] for n, r in enumerate(rows)),
                f'{sid}: native PTS map')
        samples = doc['reviewed_samples']
        require(samples == sorted(set(samples)) and all(type(n) is int and 0 <= n < count
                                                       for n in samples), f'{sid}: samples')
        cursor = 0
        identifiers = set()
        for item in doc['intervals']:
            a, b = item['start_frame'], item['end_frame_exclusive']
            require(type(a) is int and type(b) is int and a == cursor and a < b <= count,
                    f'{sid}: gap/overlap/bounds at {item["id"]}')
            require(item['id'] not in identifiers, f'{sid}: duplicate interval id')
            identifiers.add(item['id'])
            require(item['start_pts_ticks'] == a * 256 and item['end_pts_ticks_exclusive'] == b * 256,
                    f'{sid}: interval PTS')
            require(type(item['uncertainty_frames']) is int and item['uncertainty_frames'] >= 0,
                    f'{sid}: uncertainty')
            require(item['observed_content'] and item['interpretation'], f'{sid}: evidence labels')
            cursor = b
        require(cursor == count, f'{sid}: incomplete timeline')
        for sheet in doc.get('contact_sheets', []):
            require(digest(here / sheet['path']) == sheet['sha256'], f'{sid}: sheet hash')
        manifest_samples = set()
        for name in doc.get('sample_manifests', []):
            record = json.loads((here / name).read_text())
            require(record['source_id'] == sid and record['sha256'] == pin['sha256'],
                    f'{sid}: sample manifest identity')
            require(record['pts_ticks'] == [n * 256 for n in record['native_indices']],
                    f'{sid}: sample manifest PTS')
            manifest_samples.update(record['native_indices'])
        if doc.get('sample_manifests'):
            require(manifest_samples == set(samples), f'{sid}: sample manifest coverage')
        results.append({'source_id': sid, 'intervals': len(identifiers),
                        'timeline_frames': count, 'reviewed_samples': len(samples),
                        'annotation_sha256': digest(path), 'source_sha256': pin['sha256']})
    return {'scope': 'source, PTS, timeline and evidence integrity; not artistic acceptance',
            'sources': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = json.dumps(verify(args.source_dir), indent=2) + '\n'
    if args.output:
        args.output.write_text(result)
    print(result, end='')

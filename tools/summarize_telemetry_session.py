#!/usr/bin/env python3
"""Read-only inventory of local playtest evidence; never an acceptance verdict."""
import argparse
import csv
import json
import math
import sys
from pathlib import Path

CSV_HEADER = 'time,x,y,z,speed,grounded,crouched,sprinting,ads,recoil_pitch_deg,ammo,shots,hits,kills,render_fps'.split(',')
JSON_LIMIT = 1024 * 1024
# The producer retains up to250,000 records; normal traces exceed metadata size.
FRAME_JSON_LIMIT = 128 * 1024 * 1024
ROW_LIMIT = 250000
MEASUREMENT = 'cpu_wall_clock_successful_present_return_interval_ns'

def reject_constant(value):
    raise ValueError('Nonfinite JSON number: ' + value)

def finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Nonfinite JSON number')
    return result

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result

def load_object(path, schema, limit=JSON_LIMIT):
    if not path.exists():
        return None
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(path.name + ' exceeds JSON size limit')
    value = json.loads(data.decode('utf-8'), object_pairs_hook=unique_object,
                       parse_constant=reject_constant, parse_float=finite_float)
    if not isinstance(value, dict) or value.get('schema') != schema:
        raise ValueError(path.name + ' has invalid schema/object')
    return value

def check_status(value, allowed, label):
    if not isinstance(value, dict) or value.get('state') not in allowed:
        raise ValueError(label + ' has invalid status')
    if value.get('error') is not None and not isinstance(value['error'], str):
        raise ValueError(label + ' has invalid error')
    return value

def analyze_session(folder):
    folder = Path(folder)
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError('Expected a nonsymlink directory')
    names = ('gameplay.csv', 'frames.json', 'IDENTITY.json', 'CSV_STATUS.json', 'OBSERVATIONS.txt')
    files = {name: folder / name for name in names}
    for path in files.values():
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError('Expected nonsymlink regular file: ' + path.name)
    identity = load_object(files['IDENTITY.json'], 'rust-duty-local-playtest-session/v1')
    frames = load_object(files['frames.json'], 'rust_duty_frame_performance_v1', FRAME_JSON_LIMIT)
    status = load_object(files['CSV_STATUS.json'], 'rust-duty-local-csv-status/v1')
    if status is not None:
        check_status(status, ('stopped', 'incomplete', 'interrupted'), 'CSV_STATUS.json')
    frame_status = None
    if frames is not None:
        if frames.get('measurement') != MEASUREMENT:
            raise ValueError('Invalid frame measurement')
        frame_status = check_status(frames.get('status'), ('complete', 'incomplete'), 'frames.json')
    rows = 0
    if files['gameplay.csv'].exists():
        with files['gameplay.csv'].open(encoding='utf-8', newline='') as stream:
            reader = csv.reader(stream, strict=True)
            if next(reader, None) != CSV_HEADER:
                raise ValueError('CSV header mismatch')
            for row in reader:
                rows += 1
                if rows > ROW_LIMIT or len(row) != len(CSV_HEADER):
                    raise ValueError('CSV row limit or width mismatch')
    warnings = ['Missing ' + name for name, path in files.items() if not path.exists()]
    for label, observed, complete in [('CSV', status, 'stopped'), ('frames', frame_status, 'complete')]:
        if observed is not None and (observed['state'] != complete or observed.get('error')):
            warnings.append(label + ' is incomplete or reports an error')
    left = identity.get('runtime_observed') if identity else None
    frame_identity = frames.get('identity') if frames else None
    right = frame_identity.get('runtime_observed') if isinstance(frame_identity, dict) else None
    for value in (left, right):
        if value is not None and not isinstance(value, dict):
            raise ValueError('Invalid runtime identity')
    if left and right and left.get('backend') and right.get('actual_backend'):
        if left['backend'] != right['actual_backend']:
            warnings.append('Backend mismatch between session and frame trace')
    return {'schema': 'rust-duty-local-session-inventory/v1', 'acceptance_proven': False,
            'identity': identity, 'files': {n: p.exists() for n, p in files.items()},
            'csv_data_rows': rows, 'csv_status': status, 'frame_status': frame_status,
            'inventory_state': 'incomplete' if warnings else 'complete', 'warnings': warnings}

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(analyze_session(args.folder), indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, csv.Error, RecursionError) as error:
        print('Invalid input: ' + str(error), file=sys.stderr)
        return 2

if __name__ == '__main__':
    sys.exit(main())

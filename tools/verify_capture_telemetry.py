#!/usr/bin/env python3
"""Strict capture telemetry parity and finite-JSON validation (stdlib only).

compare LEGACY CANDIDATE compares relative *.gameplay.json / *.time.json paths
and every field, recursively, with no tolerance or excluded metadata. Numeric
JSON types must match (integer versus fractional/exponent notation). Decimal
parsing preserves differences smaller than a binary float can represent.

validate FOLDER checks all *.json recursively. With --require-renderer, every
*.png.json capture sidecar must contain nonblank backend and adapter strings;
at least one capture sidecar is required. --renderer-glob changes that selection. Gameplay/time JSON remains unchanged.
--expected-backend also requires metadata and checks the exact backend string.

Neither command modifies input files or claims image/visual correctness.
"""

import argparse
from decimal import Decimal, DecimalException
import json
import math
from pathlib import Path
import sys


TELEMETRY_SUFFIXES = ('.gameplay.json', '.time.json')


def _reject_constant(value):
    raise ValueError(f'non-finite JSON number: {value}')


def _parse_float(value):
    # JSON's grammar permits 1e9999, but the runtime cannot represent it finitely.
    if not math.isfinite(float(value)):
        raise ValueError(f'non-finite JSON number: {value}')
    try:
        return Decimal(value)
    except DecimalException as error:
        raise ValueError(f'JSON number exceeds exact decimal parser limits: {value}') from error


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON field: {key!r}')
        result[key] = value
    return result


def read_record(path):
    """Read a nonempty JSON object, rejecting ambiguous and non-finite JSON."""
    try:
        record = json.loads(
            path.read_text(encoding='utf-8'), parse_constant=_reject_constant,
            parse_float=_parse_float, object_pairs_hook=_unique_object,
        )
        if not isinstance(record, dict) or not record:
            raise ValueError('capture record must be a nonempty JSON object')
        return record
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        raise ValueError(f'{path}: {error}') from error


def _paths(folder, telemetry_only):
    if not folder.is_dir():
        raise ValueError(f'capture directory missing or not a directory: {folder}')
    # Do not follow links: otherwise an uninspected subtree can silently vanish
    # from pathlib traversal or a capture can refer outside the chosen root.
    if folder.is_symlink():
        raise ValueError(f'capture directory is a symbolic link: {folder}')
    paths = {}
    for path in sorted(folder.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'capture tree contains a symbolic link: {path}')
        selected = path.name.endswith(TELEMETRY_SUFFIXES) if telemetry_only else path.suffix == '.json'
        if selected:
            if not path.is_file():
                raise ValueError(f'capture JSON is not a file: {path}')
            paths[path.relative_to(folder).as_posix()] = path
    if not paths:
        kind = 'gameplay/time telemetry' if telemetry_only else 'JSON'
        raise ValueError(f'no {kind} files in capture directory: {folder}')
    return paths


def _compare(left, right, location):
    if type(left) is not type(right):
        raise ValueError(f'{location}: type differs ({type(left).__name__} != {type(right).__name__})')
    if isinstance(left, dict):
        missing = sorted(left.keys() - right.keys())
        extra = sorted(right.keys() - left.keys())
        if missing or extra:
            raise ValueError(f'{location}: fields differ; missing={missing}, extra={extra}')
        for key in sorted(left):
            _compare(left[key], right[key], f'{location}[{key!r}]')
    elif isinstance(left, list):
        if len(left) != len(right):
            raise ValueError(f'{location}: array length differs ({len(left)} != {len(right)})')
        for index, (before, after) in enumerate(zip(left, right)):
            _compare(before, after, f'{location}[{index}]')
    elif left != right:
        raise ValueError(f'{location}: value differs ({left!r} != {right!r})')


def compare(legacy, candidate):
    """Compare all deterministic sidecars by relative path, schema and value."""
    before = _paths(Path(legacy), telemetry_only=True)
    after = _paths(Path(candidate), telemetry_only=True)
    missing = sorted(before.keys() - after.keys())
    extra = sorted(after.keys() - before.keys())
    if missing or extra:
        raise ValueError(f'telemetry files differ; missing={missing}, extra={extra}')
    for name in sorted(before):
        try:
            _compare(read_record(before[name]), read_record(after[name]), name)
        except RecursionError as error:
            raise ValueError(f'{name}: JSON nesting too deep to compare') from error
    return {
        'schema': 'rust-duty-capture-telemetry-parity/v1', 'passed': True,
        'files': len(before),
        'gameplay_files': sum(name.endswith('.gameplay.json') for name in before),
        'time_files': sum(name.endswith('.time.json') for name in before),
        'metadata_policy': 'All fields compared; no metadata exclusions.',
    }


def validate(folder, require_renderer=False, expected_backend=None, renderer_glob="*.png.json"):
    """Validate finite capture JSON and optionally capture renderer identity."""
    paths = _paths(Path(folder), telemetry_only=False)
    require_renderer = require_renderer or expected_backend is not None
    capture_count = 0
    for name, path in sorted(paths.items()):
        record = read_record(path)
        if Path(name).match(renderer_glob):
            capture_count += 1
            if require_renderer:
                for field in ('backend', 'adapter'):
                    value = record.get(field)
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError(f'{name}: {field} must be a nonblank string')
                if expected_backend is not None and record['backend'] != expected_backend:
                    raise ValueError(f'{name}: backend {record["backend"]!r} != {expected_backend!r}')
    if require_renderer and not capture_count:
        raise ValueError(f'renderer validation requires at least one JSON matching {renderer_glob!r}')
    return {
        'schema': 'rust-duty-capture-json-validation/v1', 'passed': True,
        'files': len(paths), 'capture_sidecars': capture_count,
        'renderer_metadata_required': require_renderer,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    parity = commands.add_parser('compare', help='exact gameplay/time telemetry parity')
    parity.add_argument('legacy', type=Path)
    parity.add_argument('candidate', type=Path)
    finite = commands.add_parser('validate', help='finite JSON and optional renderer metadata')
    finite.add_argument('folder', type=Path)
    finite.add_argument('--require-renderer', action='store_true')
    finite.add_argument('--expected-backend')
    finite.add_argument('--renderer-glob', default='*.png.json',
                        help='relative-path glob for required renderer metadata (default: *.png.json)')
    args = parser.parse_args(argv)
    try:
        if args.command == 'compare':
            result = compare(args.legacy, args.candidate)
        else:
            result = validate(args.folder, args.require_renderer, args.expected_backend, args.renderer_glob)
    except (ValueError, OSError) as error:
        print(f'capture telemetry verification failed: {error}', file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())

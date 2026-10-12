#!/usr/bin/env python3
"""Read authored DX12 progress; never launch captures or certify acceptance."""

import argparse
import json
import math
from pathlib import Path
import sys

from exclusive_output import write_text_exclusive


SUMMARY_SCHEMA = 'rust-duty-dx12-authored-acceptance/v1'
PROCESS_SCHEMA = 'rust-duty-capture-process/v1'


def _unique(pairs):
    record = {}
    for key, value in pairs:
        if key in record:
            raise ValueError(f'duplicate JSON field: {key}')
        record[key] = value
    return record


def _number(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError('non-finite JSON number')
    return value


def _constant(text):
    raise ValueError(f'non-finite JSON number: {text}')


def load_json(path):
    """Read one strict object. Only an absent file returns None."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f'symlinked evidence: {path}')
    try:
        with path.open('rb') as stream:
            raw = stream.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError('evidence JSON exceeds 16 MiB')
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique,
                           parse_constant=_constant, parse_float=_number)
        if not isinstance(value, dict):
            raise ValueError('expected a JSON object')
        return value
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        raise ValueError(f'{path}: {error}') from error


def _elapsed(value, field, nullable=True):
    if value is None and nullable:
        return None
    if type(value) not in (int, float) or value < 0 or (type(value) is float and not math.isfinite(value)):
        raise ValueError(f'{field} must be a finite nonnegative number')
    return value


def _count(value, field):
    if type(value) is not int or value < 0:
        raise ValueError(f'{field} must be a nonnegative integer')
    return value


def _process_name(check):
    if check == 'orientation-renderer-contract':
        return 'renderer-contract'
    if check == 'ads-placement-existing-validator':
        return 'ads-placement-validator'
    if check == 'layered-rates-existing-validator':
        return 'layered-rates-validator'
    if not check or '/' not in check:
        return None
    case, kind = check.split('/', 1)
    if case == 'lighting':
        return 'lighting-' + kind
    if kind == 'capture':
        return case
    if kind == 'existing-validator':
        return case + '-validator'
    return None


def summarize_dx12_progress(evidence_dir, report_path=None):
    evidence = Path(evidence_dir)
    if evidence.is_symlink():
        raise ValueError('evidence directory must not be a symlink')
    summary = load_json(evidence / 'summary.json')
    result = {'schema': 'rust-duty-dx12-progress-summary/v1', 'status': 'incomplete',
              'current_check': None, 'checks': [], 'processes': [], 'active_process': None,
              'total_elapsed_seconds': None, 'timeout_seconds': None, 'frame_count': 0,
              'frame_count_scope': 'maximum reported validated frames in one scenario, not live PNG progress',
              'acceptance_complete': False, 'issues': [],
              'scope': 'Read-only progress snapshot; no Windows, visual or hardware acceptance claim.'}
    if summary is None:
        result['issues'].append('summary.json is missing; evidence is incomplete')
    else:
        if summary.get('schema') != SUMMARY_SCHEMA:
            raise ValueError('unsupported authored summary schema')
        status = summary.get('status')
        if status not in ('running', 'passed', 'failed', 'interrupted'):
            raise ValueError('invalid authored summary status')
        checks = summary.get('checks')
        if not isinstance(checks, list):
            raise ValueError('summary checks must be a list')
        current = summary.get('current_check')
        if current is not None and (not isinstance(current, str) or not current.strip()):
            raise ValueError('current_check must be a nonblank string or null')
        for field in ('passed', 'acceptance_complete', 'budget_exhausted'):
            if field in summary and type(summary[field]) is not bool:
                raise ValueError(f'{field} must be boolean')
        result.update(status=status, current_check=current,
                      total_elapsed_seconds=_elapsed(summary.get('elapsed_seconds'), 'elapsed_seconds'),
                      timeout_seconds=_elapsed(summary.get('run_timeout_seconds'), 'run_timeout_seconds'),
                      acceptance_complete=summary.get('acceptance_complete', False))
        names = set()
        for row in checks:
            if not isinstance(row, dict) or not isinstance(row.get('name'), str) or not row['name'].strip():
                raise ValueError('every check must be an object with a nonblank name')
            name = row['name']
            if name in names:
                raise ValueError(f'duplicate check name: {name}')
            names.add(name)
            passed = row.get('passed')
            if passed is not None and type(passed) is not bool:
                raise ValueError(f'{name}: passed must be boolean or unavailable')
            if 'error' in row and not isinstance(row['error'], str):
                raise ValueError(f'{name}: error must be text')
            if passed is True and 'error' in row:
                raise ValueError(f'{name}: passing check contains an error')
            item = dict(row)
            item.update(status='passed' if passed is True else 'failed' if passed is False or 'error' in row else 'incomplete',
                        elapsed_seconds=_elapsed(row.get('elapsed_seconds'), f'{name}.elapsed_seconds'))
            if 'result' in row and not isinstance(row['result'], dict):
                raise ValueError(f'{name}: result must be an object')
            if name.endswith('/finite-images') and 'frames' in row.get('result', {}):
                frames = _count(row['result']['frames'], f'{name}.frames')
                if passed is True:
                    result['frame_count'] = max(result['frame_count'], frames)
            result['checks'].append(item)
        if status == 'passed' and (summary.get('passed') is not True or not checks or current is not None
                                   or summary.get('budget_exhausted') is True
                                   or any(row['status'] != 'passed' for row in result['checks'])):
            raise ValueError('contradictory passing summary')
    logs = evidence / 'logs'
    if logs.is_symlink():
        raise ValueError('symlinked logs directory')
    if logs.exists():
        if not logs.is_dir():
            raise ValueError('logs must be a directory')
        for folder in sorted(logs.iterdir()):
            if folder.is_symlink():
                raise ValueError(f'symlinked log entry: {folder.name}')
            if not folder.is_dir():
                continue
            row = load_json(folder / 'process.json')
            if row is None:
                result['issues'].append(f'logs/{folder.name}/process.json is missing')
                continue
            if row.get('schema') != PROCESS_SCHEMA or row.get('status') not in (
                    'starting', 'running', 'passed', 'failed', 'timed_out', 'interrupted'):
                raise ValueError(f'{folder.name}: invalid process schema/status')
            for field in ('elapsed_seconds', 'timeout_seconds'):
                _elapsed(row.get(field), f'{folder.name}.{field}', nullable=False)
            for field in ('png_files', 'stdout_bytes', 'stderr_bytes'):
                _count(row.get(field), f'{folder.name}.{field}')
            if row.get('pid') is not None:
                _count(row['pid'], f'{folder.name}.pid')
            if row.get('exit_code') is not None and type(row['exit_code']) is not int:
                raise ValueError('process exit_code must be integer or null')
            if row['status'] == 'passed' and (row.get('exit_code') != 0 or row.get('pid') is None or 'error' in row):
                raise ValueError('passing process needs its PID and clean exit without error')
            if row['status'] == 'running' and (row.get('pid') is None or row.get('exit_code') is not None):
                raise ValueError('running process needs its PID and no exit code')
            process = {**row, 'log_name': folder.name,
                       'process_file': f'logs/{folder.name}/process.json'}
            result['processes'].append(process)
            if folder.name == _process_name(result['current_check']):
                result['active_process'] = process
        # Keep process status separate: a later image validator can fail after
        # a successful process, and a running check is not appended yet.
    observed_logs = {row['log_name'] for row in result['processes']}
    expected_logs = {_process_name(row['name']) for row in result['checks']}
    expected_logs.discard(None)
    for missing in sorted(expected_logs - observed_logs):
        result['issues'].append(f'no process record for completed check in logs/{missing}')
    if result['status'] == 'passed' and (result['issues'] or any(p['status'] != 'passed' for p in result['processes'])):
        result['status'] = 'incomplete'
        result['issues'].append('passing summary lacks matching complete process evidence')
    if report_path is not None:
        data = json.dumps(result, indent=2, allow_nan=False) + '\n'
        write_text_exclusive(report_path, data, create_parents=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence_dir', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    try:
        result = summarize_dx12_progress(args.evidence_dir, args.report)
    except (OSError, ValueError) as error:
        print(f'DX12 progress summary failed: {error}', file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

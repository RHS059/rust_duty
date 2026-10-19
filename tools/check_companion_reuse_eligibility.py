#!/usr/bin/env python3
"""Schedule historical recovery only for matching committed source identities.

This offline precheck does not validate worktree bytes, external Jump source,
archives, generated packs, or native execution. The unchanged recovery workflow
must still perform every original check before using any historical companions.
Only a known committed identity difference is an inapplicable result. Invalid
locks, an unexpected checkout, and Git or I/O errors remain hard failures.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

import revalidate_reused_companions as reuse


SCOPE = ('Committed source identities only; no worktree, external source, pack, '
         'build, or native validation. Original recovery checks remain required.')


def committed_entries(root, commit):
    """Read one exact tree; an absent pinned path is a difference, not a Git error."""
    raw = subprocess.check_output(
        ['git', '-C', str(root), 'ls-tree', '-r', '-t', '-z', '--full-tree', commit],
        timeout=30)
    entries = {}
    for entry in raw.split(b'\0'):
        if not entry:
            continue
        header, separator, path = entry.partition(b'\t')
        fields = header.split()
        reuse.require(separator and path and len(fields) == 3,
                      'malformed Git tree entry')
        mode, kind, identifier = fields
        reuse.require(kind in (b'blob', b'tree', b'commit')
                      and len(mode) == 6 and all(c in b'01234567' for c in mode)
                      and reuse.SHA1.fullmatch(identifier.decode('ascii')),
                      'malformed Git tree identity')
        reuse.require(path not in entries, 'duplicate Git tree path')
        entries[path] = (kind.decode('ascii'), identifier.decode('ascii'))
    return entries


def inspect_sources(root, expected_commit, lock_path):
    root = reuse.no_links(root)
    lock = reuse.read_json(lock_path)
    reuse.validate_lock(lock)
    reuse.require(reuse.SHA1.fullmatch(expected_commit),
                  'expected source commit must be full lowercase SHA')
    reuse.require(reuse.git(root, 'rev-parse', 'HEAD') == expected_commit,
                  'current checkout commit mismatch')
    entries = committed_entries(root, expected_commit)
    mismatches = []
    expected = [('assets', 'tree', lock['eligible_assets_tree'])]
    expected.extend((row['path'], 'blob', row['git_blob'])
                    for row in lock['source_files'])
    for path, kind, identifier in expected:
        actual = entries.get(path.encode('utf-8'))
        if actual != (kind, identifier):
            mismatches.append({'path': path, 'expected_kind': kind,
                               'expected': identifier,
                               'actual_kind': actual[0] if actual else None,
                               'actual': actual[1] if actual else None})
    reuse.require(reuse.git(root, 'rev-parse', 'HEAD') == expected_commit,
                  'checkout changed during source scheduling precheck')
    return {'schema': 'rust-duty-companion-source-scheduling/v1',
            'source_matches': not mismatches,
            'current_source_commit': expected_commit,
            'mismatches': mismatches, 'scope': SCOPE}


def summary(report):
    if report['source_matches']:
        status = ('Committed source matches the historical reuse lock. Recovery '
                  'may be scheduled; all original recovery checks are still required.')
    else:
        status = ('Historical source-bound recovery is inapplicable and is skipped: '
                  'committed source differs from the pinned historical reuse scope.')
    lines = ['## Historical recovery scheduling', '', status, '',
             'Source commit: `' + report['current_source_commit'] + '`.', '',
             SCOPE, '',
             'This precheck produces no validated packs, playable preview, or native evidence.', '',
             'Use the [normal current-source build workflow]'
             '(https://github.com/RHS059/rust_duty/actions/workflows/build.yml) '
             'for this same commit. It generates and validates same-run companions '
             'and, when its own checks succeed, produces the '
             '`Rust-Duty-…-DX12-Preview-Windows-x64` artifact. '
             'A skipped historical recovery does not establish that this artifact exists.']
    if report['mismatches']:
        lines.extend(['', 'Committed identity differences:'])
        for row in report['mismatches']:
            actual = row['actual'] or 'absent'
            lines.append(f"- `{row['path']}`: expected `{row['expected']}`, actual `{actual}`.")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--expected-source-commit', required=True)
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--github-output', type=Path)
    parser.add_argument('--summary', type=Path)
    args = parser.parse_args(argv)
    try:
        report = inspect_sources(args.source_root, args.expected_source_commit, args.lock)
        if args.summary is not None:
            with args.summary.open('a', encoding='utf-8', newline='\n') as stream:
                stream.write(summary(report))
        if args.github_output is not None:
            with args.github_output.open('a', encoding='utf-8', newline='\n') as stream:
                stream.write('source_matches=' + str(report['source_matches']).lower() + '\n')
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f'companion source scheduling precheck failed: {error}', file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

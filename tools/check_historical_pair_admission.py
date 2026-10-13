#!/usr/bin/env python3
"""Cheap scheduling check for the unchanged, closed historical loader pair.

This is not a validation result. Unsupported committed source skips expensive
asset/build jobs; direct pair runners retain their own strict admission checks.
"""
import argparse
import json
import os
from pathlib import Path
import sys

import run_cpu_image_preservation as pair


def inspect(root):
    root = root.resolve()
    commit = pair.git(root, 'rev-parse', 'HEAD').decode().strip()
    expected_commit = os.environ.get('GITHUB_SHA')
    pair.require(not expected_commit or expected_commit == commit,
                 'CI source identity differs from checkout')
    sources = pair.read_sources(root, commit, pair.PRODUCTION_PATHS)
    for name, raw in sources.items():
        path = root / name
        pair.require(path.is_file() and not path.is_symlink() and path.read_bytes() == raw,
                     'Production checkout differs from committed input: ' + name)
    digest = pair.matrix.canonical_hash(pair.hashes(sources))
    admitted = digest == pair.PRODUCTION_MANIFEST
    return {'schema': 'rust-duty-historical-pair-admission/v1', 'source_commit': commit,
            'input_count': len(sources), 'production_manifest_sha256': digest,
            'required_manifest_sha256': pair.PRODUCTION_MANIFEST, 'admitted': admitted,
            'reason': 'exact reviewed production inputs' if admitted else
                      'unsupported source; historical pair skipped before asset production',
            'validation_result': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--github-output', type=Path)
    args = parser.parse_args(argv)
    try:
        result = inspect(args.root)
        print(json.dumps(result, sort_keys=True))
        if args.github_output:
            with args.github_output.open('a', encoding='utf-8') as output:
                output.write('admitted=' + str(result['admitted']).lower() + '\n')
        return 0
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

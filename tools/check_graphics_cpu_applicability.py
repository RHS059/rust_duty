#!/usr/bin/env python3
"""Scope the frozen graphics/CPU native comparison to matching production inputs.

This preflight never reports native success. Source evolution is not applicable;
dirty, incomplete, or unsafe checkouts are errors, as are failures after native
execution starts. The native runner keeps its independent strict source guard.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess

import run_graphics_cpu_contract as native


def assess(repository):
    repository = repository.resolve()
    commit = subprocess.check_output(
        ['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(
        ['git', '-C', str(repository), 'status', '--porcelain', '--untracked-files=all',
         '--', *native.SOURCE_PATHS], text=True)
    native.require(not dirty, 'applicability requires clean committed compile inputs')
    actual = native.read_git_sources(repository, commit)
    # Missing files and untracked compile inputs must fail, rather than becoming
    # an applicability skip. Also retain the independently checked caller bytes.
    inventory = native.current_checkout(repository, actual)
    expected = native.git_sources(repository, native.CANDIDATE_SOURCE)
    native.source_pair(native.git_sources(repository, native.BASELINE_SOURCE), expected)
    differences = []
    for name in sorted(set(actual) | set(expected)):
        raw = actual.get(name)
        compared = raw
        if name == 'src/asset_path.rs' and raw is not None and raw != expected.get(name):
            compared = native.finite_source._asset_path_test_base(raw)
        if compared != expected.get(name):
            differences.append(name)
    applicable = not differences
    return {
        'schema': 'rust-duty-graphics-cpu-applicability/v1',
        'status': 'applicable' if applicable else 'not-applicable',
        'current_source_commit': commit,
        'frozen_candidate_source_commit': native.CANDIDATE_SOURCE,
        'changed_compile_inputs': differences,
        'current_checkout': inventory,
        'native_controls_executed': False,
        'reason': ('Production inputs match the frozen comparison; native controls are required.'
                   if applicable else
                   'Committed production inputs have moved beyond the frozen ebf comparison. '
                   'This historical comparison does not validate the current renderer.'),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    result = assess(args.repository)
    native.shared.write_json(args.output, result)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            stream.write('applicable=' + str(result['status'] == 'applicable').lower() + '\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write('Frozen graphics/CPU comparison: ' + result['status'] + '\n\n'
                         + result['reason'] + '\n\n'
                         + 'Current source: ' + result['current_source_commit'] + '\n'
                         + 'Frozen source: ' + result['frozen_candidate_source_commit'] + '\n')
            if result['changed_compile_inputs']:
                stream.write('Changed compile inputs:\n'
                             + ''.join('- ' + name + '\n' for name in result['changed_compile_inputs']))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

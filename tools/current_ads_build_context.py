#!/usr/bin/env python3
"""Admit only this repository's actual main or same-repository PR build.

The three-key native capture context remains unchanged. This separate identity
binds the caller/event and the PR merge's ordered parents without substituting a
head SHA for GITHUB_SHA or consulting mutable remote branch tips.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

import dx12_authored_shards as shared
import verify_capture_telemetry as telemetry


REPOSITORY = 'RHS059/rust_duty'
SCHEMA = 'rust-duty-current-ads-build-identity/v1'


def require(value, message):
    if not value:
        raise ValueError(message)


def _sha(value, label):
    require(type(value) is str and re.fullmatch(r'[0-9a-f]{40}', value),
            f'{label}: expected an exact lowercase GitHub commit SHA')
    return value


def _repository(value, repository_id, label):
    require(type(value) is dict and value.get('full_name') == REPOSITORY
            and type(value.get('id')) is int and str(value['id']) == repository_id
            and value.get('fork') is False,
            f'{label}: repository identity differs or is a fork')


def current_build_identity():
    """Validate GitHub-provided environment and its original event payload."""
    context = shared.context()
    for name, expected in {
        'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': REPOSITORY,
        'GITHUB_WORKFLOW_SHA': context['source_commit'],
        'RUNNER_OS': 'Windows', 'RUNNER_ARCH': 'X64',
    }.items():
        require(os.environ.get(name) == expected, f'current build identity differs: {name}')
    require(sys.platform == 'win32' and platform.machine() in ('AMD64', 'x86_64'),
            'current source oracle requires native Windows x86_64')
    event_name = os.environ.get('GITHUB_EVENT_NAME')
    require(event_name in ('push', 'workflow_dispatch', 'pull_request'),
            'current source oracle requires a main push/dispatch or same-repository pull request')
    repository_id = os.environ.get('GITHUB_REPOSITORY_ID')
    require(type(repository_id) is str and re.fullmatch(r'[1-9][0-9]*', repository_id),
            'missing actual GitHub repository ID')
    event_path = os.environ.get('GITHUB_EVENT_PATH')
    require(type(event_path) is str and bool(event_path), 'missing original GitHub event payload')
    event_path = Path(event_path)
    require(shared._checked_stat(event_path, 'file').st_size <= 25 * 1024**2,
            'oversized GitHub event payload')
    raw = event_path.read_bytes()
    try:
        event = json.loads(raw, parse_float=telemetry._parse_float,
                           parse_constant=telemetry._reject_constant,
                           object_pairs_hook=telemetry._unique_object)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError(f'invalid GitHub event payload: {error}') from error
    require(type(event) is dict, 'GitHub event payload must be an object')
    _repository(event.get('repository'), repository_id, 'event')
    ref = os.environ.get('GITHUB_REF')
    pull_request = None
    if event_name == 'pull_request':
        number = event.get('number')
        require(type(number) is int and number > 0, 'invalid pull request number')
        require(ref == f'refs/pull/{number}/merge', 'current pull request merge ref differs')
        require(event.get('action') in ('opened', 'reopened', 'synchronize'),
                'pull request action is outside the ordinary build trigger')
        pr = event.get('pull_request')
        require(type(pr) is dict and type(pr.get('number')) is int and pr['number'] == number
                and pr.get('state') == 'open' and pr.get('merged') is False,
                'current build requires the matching open, unmerged pull request')
        require(_sha(pr.get('merge_commit_sha'), 'pull request merge') == context['source_commit'],
                'pull request merge commit differs from actual GitHub SHA')
        sides = {}
        for side in ('head', 'base'):
            value = pr.get(side)
            require(type(value) is dict, f'missing pull request {side}')
            _repository(value.get('repo'), repository_id, f'pull request {side}')
            branch = value.get('ref')
            require(type(branch) is str and bool(branch)
                    and branch == os.environ.get(f'GITHUB_{side.upper()}_REF'),
                    f'pull request {side} ref differs from actual GitHub ref')
            sides[side] = {'repository': REPOSITORY, 'repository_id': repository_id,
                           'ref': branch, 'sha': _sha(value.get('sha'), f'pull request {side}')}
        require(sides['base']['ref'] == 'main' and sides['head']['ref'] != 'main',
                'current pull request must target main from a distinct branch')
        pull_request = {'number': number, 'action': event['action'],
                        'merge_commit_sha': context['source_commit'], **sides}
    else:
        require(ref == 'refs/heads/main', 'current source oracle requires current main')
        require(not os.environ.get('GITHUB_HEAD_REF') and not os.environ.get('GITHUB_BASE_REF')
                and 'pull_request' not in event, 'main build contains a mismatched pull request context')
        if event_name == 'push':
            require(event.get('ref') == ref and event.get('after') == context['source_commit']
                    and event.get('deleted') is False, 'push event differs from the current main commit')
        else:
            require(event.get('ref') in ('main', ref), 'dispatch event differs from current main')
    workflow_ref = REPOSITORY + '/.github/workflows/build.yml@' + ref
    require(os.environ.get('GITHUB_WORKFLOW_REF') == workflow_ref,
            'current source oracle requires the ordinary build workflow at the actual ref')
    return {'schema': SCHEMA, 'capture_context': context, 'repository': REPOSITORY,
            'repository_id': repository_id, 'event_name': event_name, 'ref': ref,
            'workflow_ref': workflow_ref, 'workflow_sha': os.environ['GITHUB_WORKFLOW_SHA'],
            'event_payload_sha256': hashlib.sha256(raw).hexdigest(), 'pull_request': pull_request}


def check_build_checkout(root, identity):
    """Bind the event head/base to the actual merge object, even in shallow CI."""
    require(subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                                   text=True, timeout=60).strip() == identity['capture_context']['source_commit'],
            'current build checkout differs from actual GitHub commit')
    if identity['pull_request'] is not None:
        # `git show --format=%P` hides parents at a depth-one shallow boundary.
        # The raw commit object still exposes its exact ordered parent IDs.
        raw = subprocess.check_output(['git', '--no-replace-objects', '-C', str(root), 'cat-file', '-p',
                                       identity['capture_context']['source_commit']],
                                      timeout=60)
        headers = raw.split(b'\n\n', 1)[0].splitlines()
        parents = [line.removeprefix(b'parent ').decode('ascii') for line in headers if line.startswith(b'parent ')]
        pr = identity['pull_request']
        require(parents == [pr['base']['sha'], pr['head']['sha']],
                'actual pull request merge parents differ from the event base/head')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args(argv)
    identity = current_build_identity()
    check_build_checkout(args.root, identity)
    print(json.dumps(identity, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

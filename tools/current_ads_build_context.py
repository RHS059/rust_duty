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


def _read_event():
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
    return raw, event


def current_build_identity():
    """Validate environment/event fields; check_build_checkout seals the merge."""
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
    raw, event = _read_event()
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
        # The webhook snapshot's merge hint may be null or name an earlier test
        # merge when a synchronize event is delivered. It never selects source.
        # Admission instead requires the actual GITHUB_SHA object and its exact
        # ordered event base/head parents in check_build_checkout below.
        require('merge_commit_sha' in pr, 'missing pull request merge hint')
        merge_hint = pr['merge_commit_sha']
        if merge_hint is not None:
            _sha(merge_hint, 'pull request merge hint')
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
                        'merge_commit_sha': context['source_commit'],
                        'event_merge_commit_sha': merge_hint, **sides}
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


def _checkout_head(root):
    return subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                                   text=True, stderr=subprocess.PIPE, timeout=60).strip()


def _commit_parents(root, source_commit):
    _sha(source_commit, 'actual commit object')
    # `git show --format=%P` hides parents at a depth-one shallow boundary.
    # The raw commit object still exposes its exact ordered parent IDs.
    raw = subprocess.check_output(['git', '--no-replace-objects', '-C', str(root), 'cat-file', '-p', source_commit],
                                  stderr=subprocess.PIPE, timeout=60)
    headers = raw.split(b'\n\n', 1)[0].splitlines()
    return [line.removeprefix(b'parent ').decode('ascii') for line in headers if line.startswith(b'parent ')]


def check_build_checkout(root, identity):
    """Bind the event head/base to the actual merge object, even in shallow CI."""
    require(_checkout_head(root) == identity['capture_context']['source_commit'],
            'current build checkout differs from actual GitHub commit')
    if identity['pull_request'] is not None:
        parents = _commit_parents(root, identity['capture_context']['source_commit'])
        pr = identity['pull_request']
        require(parents == [pr['base']['sha'], pr['head']['sha']],
                'actual pull request merge parents differ from the event base/head')


def admission_diagnostics(root):
    """Read-only, allowlisted diagnostics; never an acceptance or step output."""
    names = ('GITHUB_ACTIONS', 'GITHUB_REPOSITORY', 'GITHUB_REPOSITORY_ID', 'GITHUB_SHA',
             'GITHUB_WORKFLOW_SHA', 'GITHUB_WORKFLOW_REF', 'GITHUB_EVENT_NAME', 'GITHUB_REF',
             'GITHUB_HEAD_REF', 'GITHUB_BASE_REF', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT',
             'RUNNER_OS', 'RUNNER_ARCH', 'CURRENT_ADS_SOURCE_PROOF')
    report = {'schema': SCHEMA + '/diagnostics', 'admitted': False,
              'environment': {name: os.environ.get(name) for name in names}}
    try:
        raw, event = _read_event()
        def scalar(*keys):
            value = event
            for key in keys:
                value = value.get(key) if type(value) is dict else None
            return value if type(value) in (str, int, bool, type(None)) else '<invalid scalar type>'
        paths = [('action',), ('number',), ('ref',), ('after',), ('deleted',),
                 *(('repository', key) for key in ('id', 'full_name', 'fork')),
                 *(('pull_request', key) for key in ('number', 'state', 'merged', 'merge_commit_sha')),
                 *(('pull_request', side, key) for side in ('head', 'base') for key in ('sha', 'ref')),
                 *(('pull_request', side, 'repo', key) for side in ('head', 'base')
                   for key in ('id', 'full_name', 'fork'))]
        report['event'] = {'.'.join(path): scalar(*path) for path in paths}
        report['event_payload_sha256'] = hashlib.sha256(raw).hexdigest()
    except Exception as error:
        report['event_error'] = f'{type(error).__name__}: {error}'
    try:
        head = _checkout_head(root)
        report['checkout'] = {'head': head, 'parents': _commit_parents(root, head)}
    except Exception as error:
        report['checkout_error'] = f'{type(error).__name__}: {error}'
    try:
        identity = current_build_identity()
        check_build_checkout(root, identity)
        report['admitted'] = True
    except Exception as error:
        report['rejection'] = f'{type(error).__name__}: {error}'
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--diagnostics', action='store_true', help='report allowlisted observations before strict admission')
    modes.add_argument('--diagnostics-only', action='store_true', help='report observations without granting admission')
    parser.add_argument('--emit-admission-output', action='store_true', help='emit admitted=true only after strict checks')
    args = parser.parse_args(argv)
    require(not (args.diagnostics_only and args.emit_admission_output),
            'diagnostics-only mode cannot emit an admission output')
    if args.diagnostics or args.diagnostics_only:
        print(json.dumps(admission_diagnostics(args.root), indent=2), flush=True)
    if args.diagnostics_only:
        return 0
    identity = current_build_identity()
    check_build_checkout(args.root, identity)
    if args.emit_admission_output:
        output = os.environ.get('GITHUB_OUTPUT')
        require(type(output) is str and bool(output), 'missing actual GitHub step output path')
        with open(output, 'a', encoding='utf-8', newline='\n') as stream:
            stream.write('admitted=true\n')
    print(json.dumps(identity, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

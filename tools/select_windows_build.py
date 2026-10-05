#!/usr/bin/env python3
"""Select exact-source successful Windows jobs, without waiting on Linux evidence.

Read-only GitHub API calls. No credentials are persisted. Whole-workflow success
is deliberately not a release gate: native Linux captures remain independent.
"""
import json
import os
from pathlib import Path
import re
import subprocess

REPOSITORY = 'RHS059/rust_duty'


def api(endpoint):
    return json.loads(subprocess.check_output(
        ['gh', 'api', f'repos/{REPOSITORY}/{endpoint}'], text=True))


def select(kind, commit, read=api):
    if kind not in ('game', 'launcher') or not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('invalid source selection')
    workflow = 'build.yml' if kind == 'game' else 'updater.yml'
    job_name = 'windows-latest' if kind == 'game' else 'Updater - windows-latest'
    runs = read(f'actions/workflows/{workflow}/runs?head_sha={commit}&event=push&per_page=100')['workflow_runs']
    for run in runs:
        if (run.get('head_sha') != commit or run.get('event') != 'push'
                or run.get('conclusion') in ('cancelled', 'skipped', 'stale', 'timed_out')
                or run.get('head_repository', {}).get('full_name') != REPOSITORY):
            continue
        jobs = []
        page = 1
        while True:
            result = read(f'actions/runs/{run["id"]}/jobs?filter=latest&per_page=100&page={page}')
            jobs.extend(result['jobs'])
            if len(result['jobs']) < 100:
                break
            page += 1
        matches = [j for j in jobs if j.get('name') == job_name]
        if len(matches) == 1 and matches[0].get('status') == 'completed' and matches[0].get('conclusion') == 'success':
            job = matches[0]
            return {'commit': commit, 'run_id': run['id'], 'run_url': run['html_url'],
                    'windows_job_id': job['id'], 'windows_job_url': job['html_url'],
                    'run_attempt': run['run_attempt']}
    raise ValueError(f'No successful exact-source Windows job for {kind} {commit}')


def main():
    selected = {kind: select(kind, os.environ['RELEASE_' + kind.upper() + '_REF'])
                for kind in ('game', 'launcher')}
    Path('SOURCE_PROVENANCE.json').write_text(json.dumps(selected, indent=2) + '\n')
    with open(os.environ['GITHUB_ENV'], 'a') as stream:
        for kind, item in selected.items():
            stream.write(f'{kind.upper()}_RUN_ID={item["run_id"]}\n')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Retrieve one fixed historical game ZIP in CI; never extract or execute it.

The ephemeral token goes only to GitHub through the existing retrieval helpers.
Redirect locations and credentials are neither logged nor retained. No alternate
artifact, run, repository or caller-supplied download URL is accepted.
"""
import argparse
import json
import os
from pathlib import Path

import fetch_source_bound_companions as retrieval
from run_legacy_facade_equivalence import REFERENCE, REFERENCE_IDENTITY
from run_dx12_authored import write_json
from run_windows_same_platform_return import require
from verify_capture_telemetry import _compare

SCHEMA = 'rust-duty-legacy-facade-reference/v1'


def metadata_identity(run, artifact):
    require(isinstance(run,dict) and isinstance(artifact,dict), 'GitHub metadata objects required')
    expected_run = {'id':REFERENCE['run_id'], 'run_attempt':REFERENCE['run_attempt'],
                    'run_number':REFERENCE['run_number'], 'head_sha':REFERENCE['source_commit'],
                    'head_branch':'main', 'event':'push', 'status':'completed', 'conclusion':'success',
                    'path':'.github/workflows/build.yml'}
    actual_run = {k:run.get(k) for k in expected_run}
    _compare(actual_run,expected_run,'historical run identity')
    for field in ('repository','head_repository'):
        require(isinstance(run.get(field),dict) and run[field].get('full_name')==REFERENCE['repository'],
                'historical repository identity differs')
    expected_artifact = {'id':REFERENCE['artifact_id'],
        'name':f"Rust-Duty-{REFERENCE_IDENTITY['display_version']}-Windows-x64",
        'size_in_bytes':REFERENCE['zip_bytes'], 'expired':False,
        'digest':'sha256:'+REFERENCE['zip_sha256']}
    actual_artifact = {k:artifact.get(k) for k in expected_artifact}
    _compare(actual_artifact,expected_artifact,'historical artifact identity')
    origin = artifact.get('workflow_run')
    require(isinstance(origin,dict), 'artifact origin missing')
    expected_origin = {'id':REFERENCE['run_id'], 'head_sha':REFERENCE['source_commit'], 'head_branch':'main'}
    _compare({k:origin.get(k) for k in expected_origin},expected_origin,'artifact source/run identity')
    # Retain only checked scalar provenance, never URLs or arbitrary API fields.
    return {'run':actual_run,'artifact':actual_artifact,'artifact_origin':expected_origin}


def fetch(output, token):
    require(isinstance(token,str) and bool(token.strip()), 'ephemeral job GITHUB_TOKEN required')
    output = Path(output)
    require(not output.exists() and not output.is_symlink(), 'fresh reference directory required')
    output.mkdir(parents=True,exist_ok=False)
    report = {'schema':SCHEMA,'passed':False,'reference':dict(REFERENCE),
              'zip_digest_verified':False,'extracted':False,'executed':False}
    api = '/repos/'+REFERENCE['repository']
    try:
        run = retrieval.api_json(f"{api}/actions/runs/{REFERENCE['run_id']}/attempts/{REFERENCE['run_attempt']}",token)
        artifact = retrieval.api_json(f"{api}/actions/artifacts/{REFERENCE['artifact_id']}",token)
        report['metadata'] = metadata_identity(run,artifact)
        destination = output/f"{REFERENCE['artifact_id']}.zip"
        retrieval.download(f"{api}/actions/artifacts/{REFERENCE['artifact_id']}/zip",token,destination,
                           REFERENCE['zip_bytes'],REFERENCE['zip_sha256'])
        report.update(passed=True,zip_digest_verified=True,filename=destination.name)
    except Exception:
        # Exceptions can contain a signed redirect URL. Never interpolate them.
        report['error'] = 'Pinned historical artifact retrieval failed; no alternate retrieval attempted.'
        raise ValueError(report['error']) from None
    finally:
        write_json(output/'reference-metadata.json',report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args(argv)
    try:result = fetch(args.output,os.environ.get('GITHUB_TOKEN'))
    except Exception:
        print('Pinned historical artifact retrieval failed; no facade equivalence established.')
        return 1
    print(json.dumps({'passed':True,'artifact_id':REFERENCE['artifact_id'],
                      'zip_digest_verified':result['zip_digest_verified']}))
    return 0


if __name__ == '__main__':raise SystemExit(main())

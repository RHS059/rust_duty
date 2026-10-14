#!/usr/bin/env python3
"""CI-only retrieval of pinned existing GitHub artifacts; never generates assets.

Uses the job's ephemeral GITHUB_TOKEN only at api.github.com. Redirected blob
requests contain no Authorization header; signed locations are never printed.
API contract: https://docs.github.com/en/rest/actions/artifacts#download-an-artifact
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from revalidate_reused_companions import ARTIFACT_KEYS, read_json, require, validate_lock


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api_request(path, token, *, raw=False):
    require(path.startswith('/repos/RHS059/rust_duty/'), 'API destination outside assigned repository')
    return urllib.request.Request('https://api.github.com' + path, headers={
        'Authorization': 'Bearer ' + token, 'User-Agent': 'Rust-Duty-source-bound-recovery',
        'Accept': 'application/vnd.github.raw+json' if raw else 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28'})


def redirected_request(location):
    parsed = urllib.parse.urlsplit(location)
    require(parsed.scheme == 'https' and parsed.hostname and not parsed.username
            and not parsed.password and parsed.port in (None, 443), 'unsafe artifact redirect')
    # The location was supplied by authenticated GitHub for the exact artifact.
    # A separate request deliberately has no token or inherited API headers.
    return urllib.request.Request(location, headers={'User-Agent': 'Rust-Duty-source-bound-recovery'})


def open_api(path, token, *, raw=False):
    opener = urllib.request.build_opener(NoRedirect())
    try:
        return opener.open(api_request(path, token, raw=raw), timeout=60)
    except urllib.error.HTTPError as error:
        if error.code != 302:
            raise ValueError(f'GitHub retrieval failed with HTTP {error.code}') from None
        location = error.headers.get('Location')
        require(isinstance(location, str), 'artifact redirect missing')
        try:
            return urllib.request.build_opener(NoRedirect()).open(redirected_request(location), timeout=60)
        except (urllib.error.URLError, OSError):
            raise ValueError('redirected artifact retrieval failed') from None


def api_json(path, token):
    with open_api(path, token) as response:
        data = response.read(2 * 1024 * 1024 + 1)
    require(len(data) <= 2 * 1024 * 1024, 'oversized GitHub metadata')
    return json.loads(data)


def download(path, token, destination, size, expected_hash, *, raw=False):
    require(type(size) is int and 0 < size <= 128 * 1024**2, 'invalid pinned download size')
    digest, total = hashlib.sha256(), 0
    with open_api(path, token, raw=raw) as response, Path(destination).open('xb') as output:
        while block := response.read(1024 * 1024):
            total += len(block)
            require(total <= size, 'download exceeds pinned byte count')
            digest.update(block)
            output.write(block)
    require(total == size and digest.hexdigest() == expected_hash, 'download differs from pinned bytes')


def check_artifact(metadata, expected, origin):
    require(metadata.get('id') == expected['artifact_id']
            and metadata.get('name') == expected['name']
            and metadata.get('size_in_bytes') == expected['size_bytes']
            and metadata.get('expired') is False
            and metadata.get('digest') == 'sha256:' + expected['zip_sha256'], 'artifact identity/digest mismatch')
    run = metadata.get('workflow_run', {})
    require(run.get('id') == origin['run_id'] and run.get('head_sha') == origin['head_sha'],
            'artifact belongs to another origin run or source')


def fetch(lock_path, output, token):
    require(token, 'ephemeral job GITHUB_TOKEN is required; no credential is generated')
    lock = read_json(lock_path)
    validate_lock(lock)
    origin = lock['origin']
    require(origin['repository'] == 'RHS059/rust_duty', 'unexpected origin repository')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    api = '/repos/RHS059/rust_duty'
    run = api_json(f'{api}/actions/runs/{origin["run_id"]}/attempts/{origin["run_attempt"]}', token)
    require(run.get('id') == origin['run_id'] and run.get('run_attempt') == origin['run_attempt']
            and run.get('head_sha') == origin['head_sha'] and run.get('status') == 'completed',
            'origin run identity mismatch')
    records = []
    for item in lock['artifacts']:
        metadata = api_json(f'{api}/actions/artifacts/{item["artifact_id"]}', token)
        check_artifact(metadata, item, origin)
        download(f'{api}/actions/artifacts/{item["artifact_id"]}/zip', token,
                 output / f'{item["artifact_id"]}.zip', item['size_bytes'], item['zip_sha256'])
        (output / f'{item["kind"]}-github-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
        records.append({key: item[key] for key in ARTIFACT_KEYS})
    jump = lock['jump_source']
    path = urllib.parse.quote(jump['path'], safe='/')
    download(f'{api}/contents/{path}?ref={jump["commit"]}', token,
             output / 'halcyon_jump.blend', jump['bytes'], jump['sha256'], raw=True)
    (output / 'origin.json').write_text(json.dumps({'schema': 'rust-duty-companion-origin/v1',
        'origin': origin, 'artifacts': records}, indent=2) + '\n', encoding='utf-8')
    (output / 'origin-run.json').write_text(json.dumps(run, indent=2) + '\n', encoding='utf-8')
    return {'downloaded_original_artifacts': len(records), 'generation_reused': True,
            'new_generation': False, 'zip_digests_verified': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(fetch(args.lock, args.output, os.environ.get('GITHUB_TOKEN')), indent=2))
    except (ValueError, OSError, KeyError, TypeError, urllib.error.URLError):
        # Do not expose redirect URLs, request headers or credentials in logs.
        print('Pinned artifact retrieval failed; no reuse or native acceptance established.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

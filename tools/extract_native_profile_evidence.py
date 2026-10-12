#!/usr/bin/env python3
"""Copy four pinned source diagnostics without replaying or accepting the profile.

Only the workflow retrieves data, using one immutable Actions artifact ID after
provider verification. This helper has no network, build, renderer, oracle,
artifact selector, or inventory-expansion route. The packet's inventory remains
an original reference: its companion files are intentionally absent here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

REPOSITORY = 'RHS059/rust_duty'
WORKFLOW = '.github/workflows/native-profile-evidence.yml'
SOURCE_WORKFLOW = '.github/workflows/revalidate-ads-source.yml'
ARTIFACT_ID = 11396831337
ARTIFACT_NAME = 'ads-source-revalidation-evidence-attempt-1'
ARTIFACT_BYTES = 1001472843
ARTIFACT_DIGEST = 'sha256:706a9e1da213c6649fd51926687eb5d394b972d3575ccae2a2d0b048bf825959'
SOURCE_CONTEXT = {'source_commit': '371bca3d848f5b749cf9ea989fa1fbfaca8c20cc',
                  'run_id': '37427554951', 'run_attempt': '1'}
CAPTURE_CONTEXT = {'source_commit': '8f571464be706d0abde862e124582a188f633baf',
                   'run_id': '37415102452', 'run_attempt': '1'}
COMPILER_SHA256 = '5477f9bad65b15c4c5b31fc050fc72feba651ea1b330bc75cf356a4d6b0fbc80'
PACKET = 'evidence/source-oracle/packet/'
# None means an independently pinned digest plus the conservative JSON byte bound.
FILES = {
    PACKET + 'source-packet.json': (None, 'ea0ec96d38c7f2269a1735fb666ef2945283c24f00dae9cc4f75c03ad13f0065'),
    PACKET + 'source-receipt.json': (48135, '241bb21d23bb711daaff9dac33b75b504e1c69104fa0949099b38f0f86453370'),
    PACKET + 'oracle-output/frames-opengl.jsonl': (9579381, '93d730d84e5f0055cd51e4e613f7210974ae7a4682bdb7e7f8e246d3ad1227ca'),
    PACKET + 'oracle-output/frames-dx12.jsonl': (9585202, 'cba85f192290beb1686c35b11bc923b1eeb4a1ca2c855f71c273e62c1d9aa896'),
}
UNPROVEN_FLAGS = ('backend_native_upload_identity_verified', 'native_invocation_binding_verified',
                  'profile_assumptions_independently_established', 'profile_native_verified')
MAX_JSON_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 31 * 1024 * 1024
METADATA = Path('evidence/profile-extraction-provider.json')
INPUT = Path('downloaded/source-profile-input')
OUTPUT = Path('evidence/native-profile-bounded')
PROVENANCE = 'extraction-provenance.json'
_WINDOWS_STAT = os.name == 'nt'


def require(value, message):
    if not value:
        raise ValueError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(path):
    path = Path(path)
    require('..' not in path.parts and '\\' not in path.as_posix(), 'unsafe path')
    path = path.absolute()
    for ancestor in (*reversed(path.parents), path):
        try:
            info = ancestor.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode) and not (
            getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT),
            f'symlink/reparse point rejected: {ancestor}')
    return path


def read_regular(path, limit):
    path = safe_path(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
            f'not a single-link regular file: {path}')
    require(0 < before.st_size <= limit, f'file byte bound: {path}')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    current = path.lstat()
    keys = ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    changed = f'file changed while reading: {path}'
    # Compare each API with itself, retaining full-precision change detection.
    require(len(data) == before.st_size and all(
        getattr(left, key) == getattr(right, key)
        for left, right in ((before, current), (opened, after)) for key in keys), changed)
    cross_keys = keys
    if _WINDOWS_STAT:
        # CPython 3.12 lstat reports creation time as ctime, but fstat reports
        # ChangeTime. Also, only path stat synthesizes executable mode bits.
        # Bind the two views with birthtime and the remaining exact metadata;
        # neither ctime nor mode is omitted from the same-API checks above.
        cross_keys = tuple(key for key in keys if key not in ('st_mode', 'st_ctime_ns')) + ('st_birthtime_ns',)
        executable = 0o111 if path.suffix.lower() in ('.exe', '.bat', '.cmd', '.com') else 0
        require(before.st_mode == (opened.st_mode | executable), changed)
    require(all(getattr(before, key) == getattr(opened, key) for key in cross_keys), changed)
    return data


def caller_identity(root, environ):
    expected = {'GITHUB_ACTIONS': 'true', 'GITHUB_SERVER_URL': 'https://github.com',
                'GITHUB_REPOSITORY': REPOSITORY, 'GITHUB_REF': 'refs/heads/main',
                'GITHUB_EVENT_NAME': 'push', 'GITHUB_RUN_ATTEMPT': '1',
                'GITHUB_WORKFLOW_REF': f'{REPOSITORY}/{WORKFLOW}@refs/heads/main'}
    require(all(environ.get(key) == value for key, value in expected.items()),
            'requires exact main push workflow, first attempt')
    source = environ.get('GITHUB_SHA', '')
    run_id = environ.get('GITHUB_RUN_ID', '')
    require(re.fullmatch(r'[0-9a-f]{40}', source) and environ.get('GITHUB_WORKFLOW_SHA') == source,
            'caller workflow/source mismatch')
    require(re.fullmatch(r'[1-9][0-9]*', run_id), 'invalid extraction run ID')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=root, text=True)
    require(head == source and not dirty, 'requires clean checkout of caller commit')
    return {'repository': REPOSITORY, 'workflow': WORKFLOW, 'source_commit': source,
            'run_id': run_id, 'run_attempt': '1', 'event': 'push', 'branch': 'main'}


def verify_provider(metadata):
    """Fail closed on both immutable artifact identity and the original attempt."""
    require(set(metadata) == {'artifact', 'attempt'}, 'provider metadata envelope mismatch')
    artifact, attempt = metadata['artifact'], metadata['attempt']
    expected_artifact = {'id': ARTIFACT_ID, 'name': ARTIFACT_NAME,
                         'size_in_bytes': ARTIFACT_BYTES, 'digest': ARTIFACT_DIGEST, 'expired': False}
    require(all(type(artifact.get(key)) is type(value) and artifact.get(key) == value
                for key, value in expected_artifact.items()), 'artifact metadata mismatch')
    expected_attempt = {'id': int(SOURCE_CONTEXT['run_id']), 'run_attempt': 1,
                        'head_sha': SOURCE_CONTEXT['source_commit'], 'head_branch': 'main',
                        'path': SOURCE_WORKFLOW, 'status': 'completed', 'conclusion': 'success'}
    require(all(type(attempt.get(key)) is type(value) and attempt.get(key) == value
                for key, value in expected_attempt.items()), 'source attempt mismatch')
    repository, head_repository = (attempt.get(key, {}) for key in ('repository', 'head_repository'))
    require(repository.get('full_name') == REPOSITORY and head_repository.get('full_name') == REPOSITORY,
            'source repository mismatch')
    repo_id = repository.get('id')
    require(type(repo_id) is int and repo_id > 0 and head_repository.get('id') == repo_id,
            'source repository ID mismatch')
    workflow_run = artifact.get('workflow_run', {})
    expected_run = {'id': int(SOURCE_CONTEXT['run_id']), 'repository_id': repo_id,
                    'head_repository_id': repo_id, 'head_sha': SOURCE_CONTEXT['source_commit'],
                    'head_branch': 'main'}
    require(all(type(workflow_run.get(key)) is type(value) and workflow_run.get(key) == value
                for key, value in expected_run.items()), 'artifact workflow context mismatch')
    return {'repository': REPOSITORY, 'repository_id': repo_id, 'artifact': expected_artifact,
            'source_execution_context': dict(SOURCE_CONTEXT), 'workflow': SOURCE_WORKFLOW,
            'status': 'completed', 'conclusion': 'success', 'branch': 'main',
            'artifact_digest_verification': 'provider metadata equals pinned digest; selected file bytes separately SHA256 verified'}


def validate_documents(selected):
    receipt = json.loads(selected[PACKET + 'source-receipt.json'])
    packet = json.loads(selected[PACKET + 'source-packet.json'])
    require(receipt.get('schema') == 'rust-duty-source-visibility-certificates-binding/v1', 'receipt schema mismatch')
    require(receipt.get('source_execution_context') == SOURCE_CONTEXT and
            receipt.get('capture_context') == CAPTURE_CONTEXT and
            receipt.get('source_base_commit') == CAPTURE_CONTEXT['source_commit'] and
            receipt.get('capture_rustc_sha256') == COMPILER_SHA256, 'receipt provenance mismatch')
    require('acceptance_verdict' in receipt and receipt['acceptance_verdict'] is None,
            'original acceptance verdict must remain null')
    require(packet.get('schema') == 'rust-duty-ads-source-packet/v1' and
            packet.get('receipt') == 'source-receipt.json' and
            packet.get('source_outputs') == {'windows-legacy': 'oracle-output/frames-opengl.jsonl',
                                             'dx12': 'oracle-output/frames-dx12.jsonl'}, 'packet references mismatch')
    require(all(packet.get('capture_binding', {}).get(key) == value for key, value in CAPTURE_CONTEXT.items()),
            'packet capture context mismatch')
    before = receipt.get('inputs_and_implementation_before')
    require(isinstance(before, dict) and before and before == receipt.get('inputs_and_implementation_after'),
            'receipt before/after inventory mismatch')
    require(before.get('oracle-output/rustc-Vv.txt', {}).get('sha256') == COMPILER_SHA256,
            'receipt compiler inventory mismatch')
    for backend in ('opengl', 'dx12'):
        relative = PACKET + f'oracle-output/frames-{backend}.jsonl'
        data = selected[relative]
        lines = data.splitlines()
        require(len(lines) == 554, f'{backend}: expected header and all 553 frames')
        header = json.loads(lines[0])
        report = receipt.get('backend_reports', {}).get(backend, {})
        require(report.get('exit_code') == 0 and report.get('output') ==
                {'bytes': len(data), 'sha256': sha256(data)} and report.get('header') == header,
                f'{backend}: output/receipt mismatch')
        require(header.get('schema') == 'rust-duty-source-visibility-certificate-diagnostic/v2' and
                header.get('expected_frames') == 553 and 'acceptance_verdict' in header and
                header['acceptance_verdict'] is None and all(header.get(key) is False for key in UNPROVEN_FLAGS),
                f'{backend}: conditional flags must remain false and verdict null')
        require([json.loads(line).get('frame') for line in lines[1:]] == list(range(553)),
                f'{backend}: frame sequence mismatch')
    return receipt


def verify_output(output, expected):
    actual = set()
    for directory, dirs, files in os.walk(safe_path(output), followlinks=False):
        for name in dirs:
            require(stat.S_ISDIR(safe_path(Path(directory) / name).lstat().st_mode), 'unexpected output directory')
        for name in files:
            path = safe_path(Path(directory) / name)
            relative = path.relative_to(output).as_posix()
            require(relative in expected, f'unexpected output file: {relative}')
            require(read_regular(path, MAX_TOTAL_BYTES) == expected[relative], f'output bytes mismatch: {relative}')
            actual.add(relative)
    require(actual == set(expected), 'closed output inventory mismatch')


def package(root, metadata, caller):
    provider = verify_provider(metadata)
    source = safe_path(root / INPUT)
    output = safe_path(root / OUTPUT)
    require(not output.exists(), 'output must be fresh')
    selected = {}
    for relative, (expected_size, expected_hash) in FILES.items():
        limit = MAX_TOTAL_BYTES if relative.endswith('.jsonl') else MAX_JSON_BYTES
        data = read_regular(source / relative, limit)
        require((expected_size is None or len(data) == expected_size) and sha256(data) == expected_hash,
                f'pinned file length/hash mismatch: {relative}')
        selected[relative] = data
    receipt = validate_documents(selected)
    provenance = {'schema': 'rust-duty-native-profile-evidence-extraction/v1',
                  'extraction_context': caller, 'source_provider': provider,
                  'capture_context': receipt['capture_context'], 'capture_rustc_sha256': COMPILER_SHA256,
                  'source_execution_context': receipt['source_execution_context'],
                  'files': {name: {'bytes': len(data), 'sha256': sha256(data)} for name, data in selected.items()},
                  'scope': 'Unchanged source packet, receipt, and two conditional source-output JSONLs only. '
                           'Original inventory references are preserved but inventory/companion files are not included.',
                  'new_oracle_execution': False, 'new_native_capture': False,
                  'profile_native_verified': False, 'acceptance_verdict': None,
                  'full_input_artifact_preserved': True, 'maximum_output_bytes': MAX_TOTAL_BYTES}
    selected[PROVENANCE] = (json.dumps(provenance, indent=2, sort_keys=True) + '\n').encode()
    require(sum(map(len, selected.values())) <= MAX_TOTAL_BYTES, 'total byte bound including provenance exceeded')
    output.mkdir(parents=True, exist_ok=False)
    for relative, data in selected.items():
        destination = safe_path(output / relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
    verify_output(output, selected)
    return provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['verify-provider', 'package'])
    args = parser.parse_args()
    root = safe_path(Path.cwd())
    caller = caller_identity(root, os.environ)
    metadata = json.loads(read_regular(root / METADATA, MAX_JSON_BYTES))
    if args.command == 'verify-provider':
        print(json.dumps(verify_provider(metadata), sort_keys=True))
    else:
        result = package(root, metadata, caller)
        print(json.dumps({'output': str(OUTPUT), 'files': result['files'],
                          'profile_native_verified': False, 'acceptance_verdict': None}, sort_keys=True))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Revalidate only ebf/run37490373763/attempt1 using its completed source packet.

No compiler, game, renderer or source replay is launched. Original receipts and
verdicts stay immutable. The actual caller is the verifier, never the capture.
The existing reviewed ADS leaf and full nine-shard aggregate decide acceptance.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import zipfile

import ads_source_visibility_binding as binding
import aggregate_dx12_authored as aggregate
import build_ads_source_packet as producer
import dx12_authored_shards as shared
import finite_ads_profile_binding as finite
import prepare_ads_source_oracle as prepared
import recover_ads_source_aggregate as recovery
import revalidate_ads_offset as leaf
from verify_capture_telemetry import _compare, read_record

CAPTURE = {'source_commit': 'ebf4bcb7f489766e3c7ec188c35db9bb4146c62b',
           'run_id': '37490373763', 'run_attempt': '1'}
REPOSITORY = 'RHS059/rust_duty'
REPOSITORY_ID = 1398577887
WORKFLOW = '.github/workflows/revalidate-ebf-authored-packet.yml'
CLASS_SHA256 = '91bd0030157ff8e1b4e70127b028e57543d8fc91fb3b6cc1202c4707491fb798'
PINS = read_record(Path(__file__).with_name('ebf_authored_packet_pins.json'))
ORACLE_PREFIX = 'evidence/current-ads-source/oracle-output/'
require = producer.require
checked_bytes = recovery.checked_bytes
write_bytes = recovery.write_bytes


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'metadata timestamp lacks timezone')
    return parsed


def pinned_fields(record, expected, label):
    require(type(record) is dict, f'{label}: missing object')
    _compare({key: record.get(key) for key in expected}, expected, label)


def select_artifacts(catalog, *, now=None):
    """Validate complete original-attempt metadata before requesting any bytes."""
    require(type(catalog) is dict, 'missing original artifact catalog')
    run = catalog['attempt']
    pinned_fields(run, PINS['attempt'], 'pinned original attempt')
    for key in ('repository', 'head_repository'):
        pinned_fields(run[key], {'id': REPOSITORY_ID, 'full_name': REPOSITORY}, key)
    start, end = timestamp(run['run_started_at']), timestamp(run['updated_at'])
    require(start <= end, 'invalid original attempt interval')
    now = now or datetime.now(timezone.utc)
    require(now.tzinfo is not None, 'artifact check time must have a timezone')
    require(catalog['jobs_context'] == CAPTURE, 'job listing used another capture attempt')
    for key, complete, total in (('artifacts', 'complete', 'total_count'),
                                 ('jobs', 'jobs_complete', 'jobs_total_count')):
        records = catalog[key]
        require(type(records) is list and 0 < len(records) <= 2000 and catalog[complete] is True
                and type(catalog[total]) is int and catalog[total] == len(records),
                f'{key}: incomplete or oversized listing')
        ids = [record.get('id') for record in records]
        require(all(type(value) is int and value > 0 for value in ids)
                and len(set(ids)) == len(ids), f'{key}: invalid or aliased IDs')
    for key, expected in PINS['jobs'].items():
        matches = [job for job in catalog['jobs'] if job.get('name') == expected['name']]
        require(len(matches) == 1, f'{key}: original job missing or ambiguous')
        pinned_fields(matches[0], expected, f'{key}: original job metadata')
        require(start <= timestamp(matches[0]['started_at']) <= timestamp(matches[0]['completed_at']) <= end,
                f'{key}: job time outside original attempt')
    expected_shards = {item['name'] for key, item in PINS['artifacts'].items() if key.startswith('shards/')}
    actual_shards = {item['name'] for item in catalog['artifacts']
                     if item['name'].startswith('dx12-authored-shard-')
                     and item['name'].endswith('-evidence-attempt-1')}
    require(actual_shards == expected_shards, 'unexpected or missing original authored shard')
    selected = {}
    for destination, expected in PINS['artifacts'].items():
        name = expected['name']
        matches = [item for item in catalog['artifacts'] if item.get('name') == name]
        require(len(matches) == 1, f'expected exactly one artifact named {name}')
        item = matches[0]
        require(item['id'] not in producer.DENIED_ARTIFACT_IDS, 'artifact denied under authorized access scope')
        pinned_fields(item, expected, f'{name}: pinned artifact metadata')
        require(item.get('expired') is False and timestamp(item['expires_at']) > now, f'{name}: artifact expired')
        require(start <= timestamp(item['created_at']) <= timestamp(item['updated_at']) <= end,
                f'{name}: artifact outside original attempt')
        require(type(item['size_in_bytes']) is int and 0 < item['size_in_bytes'] <= 4 * 1024**3
                and re.fullmatch(r'sha256:[0-9a-f]{64}', item['digest']), f'{name}: invalid archive size/digest')
        selected[destination] = item
    require(len(selected) == 23, 'all 23 pinned artifacts are required')
    return selected


def recover_anchors(inputs_log, aggregate_log):
    """Use only original job logs; candidate packet contents cannot set anchors."""
    logs = {}
    for key, raw in (('inputs', inputs_log), ('aggregate', aggregate_log)):
        require(type(raw) is bytes and 0 < len(raw) <= 32 * 1024**2, f'{key}: missing or oversized original log')
        _compare({'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}, PINS['logs'][key],
                 f'{key}: original job log hash')
        logs[key] = [re.sub(r'^\d{4}-\d{2}-\d{2}T\S+\s+', '', line) for line in raw.decode('utf-8').splitlines()]
    pattern = (r'authored-dual-release-v1-Windows-X64-([0-9a-f]{64})-([0-9a-f]{64})-'
               + CAPTURE['source_commit'] + r'(?![0-9a-f])')
    fingerprints = set(re.findall(pattern, inputs_log.decode('utf-8')))
    require(len(fingerprints) == 1, 'original compiler cache fingerprint is missing or conflicting')
    compiler_sha, lock_sha = next(iter(fingerprints))
    candidates = set()
    for index, line in enumerate(logs['inputs']):
        if re.match(r'^rustc \d+\.\d+\.\d+ \(', line):
            block = tuple(logs['inputs'][index:index + 7])
            if len(block) == 7 and hashlib.sha256(('\n'.join(block) + '\n').encode()).hexdigest() == compiler_sha:
                candidates.add(block)
    require(len(candidates) == 1, 'original seven-line compiler stdout does not match its cache fingerprint')
    verbose = list(next(iter(candidates)))
    compiler = ('\n'.join(verbose) + '\n').encode()
    toolchain = prepared.compiler_identity(compiler, compiler_sha)
    result = {'capture_context': dict(CAPTURE), 'rustc_sha256': compiler_sha, 'cache_lock_sha256': lock_sha,
              'toolchain': toolchain, 'rustc_verbose_lines': verbose,
              'original_job_logs': PINS['logs'], 'original_jobs': PINS['jobs']}
    for key, prefix, field in (('inputs', 'PRECOMPILED_ORACLE_RECEIPT_SHA256', 'precompiled_receipt_sha256'),
                                ('aggregate', 'INDEPENDENT_SOURCE_RECEIPT_SHA256', 'source_receipt_sha256')):
        values = [line[len(prefix) + 1:] for line in logs[key] if line.startswith(prefix + '=')]
        require(len(values) == 1 and re.fullmatch('[0-9a-f]{64}', values[0]), f'{key}: missing or conflicting {prefix}')
        result[field] = values[0]
    require('ValueError: unreviewed production file added' in logs['aggregate'],
            'original source-proof rejection differs')
    require(any('ads-offset: required successful check missing: windows-legacy/finite-images' in line
                for line in logs['aggregate']), 'original aggregate failure was not retained')
    return result


def current_verifier(root):
    context = shared.context()
    for name, expected in {
        'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': REPOSITORY,
        'GITHUB_REPOSITORY_ID': str(REPOSITORY_ID), 'GITHUB_REF': 'refs/heads/main',
        'GITHUB_WORKFLOW_REF': REPOSITORY + '/' + WORKFLOW + '@refs/heads/main',
        'GITHUB_WORKFLOW_SHA': context['source_commit'],
    }.items():
        require(os.environ.get(name) == expected, f'actual verifier identity differs: {name}')
    require(os.environ.get('GITHUB_EVENT_NAME') in ('push', 'workflow_dispatch'), 'unsupported verifier event')
    require(context != CAPTURE and context['run_id'] != CAPTURE['run_id'], 'verifier cannot impersonate original capture')
    check_checkout(root, context['source_commit'])
    return context


def check_checkout(root, expected):
    shared._checked_root(root)
    no_link_parents(root)
    require(subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True, timeout=60).strip() == expected,
            'source checkout differs from its recorded commit')
    require(not subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=no'], timeout=60),
            'tracked checkout is modified')


def no_link_parents(path):
    for parent in path.absolute().parents:
        if parent.exists() or parent.is_symlink():
            shared._checked_stat(parent, 'directory')


def compare_production(capture_root, verifier_root):
    """Only the previously reviewed exact asset-path cfg(test) repair may differ."""
    original, current = producer.production_files(capture_root), producer.production_files(verifier_root)
    require(original.keys() == current.keys(), 'current production file set differs from original ebf')
    results = {}
    for name in original:
        before, after = checked_bytes(original[name]), checked_bytes(current[name])
        if Path(name).suffix in ('.rs', '.toml', '.lock', '.wgsl'):
            before, after = finite._lf(before), finite._lf(after)
        if name == 'src/asset_path.rs':
            before, after = finite._asset_path_test_base(before), finite._asset_path_test_base(after)
        require(before == after, f'current production differs outside exact reviewed test repair: {name}')
        results[name] = {'capture': producer.digest(original[name]), 'verifier': producer.digest(current[name])}
    return results


def extract_archive(archive, destination, metadata):
    """Fail on checksum errors before extracting; never follow archive links."""
    _compare(producer.digest(archive), {'bytes': metadata['size_in_bytes'],
             'sha256': metadata['digest'].removeprefix('sha256:')}, 'downloaded archive')
    require(not destination.exists() and not destination.is_symlink(), 'archive destination already exists')
    no_link_parents(destination)
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        require(0 < len(entries) <= 100000, 'archive entry count is invalid')
        names, seen, total = set(), {}, 0
        for entry in entries:
            name = entry.filename.removesuffix('/') if entry.is_dir() else entry.filename
            shared._safe_key(name)
            require(name not in names, 'duplicate archive member')
            names.add(name)
            kind = stat.S_IFMT(entry.external_attr >> 16)
            require(kind in ((0, stat.S_IFDIR) if entry.is_dir() else (0, stat.S_IFREG)), 'archive contains nonregular member')
            require(not entry.flag_bits & 1 and entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                    'encrypted or unsupported archive compression')
            require(0 <= entry.file_size <= 256 * 1024**2, 'archive member exceeds size bound')
            total += entry.file_size
            require(total <= 8 * 1024**3, 'archive decoded size exceeds bound')
            parts = name.split('/')
            for length in range(1, len(parts) + 1):
                prefix = '/'.join(parts[:length])
                entry_kind = 'directory' if length < len(parts) or entry.is_dir() else 'file'
                previous = seen.get(prefix.casefold())
                require(previous is None or previous == (prefix, entry_kind), 'archive path alias or file/directory conflict')
                seen[prefix.casefold()] = (prefix, entry_kind)
        destination.mkdir(parents=True)
        for entry in entries:
            target = destination / entry.filename
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(entry) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output, length=1024**2)
            require(target.stat().st_size == entry.file_size, 'extracted archive member is incomplete')
    _compare(producer.digest(archive), {'bytes': metadata['size_in_bytes'],
             'sha256': metadata['digest'].removeprefix('sha256:')}, 'archive changed during extraction')
    return shared.inventory_files(destination, exclude=())


def gh_read(endpoint, destination):
    # The only remote endpoint family here is read-only GitHub Actions. A denied
    # read fails once and is never routed through another download path.
    require(endpoint.startswith(f'/repos/{REPOSITORY}/actions/'), 'unexpected GitHub read endpoint')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as output:
        subprocess.run(['gh', 'api', '--allow-escape-sequences', endpoint], stdout=output, check=True, timeout=600)


def fetch(downloads, verifier_root):
    current_verifier(verifier_root)
    require(not downloads.exists(), 'refusing existing download tree')
    downloads.mkdir(parents=True)
    api = f'/repos/{REPOSITORY}/actions/runs/{CAPTURE["run_id"]}'
    gh_read(api + '/attempts/1', downloads / 'attempt.json')
    catalog = {'attempt': read_record(downloads / 'attempt.json'), 'jobs_context': dict(CAPTURE)}
    for kind, endpoint, flag, count_key in (
        ('artifacts', api + '/artifacts', 'complete', 'total_count'),
        ('jobs', api + '/attempts/1/jobs', 'jobs_complete', 'jobs_total_count')):
        records, total, complete = [], None, False
        for page in range(1, 21):
            path = downloads / 'metadata' / f'{kind}-{page}.json'
            gh_read(endpoint + f'?per_page=100&page={page}', path)
            result = read_record(path)
            require(type(result['total_count']) is int and 0 < result['total_count'] <= 2000, 'invalid bounded listing size')
            require(total is None or total == result['total_count'], 'metadata listing changed between pages')
            total = result['total_count']
            require(type(result[kind]) is list and len(result[kind]) <= 100, 'invalid metadata page')
            records.extend(result[kind])
            if len(records) == total:
                complete = True
                break
            require(bool(result[kind]) and len(records) < total, 'metadata list ended early or exceeded total')
        catalog.update({kind: records, flag: complete, count_key: total})
    producer.write_json(downloads / 'artifact-catalog.json', catalog)
    selected = select_artifacts(catalog)
    for key, job in PINS['jobs'].items():
        gh_read(f'/repos/{REPOSITORY}/actions/jobs/{job["id"]}/logs', downloads / 'logs' / f'{key}.log')
    anchors = recover_anchors(checked_bytes(downloads / 'logs/inputs.log'), checked_bytes(downloads / 'logs/aggregate.log'))
    producer.write_json(downloads / 'independent-anchors.json', anchors)
    inventories = {}
    for destination, metadata in selected.items():
        archive = downloads / 'archives' / f'{metadata["id"]}.zip'
        gh_read(f'/repos/{REPOSITORY}/actions/artifacts/{metadata["id"]}/zip', archive)
        inventories[destination] = extract_archive(archive, downloads / destination, metadata)
        archive.unlink()  # This fresh temporary ZIP is redundant after verified extraction.
    producer.write_json(downloads / 'download-inventories.json', inventories)


def bind_precompiled(packet_path, manifest_path, capture_root, anchors):
    """Recheck the ebf-only fields not interpreted by the generic ADS binder.

    The precompiled receipt is already in the anchored source packet. Its hash
    must match the separate preparation job log; no extra artifact or replay is
    needed. A read-only ledger guards every accessed original byte until exit.
    """
    require(anchors.get('capture_context') == CAPTURE, 'independent anchor capture differs')
    ledger = binding.BoundSourcePacket()
    packet_path = Path(packet_path).absolute()
    packet_root, _ = shared._checked_root(packet_path.parent)
    packet = ledger._json(packet_path)
    shared._exact_keys(packet, {'schema', 'capture_binding', 'original_invocations', 'receipt',
                               'recorded_root', 'files', 'source_outputs', 'input_files'}, 'ebf source packet')
    require(packet['schema'] == binding.SCHEMA and packet['receipt'] == 'source-receipt.json', 'unexpected ebf packet layout')
    manifest = leaf.manifest_binding(manifest_path, CAPTURE)
    ledger._remember(manifest_path)
    shared.compare_binding(packet['capture_binding'], manifest['binding'])
    receipt_path = ledger._portable(packet_root, packet['receipt'])
    require(ledger._remember(receipt_path)['sha256'] == anchors['source_receipt_sha256'],
            'source receipt differs from original aggregate log anchor')
    receipt = ledger._json(receipt_path)
    shared._exact_keys(receipt, {'schema', 'source_base_commit', 'source_execution_context', 'capture_context',
                                'capture_rustc_sha256', 'toolchain', 'precompiled_receipt_sha256',
                                'inputs_and_implementation_before', 'inputs_and_implementation_after',
                                'backend_reports', 'reviewed_manifest_dependency_mapping', 'oracle_execution',
                                'acceptance_verdict'}, 'original source receipt')
    pinned_fields(receipt, {'schema': 'rust-duty-source-visibility-certificates-binding/v1',
                           'source_base_commit': CAPTURE['source_commit'], 'source_execution_context': CAPTURE,
                           'capture_context': CAPTURE, 'capture_rustc_sha256': anchors['rustc_sha256'],
                           'toolchain': anchors['toolchain'], 'precompiled_receipt_sha256': anchors['precompiled_receipt_sha256'],
                           'acceptance_verdict': None}, 'original source execution identity')
    before = receipt['inputs_and_implementation_before']
    _compare(before, receipt['inputs_and_implementation_after'], 'original source before/after inventory')
    shared._exact_keys(packet['files'], before, 'original packet file map')
    actual = {}
    for name, digest in before.items():
        shared._safe_key(name)
        binding._digest_shape(digest, name)
        require(packet['files'][name] == 'inventory/' + name, 'original packet mapping differs')
        actual[name] = ledger._portable(packet_root, packet['files'][name])
        _compare(ledger._remember(actual[name]), digest, f'original packet bytes/{name}')
    prep_key = ORACLE_PREFIX + 'precompiled-receipt.json'
    require(prep_key in actual, 'original packet is missing its precompiled receipt')
    require(ledger._remember(actual[prep_key])['sha256'] == anchors['precompiled_receipt_sha256'],
            'precompiled receipt differs from original preparation log anchor')
    preparation = ledger._json(actual[prep_key])
    shared._exact_keys(preparation, {'schema', 'capture_context', 'capture_binding', 'input_manifest_sha256',
                                    'platform', 'machine', 'host', 'target', 'profile', 'features', 'recorded_root',
                                    'executable', 'compiler_sha256', 'toolchain', 'active_toolchain_alias',
                                    'implementation_before', 'implementation_after', 'files'}, 'original preparation receipt')
    pinned_fields(preparation, {'schema': prepared.SCHEMA, 'capture_context': CAPTURE,
                               'input_manifest_sha256': shared._read_regular(manifest_path),
                               'platform': 'win32', 'host': producer.TARGET, 'target': producer.TARGET,
                               'profile': 'release', 'features': producer.FEATURES,
                               'executable': f'target/{producer.TARGET}/release/examples/{producer.EXAMPLE}.exe',
                               'compiler_sha256': anchors['rustc_sha256'], 'toolchain': anchors['toolchain']},
                  'original precompiled identity')
    require(preparation['machine'] in ('AMD64', 'x86_64'), 'original compiler platform differs')
    require(type(preparation['active_toolchain_alias']) is str
            and re.fullmatch('[A-Za-z0-9._-]+', preparation['active_toolchain_alias']), 'invalid original compiler alias')
    shared.compare_binding(preparation['capture_binding'], manifest['binding'])
    recorded_root = binding._recorded_path(packet['recorded_root'])
    require(recorded_root == binding._recorded_path(preparation['recorded_root']), 'source replay/build cwd differs')
    _compare(preparation['implementation_before'], preparation['implementation_after'], 'original compilation source changed')
    implementation = prepared.implementation_paths(capture_root)
    _compare(preparation['implementation_before'], {name: ledger._remember(path) for name, path in implementation.items()},
             'original compiled source inventory')
    extras = ('tools/current_ads_source_oracle.py', 'tools/collect_ads_offset_evidence.py', 'tools/finite_ads_profile_binding.py')
    expected_names = set(implementation) | set(extras) | (binding.INPUTS - {'ads-offset.cfg'}) | {
        ORACLE_PREFIX + name for name in ('source_visibility_certificate.exe', 'rustc-Vv.txt', 'build-receipt.json',
                                          'native-input-manifest.json', 'ads-offset.cfg', 'precompiled-receipt.json')}
    require(set(before) == expected_names, 'original source replay inventory has unexpected or missing files')
    for name in set(implementation) | set(extras):
        _compare(before[name], ledger._remember(capture_root / name), f'original source replay implementation/{name}')
    shared._exact_keys(preparation['files'], prepared.FILES, 'precompiled file mapping')
    for name in prepared.FILES:
        key = ORACLE_PREFIX + ('native-input-manifest.json' if name == 'input-manifest.json' else name)
        _compare(before[key], preparation['files'][name], f'precompiled/replay bytes/{name}')
    _compare(ledger._read(actual[ORACLE_PREFIX + 'native-input-manifest.json']), checked_bytes(manifest_path),
             'original precompiled manifest bytes')
    require(preparation['files']['input-manifest.json']['sha256'] == preparation['input_manifest_sha256'],
            'precompiled manifest receipt mapping differs')
    compiler = ledger._read(actual[ORACLE_PREFIX + 'rustc-Vv.txt'])
    _compare(compiler, ('\n'.join(anchors['rustc_verbose_lines']) + '\n').encode(), 'original compiler stdout bytes')
    _compare(prepared.compiler_identity(compiler, anchors['rustc_sha256']), preparation['toolchain'], 'original compiler release')
    # The original workflow uses hashFiles('Cargo.lock'): GitHub hashes the
    # binary per-file SHA256 digest again, rather than using its hex spelling.
    cache_lock = hashlib.sha256(bytes.fromhex(shared._read_regular(capture_root / 'Cargo.lock'))).hexdigest()
    require(cache_lock == anchors['cache_lock_sha256'],
            'original compiler cache lock differs from capture Cargo.lock')
    expected_oracle = {'schema': 'rust-duty-native-source-oracle/v1', 'platform': 'win32',
                       'machine': preparation['machine'], 'host': producer.TARGET, 'target': producer.TARGET,
                       'profile': 'release', 'features': producer.FEATURES,
                       'rustc_vv': ORACLE_PREFIX + 'rustc-Vv.txt', 'build_receipt': ORACLE_PREFIX + 'build-receipt.json',
                       'executable': ORACLE_PREFIX + 'source_visibility_certificate.exe',
                       'execution_receipts': receipt['oracle_execution'].get('execution_receipts')}
    _compare(receipt['oracle_execution'], expected_oracle, 'original replay executable/compiler/build mapping')
    command = binding._oracle_process(ledger._json(actual[expected_oracle['build_receipt']]), recorded_root, 'original oracle build')
    recorded_paths = {binding._recorded_path(name, recorded_root): name for name in implementation}
    binding._oracle_build(command, producer.EXAMPLE, recorded_root, recorded_paths,
                          {name.casefold(): name for name in implementation})
    _compare(packet['input_files'], {name: ORACLE_PREFIX + name if name == 'ads-offset.cfg' else name for name in binding.INPUTS},
             'original replay input mapping')
    expected_outputs = {role: ORACLE_PREFIX + f'frames-{binding.BACKENDS[role][0]}.jsonl' for role in binding.ROLES}
    _compare(packet['source_outputs'], expected_outputs, 'original replay output mapping')
    expected_files = set(packet['files'].values()) | set(expected_outputs.values()) | {'source-packet.json', 'source-receipt.json'}
    require({name for name, _ in shared._walk_files(packet_root)} == expected_files, 'unexpected or missing portable packet file')
    ledger._roots[packet_root] = expected_files
    for role, name in expected_outputs.items():
        path = ledger._portable(packet_root, name)
        _compare(ledger._remember(path), receipt['backend_reports'][binding.BACKENDS[role][0]]['output'], 'original replay output bytes')
    ledger.verify_unchanged()
    return ledger


def materialize_root(source, verifier, inputs, destination, manifest):
    """Stage a fresh full input root; preserve every original manifest hash."""
    require(not destination.exists() and not destination.is_symlink(), 'native input destination already exists')
    no_link_parents(destination)
    for original in (source, verifier, inputs):
        shared._checked_root(original)
        no_link_parents(original)
        require(not destination.resolve().is_relative_to(original.resolve())
                and not original.resolve().is_relative_to(destination.resolve()), 'native input root overlaps original evidence')
    native = manifest['binding']
    shared.validate_binding(native, expected_context=CAPTURE)
    candidates = {f'assets/{name}': path for name, path in shared._walk_files(source / 'assets')}
    candidates['settings.cfg'] = source / 'settings.cfg'
    expected = native['runtime_and_manifest_sha256']
    require(all(name == 'settings.cfg' or (name.startswith('assets/') and Path(name).suffix in
                ('.vra', '.vrs', '.vrm', '.json', '.cfg')) for name in expected), 'unsupported native runtime input')
    destination.mkdir(parents=True)
    records = {}
    for name, digest in expected.items():
        require(name in candidates, f'missing original runtime input: {name}')
        raw, records[name] = recovery.select_native_bytes(candidates[name], digest)
        write_bytes(destination / name, raw)
    for name, field in (('Cargo.toml', 'cargo_manifest_sha256'), ('Cargo.lock', 'cargo_lock_sha256')):
        raw = checked_bytes(source / name)
        require(hashlib.sha256(finite._lf(raw)).hexdigest() == native[field], f'original build input differs: {name}')
        write_bytes(destination / name, raw)
    tools = {name: path for name, path in shared._walk_files(verifier / 'tools') if path.suffix == '.py'}
    for name, path in tools.items():
        write_bytes(destination / 'tools' / name, checked_bytes(path))
    aggregate.copy_verified(inputs / shared.GL_RUNTIME_PATH, destination / shared.GL_RUNTIME_PATH)
    write_bytes(destination / shared.GL_LOCK_PATH, checked_bytes(inputs / shared.GL_RUNTIME_PATH / shared.GL_LOCK_PATH.name))
    for name, field in (('target/release/vector-range.exe', 'executable_sha256'),
                        ('target/release/examples/renderer_contract.exe', 'renderer_contract_sha256')):
        raw = checked_bytes(inputs / name)
        require(hashlib.sha256(raw).hexdigest() == native[field], f'original compiled input differs: {name}')
        write_bytes(destination / name, raw)
    shared.compare_binding(native, aggregate.validated_manifest(
        inputs / 'evidence/authored-inputs/input-manifest.json', destination, expected_context=CAPTURE))
    for name, record in records.items():
        require(producer.digest(candidates[name])['sha256'] == record['candidate_sha256'], 'original candidate changed during staging')
    return {'runtime_and_manifest_files': records,
            'verifier_tools': {name: producer.digest(destination / 'tools' / name) for name in tools}}


def verify_downloads(downloads, inventories):
    shared._exact_keys(inventories, PINS['artifacts'], 'downloaded artifact inventories')
    for destination, inventory in inventories.items():
        require(bool(inventory), f'empty original artifact: {destination}')
        no_link_parents(downloads / destination)
        shared.verify_files(downloads / destination, inventory, exclude=())


def run(*, capture_root, verifier_root, downloads, evidence, native_root):
    capture_root, verifier_root, downloads, evidence, native_root = [Path(path).absolute() for path in
        (capture_root, verifier_root, downloads, evidence, native_root)]
    verifier = current_verifier(verifier_root)
    check_checkout(capture_root, CAPTURE['source_commit'])
    sources = (capture_root, verifier_root, downloads)
    for index, source in enumerate(sources):
        for other in sources[index + 1:]:
            require(not source.resolve().is_relative_to(other.resolve())
                    and not other.resolve().is_relative_to(source.resolve()), 'original input roots overlap')
    for output in (evidence, native_root):
        require(not output.exists() and not output.is_symlink(), 'refusing existing revalidation output')
        no_link_parents(output)
        for source in sources:
            require(not output.resolve().is_relative_to(source.resolve()) and not source.resolve().is_relative_to(output.resolve()),
                    'revalidation output overlaps immutable input')
    require(not evidence.resolve().is_relative_to(native_root.resolve()) and not native_root.resolve().is_relative_to(evidence.resolve()),
            'revalidation output and native input root overlap')
    evidence.mkdir(parents=True)
    report = {'schema': 'rust-duty-ebf-authored-packet-revalidation/v1', 'passed': False,
              'acceptance_complete': False, 'capture_context': dict(CAPTURE), 'source_execution_context': dict(CAPTURE),
              'verifier_context': verifier, 'native_processes_run': 0, 'original_failures_preserved': False,
              'scope': 'Supplemental automated nine-shard revalidation; original run remains failed. Human, landmark and real-GPU gates stay open.'}
    try:
        catalog = read_record(downloads / 'artifact-catalog.json')
        selected = select_artifacts(catalog)
        anchors = recover_anchors(checked_bytes(downloads / 'logs/inputs.log'), checked_bytes(downloads / 'logs/aggregate.log'))
        _compare(read_record(downloads / 'independent-anchors.json'), anchors, 'independent recovered anchors changed')
        inventories = read_record(downloads / 'download-inventories.json')
        verify_downloads(downloads, inventories)
        report['original_workflow'] = PINS['attempt']
        producer.write_json(evidence / 'download-identities.json', selected)
        producer.write_json(evidence / 'independent-anchors.json', anchors)
        producer.write_json(evidence / 'production-comparison.json', compare_production(capture_root, verifier_root))
        original = evidence / 'original-verdicts'
        original.mkdir()
        for key in ('inputs', 'aggregate'):
            write_bytes(original / f'{key}-job.log', checked_bytes(downloads / 'logs' / f'{key}.log'))
        for scenario in shared.SCENARIOS:
            write_bytes(original / f'{scenario}-summary.json', checked_bytes(downloads / 'shards' / scenario / 'summary.json'))
        source_evidence = downloads / 'source/current-ads-source'
        write_bytes(original / 'source-producer-summary.json', checked_bytes(source_evidence / 'producer-summary.json'))
        producer_summary = read_record(source_evidence / 'producer-summary.json')
        pinned_fields(producer_summary, {'passed': False, 'capture_context': CAPTURE, 'verifier_context': CAPTURE,
                                        'phase': 'bind-finite-ads-profile', 'needs_supplement': True,
                                        'source_receipt_sha256': anchors['source_receipt_sha256'],
                                        'bounded_ads_profile_established': False,
                                        'failure': 'ValueError: unreviewed production file added'}, 'original source-proof rejection')
        report['original_failures_preserved'] = True
        manifest_path = downloads / 'inputs/evidence/authored-inputs/input-manifest.json'
        manifest = leaf.manifest_binding(manifest_path, CAPTURE)
        require(checked_bytes(downloads / 'source/current-ads-source-receipt.sha256') ==
                (anchors['source_receipt_sha256'] + '\n').encode(), 'original retained receipt anchor differs from job log')
        packet_path = source_evidence / 'packet/source-packet.json'
        provenance = bind_precompiled(packet_path, manifest_path, capture_root, anchors)
        # Stage only checked original runtime assets, then run the existing Python
        # decoder/verifier. This cannot build or execute a native application.
        producer.stage_generated_inputs(capture_root, downloads, manifest)
        materialization = evidence / 'materialization.log'
        with materialization.open('xb') as log:
            subprocess.run([sys.executable, str(capture_root / 'tools/package_game.py'), 'materialize', '--root', str(capture_root),
                            '--include-walk', '--include-ads', '--include-directional', '--include-jump', '--require-generated'],
                           cwd=capture_root, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
        producer.recover_native_text_bytes(capture_root, manifest, downloads / 'shards/ads-offset/ads-offset.cfg')
        producer.validate_consumed_inputs(capture_root, manifest, downloads / 'shards/ads-offset/ads-offset.cfg')
        report['input_root'] = materialize_root(capture_root, verifier_root, downloads / 'inputs', native_root, manifest)
        producer.write_json(evidence / 'input-root-recovery.json', report['input_root'])
        historical_manifest = downloads / 'inputs/evidence/authored-inputs/historical-manifest.json'
        recovery.verify_historical(downloads / 'legacy', historical_manifest, CAPTURE)
        reviewed_class = verifier_root / 'tools/finite_ads_gpu_cpu_class.json'
        require(shared._read_regular(reviewed_class) == CLASS_SHA256, 'reviewed GPU/CPU class changed')
        leaf_result = leaf.run(input_manifest=manifest_path, gameplay_shard=downloads / 'shards/ads-gameplay',
                               offset_shard=downloads / 'shards/ads-offset', source_packet=packet_path,
                               source_receipt_sha256=anchors['source_receipt_sha256'], capture_rustc_sha256=anchors['rustc_sha256'],
                               evidence=evidence / 'leaf', capture_context=dict(CAPTURE), verifier_context=verifier,
                               reviewed_class=reviewed_class, expected_class_sha256=CLASS_SHA256)
        require(leaf_result.get('passed') is True and leaf_result.get('bounded_ads_profile_established') is True
                and leaf_result.get('conditional_diagnostic') is False, f'ADS leaf failed: {leaf_result.get("failure")}')
        request = {'leaf_summary': str(evidence / 'leaf/summary.json'), 'source_packet': str(packet_path),
                   'source_receipt_sha256': anchors['source_receipt_sha256'], 'capture_rustc_sha256': anchors['rustc_sha256'],
                   'capture_context': dict(CAPTURE), 'leaf_verifier_context': verifier, 'verifier_context': verifier,
                   'reviewed_class': str(reviewed_class), 'expected_class_sha256': CLASS_SHA256}
        aggregate.AdsSourceSupplement(request)
        producer.write_json(evidence / 'aggregate-supplement.json', request)
        report['leaf_passed'] = True
        result = aggregate.run(native_root, downloads / 'shards', downloads / 'legacy', evidence / 'aggregate', manifest_path,
                               historical_manifest=historical_manifest, ads_source_supplement=request)
        require(result.get('passed') is True and result.get('status') == 'passed', 'mandatory full nine-shard aggregate failed')
        require(result.get('expected_checks') == aggregate.expected_checks(ads_source_supplement=True)
                and [row['name'] for row in result['checks']] == result['expected_checks']
                and all(row.get('passed') is True for row in result['checks']), 'mandatory aggregate check set incomplete')
        provenance.verify_unchanged()
        verify_downloads(downloads, inventories)
        _compare(verifier, current_verifier(verifier_root), 'actual verifier changed during validation')
        producer.write_json(evidence / 'final-production-comparison.json', compare_production(capture_root, verifier_root))
        report.update(passed=True, leaf_passed=True, aggregate_passed=True)
    except Exception as error:
        report['failure'] = f'{type(error).__name__}: {error}'
    finally:
        producer.write_json(evidence / 'summary.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('fetch', 'run'):
        current = commands.add_parser(command)
        current.add_argument('--downloads', type=Path, required=True)
        current.add_argument('--verifier-root', type=Path, required=True)
    for name in ('capture-root', 'evidence', 'native-root'):
        commands.choices['run'].add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'fetch':
            fetch(args.downloads.absolute(), args.verifier_root.absolute())
            return 0
        result = run(capture_root=args.capture_root, verifier_root=args.verifier_root, downloads=args.downloads,
                     evidence=args.evidence, native_root=args.native_root)
        print(json.dumps(aggregate.plain(result), indent=2))
        return 0 if result['passed'] else 1
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f'ebf authored packet revalidation failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

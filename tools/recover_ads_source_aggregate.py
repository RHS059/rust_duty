#!/usr/bin/env python3
"""Stage the pinned 8f nine-shard aggregate from immutable current-run artifacts.

This supplements the existing Windows ADS leaf. It never builds or runs a game
or source oracle, downloads an archive, or changes capture/verifier identities.
"""
import argparse
from datetime import datetime
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import aggregate_dx12_authored as aggregate
import build_ads_source_packet as producer
import dx12_authored_shards as shared
import revalidate_ads_offset as leaf
from verify_capture_telemetry import _compare, read_record

CAPTURE = producer.CAPTURE_CONTEXT
REPOSITORY = 'RHS059/rust_duty'
WORKFLOW_NAME = 'Rust prototype checks and playable builds'
HISTORICAL = {
    'jump-gameplay': 'native-gameplay-jump',
    'reload-gameplay': 'native-gameplay-reload',
    'walk-gameplay': 'native-gameplay-walk',
    'ads-gameplay': 'native-gameplay-ads',
    'ads-placement': 'native-ads-placement',
    'layered': 'native-layered-locomotion',
    'reload-return': 'native-reload-return',
}
require = producer.require


def artifact_names(attempt):
    return {**producer.artifact_names(attempt),
            **{f'shard_{scenario.replace("-", "_")}': f'dx12-authored-shard-{scenario}-evidence-attempt-{attempt}'
               for scenario in shared.SCENARIOS if scenario not in leaf.SCENARIOS},
            **{f'linux_{scenario.replace("-", "_")}': f'{name}-evidence-attempt-{attempt}'
               for scenario, name in HISTORICAL.items()}}


def select_artifacts(catalog, capture, repository=REPOSITORY):
    """Extend, without weakening, the leaf's exact pinned artifact guards."""
    selected = producer.select_artifacts(catalog, capture, repository)
    run = catalog['attempt']
    require(run.get('name') == WORKFLOW_NAME, 'original capture workflow name differs')
    require(run.get('conclusion') == 'failure', 'original pinned workflow failure must be preserved')
    start, end = (datetime.fromisoformat(run[key].replace('Z', '+00:00'))
                  for key in ('run_started_at', 'updated_at'))
    for key, name in artifact_names(capture['run_attempt']).items():
        if key in selected:
            continue
        matches = [item for item in catalog['artifacts'] if item['name'] == name]
        require(len(matches) == 1, f'expected exactly one artifact named {name}')
        item = matches[0]
        require(type(item['id']) is int and item['id'] > 0 and item['id'] not in producer.DENIED_ARTIFACT_IDS,
                f'{name}: artifact unavailable under the authorized access scope')
        require(item['expired'] is False, f'{name}: artifact expired')
        origin = item['workflow_run']
        require(str(origin['id']) == capture['run_id'] and origin['head_sha'] == capture['source_commit']
                and origin['repository_id'] == run['repository']['id']
                and origin['head_repository_id'] == run['head_repository']['id'], f'{name}: artifact origin differs')
        created = datetime.fromisoformat(item['created_at'].replace('Z', '+00:00'))
        require(start <= created <= end, f'{name}: artifact was not created in the selected attempt')
        require(type(item['size_in_bytes']) is int and 0 < item['size_in_bytes'] <= 4 * 1024**3,
                f'{name}: invalid or oversized archive')
        selected[key] = item
    require(len({item['id'] for item in selected.values()}) == len(selected), 'aliased artifact IDs')
    return selected


def checked_bytes(path):
    before = producer.digest(path)
    raw = path.read_bytes()
    require({'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} == before == producer.digest(path),
            f'candidate input changed while reading: {path}')
    return raw


def select_native_bytes(path, expected):
    """Allow only a unique exact-hash LF/CRLF spelling for JSON/CFG inputs."""
    raw = checked_bytes(path)
    variants = {raw: 'exact'}
    if path.suffix in ('.json', '.cfg'):
        raw.decode('utf-8')
        lf = raw.replace(b'\r\n', b'\n')
        variants.setdefault(lf, 'lf')
        variants.setdefault(lf.replace(b'\n', b'\r\n'), 'crlf')
    matches = [(candidate, label) for candidate, label in variants.items()
               if hashlib.sha256(candidate).hexdigest() == expected]
    require(len(matches) == 1, f'cannot recover exact native input bytes: {path}')
    candidate, transformation = matches[0]
    return candidate, {'candidate_sha256': hashlib.sha256(raw).hexdigest(),
                       'sha256': expected, 'bytes': len(candidate), 'transformation': transformation}


def write_bytes(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
    require(checked_bytes(path) == raw, f'materialized bytes changed: {path}')


def materialize_root(source, verifier, inputs, destination, manifest):
    """Build a fresh full hash-bound input root without altering the leaf root."""
    require(not destination.exists(), 'aggregate input root already exists')
    for original in (source, verifier, inputs):
        shared._checked_root(original)
        require(not destination.resolve().is_relative_to(original.resolve())
                and not original.resolve().is_relative_to(destination.resolve()),
                'aggregate input root must be disjoint from original evidence and checkouts')
    native = manifest['binding']
    shared.validate_binding(native, expected_context=CAPTURE)
    # Scan all candidates before reading any selected file; reject links,
    # reparse points, aliases and escaped parents with the shared inventory API.
    candidates = {f'assets/{name}': path for name, path in shared._walk_files(source / 'assets')}
    candidates['settings.cfg'] = source / 'settings.cfg'
    expected = native['runtime_and_manifest_sha256']
    require(all(name == 'settings.cfg' or (name.startswith('assets/') and Path(name).suffix in
                ('.vra', '.vrs', '.vrm', '.json', '.cfg')) for name in expected),
            'native runtime inventory contains an unsupported path')
    destination.mkdir(parents=True)
    records = {}
    for name, digest in expected.items():
        require(name in candidates, f'missing original input-root file: {name}')
        raw, records[name] = select_native_bytes(candidates[name], digest)
        write_bytes(destination / name, raw)
    for name, field in (('Cargo.toml', 'cargo_manifest_sha256'), ('Cargo.lock', 'cargo_lock_sha256')):
        raw = checked_bytes(source / name)
        require(hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest() == native[field],
                f'original {name} differs from native input manifest')
        write_bytes(destination / name, raw)
    # Only verifier Python sources are needed by the
    # original aggregate validators. No renderer or executable is launched.
    tool_files = {name: path for name, path in shared._walk_files(verifier / 'tools')
                  if path.suffix == '.py'}
    for name, path in tool_files.items():
        write_bytes(destination / 'tools' / name, checked_bytes(path))
    aggregate.copy_verified(inputs / shared.GL_RUNTIME_PATH, destination / shared.GL_RUNTIME_PATH)
    # The native runtime's sealed lock is authoritative, even if the verifier
    # checkout has since updated its own GL configuration.
    write_bytes(destination / shared.GL_LOCK_PATH,
                checked_bytes(inputs / shared.GL_RUNTIME_PATH / shared.GL_LOCK_PATH.name))
    for name, field in (('target/release/vector-range.exe', 'executable_sha256'),
                        ('target/release/examples/renderer_contract.exe', 'renderer_contract_sha256')):
        raw = checked_bytes(inputs / name)
        require(hashlib.sha256(raw).hexdigest() == native[field], f'original compiled input differs: {name}')
        write_bytes(destination / name, raw)
    # This checks the entire original asset/metadata map, both Cargo files and
    # every pinned app-local GL byte through the aggregate's unchanged API.
    manifest_path = inputs / 'evidence/authored-inputs/input-manifest.json'
    shared.compare_binding(native, aggregate.validated_manifest(manifest_path, destination, expected_context=CAPTURE))
    for name, record in records.items():
        require(producer.digest(candidates[name])['sha256'] == record['candidate_sha256'],
                f'candidate input changed during full materialization: {name}')
    return {'input_manifest_sha256': producer.digest(manifest_path)['sha256'],
            'runtime_and_manifest_files': records,
            'verifier_tools': {name: producer.digest(destination / 'tools' / name) for name in tool_files}}


def stage_shard(original, destination, summary_sha256):
    """Relocate unchanged decoded bytes on this workspace's same volume.

    The aggregate creates its own validator copies. Avoid a third full copy of
    all nine large captures; preserve a closed inventory across this rename.
    """
    require(not destination.exists(), 'staged shard destination already exists')
    recorded = shared.inventory_files(original, exclude=())
    require(bool(recorded), 'original shard is empty')
    require(recorded.get('summary.json') == summary_sha256, 'original summary changed before relocation')
    original.rename(destination)
    shared.verify_files(destination, recorded, exclude=())


def verify_historical(folder, manifest_path, capture):
    """Check the original full receipt without a redundant full evidence copy."""
    before = producer.digest(manifest_path)
    record = read_record(manifest_path)
    _compare(record, {'schema': 'rust-duty-dx12-authored-historical/v1', **capture,
                      'files': record.get('files')}, 'historical artifact download receipt')
    require(bool(record['files']), 'historical Linux inventory is empty')
    shared.verify_files(folder, record['files'], exclude=())
    require(producer.digest(manifest_path) == before, 'historical manifest changed during recovery')
    return before


def make_request(summary, packet, receipt_anchor, compiler, capture, verifier):
    producer.validate_capture(capture)
    shared._validate_context(verifier)
    saved = read_record(summary)
    require(saved.get('passed') is True and saved.get('capture_context') == capture
            and saved.get('verifier_context') == verifier, 'successful same-verifier ADS leaf required')
    receipt_sha = checked_bytes(receipt_anchor).decode('ascii').strip()
    require(compiler.get('capture_context') == capture, 'independent compiler receipt capture differs')
    rustc_sha = compiler['rustc_sha256']
    require(saved.get('source_receipt_sha256') == receipt_sha
            and saved.get('capture_rustc_sha256') == rustc_sha,
            'ADS leaf differs from independent receipt/compiler anchors')
    request = {'leaf_summary': str(summary.absolute()), 'source_packet': str(packet.absolute()),
               'source_receipt_sha256': receipt_sha, 'capture_rustc_sha256': rustc_sha,
               'capture_context': capture, 'leaf_verifier_context': verifier, 'verifier_context': verifier}
    # Validate exact fields, hash spellings and actual verifier identity now;
    # packet/leaf inventories are rechecked by the aggregate itself.
    aggregate.AdsSourceSupplement(request)
    return request


def prepare(args):
    capture = {'source_commit': args.capture_source, 'run_id': args.capture_run_id,
               'run_attempt': args.capture_run_attempt}
    producer.validate_capture(capture)
    verifier_context = shared.context()
    source, verifier, downloads, evidence = [path.absolute() for path in
        (args.capture_root, args.verifier_root, args.downloads, args.evidence)]
    evidence.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'rust-duty-ads-aggregate-recovery/v1', 'passed': False,
              'capture_context': capture, 'verifier_context': verifier_context}
    try:
        for root, expected in ((source, capture['source_commit']), (verifier, verifier_context['source_commit'])):
            require(subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip() == expected,
                    f'{root}: source checkout identity differs')
        require(not subprocess.check_output(['git', '-C', str(verifier), 'status', '--porcelain', '--untracked-files=no']),
                'reviewed verifier checkout is modified')
        catalog = read_record(downloads / 'artifact-catalog.json')
        selected = select_artifacts(catalog, capture)
        producer.write_json(evidence / 'download-identities.json', selected)
        report['original_workflow'] = {key: catalog['attempt'][key] for key in
                                       ('id', 'run_attempt', 'head_sha', 'status', 'conclusion', 'name', 'path')}
        manifest = leaf.manifest_binding(downloads / 'inputs/evidence/authored-inputs/input-manifest.json', capture)
        # Current-run artifacts have separate exact-ID destinations. Assemble
        # immutable shards, including the two already-used ADS ones, by rename.
        incoming = args.shards.absolute()
        require(not incoming.exists(), 'aggregate shard directory already exists')
        originals = evidence / 'original-verdicts'
        originals.mkdir()
        report['original_shard_summaries'] = {}
        for scenario in shared.SCENARIOS:
            original = downloads / ({'ads-gameplay': 'gameplay', 'ads-offset': 'offset'}.get(scenario,
                                       f'shards/{scenario}'))
            artifact_key = {'ads-gameplay': 'gameplay', 'ads-offset': 'offset'}.get(
                scenario, 'shard_' + scenario.replace('-', '_'))
            retained = originals / f'{scenario}-summary.json'
            write_bytes(retained, checked_bytes(original / 'summary.json'))
            require(producer.digest(retained) == producer.digest(original / 'summary.json'),
                    f'original shard summary changed during preservation: {scenario}')
            report['original_shard_summaries'][scenario] = {
                'artifact_id': selected[artifact_key]['id'], 'artifact_name': selected[artifact_key]['name'],
                'retained_path': retained.relative_to(evidence).as_posix(), **producer.digest(retained)}
        producer.write_json(evidence / 'original-shard-summaries.json', report['original_shard_summaries'])
        # Seal all nine summaries before relocating any original artifact.
        incoming.mkdir(parents=True)
        for scenario in shared.SCENARIOS:
            original = downloads / ({'ads-gameplay': 'gameplay', 'ads-offset': 'offset'}.get(scenario,
                                       f'shards/{scenario}'))
            expected = report['original_shard_summaries'][scenario]['sha256']
            stage_shard(original, incoming / scenario, expected)
            require(producer.digest(incoming / scenario / 'summary.json')['sha256'] == expected,
                    f'original summary changed during relocation: {scenario}')
        # Reuse leaf's source materialization as candidates, including the
        # original package's committed/alternate companions. No regeneration.
        report['input_root'] = materialize_root(source, verifier, downloads / 'inputs', args.root.absolute(), manifest)
        producer.write_json(evidence / 'input-root-recovery.json', report['input_root'])
        historical = downloads / 'legacy'
        historical_manifest = downloads / 'inputs/evidence/authored-inputs/historical-manifest.json'
        # Retain and check the complete historical download receipt before any
        # supplemental aggregate check. The original diagnostics stay required.
        report['historical_manifest'] = verify_historical(historical, historical_manifest, capture)
        compiler_job = producer.select_compiler_job(catalog, capture)
        compiler_path = downloads / 'compiler-recovery/compiler-recovery.json'
        compiler = read_record(compiler_path)
        recovered = producer.recover_compiler(checked_bytes(downloads / 'compiler-recovery/original-authored-inputs.log'), capture)
        require(compiler == {**recovered, 'original_job': compiler_job}, 'independent compiler recovery metadata changed')
        request = make_request(args.leaf_summary, args.source_packet, args.receipt_anchor, compiler, capture, verifier_context)
        producer.write_json(args.request, request)
        report.update(passed=True, request_sha256=producer.digest(args.request)['sha256'],
                      original_failures_preserved=True, native_processes_run=0)
        return report
    except Exception as error:
        report['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        producer.write_json(evidence / 'summary.json', report)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('select-artifacts', 'prepare'):
        current = commands.add_parser(command)
        for name in ('capture-source', 'capture-run-id', 'capture-run-attempt'):
            current.add_argument('--' + name, required=True)
    commands.choices['select-artifacts'].add_argument('--catalog', type=Path, required=True)
    for name in ('capture-root', 'verifier-root', 'downloads', 'evidence', 'root', 'shards',
                 'leaf-summary', 'source-packet', 'receipt-anchor', 'request'):
        commands.choices['prepare'].add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'select-artifacts':
            capture = {'source_commit': args.capture_source, 'run_id': args.capture_run_id,
                       'run_attempt': args.capture_run_attempt}
            selected = select_artifacts(read_record(args.catalog), capture)
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
                for key, item in selected.items():
                    stream.write(f'{key}={item["id"]}\n')
        else:
            prepare(args)
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f'ADS aggregate recovery failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

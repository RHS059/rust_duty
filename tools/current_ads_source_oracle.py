#!/usr/bin/env python3
"""Replay a precompiled current-main CPU oracle against immutable native ADS.

This path has no historical artifact lookup, source overlay, compiler invocation,
game rebuild or rendering. A separately anchored authored-input build supplies
the executable. All consumed runtime bytes come from the same native manifest.
Only a completed leaf correction produces an optional nine-shard supplement;
the original native verdicts remain untouched and acceptance remains incomplete.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

import ads_source_visibility_binding as binding
import aggregate_dx12_authored as aggregate
import build_ads_source_packet as producer
import collect_ads_offset_evidence as collector
import dx12_authored_shards as shared
import prepare_ads_source_oracle as prepared
import revalidate_ads_offset as leaf
import run_dx12_authored_shard as shard
from verify_capture_telemetry import _compare, read_record


SCHEMA = 'rust-duty-current-ads-source-oracle/v1'
REPOSITORY = 'RHS059/rust_duty'


def require(value, message):
    if not value:
        raise ValueError(message)


def current_main_context():
    """Only the actual currently executing main build can use this mode."""
    context = shared.context()
    for name, expected in {
        'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': REPOSITORY,
        'GITHUB_REF': 'refs/heads/main',
        'GITHUB_WORKFLOW_REF': REPOSITORY + '/.github/workflows/build.yml@refs/heads/main',
        'GITHUB_WORKFLOW_SHA': context['source_commit'],
        'RUNNER_OS': 'Windows', 'RUNNER_ARCH': 'X64',
    }.items():
        require(os.environ.get(name) == expected, f'current main identity differs: {name}')
    require(os.environ.get('GITHUB_EVENT_NAME') in ('push', 'workflow_dispatch'),
            'current source oracle requires a main push or dispatch')
    require(sys.platform == 'win32' and platform.machine() in ('AMD64', 'x86_64'),
            'current source oracle requires native Windows x86_64')
    return context


def check_checkout(root, context):
    require(subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                                   text=True, timeout=60).strip() == context['source_commit'],
            'current source checkout differs from actual GitHub commit')
    paths = prepared.implementation_paths(root)
    for name in ('tools/current_ads_source_oracle.py', 'tools/collect_ads_offset_evidence.py',
                 'tools/finite_ads_profile_binding.py'):
        paths[name] = root / name
    subprocess.check_output(['git', '-C', str(root), 'ls-files', '--error-unmatch', '--', *paths], timeout=60)
    require(not subprocess.check_output(['git', '-C', str(root), 'diff', '--name-only', 'HEAD', '--', *paths],
                                        timeout=60), 'current source implementation has tracked changes')
    return paths


def check_paths(root, input_manifest, shards, oracle, evidence, receipt_anchor):
    """Never replace inputs, source files, an old packet, or an old trust anchor."""
    for path in (root, shards, oracle):
        shared._checked_root(path)
    shared._checked_stat(input_manifest, 'file')
    require(not evidence.exists() and not evidence.is_symlink(), 'refusing existing source evidence')
    require(not receipt_anchor.exists() and not receipt_anchor.is_symlink(), 'refusing existing receipt anchor')
    require(evidence.resolve().is_relative_to(root.resolve()) and evidence.resolve() != root.resolve(),
            'source evidence must be a fresh directory within the current checkout')
    require(not receipt_anchor.resolve().is_relative_to(evidence.resolve()),
            'independent receipt anchor must remain outside the source evidence')
    for source in (shards, oracle):
        require(not evidence.resolve().is_relative_to(source.resolve())
                and not source.resolve().is_relative_to(evidence.resolve()),
                'new source evidence must be disjoint from immutable input artifacts')
        require(not receipt_anchor.resolve().is_relative_to(source.resolve()),
                'independent anchor cannot change immutable input artifacts')
    require(not input_manifest.resolve().is_relative_to(evidence.resolve()),
            'new source evidence cannot contain its original manifest')


def verify_native_pair(shards, native, context):
    """Inspect actual process receipts and complete frames before CPU execution."""
    folder = shards / 'ads-gameplay'
    gameplay = aggregate.read_shard(folder, 'ads-gameplay', native, expected_context=context)
    require('fatal_error' not in gameplay, 'original gameplay shard has a fatal error')
    aggregate.shard_pass(gameplay)
    for role in binding.ROLES:
        leaf.exact_invocation(folder, gameplay, role, 'ads-gameplay')
        identity = shard.role_witness_identity(native, 'ads-gameplay', role)
        shard.validate_role_images(folder / gameplay['capture_paths'][role], role, binding.FRAME_COUNT,
                                   expected_witness_identity=identity)
    shared.verify_files(folder, gameplay['files'])
    folder = shards / 'ads-offset'
    collection = collector.inspect_offset_collection(folder, native, expected_context=context)
    offset = read_record(folder / 'summary.json')
    require(shared._read_regular(folder / 'summary.json') == collection['original_summary_sha256'],
            'original offset summary changed after collection inspection')
    invocations = {role: leaf.exact_invocation(folder, offset, role, 'ads-offset') for role in binding.ROLES}
    return {'ads-gameplay': gameplay, 'ads-offset': offset}, invocations, collection if collection['needs_supplement'] else None


def check_replay_root(root, preparation):
    require(binding._recorded_path(root.as_posix()) == binding._recorded_path(preparation['recorded_root']),
            'current checkout path differs from original oracle build cwd; receipts cannot be rewritten')


def emit_outputs(**values):
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8', newline='\n') as stream:
            for name, value in values.items():
                require('\n' not in str(value) and '\r' not in str(value), 'unsafe GitHub step output')
                stream.write(f'{name}={value}\n')


def assemble(*, root, input_manifest, shards, oracle, expected_oracle_receipt_sha256,
             capture_rustc_sha256, evidence, receipt_anchor, reviewed_class=None, expected_class_sha256=None):
    root, input_manifest, shards, oracle = (Path(path).absolute() for path in (root, input_manifest, shards, oracle))
    evidence, receipt_anchor = Path(evidence).absolute(), Path(receipt_anchor).absolute()
    context = current_main_context()
    check_paths(root, input_manifest, shards, oracle, evidence, receipt_anchor)
    evidence.mkdir(parents=True)
    report = {'schema': SCHEMA, 'passed': False, 'acceptance_complete': False,
              'capture_context': context, 'verifier_context': context, 'phase': 'verify-current-build',
              'needs_supplement': False, 'bounded_ads_profile_established': False}
    try:
        implementation = check_checkout(root, context)
        manifest = leaf.manifest_binding(input_manifest, context)
        native = shared.verify_input_manifest(manifest, root / 'target/release/vector-range.exe',
                                              root / 'target/release/examples/renderer_contract.exe', root)
        prebuilt = prepared.verify_precompiled(oracle, root, input_manifest,
                                               expected_oracle_receipt_sha256, capture_rustc_sha256)
        preparation = deepcopy(prebuilt['receipt'])
        check_replay_root(root, preparation)
        env = producer.execution_environment(root, preparation['active_toolchain_alias'])
        original_paths = [input_manifest, prebuilt['receipt_path'], shards / 'ads-offset/ads-offset.cfg',
                          *(shards / scenario / 'summary.json' for scenario in ('ads-gameplay', 'ads-offset'))]
        immutable = producer.inventory({str(path): path for path in original_paths})
        _compare(immutable[str(input_manifest)], preparation['files']['input-manifest.json'],
                 'native manifest differs from original prepared bytes')
        require(immutable[str(prebuilt['receipt_path'])]['sha256'] == expected_oracle_receipt_sha256,
                'preparation receipt differs from independent job output before native inspection')
        report['phase'] = 'verify-original-native-pair'
        reports, invocations, eligibility = verify_native_pair(shards, native, context)
        _compare(immutable, producer.inventory({path: Path(path) for path in immutable}),
                 'original native inputs changed during collection inspection')
        if eligibility is None:
            report.update(passed=True, phase='original-offset-passed')
            emit_outputs(supplement_path='', source_receipt_sha256='', capture_rustc_sha256=capture_rustc_sha256)
            return report
        report['needs_supplement'] = True
        report['original_failure_eligibility'] = eligibility
        offset = shards / 'ads-offset/ads-offset.cfg'
        producer.validate_consumed_inputs(root, manifest, offset)
        work = evidence / 'oracle-output'
        work.mkdir()
        copies = {
            'source_visibility_certificate.exe': (prebuilt['executable'], preparation['files']['source_visibility_certificate.exe']),
            'rustc-Vv.txt': (prebuilt['rustc_vv'], preparation['files']['rustc-Vv.txt']),
            'build-receipt.json': (prebuilt['build_receipt'], preparation['files']['build-receipt.json']),
            'native-input-manifest.json': (input_manifest, preparation['files']['input-manifest.json']),
            'ads-offset.cfg': (offset, immutable[str(offset)]),
            'precompiled-receipt.json': (prebuilt['receipt_path'], immutable[str(prebuilt['receipt_path'])]),
        }
        for name, (source, expected) in copies.items():
            producer.copy_packet_file(source, work / name, expected)
        implementation.update({name: root / name for name in binding.INPUTS - {'ads-offset.cfg'}})
        implementation.update({path.relative_to(root).as_posix(): path for path in work.iterdir()})
        offset_key = (work / 'ads-offset.cfg').relative_to(root).as_posix()
        executable = work / 'source_visibility_certificate.exe'
        executable_key = executable.relative_to(root).as_posix()
        before = producer.inventory(implementation)
        backend_reports, executions, outputs = {}, {}, {}
        for backend, role in (('opengl', 'windows-legacy'), ('dx12', 'dx12')):
            report['phase'] = f'cpu-replay-{backend}'
            output = work / f'frames-{backend}.jsonl'
            relative = output.relative_to(root).as_posix()
            command = [executable.as_posix(), (root / 'assets/animations.cfg').as_posix(),
                       (work / 'ads-offset.cfg').as_posix(), backend, output.as_posix()]
            # Recheck the independently anchored package and staged bytes at the
            # last boundary before execution, not only after both CPU replays.
            verified = prepared.verify_precompiled(oracle, root, input_manifest,
                                                   expected_oracle_receipt_sha256, capture_rustc_sha256)
            _compare(preparation, verified['receipt'], 'original oracle preparation changed before CPU execution')
            _compare(before, producer.inventory(implementation), 'source implementation or staged inputs changed before CPU execution')
            _compare(immutable, producer.inventory({path: Path(path) for path in immutable}),
                     'original native inputs changed before CPU execution')
            for name, (source, expected) in copies.items():
                _compare(expected, producer.digest(source), f'{name}: original bytes changed before CPU execution')
                _compare(expected, producer.digest(work / name), f'{name}: staged bytes changed before CPU execution')
            executions[backend] = producer.process(command, root, env, evidence / f'logs/{backend}', 1800)
            records = [binding._parse(line, f'{backend}:{index}')
                       for index, line in enumerate(output.read_bytes().splitlines())]
            require(len(records) == binding.FRAME_COUNT + 1
                    and all(type(row) is dict and type(row.get('frame')) is int and row['frame'] == index
                            for index, row in enumerate(records[1:])),
                    f'{backend}: source output must enumerate all 553 frames')
            backend_reports[backend] = {'command': command, 'exit_code': 0,
                                        'output': producer.digest(output), 'header': records[0]}
            outputs[role] = relative
        after = producer.inventory(implementation)
        _compare(before, after, 'current source implementation/executable/inputs changed during replay')
        _compare(current_main_context(), context, 'current execution context changed')
        check_checkout(root, context)
        prepared.verify_precompiled(oracle, root, input_manifest, expected_oracle_receipt_sha256, capture_rustc_sha256)
        producer.validate_consumed_inputs(root, manifest, offset)
        _compare(immutable, producer.inventory({path: Path(path) for path in immutable}), 'immutable native inputs changed')
        for scenario, saved in reports.items():
            shared.verify_files(shards / scenario, saved['files'])
        report['phase'] = 'package-current-source-replay'
        packet_root = evidence / 'packet'
        packet_root.mkdir()
        files = {name: 'inventory/' + name for name in implementation}
        for name, source in implementation.items():
            producer.copy_packet_file(source, packet_root / files[name], before[name])
        for role, name in outputs.items():
            producer.copy_packet_file(root / name, packet_root / name, backend_reports[binding.BACKENDS[role][0]]['output'])
        key = lambda name: (work / name).relative_to(root).as_posix()
        receipt = {'schema': 'rust-duty-source-visibility-certificates-binding/v1',
                   'source_base_commit': context['source_commit'], 'source_execution_context': context,
                   'capture_context': context, 'capture_rustc_sha256': capture_rustc_sha256,
                   'toolchain': preparation['toolchain'], 'precompiled_receipt_sha256': expected_oracle_receipt_sha256,
                   'inputs_and_implementation_before': before, 'inputs_and_implementation_after': after,
                   'backend_reports': backend_reports, 'reviewed_manifest_dependency_mapping': binding.MANIFEST_ASSETS,
                   'oracle_execution': {'schema': 'rust-duty-native-source-oracle/v1', 'platform': sys.platform,
                                        'machine': platform.machine(), 'host': producer.TARGET, 'target': producer.TARGET,
                                        'profile': 'release', 'features': producer.FEATURES,
                                        'rustc_vv': key('rustc-Vv.txt'), 'build_receipt': key('build-receipt.json'),
                                        'executable': executable_key, 'execution_receipts': executions},
                   'acceptance_verdict': None}
        producer.write_json(packet_root / 'source-receipt.json', receipt)
        packet_path = packet_root / 'source-packet.json'
        producer.write_json(packet_path, {'schema': binding.SCHEMA, 'capture_binding': native,
                            'original_invocations': invocations, 'receipt': 'source-receipt.json',
                            'recorded_root': root.as_posix(), 'files': files, 'source_outputs': outputs,
                            'input_files': {name: offset_key if name == 'ads-offset.cfg' else name for name in binding.INPUTS}})
        receipt_sha = producer.digest(packet_root / 'source-receipt.json')['sha256']
        receipt_anchor.parent.mkdir(parents=True, exist_ok=True)
        with receipt_anchor.open('x', encoding='ascii', newline='\n') as stream:
            stream.write(receipt_sha + '\n')
        report['source_receipt_sha256'] = receipt_sha
        print(f'INDEPENDENT_SOURCE_RECEIPT_SHA256={receipt_sha}', flush=True)
        emit_outputs(source_receipt_sha256=receipt_sha, capture_rustc_sha256=capture_rustc_sha256)
        report['phase'] = 'bind-finite-ads-profile'
        require(reviewed_class is not None and expected_class_sha256 is not None,
                'completed independently bound finite ADS profile is required')
        frame_dirs = {role: shards / 'ads-offset' / reports['ads-offset']['capture_paths'][role]
                      for role in binding.ROLES}
        packet = binding.bind_source_packet(packet_path, expected_receipt_sha256=receipt_sha,
            expected_compiler_sha256=capture_rustc_sha256, native_binding=native,
            original_invocations=invocations, native_frame_dirs=frame_dirs,
            native_offset_settings=offset)
        profile = leaf.bind_bounded_profile(packet, packet_path, reviewed_class, expected_class_sha256,
                                           shards / 'ads-offset')
        profile_identity = leaf.bounded_profile_summary(profile)
        report['bounded_ads_profile'] = profile_identity
        report['bounded_ads_profile_established'] = True
        report['phase'] = 'reviewed-ads-leaf-revalidation'
        leaf_evidence = evidence / 'leaf'
        result = leaf.run(input_manifest=input_manifest, gameplay_shard=shards / 'ads-gameplay',
                          offset_shard=shards / 'ads-offset', source_packet=packet_path,
                          source_receipt_sha256=receipt_sha, capture_rustc_sha256=capture_rustc_sha256,
                          evidence=leaf_evidence, capture_context=context, verifier_context=context,
                          reviewed_class=reviewed_class, expected_class_sha256=expected_class_sha256)
        require(result['passed'] is True, f'reviewed ADS leaf did not pass: {result.get("failure")}')
        require(result.get('bounded_ads_profile_established') is True
                and result.get('conditional_diagnostic') is False,
                'reviewed ADS leaf requires an established finite profile')
        _compare(result.get('bounded_ads_profile'), profile_identity, 'ADS leaf/finite profile identity')
        packet.verify_unchanged()
        require(shared._read_regular(packet_root / 'source-receipt.json') == receipt_sha,
                'independently anchored source receipt changed during leaf validation')
        _compare(immutable, producer.inventory({path: Path(path) for path in immutable}), 'immutable capture verdicts changed')
        for scenario, saved in reports.items():
            shared.verify_files(shards / scenario, saved['files'])
        profile.verify_unchanged()
        request = {'leaf_summary': (leaf_evidence / 'summary.json').as_posix(), 'source_packet': packet_path.as_posix(),
                   'source_receipt_sha256': receipt_sha, 'capture_rustc_sha256': capture_rustc_sha256,
                   'capture_context': deepcopy(context), 'leaf_verifier_context': deepcopy(context),
                   'verifier_context': deepcopy(context), 'reviewed_class': str(Path(reviewed_class).absolute()),
                   'expected_class_sha256': expected_class_sha256}
        supplement_path = evidence / 'aggregate-supplement.json'
        producer.write_json(supplement_path, request)
        emit_outputs(supplement_path=supplement_path.as_posix())
        report.update(passed=True, phase='complete', source_receipt_sha256=receipt_sha,
                      supplement_path=supplement_path.as_posix())
        return report
    except Exception as error:
        report['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        producer.write_json(evidence / 'producer-summary.json', report)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'input-manifest', 'shards', 'oracle', 'evidence', 'receipt-anchor'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--expected-oracle-receipt-sha256', required=True)
    parser.add_argument('--capture-rustc-sha256', required=True)
    parser.add_argument('--reviewed-class', type=Path)
    parser.add_argument('--expected-class-sha256', help='Independent digest of the completed reviewed finite ADS profile class.')
    args = vars(parser.parse_args(argv))
    print(json.dumps(aggregate.plain(assemble(**args)), indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

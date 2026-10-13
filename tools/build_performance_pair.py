#!/usr/bin/env python3
"""Fresh fixed-profile Windows game builds for the reviewed four-file CPU pair.

Uses real Git source identities and real GitHub build metadata. Only procedural
runtime packages (public UI, no game assets) are produced. Nothing is published.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

import build_identity
import performance_matrix as matrix
import run_cpu_image_preservation as pair

BASELINE_TREE = '6027ffefbad4becad75a06e65516898be1bb5990'
COMMAND = ['cargo', 'build', '--locked', '--release', '--no-default-features',
           '--features', 'wgpu-runtime', '--bin', 'vector-range']
SETTINGS = {'CARGO_INCREMENTAL': '0', 'CARGO_BUILD_JOBS': '2', 'CARGO_PROFILE_RELEASE_DEBUG': '0'}


def source_inputs(root, expected_runtime):
    matrix.require(not pair.git(root, 'status', '--porcelain', '--untracked-files=no').strip(),
                   'Build source has tracked changes')
    matrix.require(not pair.git(root, 'ls-files', '--others', '--exclude-standard', '--',
                                *pair.PRODUCTION_PATHS, 'ui', 'settings.cfg').strip(),
                   'Untracked compile/UI/settings inputs')
    matrix.require('VR_WEAPON_ASSET' not in os.environ
                   and not (root / 'assets/weapons/hk416a5.vrm').exists(), 'Build must remain asset-free')
    source = matrix.source_identity(root)
    matrix.require(matrix.canonical_hash(source['runtime_files_sha256']) == expected_runtime,
                   'Wrong reviewed runtime source variant')
    files = pair.read_sources(root, source['commit'], pair.PRODUCTION_PATHS)
    notices = root / 'updater/notices/THIRD_PARTY_UPDATER_LICENSES.txt'
    matrix.require(not (notices.exists() or notices.is_symlink())
                   or notices.relative_to(root).as_posix() in files,
                   'Untracked generated updater notices would change the build')
    adjacent = pair.read_sources(root, source['commit'], ['ui', 'settings.cfg'])
    for name, raw in {**files, **adjacent}.items():
        matrix.require((root / name).read_bytes() == raw, 'Checkout bytes differ: ' + name)
    return source, files, adjacent


def build_pair(root, baseline, output, build_timeout=1800):
    matrix.require(sys.platform == 'win32', 'Build the real comparison pair on Windows MSVC')
    pair.check_environment(os.environ)
    matrix.require(pair.gpu.positive(build_timeout), 'Build timeout must be positive and finite')
    matrix.require(not Path(output).is_symlink(), 'Build output must not be a symlink')
    root, baseline, output = Path(root).resolve(), Path(baseline).resolve(), Path(output).resolve()
    matrix.require(root == Path(__file__).resolve().parents[1], 'Build helper and candidate checkout differ')
    matrix.require(root != baseline and not output.exists(), 'Need separate sources and fresh build evidence')
    matrix.require(pair.git(baseline, 'rev-parse', 'HEAD^{tree}').decode().strip() == BASELINE_TREE,
                   'Baseline full Git tree differs from the reviewed counterfactual')
    inputs = {label: source_inputs(path, expected) for label, path, expected in (
        ('baseline', baseline, matrix.AUDITED_GPU_CPU_BASELINE_MANIFEST),
        ('candidate', root, matrix.AUDITED_GPU_CANDIDATE_MANIFEST))}
    hashes = {label: pair.hashes(value[1]) for label, value in inputs.items()}
    matrix.require(matrix.canonical_hash(hashes['candidate']) == matrix.AUDITED_GPU_PRODUCTION_MANIFEST
                   and hashes['baseline'] == {**hashes['candidate'], **pair.CPU_BASELINE},
                   'Build pair differs from the exact closed production inventories')
    matrix.require(inputs['baseline'][2] == inputs['candidate'][2], 'Public UI/settings differ between builds')
    matrix.require(os.environ.get('GITHUB_SHA') == inputs['candidate'][0]['commit'],
                   'Candidate must match the actual GitHub build source')
    compiler = pair.toolchain_at(root)
    matrix.require('release: 1.99.0\n' in compiler['rustc']
                   and 'host: x86_64-pc-windows-msvc\n' in compiler['rustc']
                   and compiler['cargo'].startswith('cargo 1.99.0 '), 'Use reviewed Rust1.99.0 Windows MSVC')
    # Verify real CI build identity before spending compilation time. No fabricated
    # local run number or release identity is accepted by this producer.
    matrix.require(os.environ.get('GITHUB_ACTIONS') == 'true'
                   and os.environ.get('GITHUB_WORKFLOW_REF', '').startswith(
                       'RHS059/rust_duty/.github/workflows/build.yml@'),
                   'Use the real build.yml workflow identity')
    ci_identity = build_identity.context()
    output.mkdir(parents=True)
    matrix.write_json(output / 'BUILD_INPUTS.json', {'candidate_source': inputs['candidate'][0],
        'baseline_source': inputs['baseline'][0], 'compiler': compiler, 'ci_identity': ci_identity,
        'production_files_sha256': hashes, 'public_adjacent_sha256': pair.hashes(inputs['candidate'][2])})
    retained = {output / 'BUILD_INPUTS.json': matrix.sha256(output / 'BUILD_INPUTS.json')}
    directories = {}
    results = {}
    try:
        for label, source_root in (('baseline', baseline), ('candidate', root)):
            source, files, adjacent = inputs[label]
            folder = output / label
            folder.mkdir()
            env = dict(os.environ, **SETTINGS, CARGO_TARGET_DIR=str(folder / 'target'))
            pair.check_cargo_configuration(source_root, env)
            matrix.require(pair.toolchain_at(source_root) == compiler, 'Source-directory toolchain differs')
            witness_sha = matrix.export_witness(source_root, folder / 'source-witness')
            pair.logged(COMMAND, source_root, folder / 'build', env, build_timeout)
            pair.check_cargo_configuration(source_root, env)
            matrix.require(pair.toolchain_at(source_root) == compiler, 'Compiler changed during build')
            matrix.require(source_inputs(source_root, matrix.canonical_hash(source['runtime_files_sha256']))
                           == inputs[label], 'Source changed during release build')
            package = folder / 'package'
            package.mkdir()
            executable = package / 'vector-range.exe'
            shutil.copyfile(folder / 'target/release/vector-range.exe', executable)
            for name, raw in adjacent.items():
                destination = package / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw)
            # Both variants belong to this real CI run; the baseline's actual
            # separately checked-out commit is retained instead of relabeling it.
            identity_env = dict(os.environ, GITHUB_SHA=source['commit'])
            build_identity.stamp(package, 'windows', identity_env)
            receipt = {'schema': 'rust-duty-performance-release-build/v1',
                'source_commit': source['commit'], 'production_files_sha256': hashes[label],
                'executable_sha256': matrix.sha256(executable), 'command': COMMAND,
                'build_settings': SETTINGS, 'toolchain': compiler,
                'build_result': matrix.json_read(folder / 'build/result.json'),
                'build_evidence_files_sha256': pair.controls.source_manifest(folder / 'build'),
                'ci_run_source_commit': ci_identity['source']['commit'],
                'source_variant': label, 'baseline_is_exact_four_file_counterfactual': label == 'baseline',
                'scope': 'Fresh release build from exact checked-out Git bytes; no embedded or adjacent game assets'}
            matrix.write_json(folder / 'build-receipt.json', receipt)
            retained[folder / 'build-receipt.json'] = matrix.sha256(folder / 'build-receipt.json')
            for name in ('build', 'package', 'source-witness'):
                directories[folder / name] = pair.controls.source_manifest(folder / name)
            results[label] = {'source_commit': source['commit'], 'source_witness_sha256': witness_sha,
                'executable_sha256': receipt['executable_sha256'],
                'build_receipt_sha256': matrix.sha256(folder / 'build-receipt.json')}
        for label, source_root in (('baseline', baseline), ('candidate', root)):
            expected = matrix.canonical_hash(inputs[label][0]['runtime_files_sha256'])
            matrix.require(source_inputs(source_root, expected) == inputs[label], 'Earlier source changed')
            matrix.require(pair.toolchain_at(source_root) == compiler, 'Final source toolchain differs')
            pair.check_cargo_configuration(source_root, os.environ)
            matrix.require(matrix.sha256(output / label / 'package/vector-range.exe')
                           == results[label]['executable_sha256'], 'Earlier executable changed')
        matrix.require(all(matrix.sha256(path) == digest for path, digest in retained.items()),
                       'Earlier build input or release receipt changed')
        matrix.require(all(pair.controls.source_manifest(path) == expected
                           for path, expected in directories.items()),
                       'Earlier package, source witness or build evidence changed')
        matrix.write_json(output / 'BUILD_PAIR.json', {'passed': True, 'variants': results,
            'runtime_executed': False, 'scope': 'Only --build-version/--build-label metadata entrypoints executed'})
        return results
    except BaseException as error:
        matrix.write_json(output / 'BUILD_FAILURE.json', {'passed': False, 'error': str(error),
                                                         'type': type(error).__name__})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--build-timeout', type=float, default=1800)
    args = parser.parse_args(argv)
    try:
        build_pair(args.root, args.baseline, args.output, args.build_timeout)
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print('Performance build pair failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

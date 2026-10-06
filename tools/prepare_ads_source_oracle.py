#!/usr/bin/env python3
"""Prepare a small same-run Windows oracle executable, without rendering.

The authored-input job publishes the receipt digest separately as a job output.
The aggregate rechecks that anchor and all original source/runtime bytes before
using the executable. Companions stay in their existing source-bound artifacts.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tomllib

import ads_source_visibility_binding as binding
import build_ads_source_packet as producer
import dx12_authored_shards as shared
import revalidate_ads_offset as revalidate
from verify_capture_telemetry import _compare, read_record

SCHEMA = 'rust-duty-precompiled-source-oracle/v1'
TARGET = producer.TARGET
EXAMPLE = producer.EXAMPLE
FILES = ('source_visibility_certificate.exe', 'rustc-Vv.txt', 'build-receipt.json', 'input-manifest.json')


def require(value, message):
    if not value:
        raise ValueError(message)


def implementation_paths(root):
    paths = producer.production_files(root)
    for name in (f'examples/{EXAMPLE}.rs', 'tools/build_ads_source_packet.py',
                 'tools/prepare_ads_source_oracle.py'):
        paths[name] = root / name
    return paths


def require_tracked_source(root, paths):
    subprocess.check_output(['git', '-C', str(root), 'ls-files', '--error-unmatch', '--', *paths], stderr=subprocess.PIPE, timeout=60)
    require(not subprocess.check_output(['git', '-C', str(root), 'diff', '--name-only', 'HEAD', '--', *paths], timeout=60),
            'oracle production source has tracked modifications')


def native_inputs(root, manifest):
    for name, expected in manifest['binding']['runtime_and_manifest_sha256'].items():
        shared._safe_key(name)
        require(shared._read_regular(root / name) == expected, f'native runtime input differs: {name}')
    for name, field in (('Cargo.toml', 'cargo_manifest_sha256'), ('Cargo.lock', 'cargo_lock_sha256')):
        require(shared._read_regular(root / name, canonical_lf=True) == manifest['binding'][field],
                f'native build input differs: {name}')
    profile = tomllib.loads((root / 'Cargo.toml').read_text(encoding='utf-8')).get('profile', {}).get('release')
    _compare(profile, binding.ORACLE_RELEASE_PROFILE, 'native oracle release profile')


def compiler_identity(raw, expected):
    require(type(expected) is str and re.fullmatch('[0-9a-f]{64}', expected), 'missing independently captured compiler SHA256')
    producer.checked_compiler(raw, expected)
    lines = raw.decode('utf-8').splitlines()
    releases = [line.removeprefix('release: ') for line in lines if line.startswith('release: ')]
    require(len(releases) == 1 and re.fullmatch(r'\d+\.\d+\.\d+', releases[0]), 'compiler release must be exact and stable')
    require(lines[0].startswith('rustc ' + releases[0] + ' ('), 'compiler header/release disagree')
    return releases[0] + '-' + TARGET


def build_command(cargo):
    return [Path(cargo).as_posix(), 'build', '--locked', '--release', '--no-default-features',
            '--target', TARGET, '--example', EXAMPLE, '--features', ','.join(producer.FEATURES)]


def verify_precompiled(artifact_dir, root, input_manifest, expected_receipt_sha256, expected_compiler_sha256):
    """Verify a current-run build against the independently retained job outputs."""
    artifact_dir, root, input_manifest = map(lambda p: Path(p).absolute(), (artifact_dir, root, input_manifest))
    shared._checked_root(artifact_dir)
    require(type(expected_receipt_sha256) is str and re.fullmatch('[0-9a-f]{64}', expected_receipt_sha256),
            'missing independent oracle build receipt SHA256')
    receipt_path = artifact_dir / 'receipt.json'
    require(shared._read_regular(receipt_path) == expected_receipt_sha256, 'oracle build receipt differs from job output')
    receipt = read_record(receipt_path)
    expected_keys = {'schema', 'capture_context', 'capture_binding', 'input_manifest_sha256',
                     'platform', 'machine', 'host', 'target', 'profile', 'features', 'recorded_root',
                     'executable', 'compiler_sha256', 'toolchain', 'active_toolchain_alias',
                     'implementation_before', 'implementation_after', 'files'}
    shared._exact_keys(receipt, expected_keys, 'oracle preparation receipt')
    context = shared.context()
    manifest = revalidate.manifest_binding(input_manifest, context)
    require(subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True, timeout=60).strip()
            == context['source_commit'], 'current oracle checkout differs from native capture source')
    _compare(receipt['capture_context'], context, 'current oracle capture context')
    shared.compare_binding(receipt['capture_binding'], manifest['binding'])
    require(receipt['input_manifest_sha256'] == shared._read_regular(input_manifest), 'oracle native manifest changed')
    for key, expected in {'schema': SCHEMA, 'platform': 'win32', 'host': TARGET, 'target': TARGET,
                          'profile': 'release', 'features': producer.FEATURES,
                          'executable': f'target/{TARGET}/release/examples/{EXAMPLE}.exe'}.items():
        _compare(receipt[key], expected, f'oracle preparation/{key}')
    require(receipt['machine'] in ('AMD64', 'x86_64'), 'oracle was not prepared on native Windows x86_64')
    require(type(receipt['active_toolchain_alias']) is str and
            re.fullmatch(r'[A-Za-z0-9._-]+', receipt['active_toolchain_alias']), 'invalid recorded active compiler alias')
    names = {name for name, _ in shared._walk_files(artifact_dir)}
    require(names == set(FILES) | {'receipt.json'}, 'unexpected or missing precompiled oracle file')
    shared._exact_keys(receipt['files'], FILES, 'oracle preparation file inventory')
    for name in FILES:
        _compare(producer.digest(artifact_dir / name), receipt['files'][name], f'precompiled oracle/{name}')
    require(receipt['files']['input-manifest.json']['sha256'] == receipt['input_manifest_sha256'],
            'packaged native manifest differs')
    _compare(read_record(artifact_dir / 'input-manifest.json'), manifest, 'packaged native manifest')
    require(receipt['compiler_sha256'] == expected_compiler_sha256, 'oracle compiler differs from authored-input job output')
    compiler = (artifact_dir / 'rustc-Vv.txt').read_bytes()
    _compare(compiler_identity(compiler, expected_compiler_sha256), receipt['toolchain'], 'canonical oracle compiler')
    before = receipt['implementation_before']
    _compare(before, receipt['implementation_after'], 'oracle compilation changed source')
    paths = implementation_paths(root)
    require_tracked_source(root, paths)
    _compare(before, producer.inventory(paths), 'current oracle production source')
    native_inputs(root, manifest)
    recorded_root = binding._recorded_path(receipt['recorded_root'])
    command = binding._oracle_process(read_record(artifact_dir / 'build-receipt.json'), recorded_root, 'precompiled oracle build')
    recorded_paths = {binding._recorded_path(name, recorded_root): name for name in before}
    implementation = {name.casefold(): name for name in before}
    binding._oracle_build(command, EXAMPLE, recorded_root, recorded_paths, implementation)
    # No alias is used to rebuild here: the hash-bound executable is the result.
    require(shared._read_regular(receipt_path) == expected_receipt_sha256, 'oracle receipt changed during verification')
    return {'receipt': receipt, 'executable': artifact_dir / FILES[0],
            'rustc_vv': artifact_dir / FILES[1], 'build_receipt': artifact_dir / FILES[2],
            'input_manifest': artifact_dir / FILES[3], 'receipt_path': receipt_path}


def prepare(root, input_manifest, evidence, expected_compiler_sha256):
    root, input_manifest = Path(root).resolve(strict=True), Path(input_manifest).resolve(strict=True)
    evidence = Path(evidence).absolute()
    require(not evidence.exists(), 'refusing existing oracle preparation evidence')
    evidence.mkdir(parents=True)
    report = {'schema': SCHEMA + '/preparation', 'passed': False, 'acceptance_complete': False}
    try:
        require(sys.platform == 'win32' and platform.machine() in ('AMD64', 'x86_64'), 'oracle preparation requires native Windows x86_64')
        context = shared.context()
        manifest_digest = producer.digest(input_manifest)
        manifest = revalidate.manifest_binding(input_manifest, context)
        require(subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True, timeout=60).strip()
                == context['source_commit'], 'oracle checkout differs from current capture source')
        paths = implementation_paths(root)
        require_tracked_source(root, paths)
        native_inputs(root, manifest)
        before = producer.inventory(paths)
        raw = subprocess.check_output(['rustc', '-Vv'], cwd=root, timeout=60)
        canonical = compiler_identity(raw, expected_compiler_sha256)
        active = subprocess.check_output(['rustup', 'show', 'active-toolchain'], cwd=root, text=True, timeout=60).split()[0]
        require(re.fullmatch(r'[A-Za-z0-9._-]+', active), 'invalid active toolchain alias')
        env = producer.execution_environment(root, active)
        producer.checked_compiler(subprocess.check_output(['rustc', '-Vv'], cwd=root, env=env, timeout=60), expected_compiler_sha256)
        cargo = shutil.which('cargo', path=env.get('PATH'))
        require(cargo, 'active Cargo executable unavailable')
        command = build_command(cargo)
        build = producer.process(command, root, env, evidence / 'logs/build', 2700)
        require(subprocess.check_output(['rustc', '-Vv'], cwd=root, env=env, timeout=60) == raw, 'compiler changed during oracle build')
        after = producer.inventory(paths)
        _compare(before, after, 'oracle build changed production source')
        native_inputs(root, manifest)
        executable = root / f'target/{TARGET}/release/examples/{EXAMPLE}.exe'
        require(0 < shared._checked_stat(executable, 'file').st_size <= 64 * 1024**2, 'missing or oversized oracle executable')
        package = evidence / 'package'
        package.mkdir()
        producer.copy_packet_file(executable, package / FILES[0], producer.digest(executable))
        (package / FILES[1]).write_bytes(raw)
        producer.write_json(package / FILES[2], build)
        producer.copy_packet_file(input_manifest, package / FILES[3], manifest_digest)
        receipt = {'schema': SCHEMA, 'capture_context': context, 'capture_binding': deepcopy(manifest['binding']),
                   'input_manifest_sha256': manifest_digest['sha256'], 'platform': sys.platform,
                   'machine': platform.machine(), 'host': TARGET, 'target': TARGET, 'profile': 'release',
                   'features': producer.FEATURES, 'recorded_root': root.as_posix(),
                   'executable': executable.relative_to(root).as_posix(), 'compiler_sha256': expected_compiler_sha256,
                   'toolchain': canonical, 'active_toolchain_alias': active,
                   'implementation_before': before, 'implementation_after': after,
                   'files': {name: producer.digest(package / name) for name in FILES}}
        producer.write_json(package / 'receipt.json', receipt)
        anchor = shared._read_regular(package / 'receipt.json')
        verify_precompiled(package, root, input_manifest, anchor, expected_compiler_sha256)
        (evidence / 'independent-receipt.sha256').write_text(anchor + '\n', encoding='ascii', newline='\n')
        report.update(passed=True, capture_context=context, receipt_sha256=anchor,
                      compiler_sha256=expected_compiler_sha256)
        print(f'PRECOMPILED_ORACLE_RECEIPT_SHA256={anchor}', flush=True)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8', newline='\n') as output:
                output.write(f'receipt_sha256={anchor}\ncompiler_sha256={expected_compiler_sha256}\n')
        return report
    except Exception as error:
        report['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        producer.write_json(evidence / 'prepare-summary.json', report)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'input-manifest', 'evidence'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--capture-rustc-sha256', required=True)
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.root, args.input_manifest, args.evidence, args.capture_rustc_sha256), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

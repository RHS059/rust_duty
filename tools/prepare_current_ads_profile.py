#!/usr/bin/env python3
"""Build the two current-source ADS profile diagnostics on native Windows.

No source overlay, historical input restoration, rendering, or profile approval
occurs here. The authored-input job independently retains the receipt digest and
the capture compiler digest; consumers must supply both anchors explicitly.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
from types import MappingProxyType

import ads_source_visibility_binding as binding
import build_ads_source_packet as producer
import dx12_authored_shards as shared
import prepare_ads_source_oracle as oracle
import revalidate_ads_offset as revalidate
from verify_capture_telemetry import _compare, read_record

SCHEMA = 'rust-duty-precompiled-current-ads-profile/v1'
TARGET = producer.TARGET
EXAMPLES = ('source_visibility_geometry_probe', 'finite_warp_probe')
EXECUTABLES = {name: name + '.exe' for name in EXAMPLES}
BUILD_RECEIPTS = {name: name + '-build-receipt.json' for name in EXAMPLES}
FILES = (*EXECUTABLES.values(), 'rustc-Vv.txt', *BUILD_RECEIPTS.values(), 'input-manifest.json')
REQUIRED_IMPLEMENTATION = (
    'Cargo.toml', 'Cargo.lock', 'build.rs', 'build_number.rs', 'rust-toolchain.toml',
    'updater/Cargo.toml', 'updater/Cargo.lock', 'updater/build.rs',
    'examples/source_visibility_geometry_probe.rs',
    'examples/source_visibility_geometry/domain.rs', 'examples/finite_warp_probe.rs',
    'tools/build_ads_source_packet.py', 'tools/prepare_ads_source_oracle.py',
    'tools/prepare_current_ads_profile.py', 'tools/current_ads_profile_proof.py',
)


def require(value, message):
    if not value:
        raise ValueError(message)


def _freeze(value):
    """Keep the validated receipt recursively immutable for downstream callers."""
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def implementation_paths(root):
    """Inventory complete local production and dependent diagnostic source.

    Including every Python helper keeps transitive diagnostic imports bound,
    including additions to the proof's import graph. Discover on-disk source as
    well as tracked source so untracked or ignored Rust/Python injections fail
    the tracked-source check instead of silently disappearing from the receipt.
    """
    root = Path(root)
    paths = producer.production_files(root)
    for directory in ('src', 'updater/src', 'examples/source_visibility_geometry'):
        for name, path in shared._walk_files(root / directory):
            paths[directory + '/' + name] = path
    for name, path in shared._walk_files(root / 'tools'):
        if path.suffix == '.py':
            paths['tools/' + name] = path
    for name in REQUIRED_IMPLEMENTATION:
        paths[name] = root / name
    # The updater build script optionally embeds this generated notice. An
    # untracked copy must not silently change the supposedly tracked build.
    notice = 'updater/notices/THIRD_PARTY_UPDATER_LICENSES.txt'
    if (root / notice).exists() or (root / notice).is_symlink():
        paths[notice] = root / notice
    for name in paths:
        shared._safe_key(name)
    require(len({name.casefold() for name in paths}) == len(paths), 'source inventory contains path aliases')
    return dict(sorted(paths.items()))


def require_tracked_source(root, paths):
    # Git's NUL-delimited inventory avoids a large Windows command line while
    # retaining an exact closed tracked set and requiring the original HEAD.
    tracked = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z'], timeout=60).decode('utf-8').split('\0')
    require(set(paths) <= set(tracked), 'profile implementation source is not tracked')
    changed = subprocess.check_output(['git', '-C', str(root), 'diff', '--name-only', '-z', 'HEAD', '--'], timeout=60).decode('utf-8').split('\0')
    require(not set(paths).intersection(changed), 'profile implementation source has tracked modifications')
    for name, path in paths.items():
        # Reject symlinked source directories as well as linked leaf files.
        current = path
        while current != root:
            shared._checked_stat(current, 'file' if current == path else 'directory')
            current = current.parent


def native_inputs(root, manifest):
    oracle.native_inputs(root, manifest)
    assets = {f'assets/{name}': shared._read_regular(path)
              for name, path in shared._walk_files(root / 'assets')
              if path.suffix in ('.vra', '.vrs', '.vrm', '.json', '.cfg')}
    assets['settings.cfg'] = shared._read_regular(root / 'settings.cfg')
    _compare(assets, manifest['binding']['runtime_and_manifest_sha256'], 'current profile native runtime inputs')
    reference = shared.make_gl_reference(root / shared.GL_RUNTIME_PATH, root / shared.GL_LOCK_PATH)
    _compare(reference, manifest['gl_reference'], 'current profile native GL inputs')


def compiler_identity(raw, expected):
    return oracle.compiler_identity(raw, expected)


def build_command(cargo, example):
    require(example in EXAMPLES, 'unsupported current ADS profile example')
    return [Path(cargo).as_posix(), 'build', '--locked', '--release', '--no-default-features',
            '--target', TARGET, '--example', example, '--features', ','.join(producer.FEATURES)]


def _checkout(root, context):
    shared._checked_root(root)
    require(subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True, timeout=60).strip()
            == context['source_commit'], 'current profile checkout differs from native capture source')


def _package_files(artifact_dir, receipt):
    shared._exact_keys(receipt['files'], FILES, 'current profile file inventory')
    # All package files are top-level. Even an otherwise empty extra directory
    # is not part of the closed artifact contract.
    names = {name for name, _ in shared._walk_files(artifact_dir)}
    require(names == set(FILES) | {'receipt.json'} and
            {path.name for path in artifact_dir.iterdir()} == names,
            'unexpected or missing precompiled current profile file')
    for name in FILES:
        _compare(producer.digest(artifact_dir / name), receipt['files'][name], f'precompiled profile/{name}')
    for name in EXECUTABLES.values():
        require(0 < receipt['files'][name]['bytes'] <= 64 * 1024**2, 'missing or oversized profile executable')


def verify_precompiled(artifact_dir, root, input_manifest, expected_receipt_sha256, expected_compiler_sha256):
    """Verify both binaries against external job outputs and current clean source.

    Return executable paths and a deeply immutable receipt, never a newly
    calculated anchor that could authorize its own candidate evidence.
    """
    artifact_dir, root, input_manifest = map(lambda p: Path(p).absolute(), (artifact_dir, root, input_manifest))
    shared._checked_root(artifact_dir)
    for value, label in ((expected_receipt_sha256, 'receipt'), (expected_compiler_sha256, 'compiler')):
        require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value),
                f'missing independently captured current profile {label} SHA256')
    receipt_path = artifact_dir / 'receipt.json'
    require(shared._read_regular(receipt_path) == expected_receipt_sha256, 'current profile receipt differs from job output')
    receipt = read_record(receipt_path)
    shared._exact_keys(receipt, {'schema', 'capture_context', 'capture_binding', 'input_manifest_sha256',
        'platform', 'machine', 'host', 'target', 'profile', 'features', 'recorded_root',
        'executables', 'compiler_sha256', 'toolchain', 'active_toolchain_alias',
        'implementation_before', 'implementation_after', 'files'}, 'current profile preparation receipt')
    context = shared.context()
    _checkout(root, context)
    manifest = revalidate.manifest_binding(input_manifest, context)
    _compare(receipt['capture_context'], context, 'current profile capture context')
    shared.compare_binding(receipt['capture_binding'], manifest['binding'])
    manifest_sha = shared._read_regular(input_manifest)
    require(receipt['input_manifest_sha256'] == manifest_sha, 'current profile native manifest changed')
    for key, expected in {'schema': SCHEMA, 'platform': 'win32', 'host': TARGET, 'target': TARGET,
                          'profile': 'release', 'features': producer.FEATURES,
                          'executables': {name: f'target/{TARGET}/release/examples/{name}.exe' for name in EXAMPLES}}.items():
        _compare(receipt[key], expected, f'current profile preparation/{key}')
    require(receipt['machine'] in ('AMD64', 'x86_64'), 'profile was not prepared on native Windows x86_64')
    require(type(receipt['active_toolchain_alias']) is str and
            re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', receipt['active_toolchain_alias']), 'invalid recorded active compiler alias')
    _package_files(artifact_dir, receipt)
    require(receipt['files']['input-manifest.json']['sha256'] == manifest_sha, 'packaged native manifest differs')
    _compare(read_record(artifact_dir / 'input-manifest.json'), manifest, 'packaged native manifest')
    require(receipt['compiler_sha256'] == expected_compiler_sha256, 'profile compiler differs from authored-input job output')
    compiler = (artifact_dir / 'rustc-Vv.txt').read_bytes()
    _compare(compiler_identity(compiler, expected_compiler_sha256), receipt['toolchain'], 'canonical profile compiler')
    before = receipt['implementation_before']
    _compare(before, receipt['implementation_after'], 'current profile compilation changed source')
    paths = implementation_paths(root)
    require_tracked_source(root, paths)
    _compare(before, producer.inventory(paths), 'current profile implementation source')
    native_inputs(root, manifest)
    recorded_root = binding._recorded_path(receipt['recorded_root'])
    recorded_paths = {binding._recorded_path(name, recorded_root): name for name in before}
    implementation = {name.casefold(): name for name in before}
    for example in EXAMPLES:
        command = binding._oracle_process(read_record(artifact_dir / BUILD_RECEIPTS[example]),
                                          recorded_root, f'current {example} build')
        binding._oracle_build(command, example, recorded_root, recorded_paths, implementation)
    # Detect replacement while parsing any package or input file; verification
    # never rewrites the incoming packet or refreshes either independent anchor.
    _package_files(artifact_dir, receipt)
    require(shared._read_regular(input_manifest) == manifest_sha, 'native input manifest changed during verification')
    require(shared._read_regular(receipt_path) == expected_receipt_sha256, 'profile receipt changed during verification')
    return {'receipt': _freeze(receipt),
            'executables': {name: artifact_dir / EXECUTABLES[name] for name in EXAMPLES},
            'rustc_vv': artifact_dir / 'rustc-Vv.txt',
            'build_receipts': {name: artifact_dir / BUILD_RECEIPTS[name] for name in EXAMPLES},
            'input_manifest': artifact_dir / 'input-manifest.json', 'receipt_path': receipt_path}


def prepare(root, input_manifest, evidence, expected_compiler_sha256):
    root, input_manifest = Path(root).resolve(strict=True), Path(input_manifest).resolve(strict=True)
    evidence = Path(evidence).absolute()
    require(not evidence.exists() and not evidence.is_symlink(), 'refusing existing current profile preparation evidence')
    evidence.mkdir(parents=True)
    report = {'schema': SCHEMA + '/preparation', 'passed': False, 'acceptance_complete': False}
    try:
        require(sys.platform == 'win32' and platform.machine() in ('AMD64', 'x86_64'),
                'current profile preparation requires native Windows x86_64')
        context = shared.context()
        _checkout(root, context)
        manifest_digest = producer.digest(input_manifest)
        manifest = revalidate.manifest_binding(input_manifest, context)
        paths = implementation_paths(root)
        require_tracked_source(root, paths)
        native_inputs(root, manifest)
        before = producer.inventory(paths)
        raw = subprocess.check_output(['rustc', '-Vv'], cwd=root, timeout=60)
        canonical = compiler_identity(raw, expected_compiler_sha256)
        active = subprocess.check_output(['rustup', 'show', 'active-toolchain'], cwd=root, text=True, timeout=60).split()[0]
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', active), 'invalid active toolchain alias')
        env = producer.execution_environment(root, active)
        producer.checked_compiler(subprocess.check_output(['rustc', '-Vv'], cwd=root, env=env, timeout=60), expected_compiler_sha256)
        cargo = shutil.which('cargo', path=env.get('PATH'))
        require(cargo, 'active Cargo executable unavailable')
        builds, executables = {}, {}
        for example in EXAMPLES:
            producer.execution_environment(root, active, env)
            builds[example] = producer.process(build_command(cargo, example), root, env,
                                               evidence / 'logs' / example, 2700)
            require(subprocess.check_output(['rustc', '-Vv'], cwd=root, env=env, timeout=60) == raw,
                    'compiler changed during current profile build')
            producer.execution_environment(root, active, env)
            executable = root / f'target/{TARGET}/release/examples/{example}.exe'
            require(0 < shared._checked_stat(executable, 'file').st_size <= 64 * 1024**2,
                    f'missing or oversized {example} executable')
            executables[example] = producer.digest(executable)
            # Check after each process so a failed first build cannot be masked
            # by the second process restoring changed files.
            _checkout(root, context)
            after_paths = implementation_paths(root)
            require_tracked_source(root, after_paths)
            _compare(before, producer.inventory(after_paths), 'current profile build changed implementation source')
            native_inputs(root, manifest)
            require(producer.digest(input_manifest) == manifest_digest, 'native input manifest changed during profile build')
        after = producer.inventory(implementation_paths(root))
        _compare(before, after, 'current profile build changed implementation source')
        package = evidence / 'package'
        package.mkdir()
        for example in EXAMPLES:
            executable = root / f'target/{TARGET}/release/examples/{example}.exe'
            require(0 < shared._checked_stat(executable, 'file').st_size <= 64 * 1024**2,
                    f'missing or oversized {example} executable')
            producer.copy_packet_file(executable, package / EXECUTABLES[example], executables[example])
            producer.write_json(package / BUILD_RECEIPTS[example], builds[example])
        (package / 'rustc-Vv.txt').write_bytes(raw)
        producer.copy_packet_file(input_manifest, package / 'input-manifest.json', manifest_digest)
        receipt = {'schema': SCHEMA, 'capture_context': context, 'capture_binding': deepcopy(manifest['binding']),
                   'input_manifest_sha256': manifest_digest['sha256'], 'platform': sys.platform,
                   'machine': platform.machine(), 'host': TARGET, 'target': TARGET, 'profile': 'release',
                   'features': producer.FEATURES, 'recorded_root': root.as_posix(),
                   'executables': {name: f'target/{TARGET}/release/examples/{name}.exe' for name in EXAMPLES},
                   'compiler_sha256': expected_compiler_sha256, 'toolchain': canonical,
                   'active_toolchain_alias': active, 'implementation_before': before, 'implementation_after': after,
                   'files': {name: producer.digest(package / name) for name in FILES}}
        producer.write_json(package / 'receipt.json', receipt)
        anchor = shared._read_regular(package / 'receipt.json')
        verify_precompiled(package, root, input_manifest, anchor, expected_compiler_sha256)
        (evidence / 'independent-receipt.sha256').write_text(anchor + '\n', encoding='ascii', newline='\n')
        report.update(passed=True, capture_context=context, receipt_sha256=anchor,
                      compiler_sha256=expected_compiler_sha256)
        print(f'PRECOMPILED_CURRENT_ADS_PROFILE_RECEIPT_SHA256={anchor}', flush=True)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8', newline='\n') as output:
                output.write(f'receipt_sha256={anchor}\ncompiler_sha256={expected_compiler_sha256}\n')
        return report
    except Exception as error:
        report['passed'] = False
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

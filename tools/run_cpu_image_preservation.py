#!/usr/bin/env python3
"""Compare a named exact-source renderer experiment on Windows DX12/WARP.

The historical CPU mode restores four old CPU files. Geometry-reuse mode changes
only its compile-time upload policy and retains identical allocation diagnostics.
Both variants are freshly built. Existing fixed renderer and mixed line/text
fixtures own image checks; their wall times are never scored as performance.
"""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile

import dx12_contract_process as process
import performance_matrix as matrix
import run_gpu_session_contract as session
import run_pass_submission_benchmark as controls
import run_renderer_contract as renderer
import summarize_gpu_timing as gpu

BASELINE_CPU_COMMIT = '70ff2933ebe69b7180e207c7defebeaeb6e240e1'
CPU_BASELINE = {
    'src/draw/mod.rs': '9d3ea1559678bc9c5298bd423bf5546f207285596a25a43a44cd92127248c14a',
    'src/render/lines.rs': '9258cada6ad49cbb3dbd564b6f6c5b9fe78d86d37174f46aa2c1ef3c4f1669fc',
    'src/render/text.rs': '06ad5a1489c96152f516cfbade027ef2a7fa83f583889bed46c99f5dcd04a446',
    'src/render/plan.rs': 'c23e97a848435a610f5be0c72341ef8e5090fa2cd66846cda1b29159558a4c7e',
}
# All production and conditional-test compile inputs, not merely changed files
# or the narrow runtime witness. Update only after exact-source review.
# Historical timing pair admission keeps its own immutable closed digest.
PRODUCTION_MANIFEST = 'e8a9e43fd39a841868d069512b2bf1b69dac09144de1e1afdd29b355175f5bb6'
PRODUCTION_PATHS = ['Cargo.toml', 'Cargo.lock', 'build.rs', 'build_number.rs',
                    'LICENSE', 'THIRD_PARTY_LICENSES.txt', 'rust-toolchain',
                    'rust-toolchain.toml', '.cargo', '.gitattributes', 'src', 'updater']
EXAMPLES = ('renderer_contract', 'pass_submission_benchmark')
HARNESS_PATHS = [f'examples/{name}.rs' for name in EXAMPLES]
UPLOAD_POLICY_PATH = 'src/frame_upload_policy.rs'
UPLOAD_POLICY_ENABLED = b'REUSE_ENABLED: bool = true;'
UPLOAD_POLICY_DISABLED = b'REUSE_ENABLED: bool = false;'
ARENA_PATH = 'src/render/arena.rs'
ARENA_BASELINE_SHA256 = '5e39d00125b34d07ec23f845841809c0effa678980b1395988880b7d23674ddb'
EXPERIMENTS = ('cpu-overlay', 'geometry-reuse', 'arena-serialization')
SCHEMA = 'rust-duty-cpu-image-preservation/v1'
FORBIDDEN_ENV = {'RUSTFLAGS', 'RUSTDOCFLAGS', 'CARGO_ENCODED_RUSTFLAGS',
                 'CARGO_ENCODED_RUSTDOCFLAGS', 'RUSTC', 'RUSTC_WRAPPER',
                 'RUSTC_WORKSPACE_WRAPPER', 'RUSTC_BOOTSTRAP', 'RUSTDOC',
                 'RUSTUP_TOOLCHAIN', 'VR_WEAPON_ASSET'}
CONFIG_ENV_PREFIXES = ('CARGO_BUILD_', 'CARGO_TARGET_', 'CARGO_PROFILE_',
                       'CARGO_SOURCE_', 'CARGO_PATCH_')


def require(value, message):
    if not value:
        raise ValueError(message)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def read_sources(root, commit, paths):
    names = git(root, 'ls-tree', '-rz', '--name-only', commit, '--', *paths).decode().strip('\0').split('\0')
    require(names and all(names), 'source inventory is empty')
    raw = git(root, 'archive', '--format=tar', commit, '--', *names)
    result = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for entry in archive:
            if entry.isdir():
                continue
            name = Path(entry.name)
            require(entry.isfile() and not name.is_absolute() and '..' not in name.parts,
                    'source archive contains a nonregular or unsafe input')
            require(entry.name not in result, 'source archive contains a duplicate input')
            result[entry.name] = archive.extractfile(entry).read()
    require(set(result) == set(names), 'source archive differs from its Git inventory')
    return result


def hashes(sources):
    return {name: controls.digest(raw) for name, raw in sorted(sources.items())}


def source_pair(production, old_cpu, harness):
    require(matrix.canonical_hash(hashes(production)) == PRODUCTION_MANIFEST,
            'integrated production compile inventory is not the reviewed candidate')
    require(hashes(old_cpu) == CPU_BASELINE, 'baseline CPU files differ from their exact reviewed pin')
    require(set(harness) == set(HARNESS_PATHS), 'both common image fixtures are required')
    require(not set(harness).intersection(production), 'harness cannot replace production code')
    candidate = {**production, **harness}
    baseline = {**candidate, **old_cpu}
    require(set(baseline) == set(candidate) and
            {name for name in candidate if baseline[name] != candidate[name]} == set(CPU_BASELINE),
            'comparison must differ in exactly the four CPU files')
    return {'baseline': baseline, 'candidate': candidate}


def geometry_production_pair(production):
    """Same instrumented renderer, only the reviewed upload policy differs."""
    require(matrix.canonical_hash(hashes(production)) == PRODUCTION_MANIFEST,
            'integrated production compile inventory is not the reviewed candidate')
    policy = production.get(UPLOAD_POLICY_PATH, b'')
    require(policy.count(UPLOAD_POLICY_ENABLED) == 1 and UPLOAD_POLICY_DISABLED not in policy,
            'reviewed enabled upload policy is absent or ambiguous')
    baseline = {**production, UPLOAD_POLICY_PATH:
                policy.replace(UPLOAD_POLICY_ENABLED, UPLOAD_POLICY_DISABLED)}
    require({name for name in baseline if baseline[name] != production[name]} == {UPLOAD_POLICY_PATH},
            'geometry experiment must change only the upload policy')
    return {'baseline': baseline, 'candidate': production.copy()}


def serialization_production_pair(production, old_arena):
    """Restore only the exact historical arena; destination reuse stays on."""
    require(matrix.canonical_hash(hashes(production)) == PRODUCTION_MANIFEST,
            'integrated production compile inventory is not the reviewed candidate')
    require(hashes(old_arena) == {ARENA_PATH: ARENA_BASELINE_SHA256},
            'baseline arena differs from its exact reviewed bytes')
    policy = production.get(UPLOAD_POLICY_PATH, b'')
    require(policy.count(UPLOAD_POLICY_ENABLED) == 1 and UPLOAD_POLICY_DISABLED not in policy,
            'serialization comparison requires enabled upload reuse in both variants')
    baseline = {**production, **old_arena}
    require(set(baseline) == set(production) and
            {name for name in baseline if baseline[name] != production[name]} == {ARENA_PATH},
            'serialization comparison must change exactly the arena source')
    return {'baseline': baseline, 'candidate': production.copy()}


def experiment_metadata(experiment):
    require(experiment in EXPERIMENTS, 'unknown source-pair experiment')
    if experiment == 'cpu-overlay':
        return {'baseline_cpu_origin': BASELINE_CPU_COMMIT,
                'baseline_is_four_file_counterfactual': True,
                'overlay_paths': sorted(CPU_BASELINE),
                'scope': 'asset-free image-preservation experiment; not a whole-game baseline'}
    if experiment == 'arena-serialization':
        return {'experiment': experiment, 'baseline_is_four_file_counterfactual': False,
                'baseline_arena_origin': BASELINE_CPU_COMMIT,
                'baseline_arena_sha256': ARENA_BASELINE_SHA256,
                'overlay_paths': [ARENA_PATH],
                'upload_policies': {'baseline': 'bounded_reuse_v1', 'candidate': 'bounded_reuse_v1'},
                'scope': 'exact arena serialization counterfactual; destination reuse unchanged'}
    return {'experiment': experiment, 'baseline_is_four_file_counterfactual': False,
            'overlay_paths': [UPLOAD_POLICY_PATH],
            'upload_policies': {'baseline': 'immutable_per_frame_v1', 'candidate': 'bounded_reuse_v1'},
            'scope': 'compile-time upload policy counterfactual on otherwise identical instrumented sources'}


def materialize_variants(output, variants, binding, metadata):
    """Write exact closed sources and immutable receipts; never fabricate Git identity."""
    output = Path(output).resolve()
    require(not output.exists() and not output.is_symlink(), 'refusing stale comparison evidence')
    output.mkdir(parents=True, exist_ok=False)
    verifier_path = output / 'verifier-source.json'
    matrix.write_json(verifier_path, binding)
    verifier_sha256 = matrix.sha256(verifier_path)
    receipts = {}
    for label, sources in variants.items():
        destination = output / (label + '-source')
        destination.mkdir()
        for name, raw in sources.items():
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        require(controls.source_manifest(destination) == hashes(sources), 'materialized source differs')
        receipt = {'schema': SCHEMA, 'variant': label,
                   'integrated_source_commit': binding['source_commit'],
                   'production_manifest_sha256': PRODUCTION_MANIFEST,
                   'files_sha256': hashes(sources), **metadata}
        path = output / (label + '-source.json')
        matrix.write_json(path, receipt)
        receipts[label] = {'source': destination, 'files': receipt['files_sha256'],
                           'receipt_path': path, 'receipt_sha256': matrix.sha256(path),
                           'verifier_path': verifier_path, 'verifier_sha256': verifier_sha256}
    return receipts


def prepare(root, output, experiment='cpu-overlay'):
    root, output = Path(root).resolve(), Path(output)
    require(root == Path(__file__).resolve().parents[1], 'runner and checkout must be the same source tree')
    require(not output.exists() and not output.is_symlink(), 'refusing stale comparison evidence')
    binding = session.source_binding(root)
    commit = binding['source_commit']
    production = read_sources(root, commit, PRODUCTION_PATHS)
    harness = read_sources(root, commit, HARNESS_PATHS)
    for name, raw in {**production, **harness}.items():
        require((root / name).read_bytes() == raw, 'checkout bytes differ from committed source: ' + name)
    metadata = experiment_metadata(experiment)
    if experiment in ('geometry-reuse', 'arena-serialization'):
        require(set(harness) == set(HARNESS_PATHS), 'both common image fixtures are required')
        pair = (geometry_production_pair(production) if experiment == 'geometry-reuse' else
                serialization_production_pair(production,
                    read_sources(root, BASELINE_CPU_COMMIT, [ARENA_PATH])))
        variants = {label: {**sources, **harness} for label, sources in pair.items()}
    else:
        variants = source_pair(production,
                               read_sources(root, BASELINE_CPU_COMMIT, sorted(CPU_BASELINE)), harness)
    receipts = materialize_variants(output, variants, binding, metadata)
    require(session.source_binding(root) == binding, 'source changed during preparation')
    return binding, receipts


def logged(command, cwd, directory, env, timeout, executable_sha256=None):
    require(gpu.positive(timeout), 'timeout must be finite and positive')
    directory.mkdir(parents=True, exist_ok=False)
    executable = Path(command[0])
    if executable_sha256 is not None:
        require(matrix.sha256(executable) == executable_sha256, 'freshly built executable changed before execution')
    invocation = {'command': list(map(str, command)), 'cwd': str(cwd), 'timeout_seconds': timeout,
                  'executable_sha256': executable_sha256}
    matrix.write_json(directory / 'invocation.json', invocation)
    child = None
    try:
        with (directory / 'stdout.log').open('wb') as out, (directory / 'stderr.log').open('wb') as err:
            child = subprocess.Popen(command, cwd=cwd, env=env, stdout=out, stderr=err,
                                     stdin=subprocess.DEVNULL,
                                     creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            try:
                code = child.wait(timeout=timeout)
            except BaseException:
                matrix.write_json(directory / 'cleanup.json', process._terminate_process_tree(child))
                raise
        matrix.write_json(directory / 'result.json', {'exit_code': code})
        require(code == 0, 'build/control process failed; inspect retained logs')
        if executable_sha256 is not None:
            require(matrix.sha256(executable) == executable_sha256, 'executable changed during execution')
    except BaseException as error:
        matrix.write_json(directory / 'failure.json', {'error': str(error), 'type': type(error).__name__})
        raise


def verify_sources(receipts):
    for value in receipts.values():
        require(controls.source_manifest(value['source']) == value['files'], 'variant source changed')
        require(matrix.sha256(value['receipt_path']) == value['receipt_sha256'], 'source receipt changed')
        require(matrix.sha256(value['verifier_path']) == value['verifier_sha256'], 'verifier receipt changed')


def directory_manifest(root):
    require(root.is_dir() and not root.is_symlink(), 'control output directory changed')
    paths = sorted(root.rglob('*'))
    require(not any(path.is_symlink() for path in paths), 'control output symlink is unsupported')
    return [path.relative_to(root).as_posix() for path in paths if path.is_dir()]


def verify_retained_outputs(outputs, binaries, directories=None):
    for path, expected in outputs.items():
        require(controls.source_manifest(path) == expected, 'validated control output changed')
    if directories is not None:
        for path, expected in directories.items():
            require(directory_manifest(path) == expected, 'validated control directories changed')
    for variant in binaries.values():
        for binary in variant.values():
            require(matrix.sha256(binary['path']) == binary['sha256'], 'retained executable changed')


def archive_control_outputs(output, outputs, directories):
    """Retain directory entries that file-only CI artifact uploads otherwise drop."""
    verify_retained_outputs(outputs, {}, directories)
    path = output / 'control-outputs.zip'
    files = {f'{root.relative_to(output).as_posix()}/{name}': digest
             for root, manifest in outputs.items() for name, digest in manifest.items()}
    dirs = sorted(name for root, children in directories.items()
                  for name in [root.relative_to(output).as_posix(),
                               *(f'{root.relative_to(output).as_posix()}/{child}' for child in children)])
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in dirs:
            archive.write(output / name, name + '/')
        for name in sorted(files):
            archive.write(output / name, name)
    with zipfile.ZipFile(path) as archive:
        require(archive.testzip() is None, 'retained control archive has a corrupt entry')
        require(set(archive.namelist()) == set(files) | {name + '/' for name in dirs},
                'retained control archive inventory differs')
        require(all(controls.digest(archive.read(name)) == digest for name, digest in files.items()),
                'retained control archive bytes differ')
    verify_retained_outputs(outputs, {}, directories)
    return {'file': path.name, 'sha256': matrix.sha256(path), 'directories': dirs}


def check_environment(env):
    # Cargo config aliases such as CARGO_BUILD_RUSTC can otherwise select a
    # compiler different from the standalone rustc version receipt.
    bad = FORBIDDEN_ENV.intersection(env) | {
        key for key in env if key.startswith(CONFIG_ENV_PREFIXES) and key != 'CARGO_TARGET_DIR'}
    require(not bad, 'unset inherited compiler/asset/config overrides: ' + ', '.join(sorted(bad)))


def cargo_config_paths(source, env):
    source = Path(source).resolve()
    paths = {directory / '.cargo' / name for directory in (source, *source.parents)
             for name in ('config', 'config.toml')}
    home = Path(env.get('CARGO_HOME', Path.home() / '.cargo'))
    if not home.is_absolute():
        home = source / home
    paths.update(home / name for name in ('config', 'config.toml'))
    return paths


def check_cargo_configuration(source, env):
    # The reviewed production tree has no Cargo config. Never read or
    # copy private config contents; refuse an unbound compiler/dependency input.
    require(not any(path.exists() or path.is_symlink() for path in cargo_config_paths(source, env)),
            'unbound Cargo configuration exists in a source ancestor or Cargo home')


def toolchain_at(directory):
    return {name: subprocess.check_output([name, flag], cwd=directory, text=True, timeout=30)
            for name, flag in (('rustc', '-Vv'), ('cargo', '-V'))}


def run(root, output, build_timeout=1200, process_timeout=180, experiment='cpu-overlay'):
    require(sys.platform == 'win32', 'image preservation requires Windows DX12/WARP')
    require(gpu.positive(build_timeout) and gpu.positive(process_timeout), 'timeouts must be finite and positive')
    check_environment(os.environ)
    compiler = toolchain_at(Path(root).resolve())
    rustc = compiler['rustc']
    require('release: 1.99.0\n' in rustc and 'host: x86_64-pc-windows-msvc\n' in rustc,
            'use reviewed Rust 1.99.0 Windows MSVC toolchain')
    binding, receipts = prepare(root, output, experiment)
    root, output = Path(root).resolve(), Path(output).resolve()
    try:
        matrix.write_json(output / 'toolchain.json', compiler)
        binaries, devices, fixed, outputs, directories = {}, [], {}, {}, {}
        for label, receipt in receipts.items():
            target = output / (label + '-target')
            env = dict(os.environ, CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL='0',
                       CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_DEV_OPT_LEVEL='2',
                       CARGO_BUILD_JOBS='2', PASS_SUBMISSION_SOURCE_SHA256=receipt['receipt_sha256'])
            matrix.write_json(output / (label + '-build-settings.json'),
                              {key: env[key] for key in ('CARGO_TARGET_DIR', 'CARGO_INCREMENTAL',
                               'CARGO_PROFILE_DEV_DEBUG', 'CARGO_PROFILE_DEV_OPT_LEVEL',
                               'CARGO_BUILD_JOBS', 'PASS_SUBMISSION_SOURCE_SHA256')})
            check_cargo_configuration(receipt['source'], env)
            require(toolchain_at(receipt['source']) == compiler,
                    'toolchain differs in materialized source directory')
            command = ['cargo', 'build', '--locked', '--no-default-features', '--features', 'wgpu-runtime']
            for example in EXAMPLES:
                command += ['--example', example]
            logged(command, receipt['source'], output / (label + '-build'), env, build_timeout)
            check_cargo_configuration(receipt['source'], env)
            verify_sources(receipts)
            binaries[label] = {name: {'path': str(target / 'debug/examples' / (name + '.exe')),
                                     'sha256': matrix.sha256(target / 'debug/examples' / (name + '.exe'))}
                               for name in EXAMPLES}
            matrix.write_json(output / (label + '-executables.json'), binaries[label])
            for name in EXAMPLES:
                directory = output / (label + '-' + name)
                binary = binaries[label][name]
                command = [binary['path']]
                if name == 'renderer_contract':
                    command += ['--renderer=dx12', '--force-fallback-adapter']
                command += ['--output-dir', str(directory)]
                log = output / (label + '-' + name + '-process')
                logged(command, receipt['source'], log, env, process_timeout, binary['sha256'])
                process.validate_renderer_log(log)
                devices.append(controls.device_evidence(log / 'stderr.log'))
                if name == 'renderer_contract':
                    fixed[label] = renderer.validate_outputs(directory)
                    require(fixed[label].get('passed') is True and fixed[label].get('captures') == 21,
                            'all fixed renderer captures must pass')
                else:
                    require({p.name for p in directory.iterdir()} == {'before.png', 'after.png', 'report.json'},
                            'mixed fixture outputs are not closed')
                    controls.validate_report(matrix.json_read(directory / 'report.json'), receipt['receipt_sha256'])
                outputs[directory] = controls.source_manifest(directory)
                directories[directory] = directory_manifest(directory)
                verify_sources(receipts)
        same_device = controls.require_same_devices(devices)
        verify_retained_outputs(outputs, binaries, directories)
        for receipt in receipts.values():
            check_cargo_configuration(receipt['source'], os.environ)
            require(toolchain_at(receipt['source']) == compiler, 'variant toolchain changed during execution')
        exact_contract = controls.contract_pixels(output / 'baseline-renderer_contract',
                                                  output / 'candidate-renderer_contract')
        mixed = controls.exact_pixels([output / (label + '-pass_submission_benchmark') / name
                                       for label in ('baseline', 'candidate') for name in ('before.png', 'after.png')])
        verify_retained_outputs(outputs, binaries, directories)
        require(session.source_binding(root) == binding, 'verifier/source changed during execution')
        verify_sources(receipts)
        require(toolchain_at(root) == compiler, 'toolchain changed during execution')
        control_archive = archive_control_outputs(output, outputs, directories)
        result = {'schema': SCHEMA, 'passed': True, 'source_commit': binding['source_commit'],
                  'production_manifest_sha256': PRODUCTION_MANIFEST, 'device': same_device,
                  'fixed_validations': fixed, 'exact_fixed_pixels': exact_contract, 'exact_mixed_pixels': mixed,
                  'control_output_files_sha256': {str(path.relative_to(output)): value for path, value in outputs.items()},
                  'control_outputs_archive': control_archive,
                  'executables': binaries, 'gpu_lifecycle_verified': False, 'authored_acceptance': False,
                  'performance_improvement': None, 'experiment': experiment,
                  'scope': experiment_metadata(experiment)['scope'] + '; no FPS, RTX or authored source-visibility verdict'}
        matrix.write_json(output / 'summary.json', result)
        return result
    except BaseException as error:
        matrix.write_json(output / 'failure.json', {'passed': False, 'error': str(error), 'type': type(error).__name__})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'run'))
    parser.add_argument('--experiment', choices=EXPERIMENTS, default='cpu-overlay')
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--build-timeout', type=float, default=1200)
    parser.add_argument('--process-timeout', type=float, default=180)
    args = parser.parse_args(argv)
    try:
        if args.mode == 'prepare':
            binding, _ = prepare(args.root, args.output, args.experiment)
            print(json.dumps({'prepared': True, 'source_commit': binding['source_commit'], 'executed': False}))
        else:
            print(json.dumps(run(args.root, args.output, args.build_timeout, args.process_timeout, args.experiment), allow_nan=False))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print('cpu-image-preservation: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

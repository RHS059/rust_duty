#!/usr/bin/env python3
"""Produce a Windows source oracle for immutable ADS captures; never render.

Run from the verifier checkout, with a separate clean checkout at capture-source.
Only the reviewed read-only pose bridge and diagnostic example are overlaid.
Every consumed native input must match the historical input manifest first.
The receipt SHA is emitted outside the portable packet as a CI step output and
an independent anchor file. A failed producer cannot provide a passing oracle.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

import ads_source_visibility_binding as binding
import aggregate_dx12_authored as aggregate
import dx12_authored_shards as shared
import revalidate_ads_offset as revalidate
from verify_capture_telemetry import read_record

TARGET = 'x86_64-pc-windows-msvc'
EXAMPLE = 'source_visibility_certificate'
DENIED_ARTIFACT_IDS = {11364272946, 11385711086, 11386835833, 11386227794}
CAPTURE_CONTEXT = {'source_commit': '8f571464be706d0abde862e124582a188f633baf',
                   'run_id': '37415102452', 'run_attempt': '1'}
FEATURES = ['legacy-macroquad', 'wgpu-runtime']
ENVIRONMENT_KEYS = ('RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'RUSTC_WRAPPER')
BLOCKED_ENVIRONMENT = ENVIRONMENT_KEYS + (
    'RUSTC_WORKSPACE_WRAPPER', 'RUSTC', 'CARGO_BUILD_RUSTC',
    'CARGO_BUILD_RUSTC_WRAPPER', 'CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER',
    'CARGO_BUILD_RUSTFLAGS', 'CARGO_BUILD_TARGET', 'CARGO_TARGET_DIR',
    'VR_WEAPON_ASSET',)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return {'bytes': shared._checked_stat(path, 'file').st_size,
            'sha256': shared._read_regular(path)}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(aggregate.plain(value), stream, indent=2, allow_nan=False)
        stream.write('\n')


def validate_capture(capture):
    shared._validate_context(capture)
    require(capture == CAPTURE_CONTEXT, 'only the pinned 8f capture run37415102452 attempt1 is supported')


def validate_parameters(capture, toolchain, rustc_hash):
    validate_capture(capture)
    require(type(toolchain) is str and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+-x86_64-pc-windows-msvc', toolchain),
            'toolchain must be an exact stable version with x86_64-pc-windows-msvc suffix')
    require(type(rustc_hash) is str and re.fullmatch('[0-9a-f]{64}', rustc_hash),
            'capture rustc -Vv SHA-256 must be independently verified and explicitly supplied')


def artifact_names(attempt):
    return {'inputs': f'dx12-authored-inputs-attempt-{attempt}',
            'gameplay': f'dx12-authored-shard-ads-gameplay-evidence-attempt-{attempt}',
            'offset': f'dx12-authored-shard-ads-offset-evidence-attempt-{attempt}',
            **{name: f'generated-{name}-runtime-attempt-{attempt}'
               for name in ('reload', 'walk', 'ads', 'directional', 'jump')}}


def select_artifacts(catalog, capture, repository):
    """Select eight IDs without requesting an archive or retrying denied access.

    The workflow fetches at most 20 pages of 100 records. Attempt-qualified
    assets must have been created inside this exact completed attempt. Content
    hashes are still checked against the native manifest after materialization.
    """
    validate_capture(capture)
    require(repository == 'RHS059/rust_duty', 'unexpected artifact repository')
    run = catalog['attempt']
    require(str(run['id']) == capture['run_id'] and str(run['run_attempt']) == capture['run_attempt']
            and run['head_sha'] == capture['source_commit'], 'capture run/attempt/source identity differs')
    require(run['repository']['full_name'] == repository and run['head_repository']['full_name'] == repository,
            'capture run repository differs')
    require(run['head_branch'] == 'main' and run['path'] == '.github/workflows/build.yml',
            'capture must come from the main build workflow')
    require(run['status'] == 'completed', 'capture attempt is not complete')
    start, end = (datetime.fromisoformat(run[key].replace('Z', '+00:00'))
                  for key in ('run_started_at', 'updated_at'))
    require(start <= end, 'invalid attempt time interval')
    records = catalog['artifacts']
    require(type(records) is list and len(records) <= 2000 and catalog['complete'] is True,
            'artifact listing was incomplete or exceeded the bounded limit')
    result = {}
    for key, name in artifact_names(capture['run_attempt']).items():
        matches = [item for item in records if item['name'] == name]
        require(len(matches) == 1, f'expected exactly one artifact named {name}')
        item = matches[0]
        require(type(item['id']) is int and item['id'] > 0 and item['id'] not in DENIED_ARTIFACT_IDS,
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
        result[key] = item
    require(len({item['id'] for item in result.values()}) == len(result), 'aliased artifact IDs')
    return result


def select_compiler_job(catalog, capture):
    """Only the successful original authored-input compiler job may anchor CPU math."""
    validate_capture(capture)
    jobs = catalog['jobs']
    shared._validate_context(catalog['jobs_context'])
    require(catalog['jobs_context'] == capture, 'original jobs were queried from a different attempt')
    require(type(jobs) is list and len(jobs) <= 2000 and catalog['jobs_complete'] is True,
            'original job listing is incomplete')
    matches = [job for job in jobs if job['name'] == 'authored-inputs'
               or job['name'].endswith(' / authored-inputs')]
    require(len(matches) == 1, 'expected one original authored-inputs compiler job')
    job = matches[0]
    require(type(job['id']) is int and job['id'] > 0 and str(job['run_id']) == capture['run_id']
            and ('run_attempt' not in job or str(job['run_attempt']) == capture['run_attempt'])
            and job['head_sha'] == capture['source_commit'],
            'original compiler job source/run/attempt differs')
    require(job['id'] == 112121396166, 'pinned original compiler job ID differs')
    require(job['status'] == 'completed' and job['conclusion'] == 'success', 'original compiler job was unsuccessful')
    require('windows-latest' in job['labels'], 'original compiler job was not the Windows producer')
    return job


def recover_compiler(log, capture, *, claimed_toolchain='', claimed_sha256=''):
    """Read independently recorded historical fingerprints, never new rustc output."""
    validate_capture(capture)
    require(type(log) is bytes and 0 < len(log) <= 32 * 1024**2, 'missing or oversized original compiler log')
    text = log.decode('utf-8')
    pattern = (r'authored-dual-release-v1-Windows-X64-([0-9a-f]{64})-([0-9a-f]{64})-'
               + re.escape(capture['source_commit']) + r'(?![0-9a-f])')
    matches = set(re.findall(pattern, text))
    require(len(matches) == 1, 'original job log has no unique source-bound rustc fingerprint cache key')
    rustc_sha, cache_lock_sha = next(iter(matches))
    lines = [re.sub(r'^\d{4}-\d{2}-\d{2}T\S+\s+', '', line) for line in text.splitlines()]
    candidates = set()
    for index, line in enumerate(lines):
        if re.match(r'^rustc [0-9]+\.[0-9]+\.[0-9]+ \(', line):
            block = tuple(lines[index:index + 7])
            if len(block) == 7 and hashlib.sha256(('\n'.join(block) + '\n').encode()).hexdigest() == rustc_sha:
                candidates.add(block)
    require(len(candidates) == 1, 'historical verbose compiler bytes do not reproduce the recorded fingerprint')
    verbose = next(iter(candidates))
    version = re.match(r'^rustc ([0-9]+\.[0-9]+\.[0-9]+) \(', verbose[0]).group(1)
    require(verbose[4] == f'host: {TARGET}' and verbose[5] == f'release: {version}',
            'verified compiler header, release line or Windows host disagree')
    toolchain = version + '-' + TARGET
    validate_parameters(capture, toolchain, rustc_sha)
    require(not claimed_toolchain or claimed_toolchain == toolchain, 'explicit toolchain differs from captured job log')
    require(not claimed_sha256 or claimed_sha256 == rustc_sha, 'explicit compiler anchor differs from captured job log')
    return {'toolchain': toolchain, 'rustc_sha256': rustc_sha, 'cache_lock_sha256': cache_lock_sha,
            'rustc_verbose_lines': list(verbose), 'original_job_log_sha256': hashlib.sha256(log).hexdigest(),
            'capture_context': capture}


def recover_native_text_bytes(source, manifest, offset):
    """Select bytes by the native SHA, preserving newline identity exactly.

    Capture's text APIs may have normalized the base before writing its offset
    file on Windows. Try only that known LF/CRLF spelling transformation and
    demand the exact historical digest before materializing a candidate.
    """
    native_hashes = manifest['binding']['runtime_and_manifest_sha256']
    offset_raw = offset.read_bytes()
    suffix_lf = binding.OFFSET_SUFFIX.encode('utf-8')
    candidates = set()
    for suffix in (suffix_lf, suffix_lf.replace(b'\n', b'\r\n')):
        if offset_raw.endswith(suffix):
            prefix = offset_raw[:-len(suffix)]
            lf = prefix.replace(b'\r\n', b'\n')
            candidates.update((prefix, lf, lf.replace(b'\n', b'\r\n')))
    selected = [raw for raw in candidates if hashlib.sha256(raw).hexdigest() == native_hashes['settings.cfg']]
    require(len(selected) == 1, 'cannot recover exact native base settings from sealed offset settings')
    (source / 'settings.cfg').write_bytes(selected[0])
    path = source / 'assets/animations.cfg'
    raw = path.read_bytes()
    lf = raw.replace(b'\r\n', b'\n')
    selected = [candidate for candidate in set((raw, lf, lf.replace(b'\n', b'\r\n')))
                if hashlib.sha256(candidate).hexdigest() == native_hashes['assets/animations.cfg']]
    require(len(selected) == 1, 'materialized animation manifest does not match exact native bytes')
    path.write_bytes(selected[0])


def execution_environment(source, toolchain, environment=None):
    env = dict(os.environ if environment is None else environment)
    forbidden = [key for key in env if key in BLOCKED_ENVIRONMENT or key.startswith('CARGO_PROFILE_')
                 or (key.startswith('CARGO_TARGET_') and key.endswith(('_RUSTFLAGS', '_RUSTC', '_LINKER', '_RUNNER')))]
    require(not forbidden, f'unsupported compiler/profile environment overrides: {sorted(forbidden)}')
    # Cargo walks ancestors and the selected CARGO_HOME. Configuration there
    # could silently replace the compiler or CPU flags despite a clean checkout.
    folders = [source, *source.parents]
    cargo_home = Path(env.get('CARGO_HOME', str(Path.home() / '.cargo')))
    configs = [folder / '.cargo' / name for folder in folders for name in ('config', 'config.toml')]
    configs += [cargo_home / name for name in ('config', 'config.toml')]
    require(not any(path.exists() or path.is_symlink() for path in configs), 'unreviewed Cargo configuration exists')
    env['RUSTUP_TOOLCHAIN'] = toolchain
    return env


def checked_compiler(raw, expected_sha256):
    require(hashlib.sha256(raw).hexdigest() == expected_sha256, 'installed rustc -Vv differs from captured compiler')
    require(f'host: {TARGET}' in raw.decode('utf-8').splitlines(), 'compiler is not the captured Windows x86_64 host')


def reviewed_bridge(original, overlay):
    """Removing only the three reviewed additive regions must recover source.

    The third region contains cfg(test) fixtures, never release production code.
    This rejects replacing unrelated original code with the verifier revision.
    """
    text = overlay.decode('utf-8')
    regions = [
        ('/// Read-only evaluated source pose for independent CPU diagnostics.', 'impl AuthoredViewmodel {'),
        ('    /// Snapshot the same effective pose selected by `draw_checked`, before',
         '    /// Loads CPU mesh and texture descriptors without requiring a render context.'),
    ]
    for start, end in regions:
        require(text.count(start) == 1 and text.count(end) == 1, 'reviewed pose bridge anchors are missing or duplicated')
        first, last = text.index(start), text.index(end)
        require(first < last, 'invalid pose bridge ordering')
        text = text[:first] + text[last:]
    fixture = '\n\n    fn layered_contact_fixture() -> AuthoredViewmodel {'
    require(text.count(fixture) == 1 and text.rstrip().endswith('}'), 'reviewed pose bridge test fixture is missing')
    start = text.index(fixture)
    require('#[cfg(test)]' in text[:start] and '\nmod tests {' in text[:start], 'bridge fixture must be inside test module')
    text = text[:start] + text[text.rfind('\n}'):]
    require(text.encode('utf-8') == original, 'overlay changes original production code beyond the reviewed read-only bridge')
    return overlay


def validate_consumed_inputs(source, manifest, offset):
    hashes = manifest['binding']['runtime_and_manifest_sha256']
    for name in sorted(binding.INPUTS - {'ads-offset.cfg'}):
        require(name in hashes and digest(source / name)['sha256'] == hashes[name], f'consumed native input differs: {name}')
    base = (source / 'settings.cfg').read_text(encoding='utf-8')
    require(offset.read_text(encoding='utf-8') == base + binding.OFFSET_SUFFIX,
            'native offset settings are not the exact base-plus-offset transform')


def process(command, cwd, env, logs, timeout):
    logs.mkdir(parents=True, exist_ok=False)
    receipt = {'command': [str(part) for part in command], 'cwd': cwd.as_posix(),
               'exit_code': None, 'environment': {key: env.get(key) for key in ENVIRONMENT_KEYS}}
    try:
        with (logs / 'stdout.log').open('xb') as out, (logs / 'stderr.log').open('xb') as err:
            completed = subprocess.run(command, cwd=cwd, env=env, stdout=out, stderr=err, timeout=timeout, check=False)
        receipt['exit_code'] = completed.returncode
    finally:
        # Retain attempted argv and compiler environment even for setup errors
        # and bounded process timeouts; null exit_code never passes the binder.
        write_json(logs / 'invocation.json', receipt)
    require(completed.returncode == 0, f'process failed ({completed.returncode}); see {logs}')
    return receipt


def production_files(source):
    names = subprocess.check_output(['git', '-C', str(source), 'ls-files', '-z']).decode('utf-8').split('\0')
    return {name: source / name for name in names if name and
            (name.startswith(('src/', 'updater/src/')) or name in
             ('Cargo.toml', 'Cargo.lock', 'build.rs', 'build_number.rs', 'updater/Cargo.toml',
              'updater/Cargo.lock', 'updater/build.rs', 'assets/weapons/hk416a5.vrm'))}


def inventory(paths):
    return {key: digest(path) for key, path in sorted(paths.items())}


def copy_packet_file(source, destination, expected):
    require(digest(source) == expected, f'{source}: changed before portable copy')
    destination.parent.mkdir(parents=True, exist_ok=True)
    require(not destination.exists(), 'portable packet destination already exists')
    shutil.copyfile(source, destination)
    require(digest(source) == digest(destination) == expected, f'{source}: changed during portable copy')


def build(args):
    capture = {'source_commit': args.capture_source, 'run_id': args.capture_run_id, 'run_attempt': args.capture_run_attempt}
    validate_parameters(capture, args.toolchain, args.capture_rustc_sha256)
    source, verifier, downloads = (getattr(args, name).resolve(strict=True) for name in ('capture_root', 'verifier_root', 'downloads'))
    evidence, anchor = args.evidence.absolute(), args.receipt_anchor.absolute()
    for root in (source, verifier, downloads):
        require(not evidence.is_relative_to(root) and not root.is_relative_to(evidence), 'evidence must be disjoint from source/download roots')
    require(not source.is_relative_to(verifier) and not verifier.is_relative_to(source), 'capture and verifier checkouts must be separate')
    require(not evidence.exists() and not anchor.exists(), 'refusing to replace source evidence or its retained SHA anchor')
    evidence.mkdir(parents=True)
    report = {'schema': 'rust-duty-ads-source-producer/v1', 'passed': False, 'acceptance_complete': False,
              'capture_context': capture, 'verifier_context': shared.context(), 'phase': 'setup'}
    try:
        require(sys.platform == 'win32' and platform.machine() in ('AMD64', 'x86_64'), 'authoritative source generation requires native Windows x86_64')
        for root, expected in ((source, capture['source_commit']), (verifier, report['verifier_context']['source_commit'])):
            actual = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
            require(actual == expected, f'{root}: checkout commit differs')
            require(not subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=no']),
                    f'{root}: tracked source is modified before oracle staging')
        env = execution_environment(source, args.toolchain)
        compiler_before = subprocess.check_output(['rustc', '-Vv'], cwd=source, env=env)
        checked_compiler(compiler_before, args.capture_rustc_sha256)
        catalog = read_record(downloads / 'artifact-catalog.json')
        selected = select_artifacts(catalog, capture, args.repository)
        compiler_job = select_compiler_job(catalog, capture)
        compiler_log = downloads / 'compiler-recovery/original-authored-inputs.log'
        recovered = recover_compiler(compiler_log.read_bytes(), capture, claimed_toolchain=args.toolchain,
                                     claimed_sha256=args.capture_rustc_sha256)
        require(read_record(downloads / 'compiler-recovery/compiler-recovery.json') ==
                {**recovered, 'original_job': compiler_job}, 'independent compiler recovery metadata changed')
        write_json(evidence / 'download-identities.json', selected)
        manifest_path = downloads / 'inputs/evidence/authored-inputs/input-manifest.json'
        manifest = revalidate.manifest_binding(manifest_path, capture)
        native = manifest['binding']
        for name, field in (('Cargo.toml', 'cargo_manifest_sha256'), ('Cargo.lock', 'cargo_lock_sha256')):
            require(digest(source / name)['sha256'] == native[field], f'original {name} differs from capture binding')
        original = evidence / 'original-verdicts'
        original.mkdir()
        shutil.copyfile(manifest_path, original / 'input-manifest.json')
        shards, invocations = {}, {}
        for scenario, directory in (('ads-gameplay', 'gameplay'), ('ads-offset', 'offset')):
            folder = downloads / directory
            shards[scenario] = aggregate.read_shard(folder, scenario, native, expected_context=capture)
            saved = shards[scenario]
            aggregate.require_checks(saved, ['validated-inputs', 'inputs-unchanged', 'windows-legacy/stock-probe', 'windows-legacy/capture', 'dx12/capture'])
            require(saved['budget_exhausted'] is False and saved['current_check'] is None and saved['status'] in ('failed', 'passed'),
                    'native capture did not finish cleanly')
            shutil.copyfile(folder / 'summary.json', original / f'{scenario}-summary.json')
            if scenario == 'ads-offset':
                invocations = {role: revalidate.exact_invocation(folder, saved, role, scenario) for role in binding.ROLES}
        immutable = {str(path): digest(path) for path in (manifest_path, downloads / 'gameplay/summary.json',
                                                         downloads / 'offset/summary.json', downloads / 'offset/ads-offset.cfg')}
        # Source-bound materialization is only a candidate input source. The
        # captured manifest, never the freshly generated pack, is authoritative.
        report['phase'] = 'materialize-and-compare-native-inputs'
        for family in ('reload', 'walk', 'ads', 'directional', 'jump'):
            for name, path in shared._walk_files(downloads / family):
                target = source / 'assets' / family / name
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    require(digest(target) == digest(path), f'generated runtime would overwrite differing committed bytes: {target}')
                else:
                    shutil.copyfile(path, target)
        process([sys.executable, str(source / 'tools/package_game.py'), 'materialize', '--root', str(source),
                 '--include-walk', '--include-ads', '--include-directional', '--include-jump', '--require-generated'],
                source, env, evidence / 'logs/materialize', 600)
        recover_native_text_bytes(source, manifest, downloads / 'offset/ads-offset.cfg')
        validate_consumed_inputs(source, manifest, downloads / 'offset/ads-offset.cfg')
        tracked_before = inventory(production_files(source))
        overlay_path = verifier / 'src/authored_viewmodel.rs'
        original_bridge = (source / 'src/authored_viewmodel.rs').read_bytes()
        overlay = reviewed_bridge(original_bridge, overlay_path.read_bytes())
        (source / 'src/authored_viewmodel.rs').write_bytes(overlay)
        example_path = source / f'examples/{EXAMPLE}.rs'
        example_path.parent.mkdir(exist_ok=True)
        shutil.copyfile(verifier / f'examples/{EXAMPLE}.rs', example_path)
        oracle = source / 'oracle-output'
        require(not oracle.exists(), 'source checkout already contains oracle output')
        oracle.mkdir()
        shutil.copyfile(downloads / 'offset/ads-offset.cfg', source / 'ads-offset.cfg')
        (oracle / 'original-authored_viewmodel.rs').write_bytes(original_bridge)
        (oracle / 'rustc-Vv.txt').write_bytes(compiler_before)
        shutil.copyfile(manifest_path, oracle / 'native-input-manifest.json')
        shutil.copyfile(compiler_log, oracle / 'original-authored-inputs.log')
        shutil.copyfile(downloads / 'compiler-recovery/compiler-recovery.json', oracle / 'compiler-recovery.json')
        producer = source / 'tools/build_ads_source_packet.py'
        require(not producer.exists(), 'capture source already contains an oracle producer; review its baseline explicitly')
        shutil.copyfile(Path(__file__), producer)
        # Resolve the cargo binary in the selected, hash-checked toolchain.
        cargo = subprocess.check_output(['rustup', 'which', '--toolchain', args.toolchain, 'cargo'], env=env, text=True).strip()
        command = [Path(cargo).as_posix(), 'build', '--locked', '--release', '--no-default-features',
                   '--target', TARGET, '--example', EXAMPLE, '--features', ','.join(FEATURES)]
        report['phase'] = 'build-original-source-with-read-only-bridge'
        build_receipt = process(command, source, env, evidence / 'logs/build', 2700)
        write_json(oracle / 'build-receipt.json', build_receipt)
        executable = source / f'target/{TARGET}/release/examples/{EXAMPLE}.exe'
        implementation = production_files(source)
        for name in (f'examples/{EXAMPLE}.rs', 'tools/build_ads_source_packet.py',
                     'oracle-output/original-authored_viewmodel.rs', 'oracle-output/rustc-Vv.txt',
                     'oracle-output/original-authored-inputs.log', 'oracle-output/compiler-recovery.json',
                     'oracle-output/native-input-manifest.json',
                     'oracle-output/build-receipt.json', f'target/{TARGET}/release/examples/{EXAMPLE}.exe'):
            implementation[name] = source / name
        implementation.update({name: source / name for name in binding.INPUTS})
        unchanged = inventory(production_files(source))
        require({k: v for k, v in unchanged.items() if k != 'src/authored_viewmodel.rs'} ==
                {k: v for k, v in tracked_before.items() if k != 'src/authored_viewmodel.rs'},
                'build changed original production source outside reviewed bridge')
        before = inventory(implementation)
        write_json(evidence / 'inputs-and-implementation-before.json', before)
        reports, executions, outputs = {}, {}, {}
        for backend, role in (('opengl', 'windows-legacy'), ('dx12', 'dx12')):
            report['phase'] = f'generate-{backend}-553-frames'
            relative = f'oracle-output/frames-{backend}.jsonl'
            output = source / relative
            command = [executable.as_posix(), (source / 'assets/animations.cfg').as_posix(),
                       (source / 'ads-offset.cfg').as_posix(), backend, output.as_posix()]
            executions[backend] = process(command, source, env, evidence / f'logs/{backend}', 1800)
            records = [json.loads(line) for line in output.read_bytes().splitlines()]
            require(len(records) == 554 and [row['frame'] for row in records[1:]] == list(range(553)),
                    f'{backend}: source output must enumerate every one of 553 frames')
            reports[backend] = {'command': command, 'exit_code': 0, 'output': digest(output), 'header': records[0]}
            outputs[role] = relative
        after = inventory(implementation)
        write_json(evidence / 'inputs-and-implementation-after.json', after)
        require(before == after, 'source implementation, executable or consumed inputs changed during oracle execution')
        require(subprocess.check_output(['rustc', '-Vv'], cwd=source, env=env) == compiler_before, 'compiler identity changed during execution')
        require(sys.platform == 'win32' and platform.machine() in ('AMD64', 'x86_64'), 'native execution platform identity changed')
        for root, expected in ((source, capture['source_commit']), (verifier, report['verifier_context']['source_commit'])):
            require(subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip() == expected,
                    'capture/verifier source revision changed during oracle execution')
        validate_consumed_inputs(source, manifest, downloads / 'offset/ads-offset.cfg')
        require(immutable == {path: digest(Path(path)) for path in immutable}, 'immutable capture manifest or verdicts changed')
        for scenario, directory in (('ads-gameplay', 'gameplay'), ('ads-offset', 'offset')):
            shared.verify_files(downloads / directory, shards[scenario]['files'])
        report['phase'] = 'package-source-receipt'
        packet_root = evidence / 'packet'
        packet_root.mkdir()
        files = {key: 'inventory/' + key for key in implementation}
        for key, path in implementation.items():
            copy_packet_file(path, packet_root / files[key], before[key])
        for role, relative in outputs.items():
            copy_packet_file(source / relative, packet_root / relative, reports['opengl' if role == 'windows-legacy' else 'dx12']['output'])
        receipt = {'schema': 'rust-duty-source-visibility-certificates-binding/v1',
                   'source_base_commit': capture['source_commit'],
                   'source_execution_context': report['verifier_context'],
                   'capture_context': capture, 'capture_rustc_sha256': args.capture_rustc_sha256,
                   'toolchain': args.toolchain, 'inputs_and_implementation_before': before,
                   'inputs_and_implementation_after': after, 'backend_reports': reports,
                   'reviewed_manifest_dependency_mapping': binding.MANIFEST_ASSETS,
                   'oracle_execution': {'schema': 'rust-duty-native-source-oracle/v1', 'platform': sys.platform,
                                        'machine': platform.machine(), 'host': TARGET, 'target': TARGET, 'profile': 'release',
                                        'features': FEATURES, 'rustc_vv': 'oracle-output/rustc-Vv.txt',
                                        'build_receipt': 'oracle-output/build-receipt.json',
                                        'executable': f'target/{TARGET}/release/examples/{EXAMPLE}.exe',
                                        'execution_receipts': executions},
                   'acceptance_verdict': None}
        receipt_path = packet_root / 'source-receipt.json'
        write_json(receipt_path, receipt)
        write_json(packet_root / 'source-packet.json', {'schema': binding.SCHEMA, 'capture_binding': native,
                   'original_invocations': invocations, 'receipt': 'source-receipt.json', 'recorded_root': source.as_posix(),
                   'files': files, 'source_outputs': outputs, 'input_files': {name: name for name in binding.INPUTS}})
        receipt_sha = digest(receipt_path)['sha256']
        # This anchor is deliberately outside the packet and is retained in the
        # native job log and step output before invoking any revalidator.
        anchor.parent.mkdir(parents=True, exist_ok=True)
        with anchor.open('x', encoding='ascii', newline='\n') as stream:
            stream.write(receipt_sha + '\n')
        report.update(passed=True, phase='complete', source_receipt_sha256=receipt_sha)
        print(f'INDEPENDENT_SOURCE_RECEIPT_SHA256={receipt_sha}', flush=True)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
                stream.write(f'source_receipt_sha256={receipt_sha}\n')
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
                stream.write(f'Windows source receipt SHA256: {receipt_sha}\n\nCapture: {capture}\n\nSource oracle/verifier: {report["verifier_context"]}\n')
        return report
    except Exception as error:
        report['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        write_json(evidence / 'producer-summary.json', report)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('select-artifacts', 'recover-compiler', 'build'):
        command = sub.add_parser(name)
        for key in ('capture-source', 'capture-run-id', 'capture-run-attempt'):
            command.add_argument('--' + key, required=True)
        for key in ('toolchain', 'capture-rustc-sha256'):
            command.add_argument('--' + key, required=name == 'build', default='')
        command.add_argument('--repository', default='RHS059/rust_duty')
    select = sub.choices['select-artifacts']
    select.add_argument('--catalog', type=Path, required=True)
    recover = sub.choices['recover-compiler']
    recover.add_argument('--catalog', type=Path, required=True)
    recover.add_argument('--output', type=Path, required=True)
    create = sub.choices['build']
    for key in ('capture-root', 'verifier-root', 'downloads', 'evidence', 'receipt-anchor'):
        create.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command in ('select-artifacts', 'recover-compiler'):
        capture = {'source_commit': args.capture_source, 'run_id': args.capture_run_id, 'run_attempt': args.capture_run_attempt}
        validate_capture(capture)
        catalog = read_record(args.catalog)
        selected = select_artifacts(catalog, capture, args.repository)
        job = select_compiler_job(catalog, capture)
        if args.command == 'recover-compiler':
            require(not args.output.exists(), 'refusing existing compiler evidence directory')
            args.output.mkdir(parents=True)
            command = ['gh', 'api', '--allow-escape-sequences',
                       f'/repos/{args.repository}/actions/jobs/{job["id"]}/logs']
            # gh follows the official endpoint's download redirect. A denied
            # read fails once; no alternate route or archive retry is attempted.
            with (args.output / 'original-authored-inputs.log').open('xb') as out, (args.output / 'download-errors.log').open('xb') as err:
                completed = subprocess.run(command, stdout=out, stderr=err, timeout=120, check=False)
            require(completed.returncode == 0, 'original compiler job log download failed; see retained error log')
            recovered = recover_compiler((args.output / 'original-authored-inputs.log').read_bytes(), capture,
                                         claimed_toolchain=args.toolchain, claimed_sha256=args.capture_rustc_sha256)
            recovered['original_job'] = job
            write_json(args.output / 'compiler-recovery.json', recovered)
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
                stream.write(f'toolchain={recovered["toolchain"]}\nrustc_sha256={recovered["rustc_sha256"]}\n')
            return 0
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            for key, item in selected.items():
                stream.write(f'{key}={item["id"]}\n')
        return 0
    build(args)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

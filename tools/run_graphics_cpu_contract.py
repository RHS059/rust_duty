#!/usr/bin/env python3
"""Bounded current-source Windows controls; reuse the reviewed batching binary.

No full game build, old-source relabeling, native success on Linux, or finite
profile activation. The caller downloads only the explicitly pinned baseline
artifact through its normal authorized GitHub route and supplies its metadata.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile

import finite_ads_profile_binding as finite_source
import run_pass_submission_benchmark as shared
import summarize_frame_performance as cpu_reader

BASELINE_SOURCE = 'b085f31d71e8eeb4dd9f36786a9c7e82da90b809'
BASELINE_COMPILED_SOURCE = '5abf2bca825a252fb7ad6665c444c89861ee8ef9'
CANDIDATE_SOURCE = 'ebf4bcb7f489766e3c7ec188c35db9bb4146c62b'
BASELINE_RUN = 37482428571
BASELINE_ARTIFACT = 11422371812
BASELINE_ARCHIVE_SHA256 = 'f29ff7c9fada89478e86f3bae86e0382350d1ac249771116dc920274de5b8994'
BASELINE_REVIEW_SHA256 = '4c2ae5f087ac1e548a9285f635fbb17de9de3defbaa4fab0da014fdb5c976699'
COMPILER_SHA256 = '5477f9bad65b15c4c5b31fc050fc72feba651ea1b330bc75cf356a4d6b0fbc80'
EXAMPLE = 'graphics_cpu_contract'
HARNESS = 'examples/' + EXAMPLE + '.rs'
CHANGED = frozenset(('src/app.rs', 'src/frame_performance.rs', 'src/frame_performance_session.rs',
    'src/graphics_device.rs', 'src/lib.rs', 'src/main.rs', 'src/pause_menu.rs', 'src/render/backend.rs',
    'src/render/device.rs', 'src/render/frame.rs', 'src/render/mod.rs', 'src/render/runtime.rs'))
ADDED = frozenset(('src/graphics_device.rs',))
MODES = ('seed', 'windowed-saved', 'windowed-missing', 'windowed-forced', 'headless-bypass', 'windowed-cpu')
SOURCE_PATHS = shared.SOURCE_PATHS
MAX_SOURCE_BYTES = 32 * 1024 * 1024

def require(condition, message):
    if not condition:
        raise ValueError(message)

def identity(path):
    raw = Path(path).read_bytes()
    return {'bytes': len(raw), 'sha256': shared.digest(raw)}

def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON field: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError('nonfinite JSON: ' + v)))

def git_sources(repository, commit):
    require(commit in (BASELINE_SOURCE, CANDIDATE_SOURCE), 'unreviewed source revision')
    names = subprocess.check_output(['git', '-C', str(repository), 'ls-tree', '-r', '--name-only',
                                      commit, '--', *SOURCE_PATHS]).decode().splitlines()
    require({'Cargo.toml', 'Cargo.lock', 'examples/renderer_contract.rs', 'src/render/frame.rs'} <= set(names),
            'incomplete source tree')
    raw = subprocess.check_output(['git', '-C', str(repository), 'archive', commit, '--', *names])
    result = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for item in archive:
            if item.isdir():
                continue
            path = PurePosixPath(item.name)
            require(item.isfile() and not path.is_absolute() and '..' not in path.parts
                    and '\\' not in item.name and ':' not in item.name and item.name not in result,
                    'unsafe or duplicate source entry')
            result[item.name] = archive.extractfile(item).read()
    require(sum(map(len, result.values())) <= MAX_SOURCE_BYTES, 'source byte bound exceeded')
    return result

def source_pair(baseline, candidate):
    require(set(candidate) - set(baseline) == ADDED and not set(baseline) - set(candidate),
            'unexpected added or removed production source')
    changed = {name for name in candidate if candidate[name] != baseline.get(name)}
    require(changed == CHANGED, 'source changes are outside the reviewed 12-file boundary')
    return {label: {name: {'bytes': len(raw), 'sha256': shared.digest(raw)}
                    for name, raw in sorted(files.items())}
            for label, files in [('baseline', baseline), ('candidate', candidate)]}

def current_checkout(root, expected):
    """Match the ebf pin, admitting only the exact reviewed cfg(test) fixture repair."""
    files, test_only_equivalences = {}, {}
    for name, raw in expected.items():
        path = root / name
        require(path.is_file() and not path.is_symlink(),
                'current checkout differs from the declared ebf production source: ' + name)
        actual = path.read_bytes()
        matched = actual
        if name == 'src/asset_path.rs' and actual != raw:
            matched = finite_source._asset_path_test_base(actual)
        require(matched == raw,
                'current checkout differs from the declared ebf production source: ' + name)
        files[name] = {'bytes': len(actual), 'sha256': shared.digest(actual)}
        if actual != raw:
            test_only_equivalences[name] = {
                'current_checkout': files[name],
                'compiled_source': {'bytes': len(raw), 'sha256': shared.digest(raw)},
            }
    for folder in ('src', 'updater', '.cargo'):
        directory = root / folder
        if directory.exists():
            for path in directory.rglob('*'):
                require(not path.is_symlink(), 'symlink in current compile inventory')
                if path.is_file():
                    require(path.relative_to(root).as_posix() in expected, 'extra current compile input: ' + str(path))
    return {'files': files, 'test_only_equivalences': test_only_equivalences}

def baseline_provider(metadata):
    require(type(metadata) is dict, 'baseline metadata must be the actual artifact object')
    expected = {'id': BASELINE_ARTIFACT, 'name': 'pass-submission-full-attempt-1',
                'size_in_bytes': 15858877, 'digest': 'sha256:' + BASELINE_ARCHIVE_SHA256, 'expired': False}
    require(all(type(metadata.get(k)) is type(v) and metadata[k] == v for k, v in expected.items()),
            'baseline artifact identity/digest/availability differs')
    run = metadata.get('workflow_run', {})
    require(run.get('id') == BASELINE_RUN and run.get('head_sha') ==
            '4c116be39e426f38f65772ae83ce539891a54e55' and run.get('head_branch') == 'main'
            and run.get('repository_id') == run.get('head_repository_id') == 1398577887,
            'baseline artifact repository/run/source differs')
    return metadata

def verified_baseline(root, review_path, baseline_source):
    require(identity(review_path)['sha256'] == BASELINE_REVIEW_SHA256, 'baseline review anchor changed')
    review = read_json(review_path)
    require(review['artifact'] == {'run_id': str(BASELINE_RUN), 'run_attempt': '1',
        'artifact_id': str(BASELINE_ARTIFACT), 'archive_sha256': BASELINE_ARCHIVE_SHA256},
        'baseline review artifact differs')
    variant = review['variants']['candidate']
    source_receipt_path = root / 'candidate-source-receipt.json'
    require(identity(source_receipt_path) == variant['source_receipt'], 'baseline source receipt changed')
    receipt = read_json(source_receipt_path)
    require(receipt['candidate_commit'] == BASELINE_COMPILED_SOURCE, 'historical compiled source differs')
    require(shared.source_manifest(root / 'candidate-source') == receipt['files'],
            'historical source inventory is incomplete or changed')
    require(set(receipt['files']) == set(baseline_source) | {'examples/pass_submission_benchmark.rs'},
            'historical baseline source inventory changed')
    for name, raw in baseline_source.items():
        require((root / 'candidate-source' / name).read_bytes() == raw,
                'historical 5abf production does not equal b085 baseline: ' + name)
    binary = root / 'candidate-renderer_contract.exe'
    require(identity(binary) == variant['contract_executable'], 'historical executable identity differs')
    require(identity(root / 'build-receipts.json') == review['build_receipts'], 'historical build receipts differ')
    build = read_json(root / 'build-receipts.json')['candidate']
    require(build['renderer_contract']['executable_sha256'] == identity(binary)['sha256']
            and build['source_receipt_sha256'] == identity(source_receipt_path)['sha256'],
            'historical binary/source linkage differs')
    original_compiler = receipt['toolchain'].encode('utf-8')
    require(shared.digest(original_compiler) == COMPILER_SHA256, 'historical compiler stdout differs')
    return binary, receipt, review

def archive_input(root, output, names):
    for name in names:
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, destination)

def verify_cpu_trace(path, source_hash, actual_device):
    report = cpu_reader.read_report(path)
    require(report['status']['state'] == 'complete', 'native CPU trace is incomplete')
    require(report['identity']['runtime_observed']['actual_backend'] == 'Dx12', 'CPU trace backend differs')
    adapter = report['identity']['runtime_observed']['actual_adapter']
    require(adapter.get('name') == 'Microsoft Basic Render Driver' and adapter.get('device_type') == 'Cpu'
            and adapter.get('present_mode') == 'Fifo', 'CPU trace lacks actual windowed WARP identity')
    require(adapter == actual_device, 'CPU trace belongs to a different native window/device')
    build = report['identity']['runtime_observed']['build']
    require(build.get('source_commit') == CANDIDATE_SOURCE and build.get('source_sha256') == source_hash,
            'CPU trace source differs from its compiled control')
    extension = report.get('cpu_frame_stages')
    require(isinstance(extension, dict), 'native CPU stage extension missing')
    summary = cpu_reader._cpu_stage_summary(extension, report['records'])
    require(all(row['sample_count'] >= 2 for row in summary['summary'].values()),
            'need two eligible interval-bearing paired samples for every CPU stage')
    presents = [(i, row) for i, row in enumerate(report['records']) if row['kind'] == 'successful_present_return']
    require(len(presents) == report['successful_present_count'] == 5,
            'CPU trace omitted a successful recorded present')
    successful_samples = [sample for sample in extension['samples']
                          if report['records'][sample['record_index']]['kind'] == 'successful_present_return']
    require(len(successful_samples) == 4 and
            {sample['record_index'] for sample in successful_samples} == {i for i, _ in presents[1:]},
            'CPU trace must retain exactly four full frames after its midframe baseline')
    require(all(all(span is not None for span in sample['spans'].values()) for sample in successful_samples),
            'a successful native frame is missing a paired CPU stage')
    dimensions = set()
    for sample in extension['samples']:
        row = report['records'][sample['record_index']]
        if row['kind'] == 'successful_present_return':
            require(sample['physical_width'] > 0 and sample['physical_height'] > 0,
                    'presented frame has zero physical dimensions')
            dimensions.add((sample['physical_width'], sample['physical_height']))
    return {'status': 'passed', 'trace': identity(path), 'stage_summary': summary,
            'actual_physical_dimensions': sorted(dimensions), 'gpu_duration_measured': False,
            'rtx_or_1080p60_acceptance': False}

def execute(args):
    require(sys.platform == 'win32', 'native controls require Windows; Linux can run guard tests only')
    repository, verifier_root = args.repository.resolve(), args.verifier_root.resolve()
    baseline_root, output = args.baseline_artifact.resolve(), args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    provider = baseline_provider(read_json(args.baseline_provider))
    shared.write_json(output / 'baseline-provider.json', provider)
    old, current = git_sources(repository, BASELINE_SOURCE), git_sources(repository, CANDIDATE_SOURCE)
    inventories = source_pair(old, current)
    checkout = current_checkout(verifier_root, current)
    # These are the actual caller bytes, distinct from the ebf bytes compiled below.
    checkout_path = output / 'current-checkout-source-inventory.json'
    shared.write_json(checkout_path, checkout)
    archive_input(verifier_root, output / 'current-checkout', checkout['test_only_equivalences'])
    baseline_binary, baseline_receipt, original_review = verified_baseline(baseline_root,
        verifier_root / 'tools/finite_ads_pass_batching_evidence/native-review.json', old)
    # Retain the exact baseline bytes that this new native invocation actually uses.
    shutil.copyfile(baseline_binary, output / 'baseline-renderer_contract.exe')
    archive_input(baseline_root, output / 'baseline-original',
                  ['candidate-source-receipt.json', 'build-receipts.json', 'candidate-build.command.json',
                   'candidate-build.log', 'rustc.txt', 'cargo.txt'])
    shutil.copytree(baseline_root / 'candidate-source', output / 'baseline-original/candidate-source')
    require(shared.source_manifest(output / 'baseline-original/candidate-source') == baseline_receipt['files'],
            'retained baseline source copy differs from its original receipt')
    shutil.copyfile(verifier_root / 'tools/finite_ads_pass_batching_evidence/native-review.json',
                    output / 'baseline-original/native-review.json')
    require(identity(output / 'baseline-original/native-review.json')['sha256'] == BASELINE_REVIEW_SHA256,
            'retained baseline review anchor changed')
    shared.write_json(output / 'baseline-original-inventory.json', shared.source_manifest(output / 'baseline-original'))
    shared.write_json(output / 'production-source-inventories.json', inventories)
    harness = (verifier_root / HARNESS).read_bytes()
    # All unchanged fixed assertions come from the already reviewed batching source.
    copied = (HARNESS, 'tools/run_graphics_cpu_contract.py', 'tools/test_graphics_cpu_contract.py',
              'tools/finite_ads_profile_binding.py',
              'tools/run_pass_submission_benchmark.py', 'tools/summarize_frame_performance.py', 'tools/exclusive_output.py',
              *shared.FIXED_VALIDATORS)
    archive_input(verifier_root, output / 'verifier', copied)
    for name in shared.FIXED_VALIDATORS:
        pinned = subprocess.check_output(['git', '-C', str(repository), 'show', BASELINE_SOURCE + ':' + name])
        require((verifier_root / name).read_bytes() == pinned, 'fixed native validator changed: ' + name)
    shared.write_json(output / 'verifier-receipt.json', shared.source_manifest(output / 'verifier'))
    source = output / 'candidate-source'
    source.mkdir()
    for name, raw in {**current, HARNESS: harness}.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    manifest = shared.source_manifest(source)
    env = os.environ.copy()
    forbidden = ('RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'RUSTC', 'RUSTC_WRAPPER',
                 'RUSTC_WORKSPACE_WRAPPER', 'VR_WEAPON_ASSET', 'RUSTUP_TOOLCHAIN')
    require(not any(env.get(name) for name in forbidden), 'inherited compiler/asset overrides are not permitted')
    temp = output / 'temp'; temp.mkdir()
    settings = {'CARGO_TARGET_DIR': str(output / 'target'), 'CARGO_INCREMENTAL': '0',
                'CARGO_PROFILE_DEV_DEBUG': '0', 'CARGO_PROFILE_DEV_OPT_LEVEL': '2', 'CARGO_BUILD_JOBS': '2', 'CI': 'true',
                **{key: str(temp) for key in ('TMP', 'TEMP', 'TMPDIR')}}
    env.update(settings)
    compiler = subprocess.check_output(['rustup', 'run', shared.TOOLCHAIN, 'rustc', '-Vv'], env=env)
    require(shared.digest(compiler) == COMPILER_SHA256 and compiler.decode() == baseline_receipt['toolchain'],
            'actual candidate compiler differs from reviewed baseline compiler')
    (output / 'rustc-stdout.bin').write_bytes(compiler)
    receipt = {'schema': 'rust-duty-graphics-cpu-source/v1', 'source_commit': CANDIDATE_SOURCE,
               'workflow_source_commit': os.environ.get('GITHUB_SHA'), 'workflow_run_id': os.environ.get('GITHUB_RUN_ID'),
               'workflow_run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'), 'files': manifest,
               'current_checkout_inventory': identity(checkout_path),
               'harness_sha256': shared.digest(harness), 'compiler_stdout_sha256': shared.digest(compiler),
               'build_environment': settings, 'scope': 'exact ebf production plus new validation example; no game assets'}
    receipt_path = output / 'candidate-source-receipt.json'; shared.write_json(receipt_path, receipt)
    source_hash = identity(receipt_path)['sha256']
    command = ['rustup', 'run', shared.TOOLCHAIN, 'cargo', 'build', '--locked', '--no-default-features',
               '--features', 'wgpu-runtime', '--example', 'renderer_contract', '--example', EXAMPLE,
               '--message-format=json-render-diagnostics']
    log = output / 'candidate-build.log'
    shared.run_logged(command, source, log, {**env, 'GRAPHICS_CPU_SOURCE_SHA256': source_hash}, 1200)
    require(shared.source_manifest(source) == manifest, 'candidate source changed during build')
    compiled = {}
    for line in log.read_text(encoding='utf-8').splitlines():
        try: item = json.loads(line)
        except ValueError: continue
        name = item.get('target', {}).get('name')
        if item.get('reason') == 'compiler-artifact' and name in ('renderer_contract', EXAMPLE) and item.get('executable'):
            require(name not in compiled, 'duplicate compiled example receipt')
            require(item['target']['kind'] == ['example'], 'compiled target is not an example')
            destination = output / ('candidate-' + name + '.exe')
            shutil.copyfile(item['executable'], destination)
            compiled[name] = {'path': destination.name, **identity(destination)}
    require(set(compiled) == {'renderer_contract', EXAMPLE}, 'missing candidate example executable')
    shared.write_json(output / 'candidate-executables.json', compiled)
    fixed_checks, devices = {}, []
    for label in ('baseline', 'candidate'):
        binary = output / (label + '-renderer_contract.exe')
        expected = original_review['variants']['candidate']['contract_executable'] if label == 'baseline' else {
            k: compiled['renderer_contract'][k] for k in ('bytes', 'sha256')}
        require(identity(binary) == expected, 'native contract binary changed before invocation')
        shared.run_logged([str(binary), '--renderer=dx12', '--force-fallback-adapter',
                           '--output-dir', str(output / (label + '-renderer-contract'))],
                          output, output / (label + '-renderer-contract.log'), env, 180)
        devices.append(shared.device_evidence(output / (label + '-renderer-contract.log')))
        fixed_checks[label] = shared.fixed_validation(output / (label + '-renderer-contract'),
            output / 'verifier', output / (label + '-fixed-validator.log'), env)
    device = shared.require_same_devices(devices)
    for key in ('device_type', 'vendor_id', 'device_id', 'driver', 'driver_info'):
        require(device[key] == original_review['variants']['candidate']['runtime_identity'][key],
                'runtime differs from historical finite profile: ' + key)
    pixels = shared.contract_pixels(output / 'baseline-renderer-contract', output / 'candidate-renderer-contract')
    shared.write_json(output / 'production-contract-exact-pixels.json', pixels)
    shared.write_json(output / 'production-contract-fixed-validation.json', fixed_checks)
    # The mode verifier below owns all additional native controls; a missing mode
    # or unsupported window is a failure, never an applicability skip.
    controls = run_controls(output, compiled[EXAMPLE], source_hash, env, device)
    require(shared.source_manifest(source) == manifest, 'candidate source changed during native controls')
    require(current_checkout(verifier_root, current) == checkout,
            'current checkout changed during native controls')
    require(identity(checkout_path) == receipt['current_checkout_inventory'],
            'retained current checkout inventory changed')
    for name in checkout['test_only_equivalences']:
        require(identity(output / 'current-checkout' / name) == checkout['files'][name],
                'retained current checkout source changed: ' + name)
    summary = {'schema': 'rust-duty-graphics-cpu-native-comparison/v1', 'status': 'passed',
        'baseline_compiled_source_commit': BASELINE_COMPILED_SOURCE, 'baseline_equivalent_source_commit': BASELINE_SOURCE,
        'candidate_source_commit': CANDIDATE_SOURCE, 'baseline_artifact': provider,
        'candidate_source_receipt': identity(receipt_path), 'candidate_executables': compiled,
        'compiler_stdout_sha256': shared.digest(compiler), 'device_evidence': device,
        'fixed_renderer_contracts': fixed_checks, 'exact_renderer_pixels': pixels, 'controls': controls,
        'finite_profile_activated': False, 'rtx_or_1080p60_acceptance': False,
        'scope': 'source-bound WARP renderer equality and selector/timing integration; no gameplay or GPU-duration verdict'}
    shared.write_json(output / 'summary.json', summary)
    return summary

def preference_evidence(value, path):
    require(type(value) is dict and set(value) == {'length', 'bytes', 'utf8'}, 'preference byte evidence missing')
    raw = path.read_bytes()
    require(value['length'] == len(raw) and type(value['length']) is int
            and type(value['bytes']) is list
            and all(type(v) is int and 0 <= v <= 255 for v in value['bytes'])
            and bytes(value['bytes']) == raw and value['utf8'] == raw.decode('utf-8'),
            'retained preference bytes differ')
    parsed = read_json(path)
    require(parsed.get('schema') == 'rust-duty-graphics-device/v1' and type(parsed.get('adapter')) is dict,
            'preference schema/fingerprint missing')
    return parsed['adapter']

def actual_devices(log, count, expected_device):
    lines = log.read_text(encoding='utf-8').splitlines()
    def records(prefix):
        return [json.loads(line[len(prefix):]) for line in lines if line.startswith(prefix)]
    old, rich = records('renderer device_evidence='), records('renderer graphics_device_evidence=')
    require(len(old) == len(rich) == count, 'native creation/evidence count differs')
    require(lines.count('renderer dx12_shader_compiler=Fxc') == count, 'native FXC initialization count differs')
    for narrow, full in zip(old, rich):
        require(set(narrow) == set(expected_device), 'old device evidence contract changed')
        for key in ('device_type', 'vendor_id', 'device_id', 'driver', 'driver_info'):
            require(full.get(key) == narrow[key] == expected_device[key], 'native device differs: ' + key)
        require(full.get('name') == 'Microsoft Basic Render Driver' and full.get('backend') == 'Dx12',
                'native control is not actual DX12 WARP')
        require(all(full.get(key) == value for key, value in narrow.items()), 'rich/narrow device evidence differs')
    return rich

def synthetic_pixels(path, expected_size=None):
    from PIL import Image
    with Image.open(path) as image:
        require(image.format == 'PNG' and image.mode == 'RGBA' and image.width >= 176 and image.height >= 64,
                'invalid synthetic native image')
        if expected_size is not None:
            require(image.size == tuple(expected_size), 'native image differs from observed physical extent')
        pixels = image.tobytes()
        require(all(v == 255 for v in pixels[3::4]), 'native display image has nonopaque alpha')
        for x, y, expected in [(24, 24, (255, 0, 0, 255)), (80, 24, (0, 255, 0, 255)),
                                (136, 24, (0, 0, 255, 255)), (168, 56, (0, 0, 0, 255))]:
            require(all(abs(a - b) <= 2 for a, b in zip(image.getpixel((x, y)), expected)),
                    'independent synthetic pixel expectation failed')
        return {**identity(path), 'rgba_sha256': shared.digest(pixels), 'width': image.width, 'height': image.height}

def control_report(report, mode, source_hash):
    expected = {'schema': 'rust-duty-graphics-cpu-contract/v1', 'mode': mode, 'status': 'passed',
                'source_commit': CANDIDATE_SOURCE, 'source_sha': source_hash,
                'compiled_source_sha256': source_hash, 'platform': 'windows'}
    require(type(report) is dict and all(type(report.get(k)) is type(v) and report[k] == v
                                      for k, v in expected.items()), 'native control identity/status differs')
    require(type(report.get('pid')) is int and report['pid'] > 0, 'native process identity missing')
    require(all(type(report.get(k)) is str and report[k] for k in ('build_label', 'build_version', 'build_number')),
            'native build context missing')
    require('error' not in report and 'preference_after_error' not in report, 'native control retained an error')

def run_controls(output, executable, source_hash, env, expected_device):
    preferences = output / 'preferences'; preferences.mkdir()
    seed_path = preferences / 'saved-warp.json'
    binary = output / executable['path']
    expected_binary = {k: executable[k] for k in ('bytes', 'sha256')}
    controls, saved_fingerprint = {}, None
    for mode in MODES:
        directory = output / mode
        settings = seed_path if mode in ('seed', 'windowed-saved', 'windowed-cpu') else preferences / (mode + '.json')
        require(identity(binary) == expected_binary, 'control executable changed before run')
        before_seed = identity(seed_path) if seed_path.exists() else None
        log = output / (mode + '.log')
        shared.run_logged([str(binary), '--mode', mode, '--output-dir', str(directory),
            '--graphics-settings', str(settings), '--source-sha', source_hash], output, log, env, 60)
        report_path = directory / 'report.json'
        report = read_json(report_path); control_report(report, mode, source_hash)
        require(report['graphics_settings'] == str(settings), 'control preference destination differs')
        complete_prefix = 'graphics_cpu_contract phase=complete evidence='
        completed = [json.loads(line[len(complete_prefix):]) for line in log.read_text(encoding='utf-8').splitlines()
                     if line.startswith(complete_prefix)]
        require(completed == [report], 'native complete stdout/report differ')
        fingerprint = preference_evidence(report.get('preference_after'), settings)
        expected_names = {'report.json'}
        extra = {}
        if mode == 'seed':
            require(report.get('preference_before') is None and before_seed is None, 'seed reused existing preferences')
            require(report.get('save_api') == 'graphics_device::save_choice'
                    and report.get('catalog_surface_checked') is False, 'seed did not use actual selection API')
            expected = {'backend': 'dx12', 'name': 'Microsoft Basic Render Driver',
                'vendor_id': expected_device['vendor_id'], 'device_id': expected_device['device_id'], 'device_type': 'Cpu'}
            require(fingerprint == report.get('saved_fingerprint') == expected, 'saved native WARP fingerprint differs')
            catalog = report.get('catalog')
            require(type(catalog) is list and sum(c.get('fingerprint') == fingerprint for c in catalog) == 1,
                    'saved WARP fingerprint is missing or ambiguous in actual enumeration')
            actual_devices(log, 0, expected_device)
            saved_fingerprint = fingerprint
        else:
            require(preference_evidence(report.get('preference_before'), settings) == fingerprint,
                    'control rewrote its preference bytes')
            require(identity(seed_path) == before_seed, 'a restarted control rewrote the seed choice')
            if mode in ('windowed-saved', 'windowed-cpu'):
                require(fingerprint == saved_fingerprint, 'restart did not consume the exact saved choice')
            else:
                require(report.get('fixture_fingerprint') == fingerprint
                        and fingerprint.get('vendor_id') == fingerprint.get('device_id') == 2**32 - 1
                        and fingerprint.get('name', '').startswith('Rust Duty deliberately missing adapter '),
                        'negative control does not use its declared impossible fingerprint')
            if mode == 'windowed-missing':
                actual_devices(log, 0, expected_device)
                require(report.get('no_fallback_verified') is True and
                        'is missing. No fallback was used.' in report.get('expected_failure', ''),
                        'missing explicit choice did not fail closed')
                require(report.get('backend_evidence') is None
                        and report['window']['app_frames'] == report['window']['successful_end_frames'] == 0,
                        'missing choice rendered or substituted another adapter')
                require(report.get('loaded_startup_preference') == fingerprint, 'missing choice was not read')
            elif mode == 'headless-bypass':
                devices = actual_devices(log, 2, expected_device)
                creations = report.get('headless_creations')
                require(type(creations) is list and len(creations) == 2, 'both headless bypass cases are required')
                for forced, creation, device, name in zip((False, True), creations, devices,
                        ('headless-auto.png', 'headless-forced.png')):
                    require(creation.get('loaded_startup_preference') == fingerprint
                            and creation.get('force_fallback_requested') is forced and creation.get('windowed') is False,
                            'headless bypass fixture changed')
                    require(device.get('force_fallback_requested') is forced and device.get('present_mode') is None
                            and device.get('requested_fingerprint') is None
                            and device.get('selection_mode') == ('forced_fallback' if forced else 'automatic'),
                            'headless constructor did not bypass the impossible saved choice')
                    expected_names.add(name); extra[name] = synthetic_pixels(directory / name, (320, 180))
                extra['devices'] = devices
            else:
                forced = mode == 'windowed-forced'
                device = actual_devices(log, 1, expected_device)[0]
                require(device == report.get('backend_evidence'), 'windowed actual evidence differs from original log')
                require(device.get('present_mode') == 'Fifo' and device.get('force_fallback_requested') is forced,
                        'actual windowed present mode/fallback differs')
                if forced:
                    require(report.get('loaded_startup_preference') is None
                            and device.get('selection_mode') == 'forced_fallback'
                            and device.get('requested_fingerprint') is None, 'forced window consulted saved choice')
                else:
                    require(report.get('loaded_startup_preference') == fingerprint
                            and device.get('selection_mode') == 'explicit_fingerprint'
                            and device.get('requested_fingerprint') == device.get('actual_fingerprint') == fingerprint,
                            'explicit window selected a different adapter')
                window = report['window']; frames = 6 if mode == 'windowed-cpu' else 2
                require(window.get('app_frames') == window.get('successful_end_frames') == frames
                        and frames <= window.get('attempts', 0) <= 128,
                        'windowed control omitted a normal final presented frame')
                expected_names.add('windowed.png')
                extra['windowed.png'] = synthetic_pixels(directory / 'windowed.png',
                    (window['physical_width'], window['physical_height']))
                extra['device'] = device
                if mode == 'windowed-cpu':
                    expected_names.add('cpu-capture.json')
                    require(report.get('cpu_validation') == {'complete': True, 'uninstrumented_present_count': 1,
                        'recorded_present_count': 5, 'complete_cpu_sample_count': 4,
                        'first_recorded_present_has_cpu_sample': False, 'normal_final_present_export': True},
                        'CPU control did not preserve its uninstrumented/final-frame lifecycle')
                    extra['cpu_trace'] = verify_cpu_trace(directory / 'cpu-capture.json', source_hash, device)
                    require(extra['cpu_trace']['actual_physical_dimensions'] ==
                            [(window['physical_width'], window['physical_height'])],
                            'CPU sample dimensions differ from actual native window')
        require({p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()} == expected_names,
                'native control output inventory differs')
        controls[mode] = {'report': identity(report_path), 'log': identity(log),
            'process': identity(log.with_suffix('.command.json')), 'preference': identity(settings), **extra}
        shared.write_json(output / 'completed-controls.json', controls)
    require(set(controls) == set(MODES), 'not all native controls completed')
    return controls

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('repository', 'verifier-root', 'baseline-artifact', 'baseline-provider', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(argv)
    existed = args.output_dir.exists()
    try:
        result = execute(args)
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
        if not existed and args.output_dir.is_dir():
            shared.write_json(args.output_dir / 'failure.json', {'status': 'failed', 'error': str(error)})
        parser.exit(1, 'graphics/CPU native controls failed: ' + str(error) + '\n')
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

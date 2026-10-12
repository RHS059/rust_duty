#!/usr/bin/env python3
"""Build a source-bound asset-free Windows DX12/WARP GPU stop/restart fixture.

Uses the existing process and primary/sidecar validators. Unsupported timestamp
features are explicit unavailable coverage, never a measured-path pass. No FPS
or target-hardware verdict is produced. Evidence directories must be new.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import dx12_contract_process as process
import performance_matrix as matrix
import summarize_cpu_substages as cpu
import summarize_cpu_encode_detail as encode
import summarize_gpu_timing as gpu

FRAMES = 64
IDLE = 4
REPORT = 'gpu-session-contract.json'
SCHEMA = 'rust-duty-gpu-session-contract/v1'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def source_binding(root):
    """Bind audited runtime plus public compile inputs; never read weapon assets."""
    root = Path(root)
    require('VR_WEAPON_ASSET' not in os.environ, 'VR_WEAPON_ASSET must be unset')
    require(not (root / 'assets/weapons/hk416a5.vrm').exists(),
            'asset-free fixture requires a checkout without the optional embedded weapon')
    require(not git(root, 'status', '--porcelain', '--untracked-files=no').strip(),
            'source checkout has tracked changes')
    identity = matrix.source_identity(root)
    require(not os.environ.get('GITHUB_SHA') or os.environ['GITHUB_SHA'] == identity['commit'],
            'GITHUB_SHA differs from the checked-out revision')
    paths = ['Cargo.toml', 'Cargo.lock', 'build.rs', 'build_number.rs', 'rust-toolchain',
             'rust-toolchain.toml', '.cargo', '.gitattributes', 'src', 'updater',
             'examples/gpu_session_contract.rs', 'tools']
    require(not git(root, 'ls-files', '--others', '--exclude-standard', '--', *paths).strip(),
            'untracked compile/validator inputs are not source-bound')
    names = git(root, 'ls-files', '-z', '--', *paths).decode().strip('\0').split('\0')
    require('examples/gpu_session_contract.rs' in names, 'fixture must be committed before native execution')
    hashes = {name: matrix.sha256(root / name) for name in sorted(names)}
    for name in ('.cargo/config', '.cargo/config.toml'):
        require(not (root / name).exists() or name in hashes,
                'untracked Cargo configuration would change the compiled artifact')
    # Optional generated updater notices alter build output, even when ignored.
    notices = root / 'updater/notices/THIRD_PARTY_UPDATER_LICENSES.txt'
    require(not notices.exists() or notices.relative_to(root).as_posix() in hashes,
            'untracked generated updater notices would change the compiled artifact')
    return {'source_commit': identity['commit'], 'runtime_identity': identity,
            'files_sha256': hashes, 'source_sha256': matrix.canonical_hash(hashes),
            'embedded_weapon_present': False}


def validate_outputs(output, binding, opt_in=True):
    output = Path(output)
    suffixes = ('.json', '.cpu-substages.json', '.cpu-encode-detail.json') + (('.gpu-timing.json',) if opt_in else ())
    expected = {REPORT} | {f'session-{i}{suffix}' for i in range(2) for suffix in suffixes}
    require({p.name for p in output.iterdir()} == expected, 'missing or unexpected fixture output')
    require(all(p.is_file() and not p.is_symlink() for p in output.iterdir()),
            'fixture outputs must be regular nonsymlink files')
    report, _ = cpu.read_json(output / REPORT)
    require(isinstance(report, dict), 'fixture report must be an object')
    require(report.get('schema') == SCHEMA and report.get('status') == 'passed'
            and report.get('error') is None and report.get('platform') == 'windows', 'fixture did not pass on Windows')
    for name in ('source_commit', 'source_sha256'):
        require(report.get(name) == binding[name], 'compiled fixture binding differs: ' + name)
    mode = 'enabled' if opt_in else 'default-off'
    require(report.get('gpu_timestamps_requested') is opt_in and report.get('mode') == mode,
            'fixture timestamp mode differs')
    require(type(report.get('frames_per_session')) is int and report['frames_per_session'] == FRAMES
            and type(report.get('idle_frames_before_each')) is int and report['idle_frames_before_each'] == IDLE,
            'fixture frame bounds differ')
    expected_presents = 2 * (FRAMES + IDLE) + 1
    require(type(report.get('successful_end_frames')) is int
            and report['successful_end_frames'] == expected_presents
            and type(report.get('attempts')) is int and expected_presents <= report['attempts'] <= 512,
            'window closed early or exceeded its attempt bound')
    adapter = report.get('backend_evidence', {})
    require(isinstance(adapter, dict), 'adapter evidence must be an object')
    require(adapter.get('backend') == 'Dx12' and adapter.get('name') == 'Microsoft Basic Render Driver'
            and adapter.get('device_type') == 'Cpu' and adapter.get('force_fallback_requested') is True
            and adapter.get('present_mode') == 'Fifo'
            and adapter.get('gpu_timestamps_requested') is opt_in
            and type(adapter.get('gpu_timestamp_features_enabled')) is bool,
            'actual DX12/WARP/Fifo renderer or timestamp opt-in differs')
    sessions = report.get('sessions')
    require(isinstance(sessions, list) and len(sessions) == 2, 'both session completions are required')
    summaries = []
    encode_summaries = []
    session_ids = []
    features = adapter['gpu_timestamp_features_enabled']
    require(opt_in or not features, 'default-off constructor enabled timestamp features')
    for ordinal, completion in enumerate(sessions):
        start = IDLE + ordinal * (FRAMES + IDLE)
        expected_completion = {'ordinal': ordinal, 'started_after_present': start,
                               'completed_after_present': start + FRAMES,
                               'stop_before_final_present': True, 'completion_consumed_once': True}
        require(completion == expected_completion
                and all(type(completion[key]) is type(value) for key, value in expected_completion.items()),
                'session stop/restart ordering or completion differs')
        primary, digest = cpu.read_json(output / f'session-{ordinal}.json')
        substages, _ = cpu.read_json(output / f'session-{ordinal}.cpu-substages.json')
        cpu.validate(substages, primary, digest)
        require(primary['status']['state'] == 'complete', 'primary capture is incomplete')
        runtime = primary['identity']['runtime_observed']
        require(runtime['actual_backend'] == 'Dx12' and runtime['actual_adapter'] == adapter
                and runtime['build'] == {key: binding[key] for key in ('source_commit', 'source_sha256')}
                and runtime['scene'] == {'fixture': 'gpu-session-contract', 'ordinal': ordinal, 'gameplay': False},
                'primary identity differs from fixture, source, or session ordinal')
        window = runtime['initial_window']
        require(window['physical_width'] == 1920 and window['physical_height'] == 1080
                and window['mode'] == 'windowed', 'fixture initial physical extent must be 1920x1080 windowed')
        require(all(row['physical_width'] == 1920 and row['physical_height'] == 1080
                    for row in primary['cpu_frame_stages']['samples']),
                'fixture CPU frame physical extent changed')
        require(all(row['context']['physical_width'] == 1920 and row['context']['physical_height'] == 1080
                    and row['context']['mode'] == 'windowed'
                    for row in primary['records'] if row['kind'] == 'window_context'),
                'fixture observed window context changed')
        require(primary['successful_present_count'] == FRAMES, 'session normal-present count differs')
        require(primary['records'][-1]['kind'] == 'successful_present_return'
                and primary['stop_requested_ns'] is not None
                and primary['records'][-1]['at_ns'] >= primary['stop_requested_ns'],
                'capture did not finish with the requested final normal present')
        require(len(primary['cpu_frame_stages']['samples']) >= FRAMES - 1,
                'real per-frame CPU/GPU attempts are missing')
        require(all(row['details']['state'] == 'complete' for row in substages['samples']),
                'CPU substage accounting is incomplete')
        details, _ = cpu.read_json(output / f'session-{ordinal}.cpu-encode-detail.json')
        encode_summary = encode.summarize(details, substages, primary, digest)
        require(encode_summary['diagnostic_status'] == 'complete'
                and encode_summary['summarized_attempts'] == len(substages['samples'])
                and encode_summary['summarized_attempts'] > 0,
                'CPU encode-detail accounting or eligible phase observations are incomplete')
        encode_summaries.append(encode_summary)
        if not opt_in:
            continue
        sidecar, _ = cpu.read_json(output / f'session-{ordinal}.gpu-timing.json')
        summary = gpu.summarize(sidecar, primary, digest)
        require(summary['state'] == 'complete', 'primary/GPU accounting is incomplete')
        require(sidecar['samples'] and sidecar['samples'][0]['attempt'] == 0,
                'restart must begin with a fresh attempt zero')
        negotiation = sidecar['feature_negotiation']
        require(negotiation['adapter_supports_required_features'] == features
                and negotiation['device_features_enabled'] == features, 'supported timestamp features were not enabled')
        if features:
            require(sidecar['availability']['state'] == 'available'
                    and summary['measured_eligible_count'] > 0, 'enabled device did not produce a real measured eligible GPU span')
            require(set(summary['status_counts']) <= {'measured', 'pending_at_stop', 'ring_full', 'not_submitted'},
                    'GPU error/rejection/unconfirmed status in the successful fixture')
        else:
            require(sidecar['availability']['state'] == 'device_features_not_enabled'
                    and set(summary['status_counts']) <= {'device_features_not_enabled', 'not_submitted'}
                    and summary['measured_eligible_count'] == 0, 'unsupported device did not report explicit unavailable timing')
        session_ids.append(sidecar['session'])
        summaries.append(summary)
    require(not opt_in or session_ids[1] > session_ids[0], 'restart reused an earlier GPU session identity')
    return {'passed': True, 'contract': SCHEMA, 'bound_source_commit': binding['source_commit'],
            'bound_source_sha256': binding['source_sha256'], 'session_ids': session_ids,
            'mode': mode,
            'measurement_path': 'disabled_control' if not opt_in else ('measured' if features else 'unavailable_device_features'),
            'measurement_path_verified': features, 'sessions': summaries,
            'cpu_encode_sessions': encode_summaries,
            'scope': 'bounded synthetic DX12/WARP lifecycle only; no FPS, RTX, gameplay, or scan-out verdict'}


def run(root, evidence, timeout=90, build_timeout=1200):
    require(sys.platform == 'win32', 'native GPU session contract requires Windows; no alternate backend is permitted')
    for value in (timeout, build_timeout):
        require(gpu.positive(value), 'timeouts must be finite and positive')
    require(not Path(evidence).is_symlink(), 'evidence directory cannot be a symlink')
    root, evidence = Path(root).resolve(), Path(evidence).resolve()
    require(root == Path(__file__).resolve().parents[1], 'runner and checkout must be the same source tree')
    require(not evidence.exists(), 'refusing stale build/process evidence')
    binding = source_binding(root)
    evidence.mkdir(parents=True, exist_ok=False)
    matrix.write_json(evidence / 'source-binding.json', binding)
    env = dict(os.environ, GPU_SESSION_SOURCE_COMMIT=binding['source_commit'],
               GPU_SESSION_SOURCE_SHA256=binding['source_sha256'], CARGO_TARGET_DIR=str(evidence / 'target'))
    argv = ['cargo', 'build', '--locked', '--no-default-features', '--features', 'wgpu-runtime',
            '--example', 'gpu_session_contract']
    matrix.write_json(evidence / 'build-invocation.json', {'command': argv, 'cwd': str(root),
        'source_commit': binding['source_commit'], 'source_sha256': binding['source_sha256'],
        'rustc': subprocess.check_output(['rustc', '-Vv'], text=True), 'timeout_seconds': build_timeout})
    try:
        with (evidence / 'build.stdout.log').open('wb') as out, (evidence / 'build.stderr.log').open('wb') as err:
            build = subprocess.Popen(argv, cwd=root, env=env, stdout=out, stderr=err,
                stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            try:
                code = build.wait(timeout=build_timeout)
            except BaseException:
                matrix.write_json(evidence / 'build-cleanup.json', process._terminate_process_tree(build))
                raise
        matrix.write_json(evidence / 'build-result.json', {'exit_code': code})
        require(code == 0, 'fixture build failed; inspect build logs')
        require(source_binding(root) == binding, 'source changed during build')
        executable = evidence / 'target/debug/examples/gpu_session_contract.exe'
        built_hash = matrix.sha256(executable)
        matrix.write_json(evidence / 'built-executable.json', {'sha256': built_hash})
        results = {}
        for mode in ('default-off', 'enabled'):
            # Existing process runner inherits the environment. Scope and restore
            # this fixture-only mode; the producer and validator both attest it.
            previous = os.environ.get('GPU_SESSION_CONTRACT_MODE')
            os.environ['GPU_SESSION_CONTRACT_MODE'] = mode
            try:
                def validate(output):
                    result = validate_outputs(output, binding, opt_in=mode == 'enabled')
                    require(source_binding(root) == binding, 'source changed during execution')
                    return result
                require(matrix.sha256(executable) == built_hash, 'built executable changed between controls')
                receipt = process.run(executable, root,
                    evidence / mode / 'process', evidence / mode / 'output', timeout,
                    'gpu-session-contract-' + mode, validate)
                require(receipt.get('executable_sha256') == built_hash,
                        'process executable differs from the freshly built fixture')
                results[mode] = receipt
            finally:
                if previous is None:
                    os.environ.pop('GPU_SESSION_CONTRACT_MODE', None)
                else:
                    os.environ['GPU_SESSION_CONTRACT_MODE'] = previous
        result = {'passed': True, 'source_commit': binding['source_commit'],
                  'source_sha256': binding['source_sha256'], 'executable_sha256': built_hash,
                  'controls': results}
        matrix.write_json(evidence / 'summary.json', result)
        return result
    except BaseException as error:
        matrix.write_json(evidence / 'failure.json', {'passed': False, 'error': str(error),
                                                    'error_type': type(error).__name__})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=90)
    parser.add_argument('--build-timeout', type=float, default=1200)
    args = parser.parse_args(argv)
    try:
        result = run(args.root, args.evidence, args.timeout, args.build_timeout)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print('gpu-session-contract: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

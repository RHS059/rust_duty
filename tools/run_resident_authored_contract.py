#!/usr/bin/env python3
"""Prove actual companion loaders execute resident GPU commands against CPU originals."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image
import dx12_contract_process as process
import performance_matrix as matrix
import run_authored_loader_pair as authored
import run_cpu_image_preservation as pair
import run_windows_cpu_profile as profile
import summarize_cpu_encode_detail as detail

SCHEMA = 'rust-duty-resident-authored-contract/v1'
EXAMPLE = 'resident_authored_contract'
STATS = tuple(name.removeprefix('resident_') for name in detail.COUNTERS_V3[len(detail.COUNTERS_V2):])
require = authored.require


def validate_report(report, receipt_sha256):
    require(isinstance(report, dict) and report.get('schema') == SCHEMA,
            'resident authored schema differs')
    require(report.get('passed') is True, 'resident authored producer did not pass')
    require(report.get('source_receipt_sha256') == receipt_sha256 and authored.digest_string(receipt_sha256),
            'compiled source receipt differs')
    cases = report.get('cases')
    require(isinstance(cases, list) and all(isinstance(c, dict) for c in cases)
            and [c.get('name') for c in cases] == authored.CASE_NAMES, 'resident pose inventory differs')
    for label in ('cpu', 'resident'):
        proxy = copy.deepcopy(report)
        proxy.update(schema=authored.SCHEMA, native_images=True)
        proxy['cases'] = [{'name': c['name'], 'metadata': c.get('metadata'),
                           'commands': c.get(label + '_commands')} for c in cases]
        authored.validate_report(proxy, receipt_sha256)
    for case in cases:
        require(case['cpu_commands'] == case['resident_commands'] and case.get('expanded_equal') is True,
                'ordered world corners/material snapshots differ')
        count = len(case['cpu_commands'])
        cpu, gpu = case.get('cpu_paths'), case.get('resident_paths')
        require(isinstance(cpu, list) and isinstance(gpu, list) and len(cpu) == len(gpu) == 3
                and all(type(n) is int and 0 <= n <= 2048 for n in cpu + gpu), 'invalid path counts')
        require(cpu == [count, 0, 0] and gpu[0] == 0 and gpu[1] > 0 and sum(gpu) == count,
                'actual original-loader/resident paths are not both proven')
        require(gpu[2] == 0 if case['name'].startswith('rigid-alpha-') else gpu[2] > 0,
                'expected rigid/skin path is absent')
        for label, expected in (('cpu', [0, 0]), ('resident', gpu[1:])):
            stats = case.get(label + '_stats')
            require(isinstance(stats, dict) and set(stats) == set(STATS)
                    and all(type(n) is int and 0 <= n <= 2**64-1 for n in stats.values()),
                    'resident stats fields/types differ')
            require([stats['rigid_draws'], stats['skinned_draws']] == expected,
                    'submitted resident class counts differ from recorded commands')
            detail.validate_resident_counters({'prepared_draws': count,
                                               **{'resident_' + k: v for k, v in stats.items()}})
            if label == 'cpu':
                require(not any(stats.values()), 'CPU oracle unexpectedly used resident resources')
        for label in ('cpu', 'resident'):
            require(authored.digest_string(case.get(label + '_expanded_sha256')), 'invalid corner digest')
        require(case['cpu_expanded_sha256'] == case['resident_expanded_sha256'], 'corner digests differ')
        require(type(case.get('differing_pixels')) is int and case['differing_pixels'] == 0
                and type(case.get('maximum_channel_delta')) is int and case['maximum_channel_delta'] == 0
                and type(case.get('foreground_pixels')) is int
                and 100 < case['foreground_pixels'] <= authored.EXTENT[0] * authored.EXTENT[1],
                'pixel parity/visibility failed')
    adapter = report.get('backend')
    require(adapter in ({'requested': 'dx12', 'backend': 'Dx12', 'adapter': 'Microsoft Basic Render Driver'},
                        {'requested': 'vulkan', 'backend': 'Vulkan', 'adapter': 'NVIDIA A100-SXM4-40GB'}),
            'unreviewed native backend identity')
    return report


def validate_outputs(directory, report, receipt_sha256):
    directory = Path(directory)
    validate_report(report, receipt_sha256)
    require(matrix.json_read(directory / 'report.json') == report, 'retained report changed')
    expected = {'report.json', 'camera.json'} | {
        f'{name}-{label}{suffix}' for name in authored.CASE_NAMES for label in ('cpu', 'resident')
        for suffix in ('.corners.bin', '.png')}
    require({p.name for p in directory.iterdir()} == expected
            and all(p.is_file() and not p.is_symlink() for p in directory.iterdir()),
            'resident output inventory is not exact regular files')
    require(matrix.json_read(directory / 'camera.json') == report['camera'], 'camera receipt differs')
    for case in report['cases']:
        images = []
        for label in ('cpu', 'resident'):
            raw = (directory / f'{case["name"]}-{label}.corners.bin').read_bytes()
            require(pair.controls.digest(raw) == case[label + '_expanded_sha256'], 'retained corners differ')
            offset = 0
            for command in case[label + '_commands']:
                size = command['indices'] * 40
                require(pair.controls.digest(raw[offset:offset+size]) == command['expanded_sha256'],
                        'ordered raw corner chunk differs')
                offset += size
            require(offset == len(raw), 'corner extent differs')
            with Image.open(directory / f'{case["name"]}-{label}.png') as image:
                require(image.mode == 'RGBA' and list(image.size) == authored.EXTENT, 'native pixels format differs')
                pixels = image.tobytes()
            require(all(pixels[i] == 255 for i in range(3, len(pixels), 4)), 'display alpha is not opaque')
            rgba = list(zip(*(iter(pixels),) * 4))
            foreground = sum(any(abs(x-y) > 4 for x, y in zip(pixel[:3], (8,16,24))) for pixel in rgba)
            require(foreground == case['foreground_pixels'] and len(set(rgba)) >= 8,
                    'retained foreground/shading contradicts report')
            images.append(pixels)
        require(images[0] == images[1], 'actual native RGBA differs')
    return {'passed': True, 'exact_authored_pairs': 22, 'original_cpu_oracle': True,
            'actual_resident_commands': True, 'backend': report['backend'],
            'scope': 'fixed authored overview correctness; no frame-rate or gameplay-visibility verdict'}


def logged(command, root, output, env, timeout, executable_sha256=None):
    require(pair.gpu.positive(timeout), 'timeout must be finite and positive')
    output.mkdir(parents=True, exist_ok=False)
    if executable_sha256:
        require(matrix.sha256(Path(command[0])) == executable_sha256, 'executable changed before process')
    matrix.write_json(output / 'invocation.json', {'command': list(map(str, command)), 'cwd': str(root),
        'timeout_seconds': timeout, 'executable_sha256': executable_sha256})
    try:
        options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == 'win32' else {'start_new_session': True}
        with (output / 'stdout.log').open('wb') as stdout, (output / 'stderr.log').open('wb') as stderr:
            child = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                                     stdout=stdout, stderr=stderr, **options)
            try:
                code = child.wait(timeout=timeout)
            except BaseException:
                matrix.write_json(output / 'cleanup.json', process._terminate_process_tree(child))
                raise
        matrix.write_json(output / 'result.json', {'exit_code': code})
        require(code == 0, 'native build/process failed; inspect retained original evidence')
        if executable_sha256:
            require(matrix.sha256(Path(command[0])) == executable_sha256, 'executable changed during process')
    except BaseException as error:
        matrix.write_json(output / 'failure.json', {'error': str(error), 'type': type(error).__name__})
        raise


def device_evidence(log, report):
    if sys.platform == 'win32':
        require(report['backend']['backend'] == 'Dx12', 'wrong host/backend pairing')
        return pair.controls.device_evidence(log)
    require(sys.platform.startswith('linux') and report['backend']['backend'] == 'Vulkan', 'wrong host/backend pairing')
    prefix = 'renderer graphics_device_evidence='
    lines = [line[len(prefix):] for line in log.read_text(encoding='utf-8').splitlines() if line.startswith(prefix)]
    require(len(lines) == 1, 'one actual hardware evidence record required')
    evidence = json.loads(lines[0])
    actual = evidence
    require(actual.get('backend') == 'Vulkan' and actual.get('name') == 'NVIDIA A100-SXM4-40GB'
            and actual.get('device_type') == 'DiscreteGpu' and actual.get('vendor_id') == 4318
            and actual.get('device_id') == 8368 and actual.get('force_fallback_requested') is False,
            'actual A100 hardware fingerprint differs')
    return evidence


def run(root, output, build_timeout=1200, process_timeout=900):
    root, output = Path(root).resolve(), Path(output).resolve()
    require(sys.platform in ('win32', 'linux'), 'unsupported native host')
    require(root == Path(__file__).resolve().parents[1], 'runner and source checkout differ')
    require(pair.gpu.positive(build_timeout) and pair.gpu.positive(process_timeout), 'invalid timeouts')
    pair.check_environment(os.environ)
    require(not (root / 'assets/weapons').exists(), 'private weapon assets excluded')
    require(output.is_dir() and not output.is_symlink()
            and {p.name for p in output.iterdir()} == {'materialize.json'}, 'fresh materialization receipt required')
    require((output / 'materialize.json').is_file() and not (output / 'materialize.json').is_symlink(), 'unsafe materialization receipt')
    pair.check_cargo_configuration(root, os.environ)
    source = profile.checked_source(root)
    runtime = matrix.source_identity(root)
    assets = profile.inventory(root / 'assets')
    require('animations.cfg' in assets and 'locomotion/asset.vrs' in assets, 'original companions missing')
    for extra in ([], ['--ignored']):
        require(not pair.git(root, 'ls-files', '--others', '--exclude-standard', *extra, '--', 'examples').strip(),
                'unbound example inputs')
    compiler = pair.toolchain_at(root)
    host = 'x86_64-pc-windows-msvc' if sys.platform == 'win32' else 'x86_64-unknown-linux-gnu'
    require('release: 1.99.0\n' in compiler['rustc'] and 'host: ' + host + '\n' in compiler['rustc']
            and compiler['cargo'].startswith('cargo 1.99.0 '), 'exact native Rust1.99 required')
    receipt = {'source': source, 'runtime': runtime, 'assets_sha256': assets, 'toolchain': compiler,
               'materialize_receipt_sha256': matrix.sha256(output / 'materialize.json')}
    matrix.write_json(output / 'inputs.json', receipt)
    receipt_hash = matrix.sha256(output / 'inputs.json')
    env = dict(os.environ, CARGO_TARGET_DIR=str(output / 'target'), PASS_SUBMISSION_SOURCE_SHA256=receipt_hash)
    executable = output / 'target/debug/examples' / (EXAMPLE + ('.exe' if sys.platform == 'win32' else ''))
    executable_hash = None
    retained = {p: matrix.sha256(p) for p in (output / 'inputs.json', output / 'materialize.json')}
    inventories, directories = {}, {}
    def retain(directory):
        inventories[directory] = pair.controls.source_manifest(directory)
        directories[directory] = pair.directory_manifest(directory)
    def verify():
        require(profile.checked_source(root) == source and matrix.source_identity(root) == runtime
                and profile.inventory(root / 'assets') == assets, 'source/runtime/assets changed')
        pair.check_cargo_configuration(root, os.environ)
        require(pair.toolchain_at(root) == compiler, 'compiler changed')
        require(all(matrix.sha256(p) == h for p, h in retained.items()), 'retained input/process evidence changed')
        if executable_hash:
            require(matrix.sha256(executable) == executable_hash, 'retained executable changed')
        pair.verify_retained_outputs(inventories, {}, directories)
    try:
        logged(['cargo', 'build', '--locked', '--no-default-features', '--features', 'wgpu-runtime',
                '--example', EXAMPLE], root, output / 'build', env, build_timeout)
        executable_hash = matrix.sha256(executable)
        matrix.write_json(output / 'executable.json', {'path': str(executable), 'sha256': executable_hash})
        retain(output / 'build')
        retained[output / 'executable.json'] = matrix.sha256(output / 'executable.json')
        verify()
        logged([str(executable), '--manifest', str(root / 'assets/animations.cfg'), '--output-dir', str(output / 'captures')],
               root, output / 'process', env, process_timeout, executable_hash)
        report = matrix.json_read(output / 'captures/report.json')
        summary = validate_outputs(output / 'captures', report, receipt_hash)
        retain(output / 'process')
        retain(output / 'captures')
        summary['device_evidence'] = device_evidence(output / 'process/stderr.log', report)
        verify()
        summary.update(source_commit=source['commit'], source_receipt_sha256=receipt_hash,
                       executable_sha256=executable_hash)
    except BaseException as error:
        matrix.write_json(output / 'failure.json', {'passed': False, 'error': str(error), 'type': type(error).__name__})
        raise
    finally:
        try:
            verify()
            matrix.write_json(output / 'final-input-check.json', {'passed': True})
        except BaseException as error:
            matrix.write_json(output / 'final-input-check.json', {'passed': False, 'error': str(error)})
            if not (output / 'failure.json').exists():
                matrix.write_json(output / 'failure.json', {'passed': False, 'error': str(error),
                    'type': type(error).__name__, 'stage': 'final-input-check'})
            raise
    matrix.write_json(output / 'summary.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--build-timeout', type=float, default=1200)
    parser.add_argument('--process-timeout', type=float, default=900)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run(args.root, args.output, args.build_timeout, args.process_timeout), indent=2))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

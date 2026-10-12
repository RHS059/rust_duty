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
# Two complete 22-pose command inventories exceed the generic 2 MiB JSON cap.
# Bound only this paired report; camera, process and source JSON keep their limits.
REPORT_MAX_BYTES = 4 * 1024 * 1024
HISTORICAL_PROBE_PIXELS = {
    **{name: [(544,257)] for name in ('ready-0','ready-1','ready-3','manifest-0','manifest-12','manifest-24')},
    'walk-0':[(561,238)],'walk-3':[(561,238)],'walk-1':[(551,253)],
    'ads-1':[(546,246),(547,246),(519,261),(519,263)],
    'reload-1':[(508,233),(510,233),(524,233),(524,234),(505,270)],
}
STATS = tuple(name.removeprefix('resident_') for name in detail.COUNTERS_V3[len(detail.COUNTERS_V2):])
require = authored.require


def read_report(path):
    return matrix.json_read(path, limit=REPORT_MAX_BYTES)


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
    require(read_report(directory / 'report.json') == report, 'retained report changed')
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


def validate_probe_parent(report, receipt_sha256):
    """Validate a complete image report structurally, retaining pixel failure.

    The original strict validator still owns acceptance. This helper permits
    only bounded numerical pixel differences for diagnostic replay; all source,
    pose, command, corner, path, resource and visibility predicates still apply.
    It never changes the caller's report or returns a passed verdict.
    """
    require(isinstance(report,dict) and type(report.get('passed')) is bool,
            'vertex probe parent verdict must be boolean')
    cases=report.get('cases')
    require(isinstance(cases,list) and all(isinstance(c,dict) for c in cases)
            and [c.get('name') for c in cases] == authored.CASE_NAMES,
            'vertex probe parent case inventory differs')
    exact=True
    for case in cases:
        count,delta=case.get('differing_pixels'),case.get('maximum_channel_delta')
        require(type(count) is int and 0<=count<=authored.EXTENT[0]*authored.EXTENT[1]
                and type(delta) is int and 0<=delta<=255 and (count==0)==(delta==0),
                'vertex probe parent pixel metrics invalid')
        exact=exact and count==0
    require(report['passed'] is exact, 'vertex probe parent pixel verdict contradicts metrics')
    structural=copy.deepcopy(report)
    structural['passed']=True
    for case in structural['cases']:
        case.update(differing_pixels=0,maximum_channel_delta=0)
    validate_report(structural,receipt_sha256)
    return report


def validate_vertex_probe(directory, report, receipt_sha256, root):
    """Strict provenance/shape/completeness only; arithmetic deltas are retained."""
    directory, root = Path(directory), Path(root)
    validate_probe_parent(report,receipt_sha256)
    require(authored.digest_string(receipt_sha256), 'vertex probe source receipt digest invalid')
    require(report.get('source_receipt_sha256') == receipt_sha256,
            'vertex probe parent source receipt differs')
    require(isinstance(report.get('cases'),list)
            and all(isinstance(c,dict) for c in report['cases'])
            and [c.get('name') for c in report['cases']] == authored.CASE_NAMES,
            'vertex probe parent case inventory differs')
    expected = {'probe-result.json'} | {name + '.json' for name in authored.CASE_NAMES}
    require(directory.is_dir() and not directory.is_symlink()
            and {p.name for p in directory.iterdir()} == expected
            and all(p.is_file() and not p.is_symlink() for p in directory.iterdir()),
            'vertex probe output inventory differs')
    result = matrix.json_read(directory / 'probe-result.json')
    require(isinstance(result,dict) and result.get('schema') == 'rust-duty-resident-vertex-probe-result/v1'
            and result.get('source_receipt_sha256') == receipt_sha256
            and result.get('image_gate_passed') is report.get('passed')
            and type(result.get('image_gate_passed')) is bool
            and result.get('probe_completed') is True and result.get('errors') == [],
            'vertex probe did not complete or parent verdict differs')
    def uint(value, maximum=2**32-1):
        return type(value) is int and 0 <= value <= maximum
    totals = dict(selected_vertices=0, current_clip_differences=0, current_color_differences=0,
                  historical_clip_differences=0, historical_color_differences=0,
                  normalization_clip_differences=0, normalization_color_differences=0)
    shader_paths = {'production_resident_shader_sha256':'src/render/resident.wgsl',
                    'production_cpu_shader_sha256':'src/render/mesh.wgsl',
                    'probe_implementation_sha256':'src/render/resident_vertex_probe.rs'}
    for case in report['cases']:
        value = matrix.json_read(directory / (case['name'] + '.json'))
        require(isinstance(value,dict) and value.get('schema') == 'rust-duty-resident-vertex-probe/v1'
                and value.get('case') == case['name'] and value.get('metadata') == case['metadata']
                and value.get('source_receipt_sha256') == receipt_sha256
                and value.get('camera_bits') == report['camera']['view_projection_bits'],
                'vertex probe source/case/camera differs')
        require(all(value.get(key) == matrix.sha256(root / path) for key,path in shader_paths.items()),
                'vertex probe shader or implementation bytes differ')
        require(value.get('selection_complete') is True
                and uint(value.get('changed_pixel_count'), 960*540)
                and value['changed_pixel_count'] == case['differing_pixels']
                and type(value.get('selection_limit_pixels')) is int and value['selection_limit_pixels'] == 16
                and type(value.get('selection_limit_triangles_per_pixel')) is int
                and value['selection_limit_triangles_per_pixel'] == 2
                and type(value.get('changed_pixels_not_selected')) is int and value['changed_pixels_not_selected'] == 0
                and type(value.get('requested_pixels_without_triangle')) is int and value['requested_pixels_without_triangle'] == 0,
                'vertex probe selection incomplete or counters differ')
        pixels, draws = value.get('pixels'), value.get('draws')
        require(isinstance(pixels,list) and len(pixels)<=16 and isinstance(draws,list)
                and len(draws)<=32 and value['changed_pixel_count'] <= len(pixels),
                'vertex probe selection bounds differ')
        require(type(value.get('representative_probe_shader_count')) is int
                and value['representative_probe_shader_count'] == 3
                and all(value.get(key) == pair.controls.digest(vertex_probe_shader(root,route,'skin',3).encode('utf-8'))
                        for route,key in (('current','current_skin_probe_shader_sha256'),
                                          ('historical','historical_skin_probe_shader_sha256'))),
                'representative vertex probe shader identity differs')
        selected, seen_pixels, selected_order = set(), set(), {}
        for pixel in pixels:
            require(isinstance(pixel,dict), 'vertex probe pixel must be an object')
            point, triangles = pixel.get('pixel'), pixel.get('triangles')
            require(isinstance(point,list) and len(point)==2 and uint(point[0],959) and uint(point[1],539)
                    and tuple(point) not in seen_pixels and isinstance(triangles,list)
                    and 1<=len(triangles)<=2, 'invalid/duplicate/uncovered probe pixel')
            seen_pixels.add(tuple(point))
            hit_order, hit_ids = [], set()
            for triangle in triangles:
                require(isinstance(triangle,dict), 'vertex probe triangle must be an object')
                command, corner = triangle.get('command'), triangle.get('corner')
                require(uint(command,len(case['cpu_commands'])-1) and uint(corner)
                        and corner%3==0 and corner+3<=case['cpu_commands'][command]['indices']
                        and type(triangle.get('cpu_depth')) in (int,float),
                        'vertex probe triangle range/type differs')
                require((command,corner) not in hit_ids, 'duplicate probe triangle')
                hit_ids.add((command,corner))
                hit_order.append((triangle['cpu_depth'],command,corner))
                selected.add((command,corner))
                order=selected_order.setdefault(command,[])
                if corner not in order: order.append(corner)
            require(hit_order == sorted(hit_order), 'probe triangle depth/order differs')
        require(set(HISTORICAL_PROBE_PIXELS.get(case['name'],())) <= seen_pixels,
                'historically requested vertex probe pixels are absent')
        actual, command_ids = set(), []
        for draw in draws:
            require(isinstance(draw,dict), 'vertex probe draw must be an object')
            command, corners, count = draw.get('command'), draw.get('triangle_corner_offsets'), draw.get('vertex_count')
            require(uint(command,len(case['cpu_commands'])-1) and command not in command_ids
                    and isinstance(corners,list) and corners and all(uint(v) for v in corners)
                    and len(corners)==len(set(corners)) and corners==selected_order.get(command)
                    and uint(count,384) and count==len(corners)*3
                    and draw.get('kind') in ('skin','rigid'), 'vertex probe draw selection differs')
            command_ids.append(command)
            actual.update((command,corner) for corner in corners)
            for key in ('cpu_model_bits','resident_model_bits'):
                words=draw.get(key)
                require(isinstance(words,list) and len(words)==16 and all(uint(v) for v in words),
                        'vertex probe matrix words invalid')
            for route,key in (('cpu','cpu_probe_shader_sha256'),('current','current_probe_shader_sha256'),
                              ('historical','historical_probe_shader_sha256')):
                expected_source = vertex_probe_shader(root,route,draw['kind'],count)
                require(draw.get(key) == pair.controls.digest(expected_source.encode('utf-8')),
                        'vertex probe generated shader identity differs')
            routes=[]
            for key in ('cpu_vertex_stage','current_vertex_stage','historical_inverse_sqrt_vertex_stage'):
                samples=draw.get(key)
                require(isinstance(samples,list) and len(samples)==count,'vertex probe sample count differs')
                parent = case['cpu_commands' if key=='cpu_vertex_stage' else 'resident_commands'][command]
                for sample in samples:
                    require(isinstance(sample,dict) and set(sample)=={'source_vertex','clip_bits','color_bits'}
                            and uint(sample['source_vertex'],parent['stored_vertices']-1)
                            and all(isinstance(sample[k],list) and len(sample[k])==4
                                    and all(uint(v) for v in sample[k]) for k in ('clip_bits','color_bits'))
                            and sample['color_bits'] != [2**32-1]*4,
                            'vertex probe sample words invalid or unwritten')
                routes.append(samples)
            for cpu,current,historical in zip(*routes):
                require(current['source_vertex']==historical['source_vertex'], 'resident probe vertex order differs')
                totals['selected_vertices']+=1
                for key,field in (('clip','clip_bits'),('color','color_bits')):
                    totals[f'current_{key}_differences']+=cpu[field]!=current[field]
                    totals[f'historical_{key}_differences']+=cpu[field]!=historical[field]
                    totals[f'normalization_{key}_differences']+=current[field]!=historical[field]
        require(command_ids==sorted(command_ids) and actual==selected,
                'vertex probe selected triangles are missing/extra/reordered')
    return {'schema':'rust-duty-resident-vertex-probe-summary/v1', 'diagnostic_completed':True,
            'image_gate_passed':report['passed'], **totals,
            'scope':'instrumented vertex-stage differences only; strict original pixel verdict is unchanged'}


def vertex_probe_shader(root, route, kind, count):
    root=Path(root)
    require(route in ('cpu','current','historical') and kind in ('rigid','skin')
            and type(count) is int and 1<=count<=384,'invalid probe shader selection')
    source=(root/'src/render/resident.wgsl').read_text(encoding='utf-8')
    current='let reciprocal = 1.0 / sqrt(length_squared);'
    historical='let reciprocal = inverseSqrt(length_squared);'
    require(source.count(current)==1 and historical not in source,'probe normalization source changed')
    if route=='cpu':
        source=(root/'src/render/mesh.wgsl').read_text(encoding='utf-8').replace('@vertex fn vs_main','fn original_vs_main')
        input_name,entry='VertexInput','original_vs_main'
    else:
        if route=='historical': source=source.replace(current,historical,1)
        source=source.replace('@vertex fn vs_rigid','fn original_vs_rigid').replace('@vertex fn vs_skin','fn original_vs_skin')
        input_name,entry=('SkinInput','original_vs_skin') if kind=='skin' else ('RigidInput','original_vs_rigid')
    template=(root/'src/render/resident_vertex_probe.wgsl').read_text(encoding='utf-8')
    require(all(template.count(token)==1 for token in ('__INPUT__','__ENTRY__','__COUNT__')),
            'probe shader template substitution differs')
    return source+'\n'+template.replace('__INPUT__',input_name).replace('__ENTRY__',entry).replace('__COUNT__',str(count))


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


def run(root, output, build_timeout=1200, process_timeout=900, vertex_probe=False):
    root, output = Path(root).resolve(), Path(output).resolve()
    require(sys.platform in ('win32', 'linux'), 'unsupported native host')
    require(type(vertex_probe) is bool, 'vertex probe opt-in must be boolean')
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
        command = [str(executable), '--manifest', str(root / 'assets/animations.cfg'), '--output-dir', str(output / 'captures')]
        if vertex_probe:
            command += ['--vertex-probe-dir', str(output / 'vertex-probe')]
        logged(command,
               root, output / 'process', env, process_timeout, executable_hash)
        report = read_report(output / 'captures/report.json')
        summary = validate_outputs(output / 'captures', report, receipt_hash)
        retain(output / 'process')
        retain(output / 'captures')
        if vertex_probe:
            retain(output / 'vertex-probe')
            summary['vertex_probe'] = validate_vertex_probe(output / 'vertex-probe', report, receipt_hash, root)
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
    parser.add_argument('--vertex-probe', action='store_true')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run(args.root, args.output, args.build_timeout, args.process_timeout, args.vertex_probe), indent=2))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

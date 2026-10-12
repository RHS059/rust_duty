#!/usr/bin/env python3
"""Exact two-loader counterfactual with original companion-backed DX12 captures.

This gate checks CPU-expanded corners and native pixels. Its baseline-derived
common overview camera is not an authored gameplay visibility acceptance rule.
"""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import struct
import sys

from PIL import Image
import performance_matrix as matrix
import run_cpu_image_preservation as pair
import run_windows_cpu_profile as profile
import run_pass_submission_benchmark as controls
import run_renderer_contract as renderer
import dx12_contract_process as process

SCHEMA = 'rust-duty-authored-loader-contract/v1'
EXAMPLE = 'authored_loader_contract'
EXAMPLES = (*pair.EXAMPLES, EXAMPLE)
HARNESS_PATHS = [f'examples/{name}.rs' for name in EXAMPLES]
CASE_NAMES = [f'{clip}-{index}' for clip in ('ready', 'walk', 'ads', 'reload') for index in range(4)] + \
             ['manifest-0', 'manifest-12', 'manifest-24', 'rigid-alpha-0', 'rigid-alpha-1', 'rigid-alpha-2']
EXTENT = [960, 540]


def require(value, message):
    if not value:
        raise ValueError(message)


def integer(value, low=0, high=4_000_000):
    return type(value) is int and low <= value <= high


def digest_string(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def float_word(word):
    require(integer(word, 0, 2**32-1), 'invalid float word')
    value = struct.unpack('<f', struct.pack('<I', word))[0]
    require(math.isfinite(value) and value >= 0, 'negative/nonfinite time')
    return value


def validate_report(report, receipt_sha256, native=True):
    require(isinstance(report, dict) and report.get('schema') == SCHEMA, 'wrong loader report schema')
    require(digest_string(receipt_sha256) and report.get('source_receipt_sha256') == receipt_sha256,
            'loader compiled source receipt differs')
    require(report.get('native_images') is native, 'loader native/prepare mode differs')
    camera = report.get('camera', {})
    require(isinstance(camera, dict), 'invalid camera object')
    words = camera.get('view_projection_bits', [])
    require(camera.get('extent') == EXTENT and isinstance(words,list) and len(words) == 16 and all(integer(x, 0, 2**32-1) for x in words),
            'loader camera extent/words differ')
    require(all(abs(struct.unpack('<f', struct.pack('<I', x))[0]) < float('inf') for x in words),
            'nonfinite camera matrix')
    cases = report.get('cases', [])
    require(isinstance(cases, list) and all(isinstance(c,dict) for c in cases) and [c.get('name') for c in cases] == CASE_NAMES, 'loader case inventory differs')
    for case in cases:
        commands = case.get('commands', [])
        require(isinstance(commands, list) and 0 < len(commands) <= 2048, 'empty/unbounded command inventory')
        for command in commands:
            require(isinstance(command,dict), 'invalid loader command object')
            require(set(command) == {'model_bits', 'blend', 'texture', 'stored_vertices', 'indices', 'expanded_sha256'},
                    'loader command fields differ')
            require(integer(command['stored_vertices'], 1, 4998) and integer(command['indices'], 3, 4998)
                    and command['indices'] % 3 == 0 and command['stored_vertices'] <= command['indices'], 'invalid loader vertex/index counts')
            require(digest_string(command['expanded_sha256']) and command['blend'] == 'Alpha', 'invalid expanded corners/blend')
            model = command['model_bits']
            require(isinstance(model, list) and len(model) == 16 and all(integer(x, 0, 2**32-1) for x in model),
                    'invalid model matrix bits')
            require(all(abs(struct.unpack('<f', struct.pack('<I', x))[0]) < float('inf') for x in model), 'nonfinite model')
            texture = command['texture']
            require(texture is None or isinstance(texture, dict) and
                    set(texture) == {'width','height','filter','wrap_x','wrap_y','rgba_sha256'} and
                    integer(texture['width'],1,16384) and integer(texture['height'],1,16384) and
                    texture['filter'] == 'Linear' and texture['wrap_x'] == texture['wrap_y'] == 'Repeat' and
                    digest_string(texture['rgba_sha256']), 'invalid loader texture identity')
        require(sum(c['indices'] for c in commands) <= 4_000_000, 'unbounded expanded corners')
        name, metadata = case['name'], case.get('metadata', {})
        require(isinstance(metadata,dict), 'invalid case metadata')
        if name.startswith('manifest-'):
            require(metadata.get('route') == 'load_manifest/committed_step/draw'
                    and integer(metadata.get('fixed_steps'), 0, 24) and metadata['fixed_steps'] == int(name.split('-')[-1])
                    and integer(metadata.get('simulation_time_bits'),0,2**64-1), 'manifest route differs')
            sim_time = struct.unpack('<d', struct.pack('<Q', metadata['simulation_time_bits']))[0]
            require(isinstance(metadata.get('warning'),str) and
                    metadata['warning'].startswith('Authored WIP: ') and
                    0 < len(metadata['warning'].encode('utf-8')) <= 512,
                    'manifest WIP notice missing or unbounded')
            dt=struct.unpack('<f',struct.pack('<f',1/120))[0]
            expected_time=sum(dt for _ in range(metadata['fixed_steps']))
            require(math.isfinite(sim_time) and sim_time == expected_time, 'manifest time differs from fixed steps')
        elif name.startswith('rigid-alpha-'):
            require(metadata == {'route':'draw_authored_parts', 'alpha': [0.5,0.25,0.5][int(name[-1])]}, 'rigid alpha control differs')
        else:
            require(metadata.get('route') == 'load/draw' and isinstance(metadata.get('clip'),str)
                    and bool(metadata['clip']) and integer(metadata.get('fraction_tenths'), 0, 9)
                    and metadata['fraction_tenths'] == [0,5,9,0][int(name[-1])]
                    and integer(metadata.get('duration_bits'),1,2**32-1)
                    and integer(metadata.get('time_bits'),0,2**32-1) and type(metadata.get('cant_bits')) is int and metadata['cant_bits'] == 0,
                    'fixed clip route differs')
            duration = float_word(metadata['duration_bits'])
            actual_time = float_word(metadata['time_bits'])
            fraction = struct.unpack('<f', struct.pack('<f', metadata['fraction_tenths']/10))[0]
            require(duration > 0 and actual_time == struct.unpack('<f', struct.pack('<f', duration*fraction))[0],
                    'clip time does not match its fixed fraction')
    require(len({case['metadata']['warning'] for case in cases[16:19]}) == 1,
            'idle manifest WIP notice changed')
    for start in (0,4,8,12):
        quartet=[case['metadata'] for case in cases[start:start+4]]
        require(len({row['clip'] for row in quartet}) == 1 and
                len({row['duration_bits'] for row in quartet}) == 1, 'same-instance clip/duration changed')
    for a,b in ((0,3),(4,7),(8,11),(12,15),(19,21)):
        require(cases[a]['commands'] == cases[b]['commands'], 'same-instance revisit changed output')
    counts = report.get('source_counts', {})
    require(isinstance(counts,dict), 'invalid source counts object')
    require(set(counts) == {'ready','walk','ads','reload'}, 'source mesh inventory differs')
    duplicate_vertices = 0
    for group in counts.values():
        require(isinstance(group,dict), 'invalid source mesh group')
        require(set(group) == {'skin','rigid'}, 'source actor classes differ')
        for meshes in group.values():
            require(isinstance(meshes,list) and 0 < len(meshes) <= 4096, 'source mesh list empty/unbounded')
            for row in meshes:
                require(isinstance(row,dict), 'invalid source mesh count')
                require(set(row) == {'old_vertices','deduplicated_vertices','indices'} and
                        all(integer(row[k], 1) for k in row) and row['indices'] % 3 == 0
                        and row['deduplicated_vertices'] <= row['old_vertices'] <= row['indices'],
                        'source vertex-count oracle is inconsistent')
                duplicate_vertices += row['old_vertices'] - row['deduplicated_vertices']
    require(duplicate_vertices > 0, 'original assets do not exercise any exact duplicate vertices')
    return report


def semantic_case(case):
    value = copy.deepcopy(case)
    for command in value['commands']:
        command.pop('stored_vertices')
    return value


def compare_reports(baseline, candidate):
    require(baseline['camera'] == candidate['camera'], 'common camera changed')
    require(baseline['source_counts'] == candidate['source_counts'], 'original source vertex inventory changed')
    require([semantic_case(c) for c in baseline['cases']] == [semantic_case(c) for c in candidate['cases']],
            'ordered expanded corners/material/model/pose changed')
    old = new = 0
    for a,b in zip(baseline['cases'],candidate['cases']):
        for x,y in zip(a['commands'],b['commands']):
            require(y['stored_vertices'] <= x['stored_vertices'], 'stored vertex count increased')
            old += x['stored_vertices']; new += y['stored_vertices']
    require(new < old, 'actual loaded/drawn vertex count did not decrease')
    return {'baseline_stored_vertices':old, 'candidate_stored_vertices':new,
            'reduced_vertices':old-new, 'ordered_expanded_commands_equal':True, 'cases':len(CASE_NAMES)}


def validate_outputs(directory, report):
    directory = Path(directory)
    require(matrix.json_read(directory/'report.json') == report, 'retained report differs')
    native = report['native_images']
    expected = {'report.json','camera.json'} | {name+'.corners.bin' for name in CASE_NAMES}
    if native: expected |= {name+'.png' for name in CASE_NAMES}
    require(set(pair.controls.source_manifest(directory)) == expected, 'loader output inventory is not exact')
    require(matrix.json_read(directory/'camera.json') == report['camera'], 'retained camera differs')
    evidence = {}
    for case in report['cases']:
        raw = (directory/(case['name']+'.corners.bin')).read_bytes()
        offset = 0
        for command in case['commands']:
            length = command['indices']*40
            require(controls.digest(raw[offset:offset+length]) == command['expanded_sha256'], 'raw expanded corner bytes differ')
            offset += length
        require(offset == len(raw), 'expanded corner file length differs')
        if native:
            with Image.open(directory/(case['name']+'.png')) as image:
                require(image.mode == 'RGBA' and list(image.size) == EXTENT, 'native image format differs')
                data=image.tobytes()
            pixels=list(zip(*(iter(data),)*4))
            require(all(p[3] == 255 for p in pixels), 'native display alpha is not opaque')
            # Exact clear color is fixed in the fixture; corner pixel cannot choose the predicate.
            foreground=sum(p[:3] != (8,16,24) for p in pixels)
            require(foreground >= 100, 'diagnostic overview is empty or too small')
            require(len(set(pixels)) >= 8, 'diagnostic image lacks material/shading variation')
            evidence[case['name']]={'rgba_sha256':controls.digest(data),'foreground_pixels':foreground}
    return evidence


def compare_images(a,b):
    require(a == b and len(a) == len(CASE_NAMES), 'native RGBA or foreground pixels differ')
    return {'exact_rgba_pairs':len(a),'zero_tolerance':True}


def run(root, output, build_timeout=1200, process_timeout=600):
    require(pair.gpu.positive(build_timeout) and pair.gpu.positive(process_timeout), 'timeouts must be finite and positive')
    require(sys.platform == 'win32', 'native Windows DX12 is required')
    root,output=Path(root).resolve(),Path(output).resolve()
    require(root == Path(__file__).resolve().parents[1], 'runner and checkout differ')
    pair.check_environment(os.environ)
    require(output.is_dir() and not output.is_symlink() and
            {p.name for p in output.iterdir()} == {'materialize.json'} and
            (output/'materialize.json').is_file() and not (output/'materialize.json').is_symlink(),
            'output must contain only the fresh companion materialization receipt')
    for extra in ([], ['--ignored']):
        require(not pair.git(root, 'ls-files', '--others', '--exclude-standard', *extra, '--', 'examples').strip(),
                'untracked/ignored example source is not permitted')
    require(not (root/'assets/weapons').exists(), 'private weapon asset inputs are excluded')
    pair.check_cargo_configuration(root, os.environ)
    source=profile.checked_source(root)
    assets=profile.inventory(root/'assets')
    require('animations.cfg' in assets and 'locomotion/asset.vrs' in assets, 'original companions missing')
    compiler=pair.toolchain_at(root)
    require('release: 1.99.0\n' in compiler['rustc'] and 'host: x86_64-pc-windows-msvc\n' in compiler['rustc']
            and compiler['cargo'].startswith('cargo 1.99.0 '), 'pinned Rust1.99 MSVC required')
    production=pair.read_sources(root,source['commit'],pair.PRODUCTION_PATHS)
    harness=pair.read_sources(root,source['commit'],HARNESS_PATHS)
    require(set(harness)==set(HARNESS_PATHS), 'all three native fixtures required')
    require(all((root/name).read_bytes()==raw for name,raw in {**production,**harness}.items()),'committed inputs differ')
    variants=pair.loader_production_pair(production,pair.read_sources(root,pair.LOADER_BASELINE_COMMIT,sorted(pair.LOADER_BASELINE)))
    variants={label:{**data,**harness} for label,data in variants.items()}
    binding={'source_commit':source['commit'],'profile_source':source}
    receipts=pair.materialize_variants(output/'sources',variants,binding,pair.experiment_metadata('authored-dedup'))
    matrix.write_json(output/'inputs.json',{'source':source,'assets_sha256':assets,'toolchain':compiler,
                      'materialize_receipt_sha256':matrix.sha256(output/'materialize.json')})
    retained={output/name:matrix.sha256(output/name) for name in ('inputs.json','materialize.json')}
    binaries,outputs,directories,devices={}, {}, {}, []
    def verify():
        require(profile.checked_source(root)==source and profile.inventory(root/'assets')==assets,'source/assets changed')
        pair.verify_sources(receipts)
        pair.verify_retained_outputs(outputs,binaries,directories)
        require(all(matrix.sha256(p)==h for p,h in retained.items()),'retained input/process receipt changed')
        require(pair.toolchain_at(root)==compiler,'root compiler changed')
        for receipt in receipts.values():
            pair.check_cargo_configuration(receipt['source'],os.environ)
            require(pair.toolchain_at(receipt['source'])==compiler,'variant compiler changed')
    def retain(directory):
        outputs[directory]=controls.source_manifest(directory);directories[directory]=pair.directory_manifest(directory)
    try:
        for label,receipt in receipts.items():
            verify()
            target=output/(label+'-target')
            env=dict(os.environ,CARGO_TARGET_DIR=str(target),CARGO_INCREMENTAL='0',CARGO_PROFILE_DEV_DEBUG='0',
                     CARGO_PROFILE_DEV_OPT_LEVEL='2',CARGO_BUILD_JOBS='2',PASS_SUBMISSION_SOURCE_SHA256=receipt['receipt_sha256'])
            command=['cargo','build','--locked','--no-default-features','--features','wgpu-runtime']
            for name in EXAMPLES: command += ['--example',name]
            pair.logged(command,receipt['source'],output/(label+'-build'),env,build_timeout)
            retain(output/(label+'-build'))
            binaries[label]={name:{'path':str(target/'debug/examples'/(name+'.exe')),
                                  'sha256':matrix.sha256(target/'debug/examples'/(name+'.exe'))} for name in EXAMPLES}
            matrix.write_json(output/(label+'-build.json'),{'command':command,'settings':{k:env[k] for k in (
                'CARGO_TARGET_DIR','CARGO_INCREMENTAL','CARGO_PROFILE_DEV_DEBUG','CARGO_PROFILE_DEV_OPT_LEVEL',
                'CARGO_BUILD_JOBS','PASS_SUBMISSION_SOURCE_SHA256')},'compiler':compiler,'executables':binaries[label],
                'source_receipt_sha256':receipt['receipt_sha256']})
            retained[output/(label+'-build.json')]=matrix.sha256(output/(label+'-build.json'))
            verify()
        reports,images={},{}
        def execute(label,name,destination,extra):
            verify();binary=binaries[label][name]
            log=output/(destination+'-process');directory=output/destination
            pair.logged([binary['path'],*extra,'--output-dir',str(directory)],receipts[label]['source'],log,
                        dict(os.environ),process_timeout,binary['sha256'])
            retain(log);retain(directory);verify();return directory,log
        prepare,_=execute('baseline',EXAMPLE,'camera-prepare',['--manifest',str(root/'assets/animations.cfg')])
        original=validate_report(matrix.json_read(prepare/'report.json'),receipts['baseline']['receipt_sha256'],False)
        validate_outputs(prepare,original)
        for label in ('baseline','candidate'):
            # Keep the fixture's ordered arguments explicit; --camera is a suffix.
            binary=binaries[label][EXAMPLE];directory=output/(label+'-authored');log=output/(label+'-authored-process')
            pair.logged([binary['path'],'--manifest',str(root/'assets/animations.cfg'),'--output-dir',str(directory),
                         '--camera',str(prepare/'camera.json')],receipts[label]['source'],log,dict(os.environ),
                        process_timeout,binary['sha256'])
            process.validate_renderer_log(log);devices.append(controls.device_evidence(log/'stderr.log'))
            reports[label]=validate_report(matrix.json_read(directory/'report.json'),receipts[label]['receipt_sha256'])
            images[label]=validate_outputs(directory,reports[label]);retain(directory);retain(log);verify()
            for name in pair.EXAMPLES:
                extra=['--renderer=dx12','--force-fallback-adapter'] if name=='renderer_contract' else []
                directory,log=execute(label,name,label+'-'+name,extra)
                process.validate_renderer_log(log);devices.append(controls.device_evidence(log/'stderr.log'))
                if name=='renderer_contract': require(renderer.validate_outputs(directory)['passed'],'original21 image validator failed')
                else: controls.validate_report(matrix.json_read(directory/'report.json'),receipts[label]['receipt_sha256'])
        require(original['cases']==reports['baseline']['cases'] and original['camera']==reports['baseline']['camera']
                and original['source_counts']==reports['baseline']['source_counts'],'baseline camera preparation output changed')
        semantic=compare_reports(reports['baseline'],reports['candidate'])
        pixels=compare_images(images['baseline'],images['candidate'])
        fixed=controls.contract_pixels(output/'baseline-renderer_contract',output/'candidate-renderer_contract')
        mixed=controls.exact_pixels([output/(label+'-pass_submission_benchmark')/name
                                    for label in ('baseline','candidate') for name in ('before.png','after.png')])
        device=controls.require_same_devices(devices);verify()
        authored_archives={}
        authored_names={'camera-prepare','baseline-authored','candidate-authored'}
        for name in sorted(authored_names):
            path=output/name
            authored_archives[name]=pair.archive_control_outputs(output,{path:outputs[path]},
                {path:directories[path]},filename=name+'-outputs.zip')
            retained[output/authored_archives[name]['file']]=authored_archives[name]['sha256']
        original={p:files for p,files in outputs.items() if p.name not in authored_names}
        archive=pair.archive_control_outputs(output,original,{p:directories[p] for p in original})
        retained[output/archive['file']]=archive['sha256'];verify()
        result={'schema':'rust-duty-authored-loader-pair/v1','passed':True,'experiment':'authored-dedup',
                'source_commit':source['commit'],'device':device,'semantic':semantic,'pixels':pixels,
                'fixed':fixed,'mixed':mixed,'control_outputs_archive':archive,
                'authored_outputs_archives':authored_archives,'executables':binaries,
                'control_output_files_sha256':{str(p.relative_to(output)):v for p,v in outputs.items()},
                'performance_improvement':None,'authored_gameplay_visibility_accepted':False,
                'scope':'deterministic original-companion loader/draw parity with a common diagnostic overview'}
        matrix.write_json(output/'summary.json',result);return result
    except BaseException as error:
        matrix.write_json(output/'failure.json',{'passed':False,'error':str(error),'type':type(error).__name__});raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('.'));parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--build-timeout',type=float,default=1200);parser.add_argument('--process-timeout',type=float,default=600)
    args=parser.parse_args()
    try: print(json.dumps(run(args.root,args.output,args.build_timeout,args.process_timeout),allow_nan=False));return 0
    except (ValueError,OSError) as error: print('authored-loader-pair: '+str(error),file=sys.stderr);return 1


if __name__=='__main__': raise SystemExit(main())

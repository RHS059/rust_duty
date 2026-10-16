#!/usr/bin/env python3
"""Admit only real, explicitly hash-pinned new256 assets and successful focus proof.

Read-only by default. --accept writes a new immutable candidate.json only after
all actual bytes, process receipts, producer recipes and strict representation
measurements validate. No Blender, runtime sampler, render, build or deletion.
"""
import argparse
from types import SimpleNamespace
from pathlib import Path
import sys
sys.dont_write_bytecode=True
from onehand_r2_common import *
import verify_onehand_r2 as parity
import window_admission as window
import conversion_admission as conversion


def validate_focus(value,fbx_sha,focus_grid_sha,oracle_sha,receipt_sha):
    for field,expected in {'source_sha256':SOURCE_SHA,'fbx_sha256':fbx_sha,'sample_grid_sha256':focus_grid_sha,
                          'independent_grid_sha256':GRID_SHA,'sample_frames':FOCUS_FRAMES,'samples':9,
                          'skin_vertex_samples':92106,'source_oracle_sha256':oracle_sha,
                          'source_receipt_sha256':receipt_sha,'source_total_bones_including_helpers':148,
                          'runtime_support_verified':False,'camera_included_and_measured':True,
                          'camera_relative_geometry_measured':True,'subframe_parity':True,'passed':True}.items():
        exact(value.get(field),expected,'fullcandidate focus '+field)
    checks=value.get('checks',{})
    require(set(parity.FBX_CHECKS)<=set(checks) and all(v is True for v in checks.values()),'focus check missing/failed')
    require(set(value.get('maxima',{}))==set(parity.FBX_KEYS),'focus matrix/skin maxima missing')
    for key,number in value['maxima'].items():require(0<=finite_number(number,key)<LIMIT,'focus unchanged threshold exceeded')
    require(0<=finite_number(value.get('camera_projection_ray_error'),'focus rays')<RAY_LIMIT,'focus ray threshold exceeded')
    window.validate_window(value.get('window_admission',{}),fbx_sha,FOCUS_FRAMES)
    require(value.get('window_recipe_pins_sha256')==sha(window.WINDOW/'pins.json'),'focus window recipe differs')
    require(value.get('full_import_control_receipt_sha256')==sha(window.CONTROL),'focus bounded/full control identity differs')
    require(value.get('off_key_source_frames')==FOCUS_FRAMES[1::2],'four focus512 midpoints must remain measured')
    require(value.get('proof_scope')=='focused-nine-time-key-and-offkey','focus proof scope differs')
    return value


def validate_native_process(record,label,pins_sha):
    command=record.get('command',[]);require(command,'native proof command absent')
    base=[command[0],'--background','--factory-startup','--disable-autoexec','--threads','1']
    source=str(ROOT/'recovery/onehand-camera-solve-v6/candidate-v1/onehand-r6-camera-reconstructed-v6.blend')
    if label=='export':
        require(record.get('completed') is True and record.get('timed_out') is False,'required export incomplete/timed out')
        require(record.get('pins_sha256')==pins_sha,'native export recipe identity differs')
        expected=base+[source,'--python-exit-code','1','--python',str(WORK/'native-dense/export_and_verify.py'),'--','export','--output-dir',str(safe_output('dense-output-v1'))]
    else:
        window.validate_resource_process(record)
        require(record.get('window_recipe_pins_sha256')==pins_sha,'native window recipe identity differs')
        if label=='focus_source':
            expected=base+[source,'--python-exit-code','1','--python',str(window.WINDOW/'sample_source.py'),'--','focus-sample','--output-dir',str(safe_output(window.FOCUS_OUTPUT)),'--dense-dir',str(safe_output('dense-output-v1'))]
        else:
            require(label in ('focus_fbx','control'),'invalid native proof stage')
            mode='control' if label=='control' else 'focus'
            expected=base+['--python-exit-code','1','--python',str(window.WINDOW/'verify_window.py'),'--',mode]
    require(command==expected,'native proof command mode/script/new-root inputs differ')
    require(record.get('owner_lock')==str(ROOT/'native-owner.lock'),'native proof owner lock differs')
    return record


def pinned_producer(path,expected):
    pin(path,expected);metadata=read(path)
    result={str(Path(path).relative_to(ROOT)):parity.file_record(path)}
    require(metadata.get('files'),'producer pin file list missing')
    for relative,digest_value in metadata['files'].items():
        actual=bounded(ROOT,relative);pin(actual,digest_value)
        result[relative]=parity.file_record(actual)
    for absolute,digest_value in metadata.get('installed_files',{}).items():
        actual=Path(absolute)
        require(actual.is_absolute() and not actual.is_symlink(),'official installed recipe path differs')
        pin(actual,digest_value);result[absolute]=parity.file_record(actual)
    return result


PIN_ARGUMENTS=('fbx','vra','vrs','vrm','manifest','focus','native-pins','window-pins','control','conversion-pins','rigid-pins')


def build_candidate(args,*,decode_runtime=True):
    candidate_spec()
    given={'fbx':args.fbx_sha256,'asset.vra':args.vra_sha256,'asset.vrs':args.vrs_sha256,
           'asset.vrm':args.vrm_sha256,'manifest':args.manifest_sha256}
    assets={}
    for name,relative in ASSET_PATHS.items():
        path=safe_output(relative);pin(path,given[name]);assets[name]=parity.file_record(path)
    dense=safe_output('dense-output-v1');focus=safe_output(window.FOCUS_OUTPUT)
    export=parity.validate_export(dense/'export-receipt.json',given['fbx'],[1.,96.],'export',None)
    parity.source_index(dense/'source-samples.json',[1.,96.])
    focus_grid=safe_output('native-dense/focus-times.json')
    exact(read(focus_grid),FOCUS_FRAMES,'independent nine-time focus grid')
    pin(window.CONTROL,args.control_sha256)
    window.validate_control(read(window.CONTROL),args.window_pins_sha256)
    pin(focus/'fresh-import-parity.json',args.focus_sha256)
    value=validate_focus(read(focus/'fresh-import-parity.json'),given['fbx'],sha(focus_grid),
                         sha(focus/'source-samples.json'),sha(focus/'export-receipt.json'))
    source,focus_invariants=parity.source_index(focus/'source-samples.json',FOCUS_FRAMES)
    _,dense_invariants=parity.source_index(dense/'source-samples.json',[1.,96.])
    require(focus_invariants==dense_invariants,'fresh focus source rest/topology/projection differs from dense endpoints')
    source_receipt=read(focus/'export-receipt.json')
    for key,expected in {'source_sha256':SOURCE_SHA,'fbx_sha256':given['fbx'],'source_bytes_unchanged':True,
                         'in_memory_source_state_restored':True,'source_saved':False,'rendered':False,
                         'mode':'focus-sample','chunk_index':None,'rig_action':ACTION,
                         'sample_frames':FOCUS_FRAMES,'source_sample_count':9,'fbx_bake_step':1/256,
                         'sample_grid_sha256':sha(focus_grid),'independent_grid_sha256':GRID_SHA}.items():
        exact(source_receipt.get(key),expected,'focus source receipt '+key)
    exact(source_receipt.get('recipes'),export['recipes'],'focus source recipe identity')
    require(source_receipt.get('source_window_recipe_sha256')==sha(window.WINDOW/'sample_source.py')
            and source_receipt.get('window_recipe_pins_sha256')==args.window_pins_sha256,'focus source window producer differs')
    require({'source-samples.json','camera-contract.json','fbx-take-contract.json'}<=set(source_receipt.get('evidence_sha256',{})),'focus source evidence missing')
    for relative,expected in source_receipt['evidence_sha256'].items():pin(bounded(focus,relative),expected)
    producers={}
    for folder,expected in [('native-dense',args.native_pins_sha256),('native-window-v2',args.window_pins_sha256),('runtime-conversion-v2',args.conversion_pins_sha256),('native-rigid-v2',args.rigid_pins_sha256)]:
        producers.update(pinned_producer(safe_output(folder+'/pins.json'),expected))
    processes={}
    for name,relative in {'export':'logs/export-dense-v1/export.exit.json','focus_source':window.FOCUS_LOG+'/sample.exit.json',
                          'focus_fbx':window.FOCUS_LOG+'/verify.exit.json','control':'logs/window-control-v2/verify.exit.json'}.items():
        path=safe_output(relative);processes[name]=parity.process_record(path,blender=True)
    for label in ('export','focus_source','focus_fbx','control'):
        validate_native_process(processes[label]['record'],label,args.native_pins_sha256 if label=='export' else args.window_pins_sha256)
    converted=conversion.validate(given['fbx'],args.conversion_pins_sha256)
    processes['conversion']={key:converted[key] for key in ('file','record')}
    require(processes['conversion']['record'].get('fbx_sha256')==given['fbx'],'conversion binds different FBX')
    require(processes['conversion']['record'].get('canonical_sha256')==CANONICAL_SHA,'conversion canonical differs')
    require(processes['conversion']['record'].get('recipe_pins_sha256')==args.conversion_pins_sha256,'conversion recipe receipt differs')
    if decode_runtime:
        parity.load_runtime(safe_output('runtime-v1/asset.vra'),ROOT/'low-vault-runtime-20261015/conversion-inputs/canonical-locomotion.vra',given['fbx'])
    evidence={'conversion/'+key:value for key,value in converted['evidence'].items()}
    for folder in (dense,focus):
        for name in ('source-samples.json','export-receipt.json','fresh-import-parity.json','camera-contract.json','fbx-take-contract.json'):
            path=folder/name
            if path.is_file():evidence[str(path.relative_to(WORK))]=parity.file_record(path)
        witness=read(folder/'source-samples.json')
        for row in witness['frames'].values():
            for kind in ('row','skin'):
                path=bounded(folder,row[kind+'_path']);evidence[str(path.relative_to(WORK))]=parity.file_record(path)
    evidence['focus_grid']=parity.file_record(focus_grid)
    evidence['bounded_full_control']=parity.file_record(window.CONTROL)
    for name,value_process in processes.items():evidence['process/'+name]=value_process['file']
    candidate={'schema':CANDIDATE_SCHEMA,'state':'accepted','proof_root':str(WORK.resolve()),
               'candidate_spec_sha256':sha(HERE/'candidate-spec.json'),'source_sha256':SOURCE_SHA,
               'action':ACTION,'action_fingerprint':ACTION_SHA,'sample_grid_sha256':GRID_SHA,
               'fbx_subdivisions':256,'runtime_subdivisions':256,'runtime_hz':15360,'runtime_keys':24321,
               'thresholds':THRESHOLDS,'acceptance_pins':{name:getattr(args,name.replace('-','_')+'_sha256') for name in PIN_ARGUMENTS},'assets':assets,'evidence':evidence,'producer_files':producers,
               'representation_passed':True,'processes_verified':True,'focus_sample_frames':FOCUS_FRAMES,
               'focus_maxima':value['maxima'],'runtime_complete':False,'runtime_activated':False}
    validate_candidate(candidate)
    return candidate


def validate_admitted(candidate):
    """Recheck retained semantic gates; booleans in candidate.json are not proof."""
    pins=candidate.get('acceptance_pins',{})
    require(set(pins)==set(PIN_ARGUMENTS),'actual admission input pin inventory differs')
    args=SimpleNamespace(**{name.replace('-','_')+'_sha256':value for name,value in pins.items()})
    # Immutable VRA bytes are hash-checked here. Full decoding and actual Rust
    # mapping are required again by fresh initialize, rather than on every row.
    actual=build_candidate(args,decode_runtime=False)
    require(actual==candidate,'accepted candidate differs from independently revalidated source/focus/process evidence')
    return candidate


def prepare(args):
    require(not (HERE/'candidate.json').exists(),'preserve accepted candidate; no replacement')
    candidate=build_candidate(args)
    if args.accept:write_new(HERE/'candidate.json',candidate)
    return {'candidate_validated':True,'accepted':args.accept,'candidate_path':str(HERE/'candidate.json') if args.accept else None,
            'candidate_sha256':sha(HERE/'candidate.json') if args.accept else None,'full_runtime_proof_complete':False}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in PIN_ARGUMENTS:
        p.add_argument('--'+name+'-sha256',required=True)
    p.add_argument('--accept',action='store_true');a=p.parse_args(argv)
    try:result=prepare(a)
    except Exception as exc:
        print(json.dumps({'passed':False,'accepted':False,'error':type(exc).__name__+': '+str(exc)}),file=sys.stderr);return 1
    print(json.dumps(result,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())

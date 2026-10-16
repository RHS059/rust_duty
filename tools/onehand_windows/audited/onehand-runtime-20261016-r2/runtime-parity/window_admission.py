"""Independent consumer-side admission of exact retained FBX key windows."""
import hashlib
import math
import struct
import numpy as np
from onehand_r2_common import *

WINDOW=WORK/'native-window-v2'
FOCUS_OUTPUT='focus-output-v2'
FOCUS_LOG='logs/focus-v2'
CONTROL=WORK/'window-control-v2/full-import-control.json'
CONTROL_LOG=WORK/'logs/window-control-v2/verify.exit.json'
OLD_FBX_SHA='17608683c81465964b5890b4d9869774a0f35122cf62ebd6e564cedf1b1ddbe4'
FULL_CONTROL=ORIGINAL_WORK/'diagnostics/chunk036-scalar-v1/native-job/import.json'
FULL_CONTROL_SHA='6c5a559b48f023789225dbcaa17c3f57f2e9836ce390d9435af0dbdfb244d05b'
RSS_CEILING=3*1024**3


def sha_string(value):
    require(isinstance(value,str) and len(value)==64 and all(v in '0123456789abcdef' for v in value),'missing/invalid measured array hash')
    return value


def expected_selection(selected,n):
    require(type(n) is int and n in (64,256),'invalid exact window subdivision')
    require(selected and all(type(f) is float and math.isfinite(f) and 1<=f<=96 for f in selected),'window needs exact float sample grid')
    require(selected==sorted(set(selected)),'window sample order/duplicate differs')
    retained={0,95*n};brackets=[]
    for f in selected:
        lo=math.floor((f-1)*n);hi=math.ceil((f-1)*n);retained.update((lo,hi))
        brackets.append({'source_frame':f,'lower_index':lo,'upper_index':hi,'lower_frame':1+lo/n,'upper_frame':1+hi/n})
    indices=sorted(retained);require(len(indices)<=4096,'retained key cap exceeded')
    return {'requested_source_frames':selected,'allowed_evaluation_frames':sorted(set([1.,*selected])),
            'retained_indices':indices,'retained_source_frames':[1+i/n for i in indices],'sample_brackets':brackets,
            'retained_key_count':len(indices),'full_key_count':95*n+1,'subdivisions':n}


def validate_actions(actions,counts):
    require(isinstance(actions,list) and len(actions)==6,'six retained Actions required')
    names=[r.get('action') for r in actions]
    require(all(isinstance(v,str) and v for v in names) and len(set(names))==6,'retained Action identity differs')
    for row in actions:
        require(row.get('frame_range')==[1,96] and type(row.get('curves')) is int and row['curves']>0,'retained Action range/count differs')
        require(row['curves']==counts.get(row['action']),'retained Action curve coverage differs')
    require(set(names)==set(counts),'retained curve Actions missing or extra')


def validate_window(value,fbx_sha,selected,n=256,recipe_sha=None,export_raw=None):
    recipe_sha=sha(WINDOW/'pins.json') if recipe_sha is None else recipe_sha
    for key,expected in {'schema':'rust-duty-fbx-bounded-key-window/v1','passed':True,'fbx_sha256':fbx_sha,
                         **expected_selection(selected,n),'linear_interpolation':True,'partial_instantiation_only':True,
                         'full_clip_instantiated':False,'selection_stage':'after complete official transformation/hemisphere/unwrap sequence',
                         'recipe_pins_sha256':recipe_sha}.items():
        exact(value.get(key),expected,'bounded window '+key)
    full_count=95*n+1
    expected_times=np.asarray([1+i/n for i in range(full_count)],dtype='<f4')
    full_time_hash=hashlib.sha256(expected_times.tobytes()).hexdigest()
    retained_hash=hashlib.sha256(expected_times[value['retained_indices']].tobytes()).hexdigest()
    require(value.get('retained_native_grid_sha256')==retained_hash,'retained exact float32 times differ')
    raw=value.get('full_raw_admission',{})
    for key,expected in {'passed':True,'fbx_sha256':fbx_sha,'curve_count':1379,'key_count':full_count,
                         'subdivisions':n,'all_times_values_finite_checked':True,'linear_flags':24836}.items():
        exact(raw.get(key),expected,'full raw window '+key)
    require(type(raw.get('fbx_version')) is int and raw['fbx_version']>0,'full raw FBX version absent')
    curves=raw.get('curves');require(isinstance(curves,list) and len(curves)==1379,'all1379 raw curves required')
    ids=set();time_hashes={}
    for row in curves:
        ident=row.get('curve_uuid');require(type(ident) is int and ident not in ids,'raw curve UUID duplicate/missing');ids.add(ident)
        exact(row.get('key_count'),full_count,'raw curve full key count')
        time_sha=sha_string(row.get('time_sha256'));sha_string(row.get('value_sha256'))
        time_hashes[time_sha]=time_hashes.get(time_sha,0)+1
    require(value.get('full_raw_admission_sha256')==digest(raw),'raw full admission hash differs')
    if export_raw is not None:
        require(n==256,'export-linked admission must use candidate256 grid');validate_raw_key_grid(export_raw)
        require(time_hashes==export_raw['ktime_grid_hashes'] and raw['fbx_version']==export_raw['fbx_version'],'full raw window clocks differ from full export')
    transformed=value.get('full_transformed_admission',{})
    for key,expected in {'passed':True,'full_transform_sequence_preserved_before_selection':True,
                         'all_full_input_times_values_checked':True}.items():exact(transformed.get(key),expected,'full transformed window '+key)
    rows=transformed.get('curves');count=transformed.get('curve_count')
    require(type(count) is int and count>0 and isinstance(rows,list) and len(rows)==count,'all transformed curves required')
    identities=set();counts={}
    for row in rows:
        owner,path,index=row.get('owner_action'),row.get('data_path'),row.get('array_index')
        require(isinstance(owner,str) and owner and isinstance(path,str) and path and type(index) is int and index>=0,'transformed channel identity missing')
        ident=(owner,path,index);require(ident not in identities,'transformed channel duplicate');identities.add(ident)
        counts[owner]=counts.get(owner,0)+1
        exact(row.get('full_key_count'),full_count,'transformed full key count')
        require(row.get('full_time_sha256')==full_time_hash,'transformed complete clock differs')
        sha_string(row.get('full_value_sha256'));sha_string(row.get('retained_value_sha256'))
    validate_actions(transformed.get('actions'),counts)
    require(value.get('actions')==transformed['actions'] and value.get('imported_curve_count')==count,'retained/transformed Action coverage differs')
    require(value.get('full_transformed_admission_sha256')==digest(transformed),'full transformed admission hash differs')
    validate_import_admission({'patches':value.get('patches',{}),'single_stack_admission':value.get('single_stack_admission',{})})
    return value


def exact_recursive(actual,expected,label):
    if isinstance(expected,dict):
        require(isinstance(actual,dict) and set(actual)==set(expected),'control dictionary differs: '+label)
        for key in expected:exact_recursive(actual[key],expected[key],label+'/'+key)
    elif isinstance(expected,list):
        require(isinstance(actual,list) and len(actual)==len(expected),'control list differs: '+label)
        for i,(a,b) in enumerate(zip(actual,expected)):exact_recursive(a,b,label+'/'+str(i))
    elif type(expected) is float:
        require(type(actual) is float and math.isfinite(actual) and math.isfinite(expected)
                and struct.pack('<d',actual)==struct.pack('<d',expected),'control component bits differ: '+label)
    else:exact(actual,expected,'control scalar '+label)


def validate_control(value,recipe_sha=None):
    recipe_sha=sha(WINDOW/'pins.json') if recipe_sha is None else recipe_sha
    pin(FULL_CONTROL,FULL_CONTROL_SHA);original=read(FULL_CONTROL)
    for key,expected in {'schema':'rust-duty-fbx-bounded-full-import-control/v1','passed':True,'fbx_sha256':OLD_FBX_SHA,
                         'full_import_control_sha256':FULL_CONTROL_SHA,'source_frames':FOCUS_FRAMES,'bones':148,
                         'matrix_components_checked':21312,'matrix_component_bit_mismatch_count':0,
                         'focus_channel_bit_mismatch_count':0,'maximum_component_difference':0.,'mismatches':[],
                         'window_recipe_pins_sha256':recipe_sha}.items():exact(value.get(key),expected,'bounded/full control '+key)
    require(original['fbx_sha256']==OLD_FBX_SHA and original['source_frames']==FOCUS_FRAMES,'original full import identity differs')
    samples=value.get('samples',[]);require(len(samples)==9,'all nine full-import control samples required')
    for row,expected in zip(samples,original['samples']):
        exact(row.get('source_frame'),expected['source_frame'],'control frame')
        require(len(row.get('deformation_world',{}))==148,'control all148 matrices required')
        for field in ('deformation_world','focus_bones'):exact_recursive(row.get(field),expected[field],field)
    validate_window(value.get('window_admission',{}),OLD_FBX_SHA,FOCUS_FRAMES,64,recipe_sha)
    return value


def validate_resource_process(record):
    for key,expected in {'exit_code':0,'completed':True,'resource_stop_reason':None,'signal':None,
                         'timed_out':False,'rss_ceiling_bytes':RSS_CEILING}.items():exact(record.get(key),expected,'bounded process '+key)
    samples=record.get('memory_samples',[]);require(isinstance(samples,list) and samples,'bounded process memory observations absent')
    observed=[];previous=-1
    for row in samples:
        elapsed=finite_number(row.get('elapsed_seconds'),'memory sample time');require(elapsed>=previous,'memory sample reordering');previous=elapsed
        rss=row.get('rss_bytes')
        require(rss is None or type(rss) is int and 0<=rss<=RSS_CEILING,'native sampled RSS ceiling exceeded')
        require(type(row.get('mem_available_bytes')) is int and row['mem_available_bytes']>0,'memory sample capacity absent')
        if rss is not None:observed.append(rss)
    peak=record.get('peak_sampled_rss_bytes')
    require(observed and type(peak) is int and peak==max(observed) and 0<peak<=RSS_CEILING,'native peak sampled RSS missing/differs')
    require(record.get('remaining_bytes',0)>=1024**3,'native process violated disk floor')
    return record

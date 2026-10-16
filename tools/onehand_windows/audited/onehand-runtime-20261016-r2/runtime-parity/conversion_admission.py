"""Admission of all thirteen bounded native conversion stages and streamed VRA."""
from onehand_r2_common import *
import window_admission as window

RECIPE=WORK/'runtime-conversion-v2'
LOGS=WORK/'logs/conversion-v2'


def record(path):
    path=Path(path).resolve()
    return {'path':str(path),'sha256':sha(path),'bytes':path.stat().st_size}


def validate_manifest_provenance(manifest):
    value=manifest.get('bounded_conversion',{})
    for key,expected in {'schema':'rust-duty-onehand-bounded-runtime-conversion/v1','block_count':12,
                         'maximum_retained_keys_per_curve':2051,'full_key_count':24321,
                         'partial_instantiation_only':True,'full_clip_instantiated':False}.items():
        exact(value.get(key),expected,'bounded runtime provenance '+key)
    for key in ('recipe_pins_sha256','geometry_metadata_sha256','assembly_receipt_sha256','geometry_process_receipt_sha256',
                'full_raw_admission_sha256','source_focus_receipt_sha256','full_import_control_receipt_sha256'):
        window.sha_string(value.get(key))
    blocks=value.get('block_receipts',[]);require(len(blocks)==12,'all12 bounded runtime blocks required')
    for i,row in enumerate(blocks):
        exact(row.get('block_index'),i,'bounded runtime block order')
        require(row.get('path')==f'runtime-blocks-v2/block-{i:03d}/receipt.json','bounded runtime receipt path differs')
        window.sha_string(row.get('sha256'));window.sha_string(row.get('process_receipt_sha256'))
    return value


def full_channels(admission):
    return digest([{k:v for k,v in row.items() if k!='retained_value_sha256'} for row in admission['full_transformed_admission']['curves']])


def validate_assembly_crc(assembly,path):
    with Path(path).open('rb') as stream:
        header=stream.read(G.vrview.HEADER.size)
    require(len(header)==G.vrview.HEADER.size,'streamed VRA header is truncated')
    magic,version,length,checksum,reserved=G.vrview.HEADER.unpack(header)
    require(magic==G.vrview.MAGIC and version==G.vrview.VERSION and reserved==0
            and length==Path(path).stat().st_size-G.vrview.HEADER.size,'streamed VRA header differs')
    require(assembly.get('payload_crc32')==f'{checksum:08x}','streamed assembly CRC differs from admitted VRA')


def validate(fbx_sha,recipe_sha):
    import verify_onehand_r2 as parity
    out=safe_output('runtime-v1');manifest=read(out/'manifest.json');provenance=validate_manifest_provenance(manifest)
    pin(RECIPE/'pins.json',recipe_sha)
    require(provenance['recipe_pins_sha256']==recipe_sha,'bounded conversion recipe differs')
    require(provenance['source_focus_receipt_sha256']==sha(WORK/'focus-output-v2/fresh-import-parity.json')
            and provenance['full_import_control_receipt_sha256']==sha(window.CONTROL),'bounded conversion prerequisites differ')
    meta_path=out/'geometry-metadata.json';pin(meta_path,provenance['geometry_metadata_sha256']);meta=read(meta_path)
    for key,expected in {'schema':'rust-duty-onehand-bounded-runtime-geometry/v1','passed':True,'source_sha256':SOURCE_SHA,
                         'fbx_sha256':fbx_sha,'canonical_sha256':CANONICAL_SHA,'clip_name':ACTION,'loop':False,
                         'ticks_per_second':15360,'last_tick':24320,'recipe_pins_sha256':recipe_sha}.items():exact(meta.get(key),expected,'bounded geometry '+key)
    require(len(meta.get('bones',[]))==72 and [a.get('name') for a in meta.get('actors',[])]==list(ACTORS),'bounded geometry canonical/actor inventory differs')
    require(meta.get('static_import_sha256')==digest(meta.get('static_import')),'bounded static geometry/rest hash differs')
    raw=read(WORK/'dense-output-v1/export-receipt.json')['raw_key_grid']
    window.validate_window(meta.get('window_admission',{}),fbx_sha,[1.],export_raw=raw)
    raw_hash=meta['window_admission']['full_raw_admission_sha256'];channels=full_channels(meta['window_admission'])
    require(provenance['full_raw_admission_sha256']==raw_hash,'bounded conversion raw sequence differs')
    evidence={'geometry':record(meta_path)};native_paths=[];native_processes=[]
    for name,info in meta.get('files',{}).items():
        path=bounded(out,name);require(path.stat().st_size==info['bytes'],'bounded geometry file size differs');pin(path,info['sha256'])
        evidence['geometry/'+name]=record(path)
    require(set(meta.get('files',{}))=={'asset.vrs','asset.vrm','geometry-only.glb'},'bounded geometry companion inventory differs')
    for stage,index in [('geometry',None),*[('block',i) for i in range(12)]]:
        label='geometry' if index is None else f'block-{index:03d}'
        process_path=LOGS/label/'process-receipt.json';p=parity.process_record(process_path,blender=True);native_paths.append(process_path);native_processes.append(p['record'])
        process=p['record'];window.validate_resource_process(process)
        for key,expected in {'stage':stage,'block_index':index,'source_sha256':SOURCE_SHA,'fbx_sha256':fbx_sha,
                             'canonical_sha256':CANONICAL_SHA,'recipe_pins_sha256':recipe_sha,'owner_lock':str(ROOT/'native-owner.lock')}.items():
            exact(process.get(key),expected,'bounded native conversion '+key)
        command=[process['command'][0],'--background','--factory-startup','--disable-autoexec','--threads','1','--python-exit-code','1','--python',str(RECIPE/'native_runtime.py'),'--',stage]
        if index is not None:command+=['--block-index',str(index)]
        require(process['command']==command,'bounded native conversion command differs')
        pin(process_path.parent/'run.log',process['stdout_sha256']);evidence['native/'+label]=p['file'];evidence['native/'+label+'/log']=record(process_path.parent/'run.log')
        if index is None:
            require(process['output_receipt_sha256']==sha(meta_path) and sha(process_path)==provenance['geometry_process_receipt_sha256'],'bounded geometry normal-exit binding differs')
            continue
        folder=safe_output(f'runtime-blocks-v2/block-{index:03d}');path=folder/'receipt.json';block=read(path)
        declared=provenance['block_receipts'][index];pin(path,declared['sha256']);pin(process_path,declared['process_receipt_sha256'])
        require(process['output_receipt_sha256']==sha(path),'bounded block normal-exit result differs')
        lo=index*2048;hi=min(lo+2048,24320);selected=[1+i/256 for i in range(lo,hi+1)]
        for key,expected in {'schema':'rust-duty-onehand-bounded-runtime-block/v1','passed':True,'block_index':index,
                             'start_tick':lo,'end_tick':hi,'frames':hi-lo+1,'frame_bytes':3007,'source_sha256':SOURCE_SHA,
                             'fbx_sha256':fbx_sha,'canonical_sha256':CANONICAL_SHA,'geometry_metadata_sha256':sha(meta_path),
                             'static_import_sha256':meta['static_import_sha256'],'recipe_pins_sha256':recipe_sha,
                             'frame_file_bytes':(hi-lo+1)*3007,'final_full_key_count':24321,'full_clip_instantiated':False}.items():
            exact(block.get(key),expected,'bounded runtime block '+key)
        window.validate_window(block.get('window_admission',{}),fbx_sha,selected,export_raw=raw)
        require(block['window_admission']['full_raw_admission_sha256']==raw_hash and full_channels(block['window_admission'])==channels,
                'full raw/transformed sequence differs across bounded native blocks')
        frames_path=folder/'frames.bin';require(frames_path.stat().st_size==block['frame_file_bytes'],'bounded frame block size differs');pin(frames_path,block['frame_file_sha256'])
        evidence['block/'+label]=record(path);evidence['block/'+label+'/frames']=record(frames_path)
    assembly_path=out/'assembly-receipt.json';pin(assembly_path,provenance['assembly_receipt_sha256']);assembly=read(assembly_path)
    for key,expected in {'schema':'rust-duty-streamed-vra-report/v1','passed':True,'format':'VRANIM01','sha256':sha(out/'asset.vra'),'bytes':(out/'asset.vra').stat().st_size,
                         'clip_name':ACTION,'loop':False,'frames':24321,'bones':72,'actors':3,'frame_bytes':3007,
                         'transforms':1824075,'blocks':12,'source_records':24332,'seams_verified':11,
                         'seam_ticks':[i*2048 for i in range(1,12)],'duplicate_seam_records_removed':11,
                         'source_sha256':SOURCE_SHA,'fbx_sha256':fbx_sha,'canonical_sha256':CANONICAL_SHA,
                         'geometry_metadata_sha256':sha(meta_path),'static_import_sha256':meta['static_import_sha256'],
                         'recipe_pins_sha256':recipe_sha,'full_raw_admission_sha256':raw_hash,'inputs_retained':True,'rust_parity_verified':False}.items():
        exact(assembly.get(key),expected,'streamed final runtime '+key)
    for name in ('vrs','vrm'):
        require(assembly.get(name+'_sha256')==sha(out/('asset.'+name)) and assembly.get(name+'_bytes')==(out/('asset.'+name)).stat().st_size,'streamed companion differs')
    validate_assembly_crc(assembly,out/'asset.vra')
    evidence['assembly']=record(assembly_path)
    process_path=LOGS/'process-receipt.json';process=read(process_path)
    for key,expected in {'schema':'rust-duty-onehand-bounded-conversion-process/v1','completed':True,'exit_code':0,'timed_out':False,
                         'resource_stop_reason':None,'source_sha256':SOURCE_SHA,'fbx_sha256':fbx_sha,'canonical_sha256':CANONICAL_SHA,
                         'recipe_pins_sha256':recipe_sha,'manifest_sha256':sha(out/'manifest.json'),'conversion_passed':True,
                         'native_processes':[{'path':str(p.relative_to(WORK)),'sha256':sha(p)} for p in native_paths],
                         'peak_sampled_rss_bytes':max(p['peak_sampled_rss_bytes'] for p in native_processes),
                         'rss_ceiling_bytes':window.RSS_CEILING,'assembly_receipt_sha256':sha(assembly_path),'runtime_verified':False}.items():
        exact(process.get(key),expected,'bounded aggregate conversion '+key)
    require(process.get('remaining_bytes',0)>=1024**3,'bounded conversion disk reserve violated')
    return {'file':record(process_path),'record':process,'evidence':evidence}

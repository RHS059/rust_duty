"""Explicit target-native witnesses and read-only assembly identity admission."""
from __future__ import annotations
import hashlib,math,struct,zlib
from pathlib import Path
import numpy as np
import pinned_math as p
from runtime_context import check_record,record

def producer(ctx):
    root=ctx.root('native_producer');p.pin(root/'PINS.json',ctx.raw['dependencies']['producer_pins_sha256'])
    for n,h in p.read(root/'PINS.json').items():p.require(Path(n).name==n,'unsafe producer pin');p.pin(root/n,h)
    known={}
    for n in ('pinned_code','stage_context','transport_binding','planner','native_stages','process_evidence','host_identity','admission'):
        known[n]=p.private_module(n,root/(n+'.py'),known)
    return known['admission']

def stage(ctx,ref,expected,index,*,retired_files=None):
    c=ctx.cc;c.exact_keys(ref,('context','native_receipt','process_terminal'),'stage reference')
    pins={n:c.FilePin.parse(n,v) for n,v in ref.items()}
    for v in pins.values():p.require(v.path.is_relative_to(ctx.candidate_root),'foreign stage reference');v.verify()
    native_context=c.strict_json(pins['context'].path);stage_id=native_context['stage_id'];p.require(type(stage_id) is str and Path(stage_id).name==stage_id and stage_id not in ('.','..'),'stage identifier')
    folder=ctx.candidate_root/'native'/stage_id
    c.exact(str(pins['native_receipt'].path),str(folder/'receipt.json'),'native receipt path')
    c.exact(str(pins['process_terminal'].path),str(ctx.candidate_root/'process'/stage_id/'terminal.json'),'native terminal path')
    api=producer(ctx);args=(pins['context'].path,pins['context'].sha256,ctx.root('context_package'),pins['native_receipt'].sha256,pins['process_terminal'].sha256)
    if retired_files is None:value=api.verify_stage(*args)
    else:
        p.require(expected=='source-chunk' and retired_files,'only complete source chunk retirement allowed')
        value=api.verify_retained_stage(*args,retired_files=retired_files)
    for key,want in {'schema':'rust-duty-windows-native-stage/v1','stage':expected,'index':index,'context_file_sha256':pins['context'].sha256,'passed':True,'source_saved':False,'rendered':False,'cross_platform_float64_equality_proved':False,'runtime_equivalence_proved':False,'artistic_approval':False,'activation_authorized':False}.items():c.exact(value[key],want,'native '+key)
    bind=dict(value['binding'])
    if expected=='export':
        c.exact(value['output_files']['animation.fbx']['sha256'],ctx.pin('actual_fbx').sha256,'actual new export');bind['actual_fbx_sha256']=ctx.pin('actual_fbx').sha256
    c.exact(bind,ctx.binding,'mixed-source/candidate/host native evidence')
    native_context=c.strict_json(pins['context'].path);folder=ctx.candidate_root/'native'/native_context['stage_id']
    c.exact(str(pins['native_receipt'].path),str(folder/'receipt.json'),'native receipt path')
    return value,folder

INPUT_ROLES={'initialize':{'source':'export','rigid':'rigid-frame1'},'focus':{'source':'source-focus','fbx':'focus-import','rigid':'rigid-focus'},'chunk':{'source':'source-chunk','fbx':'chunk-import','rigid':'rigid-chunk'}}

def input_bundle(ctx,path,expected_sha,kind,index=None):
    c=ctx.cc;path=c.ordinary(path,existing=True);p.require(path.is_relative_to(ctx.candidate_root/'contexts'),'inputs outside candidate contexts');p.pin(path,expected_sha)
    p.require(kind in INPUT_ROLES,'input bundle kind');p.require((kind=='chunk' and type(index) is int and 0<=index<67) or (kind!='chunk' and index is None),'input index')
    value=c.strict_json(path);c.exact_keys(value,('schema','binding','kind','index','stages'),'runtime inputs')
    for k,v in {'schema':'rust-duty-windows-runtime-inputs/v1','binding':ctx.runtime_binding,'kind':kind,'index':index}.items():c.exact(value[k],v,'inputs '+k)
    c.exact_keys(value['stages'],INPUT_ROLES[kind],'native input roles')
    for ref in value['stages'].values():
        c.exact_keys(ref,('context','native_receipt','process_terminal'),'stage reference')
        for role,rec in ref.items():c.FilePin.parse(role,rec)
    return value

def inputs(ctx,path,expected_sha,kind,index=None):
    value=input_bundle(ctx,path,expected_sha,kind,index)
    found={r:stage(ctx,value['stages'][r],s,index) for r,s in INPUT_ROLES[kind].items()}
    if 'fbx' in found:ctx.cc.exact(found['fbx'][0]['payload']['source_oracle_sha256'],found['source'][0]['output_files']['source-samples.json']['sha256'],'FBX source oracle linkage')
    return found

def source_index(ctx,m,path,selected,baseline=None):
    # Identity adaptation only. Mathematical checks mirror source_index exactly.
    witness=p.read(path);root=Path(path).parent
    for k,want in {'generated_source_sha256':ctx.pin('generated_source').sha256,'approved_source_sha256':ctx.cc.APPROVED_SHA,'rig_action':p.ACTION,'rig_action_fingerprint':p.ACTION_SHA,'camera_action':None,'camera_action_fingerprint':None}.items():p.exact(witness.get(k),want,'source '+k)
    rows=witness.get('frames',{});p.require(list(rows)==[str(f) for f in selected],'source frame descriptor order')
    rest,hierarchy=witness.get('source_rest_world',{}),witness.get('hierarchy',{});p.require(len(rest)==148 and set(rest)==set(hierarchy),'all148 source bones required')
    for name,value in rest.items():
        mat=m.G.matrix(value,'source rest '+name);p.require(abs(np.linalg.det(mat[:3,:3]))>1e-8,'singular source rest')
    p.require(set(witness.get('topology',{}))==set(p.SKINS),'three complete source skins required')
    for name,count in zip(p.SKINS,p.COUNTS):p.require(witness['topology'][name]['vertices']==count,'source vertex count differs')
    p.require(witness.get('projection',{}).get('type')=='PERSP','perspective projection required');m.G.finite(witness['projection'].get('ray_directions'),(4,3),'source rays')
    used=[]
    for i,(frame,row) in enumerate(zip(selected,rows.values())):
        p.require(row.get('source_frame')==frame,'descriptor frame differs')
        for kind,folder,ext in [('row','sample-rows','json'),('skin','skin-rows','npz')]:
            p.require(row.get(kind+'_path')==f'{folder}/{i:04d}.{ext}','descriptor exact local index/path differs');f=p.bounded(root,row[kind+'_path']);p.pin(f,row[kind+'_sha256']);used.append(f)
    p.require(len(set(used))==2*len(selected),'source row reused')
    invariants={k:witness[k] for k in ('source_rest_world','hierarchy','topology','projection')}
    if baseline is not None:p.require(p.digest(invariants)==baseline,'source invariants changed')
    return witness,invariants

def rigid_frame1(ctx,m,path,initial):
    value=p.read(path)
    for k,v in {'schema':'rust-duty-windows-rigid-frame1/v1','binding':ctx.binding,'generated_source_sha256':ctx.pin('generated_source').sha256,'approved_source_sha256':ctx.cc.APPROVED_SHA,'rig_action':p.ACTION,'rig_action_fingerprint':p.ACTION_SHA,'source_frame':1}.items():p.exact(value.get(k),v,'rigid frame1 '+k)
    p.require(set(value.get('actors',{}))==set(p.ACTORS),'all actor geometry required');geometry={}
    for name,row in value['actors'].items():
        count=row.get('vertex_count');p.require(type(count) is int and count>0,'rigid vertex count')
        geometry[name]=m.G.finite(row.get('vertices_local'),(count,3),'rigid local '+name);polygons=row.get('polygons')
        p.require(isinstance(polygons,list) and len(polygons)==row.get('polygon_count') and polygons,'rigid polygon count')
        p.require(all(isinstance(a,list) and len(a)>=3 and all(type(i) is int and 0<=i<count for i in a) for a in polygons),'rigid indices')
        p.require(p.digest({'vertices_local':row['vertices_local'],'polygons':polygons})==row['geometry_sha256'],'rigid geometry digest')
        p.require(np.max(np.abs(m.G.matrix(row['world_at_frame1'],name)-m.G.matrix(initial['actors_world'][name],name)))<p.LIMIT,'rigid frame1 world differs')
    return value,geometry

def rigid_samples(value,selected,baseline):
    x=value['payload'];p.exact(x['source_frames'],selected,'rigid time grid');p.exact(x['actor_count'],3,'rigid actors');p.exact(x['full_float64_and_topology_bytes_compared'],True,'rigid float64 topology')
    rows=x['samples'];p.require(len(rows)==len(selected),'rigid sample count')
    for frame,row in zip(selected,rows):
        p.exact(row['source_frame'],frame,'rigid frame');p.require(set(row['actors'])==set(p.ACTORS),'rigid actor inventory')
        for name,actor in row['actors'].items():
            p.exact(actor['geometry_sha256'],baseline['actors'][name]['geometry_sha256'],'rigid geometry unchanged');p.exact(actor['buffers'],baseline['actors'][name]['buffers'],'all rigid bytes unchanged');p.exact(actor['hide_render'],False,'rigid hidden')
    return x

def source_fbx(ctx,m,value,selected):
    x=value['payload']
    for k,v in {'passed':True,'source_sha256':ctx.pin('generated_source').sha256,'fbx_sha256':ctx.pin('actual_fbx').sha256,'samples':len(selected),'sample_frames':selected,'skin_vertex_samples':len(selected)*10234,'source_total_bones_including_helpers':148,'runtime_support_verified':False,'independent_grid_sha256':p.GRID_SHA,'off_key_source_frames':[f for f in selected if f*256!=int(f*256)]}.items():p.exact(x.get(k),v,'FBX '+k)
    p.require(set(p.FBX_CHECKS)<=set(x['checks']) and all(v is True for v in x['checks'].values()),'FBX full checks missing')
    p.require(set(x['maxima'])==set(p.FBX_KEYS),'FBX maxima inventory')
    for k,v in x['maxima'].items():p.require(0<=p.finite_number(v,k)<p.LIMIT,'FBX strict threshold')
    p.require(0<=p.finite_number(x['camera_projection_ray_error'],'ray')<p.RAY_LIMIT,'ray strict threshold')
    # Exact window algorithms retained, explicit reviewed producer recipe identity.
    m.validate_window(x['window_admission'],ctx.pin('actual_fbx').sha256,selected,recipe_sha=x['window_admission']['recipe_pins_sha256'])
    return x

def verify_assembly(ctx,m):
    """Check native conversion + every exact packed byte, without making a copy."""
    gate=p.read(ctx.pin('assembly_gate').verify());c=ctx.cc
    c.exact_keys(gate,('schema','binding','conversion_gate','assembly_report','geometry','blocks'),'assembly input gate')
    c.exact(gate['schema'],'rust-duty-windows-runtime-assembly-inputs/v1','assembly gate');c.exact(gate['binding'],ctx.binding,'assembly candidate')
    cg=c.FilePin.parse('conversion_gate',gate['conversion_gate']);cg.verify();native=producer(ctx).verify_gate(cg.path,cg.sha256,ctx.root('context_package'))
    c.exact(native['kind'],'conversion','native conversion gate');c.exact(native['binding'],ctx.binding,'conversion same candidate')
    metadata_path=check_record(gate['geometry'],c,ctx.candidate_root);metadata=p.read(metadata_path)
    p.require(gate['geometry']['sha256']==native['stages'][0]['output_files']['runtime/geometry-metadata.json']['sha256'],'native geometry linkage')
    p.require(len(gate['blocks'])==12,'all12 block inputs');blocks=[]
    for i,rec in enumerate(gate['blocks']):
        path=check_record(rec,c,ctx.candidate_root);p.require(rec['sha256']==native['stages'][i+1]['output_files']['block/receipt.json']['sha256'],'native block linkage');blocks.append(path)
    assembler_loader=p.private_module('pinned_assembler',ctx.root('context_package')/'pinned_assembler.py',{'candidate_context':c})
    a=assembler_loader.load_assembler(ctx.root('audited_source')/'onehand-runtime-20261016-r2/runtime-conversion-v2',ctx.root('audited_source')/'onehand-runtime-20261016/importer-patch/tools')
    contract=a.StreamContract(source_sha256=ctx.pin('generated_source').sha256,fbx_sha256=ctx.pin('actual_fbx').sha256,canonical_sha256=p.CANONICAL_SHA)
    p.require((contract.bone_count,contract.actor_count,contract.last_tick,contract.frame_bytes,contract.block_count)==(72,3,24320,3007,12),'full production format only')
    bones,actors,assigned=a._validate_metadata(metadata,contract)
    vrs_crc,_=a._companion(ctx.pin('vrs').path,metadata['files']['asset.vrs'],'VRS',bones,assigned)
    vrm_crc,_=a._companion(ctx.pin('vrm').path,metadata['files']['asset.vrm'],'VRM',bones,assigned)
    prefix=a._prefix(bones,actors,contract,vrs_crc,vrm_crc);descriptors=a._block_descriptors(blocks,metadata,p.sha(metadata_path),contract)
    count=0;previous=None;seams=[]
    with ctx.pin('vra').path.open('rb') as out:
        out.seek(m.G.vrview.HEADER.size);p.require(out.read(len(prefix))==prefix,'VRA metadata bytes differ')
        for i,(_,frame_path,receipt,_) in enumerate(descriptors):
            with frame_path.open('rb') as frames:
                h=hashlib.sha256()
                for tick in range(receipt['start_tick'],receipt['end_tick']+1):
                    raw=frames.read(3007);h.update(raw);a._validated_record(raw,tick,contract)
                    if i and tick==receipt['start_tick']:p.require(raw==previous,'seam byte mismatch');seams.append(tick);continue
                    p.require(tick==count and out.read(3007)==raw,'VRA frame differs from exact native block bytes');count+=1;previous=raw
                p.require(frames.read(1)==b'' and h.hexdigest()==receipt['frame_file_sha256'],'block retained bytes differ')
        p.require(out.read(1)==b'' and count==24321 and seams==[i*2048 for i in range(1,12)],'complete assembly count/seams')
    report=p.read(check_record(gate['assembly_report'],c,ctx.candidate_root))
    for k,v in {'schema':'rust-duty-streamed-vra-report/v1','passed':True,'sha256':ctx.pin('vra').sha256,'frames':24321,'bones':72,'actors':3,'frame_bytes':3007,'transforms':1824075,'blocks':12,'source_records':24332,'seams_verified':11,'seam_ticks':seams,'source_sha256':ctx.pin('generated_source').sha256,'fbx_sha256':ctx.pin('actual_fbx').sha256,'canonical_sha256':p.CANONICAL_SHA,'geometry_metadata_sha256':p.sha(metadata_path),'inputs_retained':True,'rust_parity_verified':False}.items():p.exact(report.get(k),v,'assembly '+k)
    return metadata

def load_runtime(ctx,m):
    metadata=verify_assembly(ctx,m);blobs={r:ctx.pin(r).path.read_bytes() for r in ('vrs','vrm')}
    pack=m.scan_vra(ctx.pin('vra').path,vrs=blobs['vrs'],vrm=blobs['vrm']);canon=m.scan_vra(ctx.pin('canonical').path)['bones']
    manifest=p.read(ctx.pin('manifest').path);ctx.cc.exact_keys(manifest,('schema','binding','assembly_gate_sha256','files','timing_policy','runtime_parity_verified','activation_authorized'),'runtime manifest')
    for k,v in {'schema':'rust-duty-windows-runtime-manifest/v1','binding':ctx.binding,'assembly_gate_sha256':ctx.pin('assembly_gate').sha256,'runtime_parity_verified':False,'activation_authorized':False}.items():p.exact(manifest[k],v,'manifest '+k)
    p.exact(manifest['files'],{r:ctx.pin(r).record() for r in ('vra','vrs','vrm')},'runtime companion identities');m.validate_timing_policy(manifest['timing_policy'])
    p.require(len(canon)==72 and len(pack['bones'])==72 and m.G.skeleton_parents(pack['bones'])==m.G.skeleton_parents(canon),'canonical72 parent closure')
    p.require([x['name'] for x in pack['actors']]==list(p.ACTORS),'all three actors');p.require(len(pack['clips'])==1,'single clip')
    clip=pack['clips'][0];p.require(clip['name']==p.ACTION and clip['loop'] is False,'clip identity');m.validate_runtime_times([x['time'] for x in clip['frames']])
    bones,counts,rigid=m.G.read_geometry(blobs['vrs'],blobs['vrm']);p.require(len(counts)==3 and sum(counts)==10234,'three full runtime skins')
    return pack,bones,counts,rigid

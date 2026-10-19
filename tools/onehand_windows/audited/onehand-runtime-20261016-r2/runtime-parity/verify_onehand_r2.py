#!/usr/bin/env python3
"""Actual Rust CPU consumer for exact frozen one-hand v6; no graphics or builds.

initialize anchors once at source frame 1; consume checks one exact bounded chunk;
aggregate refuses any incomplete grid; retire defaults to a non-mutating plan.
Private source geometry, maps and receipts are local evidence, never public assets.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import io
import os
import selectors
import shutil
import subprocess
import time
import sys
from pathlib import Path
sys.dont_write_bytecode = True
from onehand_r2_common import *
from bounded_vra import scan_vra
import window_admission as window
import conversion_admission as conversion

ERROR_KEYS = ('skin_world_m','skin_camera_relative_m','bone_deformation_matrix',
              'bone_head_world_m','bone_head_camera_relative_m','actor_world_matrix',
              'actor_camera_relative_matrix','rigid_world_m','rigid_camera_relative_m')
FBX_KEYS = ('bone_deformation_world_matrix','bone_head_world_m','actor_world_matrix',
            'actor_camera_relative_matrix','camera_world_matrix','rig_world_matrix',
            'skin_world_m','skin_camera_relative_m')
FBX_CHECKS = ('bone_inventory','hierarchy','animated_camera_bound','animated_rig_bound',
              'single_exact_take',*FBX_KEYS,'finite_bones','skin_topology','camera_projection_rays',
              'camera_type','single_native_clock','fps','source_unchanged','fbx_unchanged')


def file_record(path):
    path = Path(path).resolve()
    return {'path':str(path),'sha256':sha(path),'bytes':path.stat().st_size}

def check_record(record):
    path = Path(record['path'])
    require(path.is_file() and path.stat().st_size==record['bytes'], 'file size/missing: '+str(path))
    pin(path,record['sha256'])
    return path

def checked_json(record):
    return read(check_record(record))

def process_record(path, *, blender=False):
    record = read(path)
    require(record.get('exit_code') == 0 and type(record.get('exit_code')) is int, 'process did not exit successfully: '+str(path))
    if 'source_sha256' in record:
        require(record['source_sha256']==SOURCE_SHA, 'process source identity differs')
    require(record.get('completed',True) is True and record.get('timed_out',False) is False,'process incomplete or timed out: '+str(path))
    command = record.get('command')
    require(isinstance(command,list) and command and all(isinstance(v,str) for v in command), 'missing process command')
    if blender:
        require(all(flag in command for flag in ('--background','--factory-startup','--disable-autoexec')), 'unsafe source/FBX process')
        require(record.get('blender_sha256') and sha(command[0]) == record['blender_sha256'], 'Blender process binary identity differs')
    return {'file':file_record(path),'record':record}

def source_index(path, expected_frames, baseline=None):
    root = Path(path).parent
    witness = read(path)
    for field,value in {'source_sha256':SOURCE_SHA,'rig_action':ACTION,'rig_action_fingerprint':ACTION_SHA,
                        'camera_action':None,'camera_action_fingerprint':None}.items():
        require(witness.get(field)==value, 'source identity differs: '+field)
    descriptors = witness.get('frames',{})
    require(list(descriptors)==[str(f) for f in expected_frames], 'source frame descriptor order/identity differs')
    rest,hierarchy = witness.get('source_rest_world',{}),witness.get('hierarchy',{})
    require(len(rest)==148 and set(rest)==set(hierarchy), 'all 148 source bones required')
    for name,value in rest.items():
        mat = G.matrix(value,'source rest '+name)
        require(abs(np.linalg.det(mat[:3,:3]))>1e-8, 'singular source rest')
    require(set(witness.get('topology',{}))==set(SKINS), 'three complete source skins required')
    for name,count in zip(SKINS,COUNTS):
        require(witness['topology'][name]['vertices']==count, 'source vertex count differs')
    require(witness.get('projection',{}).get('type')=='PERSP', 'perspective projection required')
    G.finite(witness['projection'].get('ray_directions'),(4,3),'source rays')
    used=[]
    for i,(frame,row) in enumerate(zip(expected_frames,descriptors.values())):
        require(row.get('source_frame')==frame, 'descriptor sample frame differs')
        for kind,folder,extension in [('row','sample-rows','json'),('skin','skin-rows','npz')]:
            require(row.get(kind+'_path')==f'{folder}/{i:04d}.{extension}', 'descriptor local index/path differs')
            path=bounded(root,row[kind+'_path']);pin(path,row[kind+'_sha256'])
            used.append(path)
    require(len(set(used))==2*len(expected_frames), 'source row path reused')
    invariants={name:witness[name] for name in ('source_rest_world','hierarchy','topology','projection')}
    if baseline is not None:
        require(digest(invariants)==baseline, 'source rest/hierarchy/topology/projection changed between chunks')
    return witness,invariants

def load_row(root,descriptor,names):
    row_path=bounded(root,descriptor['row_path']);skin_path=bounded(root,descriptor['skin_path'])
    pin(row_path,descriptor['row_sha256']);pin(skin_path,descriptor['skin_sha256'])
    row=read(row_path);frame=descriptor['source_frame']
    require(row.get('source_frame')==frame and row.get('time_seconds')==(frame-1)/60
            and row.get('reference_frame_position')==7786+frame,'source row clock differs')
    for field in ('camera_world','rig_world','camera_world_delta_from_frame1','rig_world_delta_from_frame1'):
        G.matrix(row.get(field),field)
    for field in ('bone_world','bone_deformation_world'):
        require(set(row.get(field,{}))==set(names),'source row bone coverage differs')
        for name,value in row[field].items():G.matrix(value,field+' '+name)
    for field in ('actors_world','actors_camera_relative'):
        require(set(row.get(field,{}))==set(ACTORS),'source actor coverage differs')
        for name,value in row[field].items():G.matrix(value,field+' '+name)
    with np.load(skin_path,allow_pickle=False) as data:
        require(set(data.files)=={'m0','m1','m2'},'source skin identities differ')
        skin=np.concatenate([G.finite(data[f'm{i}'],(count,3),'source skin') for i,count in enumerate(COUNTS)])
    return row,skin

def rigid_frame1(path,initial):
    witness=read(path)
    for field,value in {'schema':'rust-duty-private-onehand-rigid-frame1/v1','source_sha256':SOURCE_SHA,
                        'rig_action':ACTION,'rig_action_fingerprint':ACTION_SHA,'source_frame':1}.items():
        require(witness.get(field)==value,'rigid frame1 identity differs: '+field)
    require(set(witness.get('actors',{}))==set(ACTORS),'rigid frame1 actor coverage differs')
    geometry={}
    for name,row in witness['actors'].items():
        count=row.get('vertex_count');require(type(count) is int and count>0,'invalid rigid vertex count')
        geometry[name]=G.finite(row.get('vertices_local'),(count,3),'source local '+name)
        polygons=row.get('polygons')
        require(isinstance(polygons,list) and len(polygons)==row.get('polygon_count') and polygons,'invalid source polygons')
        require(all(isinstance(p,list) and len(p)>=3 and all(type(i) is int and 0<=i<count for i in p) for p in polygons),'invalid rigid polygons')
        require(digest({'vertices_local':row['vertices_local'],'polygons':polygons})==row.get('geometry_sha256'),'rigid local geometry digest differs')
        require(np.max(np.abs(G.matrix(row.get('world_at_frame1'),name)-G.matrix(initial['actors_world'][name],name)))<LIMIT,'rigid frame1 world differs')
    return witness,geometry

def rigid_chunk(path,index,baseline):
    witness=read(path);selected=frames(index)
    for field,value in {'schema':'rust-duty-private-onehand-rigid-chunk/v1','source_sha256':SOURCE_SHA,
                        'rig_action':ACTION,'rig_action_fingerprint':ACTION_SHA,'sample_grid_sha256':GRID_SHA,
                        'chunk_index':index,'source_frames':selected,'passed':True}.items():
        exact(witness.get(field),value,'rigid chunk '+field)
    samples=witness.get('samples',[]);require(len(samples)==len(selected),'rigid sample coverage differs')
    for frame,row in zip(selected,samples):
        require(row.get('source_frame')==frame and set(row.get('actors',{}))==set(ACTORS),'rigid sample order/coverage differs')
        for name,value in row['actors'].items():
            require(value.get('geometry_sha256')==baseline['actors'][name]['geometry_sha256'],'actor local geometry changed')
            require(value.get('hide_render') is False,'unsupported hide_render source visibility')
    return witness

def rigid_receipt(output,mode,index):
    output=Path(output);path=output.with_name(output.stem+'.receipt.json');receipt=read(path)
    count=1 if mode=='frame1' else len(frames(index))
    for field,value in {'schema':'rust-duty-onehand-rigid-process/v1','mode':mode,'chunk_index':index,
                        'source_sha256':SOURCE_SHA,'rig_action_fingerprint':ACTION_SHA,'sample_grid_sha256':GRID_SHA,
                        'output_sha256':sha(output),'output_bytes':output.stat().st_size,'samples':count,
                        'source_bytes_unchanged':True,'in_memory_source_state_restored':True,
                        'source_saved':False,'rendered':False,'passed':True}.items():
        exact(receipt.get(field),value,'rigid source receipt '+field)
    candidates=[ORIGINAL_WORK/'native-rigid-v1/pins.json'] if mode=='frame1' else [WORK/'native-rigid-v2/pins.json']
    matches=[p for p in candidates if p.is_file() and sha(p)==receipt['recipe_pins_sha256']]
    require(len(matches)==1,'unknown/ambiguous rigid recipe pin manifest')
    pins=matches[0]
    for relative,expected in read(pins)['files'].items():pin(bounded(ROOT,relative),expected)
    return file_record(path)


def load_runtime(asset,canonical,fbx_sha):
    require(Path(asset).name=='asset.vra','expected converter asset.vra')
    blobs={name:(Path(asset).parent/name).read_bytes() for name in ('asset.vrs','asset.vrm')}
    manifest=read(Path(asset).parent/'manifest.json')
    pack=scan_vra(asset,vrs=blobs['asset.vrs'],vrm=blobs['asset.vrm'])
    pin(canonical,CANONICAL_SHA);canon=scan_vra(canonical)['bones']
    for field,value in {'schema':'rust-duty-fbx-segment-diagnostic/v1','status':'diagnostic',
                        'source_fbx_sha256':fbx_sha,'authoring_master_sha256':SOURCE_SHA,
                        'native_crop':[0,95],'native_fps':[60,1],'source_take':ACTION,
                        'imported_frame_offset':1,'bones':72,'actors':list(ACTORS)}.items():
        require(manifest.get(field)==value,'runtime manifest differs: '+field)
    require('prone_camera_pair' not in manifest,'prone common-motion contract forbidden for static one-hand')
    validate_patches(manifest.get('importer_patches',{}))
    conversion.validate_manifest_provenance(manifest)
    validate_timing_policy(manifest.get('timing_policy',{}))
    require(set(manifest.get('files',{}))=={'asset.vra','asset.vrs','asset.vrm'},'runtime companions differ')
    for name in manifest['files']:
        path=Path(asset).parent/name
        require(manifest['files'][name].get('bytes')==path.stat().st_size and manifest['files'][name].get('sha256')==sha(path),'runtime companion hash differs')
    require(len(canon)==72 and len(pack['bones'])==72 and G.skeleton_parents(pack['bones'])==G.skeleton_parents(canon),'runtime canonical72 closure/hierarchy differs')
    require([a['name'] for a in pack['actors']]==list(ACTORS),'runtime actor order differs')
    require(len(pack['clips'])==1,'single runtime clip required');clip=pack['clips'][0]
    require(clip['name']==ACTION and clip['loop'] is False,'runtime clip identity/loop differs')
    validate_runtime_times([r['time'] for r in clip['frames']])
    admission=manifest.get('single_stack_admission',{})
    for field,value in {'schema':'rust-duty-fbx-single-stack/v1','logical_stack':ACTION,
                        'selection':'observed exact stack/layer/owner binding','action_name_matching':False,'renamed_actions':False}.items():
        require(admission.get(field)==value,'exact single-stack admission missing/differs: '+field)
    owners=('Arms',)+ACTORS
    require(set(admission.get('owners',{}))==set(owners) and set(admission.get('owner_model_uuids',{}))==set(owners),'exact stack owner coverage differs')
    for owner in owners:
        row=admission['owners'][owner]
        require(row.get('bound_to_observed_action') is True and row.get('frame_range')==[1,96]
                and row.get('action_name') and row.get('fcurves',0)>0
                and row.get('source_model_uuid')==admission['owner_model_uuids'][owner],'owner observed binding differs')
    bones,counts,rigid=G.read_geometry(blobs['asset.vrs'],blobs['asset.vrm'])
    return pack,bones,counts,rigid

def mem_available():
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):return int(line.split()[1])*1024
    raise AdmissionError('available memory observation absent')


def child_rss(pid):
    try:
        for line in Path(f'/proc/{pid}/status').read_text().splitlines():
            if line.startswith('VmRSS:'):return int(line.split()[1])*1024
    except FileNotFoundError:return None
    return None


@contextmanager
def probe(command,receipt):
    """Actual Rust stream, bounded rows/stderr and sampled own-child resources."""
    command=list(map(str,command));started=time.time();output=hashlib.sha256();rows=0
    require(shutil.disk_usage(HERE).free >= 1024**3+32*1024**2,'CPU evidence capacity gate preserves1GiB reserve')
    require(mem_available()>=window.RSS_CEILING+512*1024**2,'insufficient available memory reserve for actual Rust load')
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=subprocess.DEVNULL)
    poller=selectors.DefaultSelector();samples=[];peak=0;reason=None;errors=bytearray();pending=bytearray();complete=False
    for stream,label in ((process.stdout,'stdout'),(process.stderr,'stderr')):
        os.set_blocking(stream.fileno(),False);poller.register(stream,selectors.EVENT_READ,label)
    def observe():
        nonlocal peak,reason
        rss=child_rss(process.pid);elapsed=time.time()-started
        if rss is not None:peak=max(peak,rss)
        samples.append({'elapsed_seconds':elapsed,'rss_bytes':rss,'mem_available_bytes':mem_available()})
        if rss is not None and rss>window.RSS_CEILING:reason='own_child_rss_ceiling'
        elif elapsed>1800:reason='own_child_timeout'
        elif shutil.disk_usage(HERE).free<1024**3:reason='own_child_disk_reserve_guard'
        require(reason is None,'actual Rust resource stop: '+str(reason))
    def iterator():
        nonlocal rows,complete
        last=0.
        while poller.get_map():
            if time.monotonic()-last>=.2:observe();last=time.monotonic()
            for key,_ in poller.select(.2):
                block=os.read(key.fileobj.fileno(),65536)
                if not block:
                    poller.unregister(key.fileobj);continue
                if key.data=='stderr':
                    errors.extend(block[:max(0,16384-len(errors))]);continue
                output.update(block);pending.extend(block)
                require(len(pending)<=16*1024**2,'oversize Rust row')
                while b'\n' in pending:
                    line,_,rest=pending.partition(b'\n');pending[:]=rest;rows+=1
                    value=loads(line.decode());require(isinstance(value,dict),'invalid Rust JSON row')
                    yield value
        require(not pending,'incomplete Rust row')
        code=process.wait();require(code==0,'actual Rust sampler failed: '+errors.decode(errors='replace'))
        complete=True
    try:
        yield iterator()
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        code=process.returncode
        receipt.update(command=command,started_unix=started,finished_unix=time.time(),exit_code=code,
                       completed=complete and code==0 and reason is None,stdout_sha256=output.hexdigest(),rows=rows,
                       stderr=errors.decode(errors='replace'),sampler_sha256=sha(command[0]),resource_stop_reason=reason,
                       signal=-code if code is not None and code<0 else None,timed_out=reason=='own_child_timeout',
                       peak_sampled_rss_bytes=peak,rss_ceiling_bytes=window.RSS_CEILING,memory_samples=samples,
                       remaining_bytes=shutil.disk_usage(HERE).free,
                       memory_scope='own launched Rust child; sampled RSS is not a guaranteed instantaneous peak')
        poller.close();process.stdout.close();process.stderr.close()


class Checker:
    def __init__(self,pack,bones,counts,rigid,invariants,initial,rigid_source,mappings=None):
        self.pack,self.bones,self.counts,self.rigid=pack,bones,counts,rigid
        self.initial,self.rigid_source=initial,rigid_source
        self.camera=G.matrix(initial['camera_world'],'initial camera');self.camera_inverse=np.linalg.inv(self.camera)
        self.rig=G.matrix(initial['rig_world'],'initial rig')
        require([(b[0],b[1]) for b in bones]==pack['bones'],'VRS/VRA hierarchy mismatch')
        self.rests=[];self.inverse_rests=[];self.rest_error=0.
        for name,parent,local,inverse_bind in bones:
            require(parent<len(self.rests),'runtime hierarchy not parent first')
            require(invariants['hierarchy'][name]==(bones[parent][0] if parent>=0 else None),'canonical source closure parent differs')
            rest=self.rests[parent]@local if parent>=0 else local
            self.rests.append(rest);self.inverse_rests.append(np.linalg.inv(rest))
            self.rest_error=max(self.rest_error,float(np.linalg.norm(rest[:3,3]-(BASIS@G.matrix(invariants['source_rest_world'][name],name))[:3,3])))
            require(np.max(np.abs(rest@inverse_bind-np.eye(4)))<LIMIT,'inverse bind/rest differs')
        require(self.rest_error<LIMIT,'runtime/source rest heads differ')
        self.actor_rest=[G.matrix(a['inverse_rest_global'],'actor inverse rest',columns=True) for a in pack['actors']]
        self.mesh_actor={}
        for i,actor in enumerate(pack['actors']):
            require(actor['meshes'],'actor geometry absent')
            for mesh in actor['meshes']:
                require(mesh not in self.mesh_actor,'rigid mesh ownership duplicated');self.mesh_actor[mesh]=i
        require(set(self.mesh_actor)==set(range(len(rigid))),'rigid mesh ownership incomplete')
        self.maps={} if mappings is None else {name:FrozenMap(value) for name,value in mappings.items()}
        if mappings is None:
            for i,actor in enumerate(pack['actors']):
                actual=G.transformed(np.concatenate([rigid[m] for m in actor['meshes']]),BASIS.T@self.actor_rest[i])
                self.maps[actor['name']]=FrozenMap.establish(actual,rigid_source[actor['name']])
        else:
            require(set(self.maps)=={'skin',*ACTORS},'frozen correspondence coverage differs')
    def check(self,result,source,skin,*,anchor=False):
        require(result.get('clip')==ACTION and result.get('game_axis') is False,'Rust clip/basis differs')
        for field in ('time','sample_time'):G.exact_time(result.get(field),source['time_seconds'],'Rust '+field)
        require(np.array_equal(G.matrix(source['camera_world'],'camera'),self.camera),'source static camera moved')
        require(np.array_equal(G.matrix(source['rig_world'],'rig'),self.rig),'source static rig moved')
        for field in ('camera_world_delta_from_frame1','rig_world_delta_from_frame1'):
            require(np.max(np.abs(G.matrix(source[field],field)-np.eye(4)))<1e-6,'source delta not static identity')
        samples=result.get('skin_meshes',[])
        require([r.get('mesh') for r in samples]==list(range(len(self.counts))),'runtime skin mesh order differs')
        actual=np.concatenate([G.finite(r.get('positions'),(count,3),'Rust skin') for r,count in zip(samples,self.counts)])
        if anchor:
            require(source['source_frame']==1 and 'skin' not in self.maps,'frame1 mapping already exists or wrong frame')
            self.maps['skin']=FrozenMap.establish(actual,G.transformed(skin,BASIS))
        mapping=self.maps['skin'];world=G.transformed(actual,BASIS.T)
        errors={'skin_world_m':mapping.error(world,skin),'skin_camera_relative_m':mapping.error(G.transformed(world,self.camera_inverse),G.transformed(skin,self.camera_inverse))}
        # Every source skin partition has its own reverse-coverage witness.
        per_skin={};start=0
        for name,count in zip(SKINS,COUNTS):
            per_skin[name]=float(np.linalg.norm(world[mapping.reverse[start:start+count]]-skin[start:start+count],axis=1).max());start+=count
        bones=result.get('bones',[]);require([r.get('name') for r in bones]==[b[0] for b in self.bones],'runtime bone72 order differs')
        be,bh,bc=[],[],[]
        for i,row in enumerate(bones):
            name=row['name'];actual=G.matrix(row.get('global'),name,columns=True)
            expected=BASIS@G.matrix(source['bone_deformation_world'][name],name)@BASIS.T
            be.append(float(np.max(np.abs(actual@self.inverse_rests[i]-expected))))
            want=G.matrix(source['bone_world'][name],name)[:3,3];got=G.transformed(actual[:3,3],BASIS.T)
            bh.append(float(np.linalg.norm(got-want)));bc.append(float(np.linalg.norm(G.transformed(got,self.camera_inverse)-G.transformed(want,self.camera_inverse))))
        errors.update(bone_deformation_matrix=max(be),bone_head_world_m=max(bh),bone_head_camera_relative_m=max(bc))
        actors=result.get('actors',[]);require([r.get('name') for r in actors]==list(ACTORS),'runtime actor order differs')
        visible=[];aw=[];ac=[]
        for i,row in enumerate(actors):
            name=row['name'];require(row.get('mesh_indices')==self.pack['actors'][i]['meshes'],'actor mesh mapping differs')
            require(type(row.get('visible')) is bool,'actor visibility not boolean')
            actual=G.matrix(row.get('global'),name,columns=True);applied=G.matrix(row.get('matrix'),name,columns=True)
            require(np.max(np.abs(applied-actual@self.actor_rest[i]))<LIMIT,'Rust actor applied/global inconsistent')
            expected=G.matrix(source['actors_world'][name],name);relative=G.matrix(source['actors_camera_relative'][name],name)
            require(np.max(np.abs(relative-self.camera_inverse@expected))<LIMIT,'source relative actor inconsistent')
            wanted=G.visible_matrix(expected);require(row['visible']==wanted,'actor visibility differs')
            visible.append(wanted)
            if wanted:
                world=BASIS.T@actual@BASIS
                aw.append(float(np.max(np.abs(world-expected))));ac.append(float(np.max(np.abs(self.camera_inverse@world-relative))))
        errors.update(actor_world_matrix=max(aw,default=0.),actor_camera_relative_matrix=max(ac,default=0.))
        meshes=result.get('rigid_meshes',[]);require([r.get('mesh') for r in meshes]==list(range(len(self.rigid))),'runtime rigid mesh order differs')
        positions=[]
        for m,row in enumerate(meshes):
            owner=self.mesh_actor[m]
            require(type(row.get('actor')) is int and row['actor']==owner and row.get('visible') is visible[owner],'runtime rigid ownership/visibility differs')
            positions.append(G.finite(row.get('positions'),self.rigid[m].shape,'runtime rigid'))
        rw=[];rc=[];rigid_vertices=0
        for i,name in enumerate(ACTORS):
            if not visible[i]:continue
            world=G.transformed(np.concatenate([positions[m] for m in self.pack['actors'][i]['meshes']]),BASIS.T)
            expected=G.transformed(self.rigid_source[name],G.matrix(source['actors_world'][name],name))
            rw.append(self.maps[name].error(world,expected));rc.append(self.maps[name].error(G.transformed(world,self.camera_inverse),G.transformed(expected,self.camera_inverse)))
            rigid_vertices+=len(expected)
        errors.update(rigid_world_m=max(rw,default=0.),rigid_camera_relative_m=max(rc,default=0.))
        passed=all(math.isfinite(v) and 0<=v<LIMIT for v in errors.values()) and all(v<LIMIT for v in per_skin.values())
        return {'source_frame':source['source_frame'],'time_seconds':source['time_seconds'],'errors':errors,'per_source_skin_maxima_m':per_skin,
                'visible':visible,'actor_visibility_checks':3,'source_skin_observations':sum(COUNTS),
                'visible_source_rigid_observations':rigid_vertices,'canonical_bone_observations':72,'passed':passed}

def validate_export(path,fbx_sha,selected,mode,index):
    receipt=read(path)
    for field,value in {'source_sha256':SOURCE_SHA,'fbx_sha256':fbx_sha,'rig_action':ACTION,
                        'sample_grid_sha256':GRID_SHA,'sample_frames':selected,'source_sample_count':len(selected),
                        'mode':mode,'chunk_index':index,'source_bytes_unchanged':True,
                        'in_memory_source_state_restored':True,'source_saved':False,'rendered':False,
                        'fbx_bake_step':1/SUBDIVISIONS}.items():
        require(receipt.get(field)==value,'source/export receipt differs: '+field)
    for name,expected in receipt.get('evidence_sha256',{}).items():pin(bounded(Path(path).parent,name),expected)
    require({'source-samples.json','camera-contract.json','fbx-take-contract.json'}<=set(receipt.get('evidence_sha256',{})),'export evidence incomplete')
    require(set(receipt.get('recipes',{}))=={'export_and_verify.py','dense_contract.py','dense_backend.py'},'source recipe set differs')
    for name,expected in receipt['recipes'].items():pin(WORK/'native-dense'/name,expected)
    if mode=='sample':
        require(receipt.get('source_window_recipe_sha256')==sha(window.WINDOW/'sample_source.py')
                and receipt.get('window_recipe_pins_sha256')==sha(window.WINDOW/'pins.json'),'source chunk window recipe differs')
    if mode=='export':
        validate_raw_key_grid(receipt.get('raw_key_grid',{}))
        backend=receipt.get('export_backend',{})
        require(backend.get('route')=='installed official export_fbx_bin.save with operator RNA defaults' and backend.get('effective_step')==1/256,'exact official backend sampling route differs')
        require(backend.get('effective_kwargs',{}).get('bake_anim_step')==1/256,'effective native export subdivision differs')
    return receipt

def validate_fbx(path,index,fbx_sha,source_sha,receipt_sha):
    value=read(path);selected=frames(index)
    for field,expected in {'source_sha256':SOURCE_SHA,'fbx_sha256':fbx_sha,'sample_grid_sha256':GRID_SHA,
                          'chunk_index':index,'sample_frames':selected,'samples':len(selected),
                          'skin_vertex_samples':len(selected)*sum(COUNTS),'source_oracle_sha256':source_sha,
                          'source_receipt_sha256':receipt_sha,'source_total_bones_including_helpers':148,
                          'runtime_support_verified':False,'camera_included_and_measured':True,
                          'camera_relative_geometry_measured':True,'subframe_parity':True,'passed':True}.items():
        exact(value.get(field),expected,'fresh FBX '+field)
    checks=value.get('checks',{})
    require(set(FBX_CHECKS)<=set(checks) and all(v is True for v in checks.values()),'missing/failed fresh FBX checks')
    require(set(value.get('maxima',{}))==set(FBX_KEYS),'fresh FBX measured maxima incomplete')
    for key,error in value['maxima'].items():require(0<=finite_number(error,key)<LIMIT,'fresh FBX threshold exceeded')
    require(0<=finite_number(value.get('camera_projection_ray_error'),'projection ray')<RAY_LIMIT,'projection ray threshold exceeded')
    window.validate_window(value.get('window_admission',{}),fbx_sha,selected,export_raw=read(WORK/'dense-output-v1/export-receipt.json')['raw_key_grid'])
    require(value.get('window_recipe_pins_sha256')==sha(window.WINDOW/'pins.json'),'chunk window recipe differs')
    require(value.get('full_import_control_receipt_sha256')==sha(window.CONTROL),'chunk bounded/full control identity differs')
    require(value.get('proof_scope')=='exact-independent-grid-chunk','chunk proof scope differs')
    require(value.get('off_key_source_frames')==[f for f in selected if f*256!=int(f*256)],'chunk off-key classification differs')
    require(value.get('independent_grid_sha256')==GRID_SHA,'independent source grid identity differs')
    return value

def own_pins():
    return {p.name:sha(p) for p in (HERE/'onehand_r2_common.py',HERE/'verify_onehand_r2.py',HERE/'admit_candidate.py',HERE/'bounded_vra.py',HERE/'window_admission.py',HERE/'focused_runtime.py',HERE/'conversion_admission.py')}

def runtime_pin_set(candidate):
    return {name:candidate['assets'][name]['sha256'] for name in ('asset.vra','asset.vrs','asset.vrm','manifest')}


def loading_path():return safe_output('runtime-parity/rust-loading-preflight.json')


def require_session_path(path):
    require(Path(path).resolve()==safe_output('runtime-parity/session.json'),
            'session must use the exact fresh runtime-parity/session.json path')


def validate_loading_row(row,frame,bones,counts,rigid,pack):
    require(row.get('clip')==ACTION and row.get('game_axis') is False,'Rust load clip/basis differs')
    for key in ('time','sample_time'):G.exact_time(row.get(key),(frame-1)/60,'Rust loading '+key)
    require([r.get('name') for r in row.get('bones',[])]==[b[0] for b in bones],'Rust loading canonical bone coverage differs')
    for bone in row['bones']:G.matrix(bone.get('global'),'Rust loading bone',columns=True)
    require([r.get('mesh') for r in row.get('skin_meshes',[])]==list(range(len(counts))),'Rust loading skin coverage differs')
    for mesh,count in zip(row['skin_meshes'],counts):G.finite(mesh.get('positions'),(count,3),'Rust loading skin')
    require([r.get('name') for r in row.get('actors',[])]==list(ACTORS),'Rust loading actor coverage differs')
    for actor,metadata in zip(row['actors'],pack['actors']):
        require(type(actor.get('visible')) is bool and actor.get('mesh_indices')==metadata['meshes'],'Rust loading actor metadata differs')
        for key in ('global','matrix'):G.matrix(actor.get(key),'Rust loading actor',columns=True)
    require([r.get('mesh') for r in row.get('rigid_meshes',[])]==list(range(len(rigid))),'Rust loading rigid coverage differs')
    for mesh,geometry in zip(row['rigid_meshes'],rigid):G.finite(mesh.get('positions'),geometry.shape,'Rust loading rigid')


def validate_loading_preflight(candidate):
    path=loading_path();value=read(path)
    for key,expected in {'schema':'rust-duty-onehand-rust-loading-preflight/v2',**candidate_identity(),
                         'passed':True,'loading_passed':True,'source_frames':[1.,96.],'samples':2,
                         'runtime_pins':runtime_pin_set(candidate),'sampler_sha256':SAMPLER_SHA,
                         'finite_complete_endpoint_geometry':True,'canonical_bones':72,
                         'full_grid_parity':False,'runtime_activated':False}.items():exact(value.get(key),expected,'Rust loading preflight '+key)
    process=value.get('process',{});window.validate_resource_process(process)
    sampler=str(ROOT/'prone-r15-runtime-20261016/cpu-probes-regenerated-v1/sample_viewmodel_clip')
    expected=[sampler,candidate['assets']['asset.vra']['path'],ACTION,'0.0',repr(95/60),'--clamp']
    require(process.get('command')==expected and process.get('rows')==2 and process.get('sampler_sha256')==SAMPLER_SHA,'actual Rust loading command/coverage differs')
    window.sha_string(process.get('stdout_sha256'))
    require(value.get('scanner_sha256')==sha(HERE/'bounded_vra.py'),'bounded admission scanner changed')
    return value


def loading_preflight(args):
    candidate=load_candidate();identity=candidate_identity();process={}
    path=loading_path();failure=safe_output('runtime-parity/rust-loading-preflight.failed.json')
    require(not path.exists() and not failure.exists(),'preserve previous Rust loading attempt')
    sampler=ROOT/'prone-r15-runtime-20261016/cpu-probes-regenerated-v1/sample_viewmodel_clip';pin(sampler,SAMPLER_SHA)
    asset=Path(candidate['assets']['asset.vra']['path'])
    try:
        pack,bones,counts,rigid=load_runtime(asset,ROOT/'low-vault-runtime-20261015/conversion-inputs/canonical-locomotion.vra',candidate['assets']['fbx']['sha256'])
        with probe([sampler,asset,ACTION,'0.0',repr(95/60),'--clamp'],process) as rows:
            for frame in (1.,96.):
                row=next(rows,None);require(row is not None,'actual Rust endpoint missing')
                validate_loading_row(row,frame,bones,counts,rigid,pack)
            require(next(rows,None) is None,'actual Rust endpoint extra row')
        window.validate_resource_process(process);load_candidate();require(identity==candidate_identity(),'candidate changed during Rust loading')
        value={'schema':'rust-duty-onehand-rust-loading-preflight/v2',**identity,'passed':True,'loading_passed':True,
               'source_frames':[1.,96.],'samples':2,'runtime_pins':runtime_pin_set(candidate),'sampler_sha256':SAMPLER_SHA,
               'scanner_sha256':sha(HERE/'bounded_vra.py'),'finite_complete_endpoint_geometry':True,'canonical_bones':72,
               'process':process,'full_grid_parity':False,'runtime_activated':False,
               'scope':'Actual unchanged Rust full-container load and finite endpoint sampling only; no source geometry equivalence claimed.'}
        write_new(path,value);validate_loading_preflight(candidate)
        return {'passed':True,'loading_preflight':str(path),'sha256':sha(path),'full_grid_parity':False}
    except BaseException as exc:
        write_new(failure,{'passed':False,**identity,'process':process,'error':type(exc).__name__+': '+str(exc)})
        raise


def initialize(args):
    candidate=load_candidate();validate_loading_preflight(candidate);admitted_sha=sha(HERE/'candidate.json');initial_recipe_pins=own_pins()
    require_session_path(args.session)
    for supplied,expected in ((args.export_process,WORK/'logs/export-dense-v1/export.exit.json'),
                              (args.rigid_process,ORIGINAL_WORK/'logs/rigid-frame1-v1/process-receipt.json'),
                              (args.conversion_process,WORK/'logs/conversion-v2/process-receipt.json')):
        require(Path(supplied).resolve()==expected.resolve(),'initialize process receipt must be its exact admitted stage')
    require(Path(args.asset).resolve()==Path(candidate['assets']['asset.vra']['path']),'runtime candidate path differs')
    require(Path(args.dense).resolve()==Path(candidate['assets']['fbx']['path']).parent,'dense candidate path differs')
    require(Path(args.rigid_frame1).resolve()==(ORIGINAL_WORK/'rigid-frame1-v1.json').resolve(),'shared independent rigid frame1 path differs')
    pin(args.rigid_frame1,FRAME1_SHA)
    require(not args.session.exists(),'refuse existing session')
    pin(args.sampler,SAMPLER_SHA);pin(ROOT/'recovery/onehand-camera-solve-v6/candidate-v1/onehand-r6-camera-reconstructed-v6.blend',SOURCE_SHA)
    dense=args.dense.resolve();fbx=dense/'aella_onehand_camera_reconstructed_v6.fbx';fbx_sha=sha(fbx)
    export=validate_export(dense/'export-receipt.json',fbx_sha,[1.,96.],'export',None)
    witness,invariants=source_index(dense/'source-samples.json',[1.,96.])
    first,skin=load_row(dense,next(iter(witness['frames'].values())),invariants['source_rest_world'])
    rigid,geometry=rigid_frame1(args.rigid_frame1,first)
    rigid_evidence=rigid_receipt(args.rigid_frame1,'frame1',None)
    pack,bones,counts,rigid_mesh=load_runtime(args.asset,args.canonical,fbx_sha)
    checker=Checker(pack,bones,counts,rigid_mesh,invariants,first,geometry)
    receipt={}
    with probe([args.sampler.resolve(),args.asset.resolve(),ACTION,'0','--clamp'],receipt) as rows:
        value=next(rows,None);require(value is not None,'Rust frame1 sample absent')
        record=checker.check(value,first,skin,anchor=True)
        require(next(rows,None) is None,'Rust frame1 returned extra samples')
    require(record['passed'],'actual Rust frame1 comparison failed')
    files={'rust_loading_preflight':file_record(loading_path()),'candidate':file_record(HERE/'candidate.json'),'candidate_spec':file_record(HERE/'candidate-spec.json'),'source':file_record(ROOT/'recovery/onehand-camera-solve-v6/candidate-v1/onehand-r6-camera-reconstructed-v6.blend'),'fbx':file_record(fbx),'rigid_frame1':file_record(args.rigid_frame1),'canonical':file_record(args.canonical),
           'sampler':file_record(args.sampler),'manifest':file_record(args.asset.parent/'manifest.json')}
    files['rigid_frame1_receipt']=rigid_evidence
    files['rigid_recipe_pins']=file_record(ORIGINAL_WORK/'native-rigid-v1/pins.json')
    for relative in read(ORIGINAL_WORK/'native-rigid-v1/pins.json')['files']:files['rigid_recipe/'+relative]=file_record(bounded(ROOT,relative))
    for name in export['recipes']:files['export_recipe/'+name]=file_record(WORK/'native-dense'/name)
    for name in ('asset.vra','asset.vrs','asset.vrm'):files[name]=file_record(args.asset.parent/name)
    for name in ('export-receipt.json','source-samples.json','camera-contract.json','fbx-take-contract.json'):files['dense/'+name]=file_record(dense/name)
    for descriptor in witness['frames'].values():
        for kind in ('row','skin'):files['dense/'+descriptor[kind+'_path']]=file_record(bounded(dense,descriptor[kind+'_path']))
    processes={'export':process_record(args.export_process,blender=True),'rigid_frame1':process_record(args.rigid_process,blender=True),
               'conversion':{key:value for key,value in conversion.validate(fbx_sha,read(args.conversion_process)['recipe_pins_sha256']).items() if key in ('file','record')}}
    conversion_record=processes['conversion']['record']
    require(conversion_record.get('fbx_sha256')==fbx_sha and conversion_record.get('canonical_sha256')==CANONICAL_SHA,'conversion input pins differ')
    conversion_pins=WORK/'runtime-conversion-v2/pins.json'
    pin(conversion_pins,conversion_record['recipe_pins_sha256']);files['conversion_recipe_pins']=file_record(conversion_pins)
    for relative,expected in read(conversion_pins)['files'].items():
        path=bounded(ROOT,relative);pin(path,expected);files['conversion_recipe/'+relative]=file_record(path)
    session={'schema':'rust-duty-onehand-cpu-session/v2',**candidate_identity(),'source_sha256':SOURCE_SHA,'action':ACTION,'action_fingerprint':ACTION_SHA,
             'sample_grid_sha256':GRID_SHA,'thresholds':THRESHOLDS,'files':files,'recipe_sha256':own_pins(),'helper_sha256':HELPERS,
             'invariants':invariants,'invariants_sha256':digest(invariants),'initial_source':first,
             'correspondence':{name:m.value for name,m in checker.maps.items()},'processes':processes,
             'anchor_rust_process':receipt,'anchor_record':record,'runtime_rest_head_error_m':checker.rest_error,
             'runtime_skin_vertices':sum(counts),'runtime_rigid_vertices':sum(len(v) for v in rigid_mesh),
             'canonical_bones':[b[0] for b in bones],
             'scope':'Static-source-camera CPU geometry parity only; no game camera, graphics, gameplay, approval or activation claim.'}
    session['correspondence_sha256']=digest(session['correspondence'])
    for rec in files.values():check_record(rec)
    load_candidate()
    require(sha(HERE/'candidate.json')==admitted_sha,'candidate changed during initialization')
    require(own_pins()==session['recipe_sha256']==initial_recipe_pins,'consumer changed during initialization')
    write_new(args.session,session)
    return {'session':str(args.session),'sha256':sha(args.session),'frame1_passed':True,'dense_complete':False}

def load_session(path):
    require_session_path(path)
    candidate=load_candidate();validate_loading_preflight(candidate)
    session=read(path)
    for key,value in candidate_identity().items():require(session.get(key)==value,'mixed or stale candidate session: '+key)
    for key,value in {'schema':'rust-duty-onehand-cpu-session/v2',**candidate_identity(),'source_sha256':SOURCE_SHA,'action':ACTION,
                      'action_fingerprint':ACTION_SHA,'sample_grid_sha256':GRID_SHA,'thresholds':THRESHOLDS,
                      'recipe_sha256':own_pins(),'helper_sha256':HELPERS}.items():
        require(session.get(key)==value,'session identity differs: '+key)
    require(session['invariants_sha256']==digest(session['invariants']),'session invariant digest differs')
    require(session['correspondence_sha256']==digest(session['correspondence']),'session mapping digest differs')
    require(set(session['correspondence'])=={'skin',*ACTORS},'session mapping coverage differs')
    for rec in session['files'].values():check_record(rec)
    for process in session['processes'].values():require(checked_json(process['file'])==process['record'],'source process receipt changed')
    require(session['anchor_rust_process'].get('exit_code')==0 and session['anchor_rust_process'].get('sampler_sha256')==SAMPLER_SHA
            and session['anchor_rust_process'].get('rows')==1 and session['anchor_record'].get('passed') is True,'frame1 actual Rust process not passed')
    require(session['anchor_rust_process'].get('command')==[session['files']['sampler']['path'],session['files']['asset.vra']['path'],ACTION,'0','--clamp'],
            'fresh actual Rust frame1 command/candidate differs')
    require(isinstance(session['anchor_rust_process'].get('stdout_sha256'),str) and len(session['anchor_rust_process']['stdout_sha256'])==64,'fresh actual Rust frame1 stream hash missing')
    window.validate_resource_process(session['anchor_rust_process'])
    grid()
    return session

def report_path(index):return safe_output(f'runtime-parity/receipts/chunk-{index:03d}.json')
def retirement_path(index):return safe_output(f'runtime-parity/retirement/chunk-{index:03d}.json')

def summarize(records):
    require(records,'empty CPU records')
    require(all(r.get('passed') is True and set(r.get('errors',{}))==set(ERROR_KEYS) for r in records),'failed/missing CPU measurements')
    for row in records:
        require(all(0<=finite_number(v,'CPU error')<LIMIT for v in row['errors'].values()),'CPU threshold exceeded')
        require(set(row.get('per_source_skin_maxima_m',{}))==set(SKINS),'per-source skin coverage missing')
        require(all(0<=finite_number(v,'skin partition error')<LIMIT for v in row['per_source_skin_maxima_m'].values()),'skin partition threshold exceeded')
        require(len(row.get('visible',[]))==3 and all(type(v) is bool for v in row['visible']),'actor visibility witnesses missing')
        for field,expected in {'actor_visibility_checks':3,'source_skin_observations':sum(COUNTS),'canonical_bone_observations':72}.items():
            exact(row.get(field),expected,'CPU count '+field)
        require(type(row.get('visible_source_rigid_observations')) is int and row['visible_source_rigid_observations']>=0,'invalid rigid observation count')
    return {'maxima':{key:max(r['errors'][key] for r in records) for key in ERROR_KEYS},
            'worst':{key:{'source_frame':max(records,key=lambda r:r['errors'][key])['source_frame'],
                          'value':max(r['errors'][key] for r in records)} for key in ERROR_KEYS},
            'per_source_skin_maxima_m':{name:max(r['per_source_skin_maxima_m'][name] for r in records) for name in SKINS},
            'skin_vertex_observations':sum(r['source_skin_observations'] for r in records),
            'actor_visibility_checks':sum(r['actor_visibility_checks'] for r in records),
            'canonical_bone_observations':sum(r['canonical_bone_observations'] for r in records),
            'visible_source_rigid_observations':sum(r['visible_source_rigid_observations'] for r in records)}

def require_runtime_focus(session):
    import focused_runtime
    return focused_runtime.validate(session)


def runtime_focus(args):
    import focused_runtime
    return focused_runtime.run(args)


def consume(args):
    session=load_session(args.session);require_runtime_focus(session);selected=frames(args.chunk_index);chunk=safe_output(f'chunks/chunk-{args.chunk_index:03d}')
    require(Path(args.rigid_chunk).resolve()==(chunk/'rigid-samples.json').resolve(),'rigid chunk must come from exact new chunk')
    require(Path(args.rigid_process).resolve()==safe_output(f'logs/rigid-v2-chunk-{args.chunk_index:03d}/process-receipt.json').resolve(),'rigid process must come from exact new chunk')
    require(not report_path(args.chunk_index).exists(),'refuse existing chunk runtime receipt')
    files=session['files'];fbx_sha=files['fbx']['sha256']
    witness,invariants=source_index(chunk/'source-samples.json',selected,session['invariants_sha256'])
    export=validate_export(chunk/'export-receipt.json',fbx_sha,selected,'sample',args.chunk_index)
    fbx=validate_fbx(chunk/'fresh-import-parity.json',args.chunk_index,fbx_sha,sha(chunk/'source-samples.json'),sha(chunk/'export-receipt.json'))
    rigid,geometry=rigid_frame1(files['rigid_frame1']['path'],session['initial_source'])
    rigid_result=rigid_chunk(args.rigid_chunk,args.chunk_index,rigid)
    if 'frame1_witness_sha256' in rigid_result:
        require(rigid_result['frame1_witness_sha256']==files['rigid_frame1']['sha256'],'rigid optimized baseline pin differs')
    rigid_evidence=rigid_receipt(args.rigid_chunk,'chunk',args.chunk_index)
    pack,bones,counts,rigid_mesh=load_runtime(Path(files['asset.vra']['path']),Path(files['canonical']['path']),fbx_sha)
    checker=Checker(pack,bones,counts,rigid_mesh,invariants,session['initial_source'],geometry,session['correspondence'])
    process={};records=[]
    processes={'source':process_record(WORK/'logs'/f'chunk-{args.chunk_index:03d}'/'sample.exit.json',blender=True),
               'fbx':process_record(WORK/'logs'/f'chunk-{args.chunk_index:03d}'/'verify.exit.json',blender=True),
               'rigid':process_record(args.rigid_process,blender=True),'rust':process}
    validate_chunk_processes(processes,args.chunk_index,session)
    command=[files['sampler']['path'],files['asset.vra']['path'],ACTION,*[repr((f-1)/60) for f in selected],'--clamp']
    with probe(command,process) as rows:
        for offset,descriptor in enumerate(witness['frames'].values()):
            pose=next(rows,None);require(pose is not None,'Rust sampler ended early')
            source,skin=load_row(chunk,descriptor,invariants['source_rest_world'])
            record=checker.check(pose,source,skin);record['global_sample_index']=args.chunk_index*64+offset
            records.append(record)
        require(next(rows,None) is None,'Rust sampler emitted extra rows')
    summary=summarize(records)
    evidence={name:file_record(chunk/name) for name in ('source-samples.json','export-receipt.json','fresh-import-parity.json','camera-contract.json','fbx-take-contract.json')}
    evidence['rigid-samples']=file_record(args.rigid_chunk)
    evidence['rigid-source-receipt']=rigid_evidence
    raw=[]
    for descriptor in witness['frames'].values():
        for kind in ('row','skin'):raw.append(file_record(bounded(chunk,descriptor[kind+'_path'])))
    report={'schema':'rust-duty-onehand-cpu-chunk/v2',**candidate_identity(),'passed':True,'complete_chunk':True,'runtime_activated':False,
            'source_sha256':SOURCE_SHA,'action':ACTION,'action_fingerprint':ACTION_SHA,'fbx_sha256':fbx_sha,
            'sample_grid_sha256':GRID_SHA,'chunk_index':args.chunk_index,'sample_frames':selected,
            'global_sample_indices':list(range(args.chunk_index*64,args.chunk_index*64+len(selected))),
            'session_sha256':sha(args.session),'correspondence_sha256':session['correspondence_sha256'],
            'thresholds':THRESHOLDS,'samples':len(selected),'records':records,'summary':summary,
            'source_fbx':fbx,'evidence':evidence,'raw_files':raw,'processes':processes,
            'focused_runtime_sha256':sha(HERE/'focused-runtime.json'),
            'failures':{'missing':0,'reordered':0,'duplicates':0,'visibility':0,'numeric':0},
            'runtime_pins':{name:files[name]['sha256'] for name in ('asset.vra','asset.vrs','asset.vrm','manifest','sampler','canonical')}}
    load_session(args.session)
    for rec in [*evidence.values(),*raw]:check_record(rec)
    write_new(report_path(args.chunk_index),report)
    return {'chunk':args.chunk_index,'passed':True,'receipt':str(report_path(args.chunk_index)),
            'receipt_sha256':sha(report_path(args.chunk_index)),'samples':len(selected),'skin_vertex_observations':summary['skin_vertex_observations']}

def validate_chunk_processes(processes,index,session):
    chunk=safe_output(f'chunks/chunk-{index:03d}')
    source=session['files']['source']['path'];dense=str(Path(session['files']['fbx']['path']).parent)
    expected_blender=session['processes']['export']['record']['blender_sha256']
    for name,mode in (('source','sample'),('fbx','verify'),('rigid','chunk')):
        record=processes[name]['record'];command=record.get('command',[])
        require(command and record.get('blender_sha256')==expected_blender,'chunk native binary differs')
        base=[command[0],'--background','--factory-startup','--disable-autoexec']
        if name=='rigid':
            expected=base+[source,'--python-exit-code','1','--python',str(WORK/'native-rigid-v2/sample_rigid.py'),'--','chunk',
                           '--output',str(chunk/'rigid-samples.json'),'--chunk-index',str(index),
                           '--frame1-witness',str(ORIGINAL_WORK/'rigid-frame1-v1.json'),'--frame1-sha256',FRAME1_SHA]
        else:
            window.validate_resource_process(record)
            require(record.get('window_recipe_pins_sha256')==sha(window.WINDOW/'pins.json'),'native chunk window pin differs')
            expected=base+['--threads','1']+([source] if name=='source' else [])+[
                '--python-exit-code','1','--python',str(window.WINDOW/('sample_source.py' if name=='source' else 'verify_window.py')),'--',mode if name=='source' else 'chunk']
            if name=='source':expected+=['--output-dir',str(chunk),'--dense-dir',dense]
            expected+=['--chunk-index',str(index)]
        require(command==expected,'native chunk command script/index/new-root inputs differ: '+name)
        require(record.get('exit_code')==0 and type(record.get('exit_code')) is int,'native chunk failed')
        require(record.get('completed',True) is True and record.get('timed_out',False) is False,'native chunk process incomplete')
    return True


def validate_cpu_report(report,index,session,session_sha,*,check_files=True):
    for key in ('proof_root','candidate_sha256','candidate_spec_sha256','runtime_subdivisions'):
        require(key in session and report.get(key)==session[key],'mixed candidate CPU receipt: '+key)
    selected=frames(index)
    for field,value in {'schema':'rust-duty-onehand-cpu-chunk/v2','passed':True,'complete_chunk':True,
                        'source_sha256':SOURCE_SHA,'action':ACTION,'action_fingerprint':ACTION_SHA,
                        'fbx_sha256':session['files']['fbx']['sha256'],'sample_grid_sha256':GRID_SHA,'chunk_index':index,
                        'sample_frames':selected,'samples':len(selected),'session_sha256':session_sha,
                        'correspondence_sha256':session['correspondence_sha256'],'thresholds':THRESHOLDS,
                        'global_sample_indices':list(range(index*64,index*64+len(selected))),
                        'failures':{'missing':0,'reordered':0,'duplicates':0,'visibility':0,'numeric':0},
                        'runtime_pins':{name:session['files'][name]['sha256'] for name in ('asset.vra','asset.vrs','asset.vrm','manifest','sampler','canonical')}}.items():
        exact(report.get(field),value,'CPU receipt '+field)
    window.sha_string(report.get('focused_runtime_sha256'))
    records=report.get('records',[])
    require([r.get('source_frame') for r in records]==selected,'CPU row ordering/coverage differs')
    require([r.get('global_sample_index') for r in records]==report['global_sample_indices'],'CPU global row indices differ')
    require([r.get('time_seconds') for r in records]==[(f-1)/60 for f in selected],'CPU exact requested time grid differs')
    require(summarize(records)==report.get('summary'),'CPU summary/maxima differs from measured records')
    process=report.get('processes',{});require(set(process)=={'source','fbx','rigid','rust'},'process receipts incomplete')
    rust=process['rust']
    require(rust.get('exit_code')==0 and type(rust.get('exit_code')) is int and rust.get('rows')==len(selected)
            and rust.get('sampler_sha256')==SAMPLER_SHA,'actual Rust process incomplete/failed')
    require(rust.get('command')==[session['files']['sampler']['path'],session['files']['asset.vra']['path'],ACTION,
                                  *[repr((f-1)/60) for f in selected],'--clamp'],'actual Rust command clock/target differs')
    require(isinstance(rust.get('stdout_sha256'),str) and len(rust['stdout_sha256'])==64,'Rust byte-stream hash absent')
    if check_files:
        require_runtime_focus(session)
        require(report.get('focused_runtime_sha256')==sha(HERE/'focused-runtime.json'),'runtime focused prerequisite differs')
        window.validate_resource_process(rust)
        validate_chunk_processes(process,index,session)
        for name in ('source','fbx','rigid'):
            require(checked_json(process[name]['file'])==process[name]['record'],'process receipt changed')
            require(process[name]['record'].get('exit_code')==0,'source/FBX/rigid process failed')
        for rec in report['evidence'].values():check_record(rec)
        fbx=validate_fbx(report['evidence']['fresh-import-parity.json']['path'],index,session['files']['fbx']['sha256'],
                         report['evidence']['source-samples.json']['sha256'],report['evidence']['export-receipt.json']['sha256'])
        require(fbx==report['source_fbx'],'retained FBX summary differs')
        validate_raw_state(report,index)
    return records

def validate_raw_state(report,index):
    chunk=safe_output(f'chunks/chunk-{index:03d}').resolve()
    source=read(check_record(report['evidence']['source-samples.json']))
    require(list(source.get('frames',{}))==[str(f) for f in frames(index)],'retained source descriptor grid differs')
    expected=[]
    for i,(frame,row) in enumerate(zip(frames(index),source['frames'].values())):
        require(row.get('source_frame')==frame,'retained source descriptor frame differs')
        for kind,folder,ext in [('row','sample-rows','json'),('skin','skin-rows','npz')]:
            require(row.get(kind+'_path')==f'{folder}/{i:04d}.{ext}','retained source descriptor index differs')
            expected.append((str(bounded(chunk,row[kind+'_path']).resolve()),row[kind+'_sha256']))
    raw=report.get('raw_files',[])
    require([(r.get('path'),r.get('sha256')) for r in raw]==expected,'measured raw hash receipts differ from source descriptor')
    exists=[Path(r['path']).exists() for r in raw]
    if all(exists):
        for record in raw:check_record(record)
    else:
        require(not any(exists),'partial raw chunk retirement; diagnostic must be preserved')
        retired=read(retirement_path(index))
        for key in ('proof_root','candidate_sha256','candidate_spec_sha256','runtime_subdivisions'):
            require(retired.get(key)==report.get(key),'retirement candidate/root differs: '+key)
        for key,value in {'schema':'rust-duty-onehand-chunk-retirement/v2','passed':True,'chunk_index':index,
                          'session_sha256':report['session_sha256'],'runtime_receipt_sha256':sha(report_path(index)),
                          'retired_files':raw,'original_source_deleted':False,'dense_export_deleted':False}.items():
            exact(retired.get(key),value,'retirement receipt '+key)


def aggregate_reports(reports,session,session_sha,*,check_files=True):
    require(len(reports)==CHUNK_COUNT,'complete aggregate requires all67 chunks')
    require(len({r.get('focused_runtime_sha256') for r in reports})==1,'mixed actual Rust focus receipts')
    records=[]
    for index,report in enumerate(reports):records.extend(validate_cpu_report(report,index,session,session_sha,check_files=check_files))
    require([r['source_frame'] for r in records]==grid(),'aggregate ordered4240 grid differs')
    require([r['global_sample_index'] for r in records]==list(range(TOTAL_SAMPLES)),'aggregate duplicate/missing/reordered global indices')
    summary=summarize(records)
    require(summary['skin_vertex_observations']==TOTAL_OBSERVATIONS,'aggregate requires43,392,160 skin observations')
    require(summary['canonical_bone_observations']==TOTAL_SAMPLES*72 and summary['actor_visibility_checks']==TOTAL_SAMPLES*3,'aggregate bone/actor coverage differs')
    return {'schema':'rust-duty-onehand-cpu-aggregate/v2',**{key:session[key] for key in ('proof_root','candidate_sha256','candidate_spec_sha256','runtime_subdivisions')},'passed':True,'complete':True,'source_sha256':SOURCE_SHA,
            'action':ACTION,'action_fingerprint':ACTION_SHA,'sample_grid_sha256':GRID_SHA,'session_sha256':session_sha,
            'correspondence_sha256':session['correspondence_sha256'],'focused_runtime_sha256':reports[0]['focused_runtime_sha256'],'chunks':CHUNK_COUNT,'samples':TOTAL_SAMPLES,
            'sample_frames':grid(),'thresholds':THRESHOLDS,'summary':summary,
            'source_fbx_bone_observations':TOTAL_SAMPLES*148,'runtime_canonical_bones':72,
            'source_fbx_maxima':{key:max(r['source_fbx']['maxima'][key] for r in reports) for key in FBX_KEYS},
            'source_fbx_projection_ray_max':max(r['source_fbx']['camera_projection_ray_error'] for r in reports),
            'runtime_activated':False,'scope':session.get('scope','CPU geometry only'),
            'not_measured':['GPU/raster appearance','game camera placement/projection','gameplay and Windows path','arbitrary times outside exact independent grid']}

def aggregate(args):
    session=load_session(args.session)
    reports=[read(report_path(i)) for i in range(CHUNK_COUNT)]
    result=aggregate_reports(reports,session,sha(args.session))
    result['chunk_receipts']=[file_record(report_path(i)) for i in range(CHUNK_COUNT)]
    result['focused_runtime_receipt']=file_record(HERE/'focused-runtime.json')
    result['rust_loading_preflight']=file_record(loading_path())
    write_new(args.output,result)
    return {'passed':True,'complete':True,'samples':TOTAL_SAMPLES,'skin_vertex_observations':TOTAL_OBSERVATIONS,'receipt':str(args.output),'sha256':sha(args.output)}

def retirement_plan(index,report,session,session_sha):
    validate_cpu_report(report,index,session,session_sha)
    chunk=safe_output(f'chunks/chunk-{index:03d}').resolve();require(chunk.is_dir(),'chunk directory missing')
    descriptor=read(chunk/'source-samples.json');expected=[]
    for row in descriptor['frames'].values():
        for kind in ('row','skin'):expected.append(bounded(chunk,row[kind+'_path']).resolve())
    require([Path(rec['path']) for rec in report['raw_files']]==expected,'retirement file set differs from measured chunk descriptor')
    require(len(expected)==2*len(frames(index)) and len(set(expected))==len(expected),'retirement file count/duplicates differ')
    for rec in report['raw_files']:
        path=check_record(rec)
        require(not path.is_symlink() and path.resolve().is_relative_to(chunk),'retirement path escaped newly generated chunk')
        require(path.parent.name in ('sample-rows','skin-rows') and path.suffix in ('.json','.npz'),'retirement file kind forbidden')
    require(not retirement_path(index).exists(),'refuse repeated retirement')
    return {'schema':'rust-duty-onehand-chunk-retirement/v2',**candidate_identity(),'passed':False,'chunk_index':index,'session_sha256':session_sha,
            'runtime_receipt_sha256':sha(report_path(index)),'source_sha256':SOURCE_SHA,'grid_sha256':GRID_SHA,
            'retired_files':report['raw_files'],'preserved_files':list(report['evidence'].values()),
            'original_source_deleted':False,'dense_export_deleted':False}

def retire(args):
    session=load_session(args.session);report=read(report_path(args.chunk_index))
    plan=retirement_plan(args.chunk_index,report,session,sha(args.session))
    if not args.execute:return {**plan,'plan_only':True}
    # This code is deliberately never invoked by consume/aggregate or initialize.
    # Only a separate coordinator-controlled command may retire measured arrays.
    # A durable pre-delete plan survives partial interruption; no original files.
    journal=HERE/'retirement'/f'chunk-{args.chunk_index:03d}.plan.json'
    write_new(journal,plan)
    for rec in plan['retired_files']:
        path=check_record(rec);path.unlink()
    require(all(not Path(r['path']).exists() for r in plan['retired_files']),'retirement incomplete')
    plan.update(passed=True,plan_sha256=sha(journal),completed_unix=time.time())
    write_new(retirement_path(args.chunk_index),plan)
    return {'retired_chunk':args.chunk_index,'passed':True,'files':len(plan['retired_files']),
            'retirement_receipt':str(retirement_path(args.chunk_index))}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session',type=Path,default=HERE/'session.json')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('loading-preflight')
    sub.add_parser('runtime-focus')
    init=sub.add_parser('initialize')
    init.add_argument('--conversion-process',type=Path,default=WORK/'logs/conversion-v2/process-receipt.json')
    for name in ('dense','asset','canonical','sampler','rigid-frame1','rigid-process','export-process'):
        init.add_argument('--'+name,type=Path,required=True)
    consume_parser=sub.add_parser('consume');consume_parser.add_argument('--chunk-index',type=int,required=True)
    consume_parser.add_argument('--rigid-chunk',type=Path,required=True);consume_parser.add_argument('--rigid-process',type=Path,required=True)
    aggregate_parser=sub.add_parser('aggregate');aggregate_parser.add_argument('--output',type=Path,default=HERE/'aggregate.json')
    retire_parser=sub.add_parser('retire');retire_parser.add_argument('--chunk-index',type=int,required=True)
    retire_parser.add_argument('--execute',action='store_true')
    args=parser.parse_args(argv)
    try:
        require_session_path(args.session)
        result={'loading-preflight':loading_preflight,'runtime-focus':runtime_focus,'initialize':initialize,'consume':consume,'aggregate':aggregate,'retire':retire}[args.command](args)
    except Exception as exc:
        print(json.dumps({'passed':False,'complete':False,'error':type(exc).__name__+': '+str(exc)}),file=sys.stderr)
        return 1
    print(json.dumps(result,indent=2,allow_nan=False));return 0

if __name__=='__main__':raise SystemExit(main())

"""Native bodies only. Importing this file never imports bpy or starts work.

All source selection/restoration, skin observations, transform history, static
geometry and packed frame math are audited exact fragments of frozen helpers.
Only context/IO/receipt boundaries are versioned here.
"""
import bisect,hashlib,inspect,json,math,struct,sys
from pathlib import Path
from pinned_code import HERE,require,file_sha,helpers,execute
from stage_context import capacity,write_new,MIB
ACTION='aella_mantle_onehand_r6_camera_reconstructed_v6'
CAMERA='RD First Person Review'
ACTORS=['hk416_weapon','hk416_magazine','hk416_magazine_outgoing']
SKINS=['Actual arms mesh 0','Actual arms mesh 1','Actual arms mesh 2']
FOCUS_BONES=('hand_l','ring_01_l','ring_02_l','ring_03_l','MCH_curl_ring_03_l','righthand_prop_lefthand')
MAXIMA=('bone_deformation_world_matrix','bone_head_world_m','actor_world_matrix','actor_camera_relative_matrix','camera_world_matrix','rig_world_matrix','skin_world_m','skin_camera_relative_m')
BASIS=((1,0,0,0),(0,0,1,0),(0,-1,0,0),(0,0,0,1))
SETTINGS={'use_selection':True,'object_types':{'MESH','ARMATURE','CAMERA'},'add_leaf_bones':False,'bake_anim':True,'bake_anim_use_nla_strips':False,'bake_anim_use_all_actions':False,'bake_anim_use_all_bones':True,'bake_anim_simplify_factor':0.,'bake_anim_step':1/256,'path_mode':'AUTO','axis_forward':'-Z','axis_up':'Y','use_armature_deform_only':False}
PATCH_SHA={'blen_read_animations':'757bd21550d94e2190881ec6b0eb0ce80b275d2a230055cf7702044fe6dcc6e2','blen_store_keyframes_multi':'793a389ebde0e71ec3cec54e731c861753aa08015355904777a8c39b70da3a4e'}

def environment(ctx,bpy,np,Matrix):
    base={'bpy':bpy,'np':np,'Matrix':Matrix,'Path':Path,'json':json,'math':math,'struct':struct,'hashlib':hashlib,'inspect':inspect,'sys':sys,'bisect':bisect,
          'require':require,'sha':file_sha,'file_sha':file_sha,'digest':ctx.cc.digest,'ACTION':ACTION,'CAMERA':CAMERA,'ACTORS':ACTORS,'SKINS':SKINS,
          'SUBDIVISIONS':256,'KEY_COUNT':24321,'EXPECTED_CURVES':1379,'RAW_CURVES':1379,'KEY_CAP':4096,'PATCH_SHA':PATCH_SHA,'EXPECTED_PATCHES':PATCH_SHA,
          'OWNERS':['Arms',*ACTORS,CAMERA],'helper_recipe_sha256':file_sha(HERE/'AUDITED_FRAGMENTS.json'),
          'ROW_JSON_BUDGET':128*1024,'ROW_SKIN_BUDGET':256*1024,'ROW_BUDGET':384*1024,'assert_free':capacity,
          'MAXIMA':MAXIMA,'BASIS':BASIS,'FRAME_BYTES':3007,'CANONICAL':ctx.pin('canonical').path,
          'SOURCE':ctx.pin('generated_source').path,'mat':lambda m:[list(r) for r in m],
          'err':lambda x,y:max(abs(x[i][j]-y[i][j]) for i in range(4) for j in range(4))}
    return helpers(ctx.root('audited_source'),base)

def canonical_source_descriptors(rows,root,frames):
    """Audited nonnumeric boundary: exact platform paths to canonical POSIX.

    The original source_rows fragment is unchanged. Require its exact expected
    relative filenames; do not replace arbitrary separators or normalize input.
    No arrays, row bytes, hashes, frame order or numeric values are rewritten.
    root may be PureWindowsPath in CPU interface fixtures.
    """
    require(list(rows)==[str(f) for f in frames],'source descriptor frame order differs')
    for i,f in enumerate(frames):
        row=rows[str(f)]
        require(row['source_frame']==f,'source descriptor time differs')
        for role,directory,suffix in (('row_path','sample-rows','json'),('skin_path','skin-rows','npz')):
            relative=(root/directory/f'{i:04d}.{suffix}').relative_to(root)
            require(row[role]==str(relative),'source descriptor platform path differs')
            row[role]=relative.as_posix()
    return rows

def source_stage(ctx,e):
    bpy=e['bpy'];source=ctx.pin('generated_source').verify()
    require('FINISHED' in bpy.ops.wm.open_mainfile(filepath=str(source),load_ui=False,use_scripts=False),'generated source open failed')
    require(Path(bpy.data.filepath)==source,'wrong source opened')
    A=bpy.data.objects['Arms'];C=bpy.data.objects[CAMERA];S=bpy.context.scene
    require(S.camera==C and C.type=='CAMERA' and (S.render.fps,S.render.fps_base)==(60,1.),'source camera/clock differs')
    require(len(A.pose.bones)==148,'all 148 source bones required')
    require(e['action_fingerprint'](bpy.data.actions[ACTION])==dict(ctx.action_hashes)['legacy'],'generated Action fingerprint differs')
    require(list(bpy.data.actions[ACTION].frame_range)==[1.,96.],'generated Action extent differs')
    e.update(A=A,C=C,S=S,P=ctx.output,FRAMES=ctx.frames())
    execute('source_capture',e)
    try:
        # Restoration covers failure during isolation too, unlike an unguarded setup.
        execute('source_select',e)
        if ctx.stage in ('export','control-export','source-focus','source-chunk'):
            execute('source_rows',e)
            canonical_source_descriptors(e['rows'],ctx.output,ctx.frames())
            result={'generated_source_sha256':ctx.pin('generated_source').sha256,'approved_source_sha256':ctx.cc.APPROVED_SHA,
                    'rig_action':ACTION,'rig_action_fingerprint':dict(ctx.action_hashes)['legacy'],'camera_action':None,'camera_action_fingerprint':None,
                    'source_rest_world':{n:e['mat'](m) for n,m in e['rest'].items()},
                    'hierarchy':{b.name:b.parent.name if b.parent else None for b in A.data.bones},
                    'projection':e['projection'],'topology':e['topology'],'frames':e['rows']}
            write_new(ctx.output/'source-samples.json',result)
            payload={'samples':len(ctx.frames()),'sample_frames':ctx.frames(),'source_samples_sha256':file_sha(ctx.output/'source-samples.json')}
            if ctx.stage in ('export','control-export'):
                # Restore frame-1 bind before export. No source save/render call.
                S.frame_set(1);A.update_tag();C.update_tag();bpy.context.view_layer.update();bpy.context.evaluated_depsgraph_get().update()
                require(e['err'](A.matrix_world,e['R0'])==0 and e['err'](C.matrix_world,e['C0'])==0,'frame-1 bind changed')
                bpy.ops.object.select_all(action='DESELECT')
                for n in ['Arms',*SKINS,*ACTORS,CAMERA]:bpy.data.objects[n].select_set(True)
                bpy.context.view_layer.objects.active=A
                path=ctx.output/'animation.fbx';capacity(ctx.output,256*MIB)
                if ctx.stage=='export':
                    status,backend=e['export_exact_grid'](path,SETTINGS);require('FINISHED' in status,'official export failed')
                    raw=e['raw_key_grid'](path)
                else:
                    # 1/64 is representable by the official RNA operator (unlike
                    # dense1/256). The control is generated on this target from
                    # the same admitted source, never copied from Linux.
                    settings=control_export_settings()
                    require(bpy.ops.export_scene.fbx.get_rna_type().properties['bake_anim_step'].hard_min<=1/64,'control operator clamp changed')
                    status=bpy.ops.export_scene.fbx(filepath=str(path),**settings);require('FINISHED' in status,'target control export failed')
                    backend={'route':'installed official bpy.ops.export_scene.fbx','effective_step':1/64,'effective_settings':{k:sorted(v) if isinstance(v,set) else v for k,v in settings.items()}}
                    raw=control_raw_grid(e,path)
                require(path.stat().st_size<=256*MIB,'FBX output exceeds original cap')
                payload.update(actual_fbx_sha256=file_sha(path),raw_key_grid=raw,backend=backend,export_bind_frame=1)
            else:ctx.pin('actual_fbx').verify()
        else:
            payload=rigid_stage(ctx,e)
    finally:
        execute('source_restore',e)
        after=json.loads(json.dumps({'snapshot':e['snapshot'](bpy),'extra':e['extra_snapshot']()},sort_keys=True))
        restored=after==e['before'];ctx.pin('generated_source').verify()
        if not restored:write_new(ctx.output/'restoration-failure.json',{'restored':False})
        require(restored,'exact in-memory source restoration failed')
    payload.update(source_bytes_unchanged=True,in_memory_source_state_restored=True,source_saved=False,rendered=False)
    return payload

def rigid_stage(ctx,e):
    bpy,A,C,S=(e[k] for k in ('bpy','A','C','S'))
    def frame(f):
        S.frame_set(math.floor(f),subframe=f-math.floor(f));A.update_tag();C.update_tag();bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();dg.update();return dg
    originals={};actors={};dg=frame(1.)
    for name in ACTORS:
        local,buffers=e['geometry'](name,dg);r=e['geometry_record'](local.tolist(),buffers.polygons())
        require(not bpy.data.objects[name].hide_render,'hidden frame-1 actor')
        originals[name]=buffers
        actors[name]={**r,
                      'buffers':buffers.digests(),'world_at_frame1':e['mat'](bpy.data.objects[name].matrix_world),'hide_render':False}
    if ctx.stage in ('rigid-chunk','rigid-focus'):
        baseline=ctx.cc.strict_json(ctx.pin('rigid_frame1').verify(),32*MIB)
        require(baseline['schema']=='rust-duty-windows-rigid-frame1/v1' and baseline['binding']==ctx.binding,'fresh same-target frame1 required')
        require(baseline['actors']==actors,'frame1 geometry differs from actual target witness')
    rows=[]
    for f in ctx.frames():
        dg=frame(f);row={}
        for name in ACTORS:
            _,buffers=e['geometry'](name,dg)
            require(buffers==originals[name] and not bpy.data.objects[name].hide_render,'rigid full float64/topology bytes changed')
            row[name]={'geometry_sha256':actors[name]['geometry_sha256'],'buffers':buffers.digests(),'hide_render':False}
        rows.append({'source_frame':f,'actors':row})
    if ctx.stage=='rigid-frame1':
        write_new(ctx.output/'rigid-frame1.json',{'schema':'rust-duty-windows-rigid-frame1/v1','binding':ctx.binding,'generated_source_sha256':ctx.pin('generated_source').sha256,'approved_source_sha256':ctx.cc.APPROVED_SHA,'source_frame':1,'rig_action':ACTION,'rig_action_fingerprint':dict(ctx.action_hashes)['legacy'],'actors':actors})
    return {'samples':rows,'source_frames':ctx.frames(),'actor_count':3,'full_float64_and_topology_bytes_compared':True,'frame1_buffer_digests':{n:r['buffers'] for n,r in actors.items()}}

def empty_scene(e):
    bpy=e['bpy'];bpy.ops.wm.read_factory_settings(use_empty=True);S=bpy.context.scene;S.render.fps=60;S.render.fps_base=1;e['S']=S

def import_stage(ctx,e):
    empty_scene(e);frames=ctx.frames();is_control=ctx.stage.startswith('control-');pin=ctx.pin('control_fbx' if is_control else 'actual_fbx');path=pin.verify()
    e.update(FRAMES=frames,fbx=path,fbx_sha=pin.sha256)
    if ctx.stage=='control-full':return full_control(ctx,e,path)
    window=e['import_window'](path,pin.sha256,64 if is_control else 256,frames)
    require(window['retained_key_count']<=2051,'native wrapper key ceiling exceeded')
    e['window']=window;execute('import_pose_setup',e)
    if is_control:
        expected=ctx.cc.strict_json(ctx.pin('full_control').verify(),32*MIB)
        require(expected['schema']=='rust-duty-windows-full-control/v1' and expected['binding']==ctx.binding,'target full oracle binding differs')
        require(expected['fbx_sha256']==pin.sha256 and expected['source_frames']==frames,'target same-file full control differs')
        e['expected']=expected;execute('bounded_control_compare',e)
        payload={'schema':'rust-duty-fbx-bounded-full-import-control/v1','passed':not e['mismatches'],'fbx_sha256':pin.sha256,
                 'full_import_control_sha256':ctx.pin('full_control').sha256,'source_frames':frames,'bones':148,'matrix_components_checked':e['checked'],
                 'matrix_component_bit_mismatch_count':sum('row' in m for m in e['mismatches']),
                 'focus_channel_bit_mismatch_count':sum('focus_channel' in m for m in e['mismatches']),
                 'maximum_component_difference':e['maximum'],'mismatches':e['mismatches'],'window_admission':window}
    else:
        expected=ctx.cc.strict_json(ctx.pin('source_samples').verify(),32*MIB)
        require(expected['generated_source_sha256']==ctx.pin('generated_source').sha256 and expected['approved_source_sha256']==ctx.cc.APPROVED_SHA,'source oracle identity differs')
        require(list(expected['frames'])==[str(f) for f in frames],'source sample exact clock differs')
        e.update(expected=expected,output=ctx.pin('source_samples').path.parent)
        execute('focus_measure',e)
        checks=e['checks'];A,C,S=(e[k] for k in ('A','C','S'));projection=e['projection'];bpy=e['bpy']
        checks.update(finite_bones=bool(e['finite']),finite_all_measured_transforms=bool(e['finite']),skin_topology=e['topology']==expected['topology'],
                      camera_projection_rays=e['ray_error']<1e-5,camera_type=projection['type']==expected['projection']['type'],
                      single_native_clock=all(list(x.frame_range)==[1.,96.] for x in bpy.data.actions),fps=S.render.fps==60 and S.render.fps_base==1,
                      source_unchanged=file_sha(ctx.pin('generated_source').path)==ctx.pin('generated_source').sha256,fbx_unchanged=file_sha(path)==pin.sha256)
        require(e['count']==len(frames)*10234,'complete three-skin coverage required')
        payload={'passed':all(checks.values()),'source_sha256':ctx.pin('generated_source').sha256,'fbx_sha256':pin.sha256,
                 'source_total_bones_including_helpers':148,'samples':len(frames),'sample_frames':frames,'skin_vertex_samples':e['count'],
                 'checks':checks,'maxima':e['maxima'],'worst':e['worst'],'camera_projection_ray_error':e['ray_error'],
                 'off_key_source_frames':[f for f in frames if f*256!=int(f*256)],'window_admission':window,
                 'source_oracle_sha256':ctx.pin('source_samples').sha256,'source_projection':expected['projection'],'imported_projection':projection,
                 'topology':e['topology'],'sample_grid_sha256':hashlib.sha256((json.dumps(list(ctx.cc.FOCUS),separators=(',',':'))+'\n').encode()).hexdigest() if ctx.stage=='focus-import' else ctx.cc.GRID_SHA,
                 'independent_grid_sha256':ctx.cc.GRID_SHA,'runtime_support_verified':False}
    write_new(ctx.output/'report.json',payload);require(payload['passed'],'native parity failed; retain evidence');return payload


def control_export_settings():
    return {**SETTINGS,'bake_anim_step':1/64}


def control_raw_grid(e,path):
    """Target-generated1/64 control with full raw arrays admitted unchanged."""
    from io_scene_fbx import parse_fbx
    tree,version=parse_fbx.parse(str(path))
    contract=e['single_stack_fbx'].inspect_stack(tree,ACTION,['Arms',*ACTORS,CAMERA])
    objects=[n for n in tree.elems if n.id==b'Objects'];require(len(objects)==1,'control Objects ambiguity')
    curves=[n for n in objects[0].elems if n.id==b'AnimationCurve'];require(len(curves)==1379,'control full raw curve inventory differs')
    records=[];ids=set()
    for curve in curves:
        require(curve.props[0] not in ids,'duplicate control curve UUID');ids.add(curve.props[0]);a={n.id:n.props for n in curve.elems}
        record=e['validate_arrays'](a[b'KeyTime'][0],a[b'KeyValueFloat'][0],64,a[b'KeyAttrFlags'][0],a[b'KeyAttrRefCount'][0]);records.append({'curve_uuid':curve.props[0],**record})
    return {'passed':True,'fbx_version':version,'logical_stack':ACTION,'curve_count':1379,'key_count':6081,'subdivisions':64,
            'all_times_values_finite_checked':True,'linear_flags':24836,'curves':records}


def full_control(ctx,e,path):
    """Fresh target-native full 1/64 oracle, never a Linux oracle copy."""
    from io_scene_fbx import parse_fbx
    tree,version=parse_fbx.parse(str(path));objects=[n for n in tree.elems if n.id==b'Objects'];require(len(objects)==1,'control Objects ambiguity')
    curves=[n for n in objects[0].elems if n.id==b'AnimationCurve'];require(len(curves)==1379,'control curve coverage differs')
    for curve in curves:
        a={n.id:n.props for n in curve.elems};e['validate_arrays'](a[b'KeyTime'][0],a[b'KeyValueFloat'][0],64,a[b'KeyAttrFlags'][0],a[b'KeyAttrRefCount'][0])
    del tree,objects,curves
    imported=e['import_exact_grid'](path);bpy=e['bpy'];np=e['np'];expected=e['native_grid'](64);count=0
    require(len(bpy.data.actions)==6,'full control Action inventory differs')
    for action in bpy.data.actions:
        require(len(action.fcurves)>0,'empty control Action')
        for fc in action.fcurves:
            require(len(fc.keyframe_points)==6081,'full control dense key count differs')
            pairs=np.empty(6081*2,dtype=np.float32);fc.keyframe_points.foreach_get('co',pairs)
            require(np.array_equal(pairs[::2],expected) and np.isfinite(pairs).all(),'full control grid differs')
            require(all(k.interpolation=='LINEAR' for k in fc.keyframe_points),'full control interpolation differs');count+=1
    e['window']={'allowed_evaluation_frames':sorted(set([1.,*ctx.frames()]))};execute('import_pose_setup',e)
    A=e['A'];require(len(A.pose.bones)==148,'full control all148 coverage required');rows=[]
    for f in ctx.frames():
        e['set_frame'](f);actual={b.name:e['mat']((A.matrix_world@b.matrix)@e['rest'][b.name].inverted()) for b in A.pose.bones};focus={}
        for name in FOCUS_BONES:
            b=A.pose.bones[name];local=b.parent.matrix.inverted()@b.matrix if b.parent else b.matrix;loc,rot,scale=local.decompose()
            focus[name]={'parent':b.parent.name if b.parent else None,'rotation_mode':b.rotation_mode,'location':list(b.location),
                         'rotation_quaternion':list(b.rotation_quaternion),'rotation_euler':list(b.rotation_euler),'scale':list(b.scale),
                         'matrix_basis':e['mat'](b.matrix_basis),'pose_parent_relative':e['mat'](local),
                         'pose_parent_relative_decomposition':{'location':list(loc),'rotation_quaternion':list(rot),'scale':list(scale)}}
        rows.append({'source_frame':f,'deformation_world':actual,'focus_bones':focus})
    result={'schema':'rust-duty-windows-full-control/v1','binding':ctx.binding,'fbx_sha256':file_sha(path),'source_frames':ctx.frames(),
            'samples':rows,'bones':148,'full_key_count':6081,'subdivisions':64,'imported_curves':count,'all_curves_full_instantiated':True,
            'import_admission':imported,'same_platform_only':True,'cross_platform_float64_equality_proved':False}
    write_new(ctx.output/'full-control.json',result);return {'fbx_sha256':file_sha(path),'full_control_sha256':file_sha(ctx.output/'full-control.json'),'bones':148,'samples':9,'full_key_count':6081,'subdivisions':64,'imported_curves':count,'all_curves_full_instantiated':True}

def conversion_stage(ctx,e):
    empty_scene(e);frames=ctx.frames();fbx=ctx.pin('actual_fbx');window=e['import_window'](fbx.verify(),fbx.sha256,256,frames)
    require(window['retained_key_count']<=2051 and window['full_key_count']==24321,'exact bounded production key counts required')
    e.update(window=window,frames=frames)
    require(len(e['bpy'].data.objects['Arms'].pose.bones)==148,'all148 imported bones required')
    execute('runtime_static',e)
    if ctx.stage=='geometry':
        e['output']=ctx.output/'runtime';execute('runtime_geometry',e);out=e['output']
        metadata={'schema':'rust-duty-onehand-bounded-runtime-geometry/v1','source_sha256':ctx.pin('generated_source').sha256,
                  'fbx_sha256':fbx.sha256,'canonical_sha256':ctx.cc.CANONICAL_SHA,'clip_name':ACTION,'loop':False,'ticks_per_second':15360,'last_tick':24320,
                  'bones':[[b[0],b[1]] for b in e['bones']],'actors':e['definitions'],'weights':e['weights'],'basis':[list(r) for r in BASIS],
                  'static_import':e['static'],'static_import_sha256':e['static_sha'],'window_admission':window,
                  'recipe_pins_sha256':file_sha(HERE/'PINS.json'),'files':{n:{'sha256':file_sha(out/n),'bytes':(out/n).stat().st_size} for n in ('asset.vrs','asset.vrm','geometry-only.glb')},
                  'windows_provenance':ctx.binding,'passed':True}
        write_new(out/'geometry-metadata.json',metadata);return {'geometry_metadata_sha256':file_sha(out/'geometry-metadata.json'),'static_import_sha256':e['static_sha'],'window_admission':window}
    metadata=ctx.cc.strict_json(ctx.pin('geometry').verify(),32*MIB)
    require(metadata['passed'] is True and metadata['windows_provenance']==ctx.binding and metadata['fbx_sha256']==fbx.sha256 and metadata['static_import_sha256']==e['static_sha'],'same candidate static geometry differs')
    for name,role in [('asset.vrs','vrs'),('asset.vrm','vrm')]:require(file_sha(ctx.pin(role).verify())==metadata['files'][name]['sha256'],'companion pin differs')
    lo=ctx.index*2048;hi=min(lo+2048,24320);folder=ctx.output/'block'
    e.update(metadata=metadata,lo=lo,hi=hi,folder=folder);execute('runtime_block',e)
    payload={'schema':'rust-duty-onehand-bounded-runtime-block/v1','passed':True,'block_index':ctx.index,'start_tick':lo,'end_tick':hi,
             'frames':hi-lo+1,'frame_bytes':3007,'source_sha256':ctx.pin('generated_source').sha256,'fbx_sha256':fbx.sha256,'canonical_sha256':ctx.cc.CANONICAL_SHA,
             'geometry_metadata_sha256':ctx.pin('geometry').sha256,'static_import_sha256':e['static_sha'],'frame_file_sha256':file_sha(folder/'frames.bin'),
             'frame_file_bytes':(folder/'frames.bin').stat().st_size,'window_admission':window,'recipe_pins_sha256':file_sha(HERE/'PINS.json'),
             'final_full_key_count':24321,'full_clip_instantiated':False,'windows_provenance':ctx.binding}
    write_new(folder/'receipt.json',payload);return payload

def perform(ctx):
    # Deliberately imported only by the admitted native entry point.
    import bpy,numpy as np
    from mathutils import Matrix
    e=environment(ctx,bpy,np,Matrix)
    if ctx.stage in ('export','control-export','source-focus','source-chunk','rigid-frame1','rigid-chunk','rigid-focus'):return source_stage(ctx,e)
    if ctx.stage in ('geometry','block'):return conversion_stage(ctx,e)
    return import_stage(ctx,e)

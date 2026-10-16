"""Pinned official FBX backend and exact dense-key admission. No source edits."""
from pathlib import Path
import hashlib,inspect,json,math,sys
from dense_contract import *
EXPECTED_CURVES=1379
EXPECTED_PATCHES={'blen_read_animations':'757bd21550d94e2190881ec6b0eb0ce80b275d2a230055cf7702044fe6dcc6e2',
                  'blen_store_keyframes_multi':'793a389ebde0e71ec3cec54e731c861753aa08015355904777a8c39b70da3a4e'}

def operator_defaults(properties):
    result={}
    for prop in properties:
        if prop.identifier in ('rna_type','check_existing','filter_glob','ui_tab'):continue
        require(prop.type in ('BOOLEAN','INT','FLOAT','STRING','ENUM'),'unexpected exporter RNA property: '+prop.identifier)
        if prop.type=='ENUM' and prop.is_enum_flag:value=set(prop.default_flag)
        elif getattr(prop,'is_array',False):value=tuple(prop.default_array)
        else:value=prop.default
        result[prop.identifier]=value
    return result

def export_exact_grid(path,settings):
    import bpy
    from mathutils import Matrix
    from bpy_extras.io_utils import axis_conversion
    from io_scene_fbx import export_fbx_bin
    require(bpy.app.version[:3]==(4,3,2),'export backend audited only for 4.3.2')
    props=bpy.ops.export_scene.fbx.get_rna_type().properties
    require(props['bake_anim_step'].hard_min>1/256,'reinspect changed RNA sampling clamp')
    kwargs=operator_defaults(props);kwargs.update(settings);kwargs['filepath']=str(path)
    require(kwargs['bake_anim_step']==1/256 and kwargs['bake_anim_simplify_factor']==0,'exact unsimplified sampling required')
    kwargs['global_matrix']=(axis_conversion(to_forward=kwargs['axis_forward'],to_up=kwargs['axis_up']).to_4x4()
                             if kwargs['use_space_transform'] else Matrix())
    reports=[]
    class Reporter:
        def report(self,level,message):
            reports.append({'level':sorted(level),'message':message})
            require('ERROR' not in level,'official FBX exporter error: '+message)
    # This is the installed official operator's same backend and all RNA defaults.
    # Calling it directly avoids the UI/RNA 0.01 minimum silently clamping 1/256.
    result=export_fbx_bin.save(Reporter(),bpy.context,**kwargs)
    return result,{'route':'installed official export_fbx_bin.save with operator RNA defaults',
                   'operator_minimum_step':props['bake_anim_step'].hard_min,'effective_step':kwargs['bake_anim_step'],
                   'effective_kwargs':{k:(sorted(v) if isinstance(v,set) else [list(r) for r in v] if k=='global_matrix' else v) for k,v in kwargs.items()},
                   'reports':reports,'exporter_file_sha256':file_sha(Path(export_fbx_bin.__file__))}

def raw_key_grid(path):
    import numpy as np
    from io_scene_fbx import parse_fbx
    tree,version=parse_fbx.parse(str(path))
    objects=[n for n in tree.elems if n.id==b'Objects'];require(len(objects)==1,'FBX Objects ambiguity')
    stacks=[n.props[1].split(b'\x00\x01')[0].decode() for n in objects[0].elems if n.id==b'AnimationStack']
    require(stacks==[ACTION],'FBX exact sole stack differs')
    curves=[n for n in objects[0].elems if n.id==b'AnimationCurve'];require(len(curves)==EXPECTED_CURVES,'FBX curve inventory differs')
    expected=1+np.arange(KEY_COUNT,dtype=np.float64)/SUBDIVISIONS;max_error=0.;groups={}
    for curve in curves:
        arrays={n.id:n.props for n in curve.elems};times=np.asarray(arrays[b'KeyTime'][0],dtype=np.int64)
        require(len(times)==KEY_COUNT and len(arrays[b'KeyValueFloat'][0])==KEY_COUNT,'FBX key count differs')
        require(np.all(np.diff(times)>0),'FBX times not strictly increasing')
        error=float(np.max(np.abs(times.astype(np.float64)*60/46186158000-expected)))
        require(error<=2*60/46186158000,'FBX rational time grid differs beyond integer ktime rounding')
        require(list(arrays[b'KeyAttrFlags'][0])==[24836],'FBX linear interpolation flags differ')
        max_error=max(max_error,error);digest=hashlib.sha256(times.astype('<i8',copy=False).tobytes()).hexdigest();groups[digest]=groups.get(digest,0)+1
    return {'passed':True,'fbx_version':version,'logical_stack':ACTION,'curve_count':len(curves),'key_count':KEY_COUNT,
            'subdivisions':SUBDIVISIONS,'maximum_native_frame_ktime_rounding':max_error,'ktime_grid_hashes':groups}

def import_exact_grid(path):
    import bpy
    import io_scene_fbx.import_fbx as imp
    sys.path.insert(0,str(ROOT/'onehand-runtime-20261016/importer-patch/tools'))
    import import_fbx_viewmodel as converter
    import single_stack_fbx
    from io_scene_fbx import parse_fbx
    tree,_=parse_fbx.parse(str(path));contract=single_stack_fbx.inspect_stack(tree,ACTION,['Arms',*ACTORS,CAMERA]);del tree
    for name,digest in EXPECTED_PATCHES.items():
        require(hashlib.sha256(inspect.getsource(getattr(imp,name)).encode()).hexdigest()==digest,'audited importer function hash differs: '+name)
    capture=single_stack_fbx.BindingCapture(contract);patches=converter.patch_importer(capture)
    require({n:d['sha256'] for n,d in patches.items()}==EXPECTED_PATCHES,'importer patch identities differ')
    result=bpy.ops.import_scene.fbx(filepath=str(path),use_anim=True,anim_offset=0.,ignore_leaf_bones=False,
                                  automatic_bone_orientation=False,use_prepost_rot=True)
    require('FINISHED' in result,'fresh FBX import failed')
    admission=capture.verify([bpy.data.objects[n] for n in ['Arms',*ACTORS,CAMERA]],list(bpy.data.actions),[1.,96.])
    return {'patches':patches,'single_stack_admission':admission,
            'semantics':'same audited dense-key preservation and exact owner binding as runtime conversion'}

def imported_key_grid():
    import bpy,numpy as np
    expected=1+np.arange(KEY_COUNT,dtype=np.float32)/SUBDIVISIONS
    require(len(bpy.data.actions)==6,'imported Action inventory differs')
    records=[];curve_count=0
    for action in bpy.data.actions:
        require(len(action.fcurves)>0,'empty imported Action')
        for fc in action.fcurves:
            require(len(fc.keyframe_points)==KEY_COUNT,'imported curve lost dense keys')
            pairs=np.empty(KEY_COUNT*2,dtype=np.float32);fc.keyframe_points.foreach_get('co',pairs)
            require(np.array_equal(pairs[::2],expected),'imported curve rational key grid differs')
            require(np.isfinite(pairs).all(),'nonfinite imported key')
            curve_count+=1
        records.append({'action':action.name,'curves':len(action.fcurves),'frame_range':list(action.frame_range)})
    return {'passed':True,'key_count':KEY_COUNT,'subdivisions':SUBDIVISIONS,'curve_count':curve_count,
            'actions':records,'native_frame_grid_sha256':hashlib.sha256(expected.astype('<f4',copy=False).tobytes()).hexdigest(),
            'all_curves_checked':True,'preservation_patch_required_and_applied':True}

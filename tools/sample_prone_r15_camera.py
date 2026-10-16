#!/usr/bin/env python3
"""Read the exact approved r15 paired camera at its 3840 Hz export grid.

Background Blender only. No rendering, authored changes, source save or runtime activation.
"""
from pathlib import Path
import argparse,hashlib,json,math,sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import prone_camera_pair as pair

def action_fingerprint(action):
    records=[(c.data_path,c.array_index,[(list(k.co),list(k.handle_left),list(k.handle_right),k.interpolation)
              for k in c.keyframe_points]) for c in action.fcurves]
    return hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest()

def main():
    import bpy
    from mathutils import Matrix
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);out=a.output.resolve()
    assert not out.exists(),'Fresh camera output required'
    source=Path(bpy.data.filepath);assert hashlib.sha256(source.read_bytes()).hexdigest()==pair.R15_SOURCE_SHA
    assert bpy.app.version_string=='4.3.2' and bpy.app.background and not bpy.context.preferences.filepaths.use_scripts_auto_execute
    A=bpy.data.objects['Arms'];C=bpy.data.objects['RD First Person Review'];S=bpy.context.scene
    assert (S.render.fps,S.render.fps_base)==(60,1.)
    for name,digest in pair.R15_FINGERPRINTS.items():assert action_fingerprint(bpy.data.actions[name])==digest
    from export_prone_pair import bound_pair
    # This function's source selection is explicit; r6 defaults remain unchanged.
    config={'armature':'Arms','camera':C.name,'base_action':'RD_00_Supplied_Base_Guarded_Recovered',
            'source_take':pair.R15_RIG_ACTION,'camera_action':pair.R15_CAMERA_ACTION}
    result=[];max_rig_residual=0.
    flat=lambda m:tuple(float(x) for row in m for x in row)
    mat=lambda m:[list(row) for row in m]
    with bound_pair(bpy,config):
        C0=C.matrix_world.copy();R0=A.matrix_world.copy()
        for i in range(4353):
            f=1+i/64;S.frame_set(math.floor(f),subframe=f-math.floor(f));A.update_tag();C.update_tag()
            bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();dg.update()
            camera=C.evaluated_get(dg).matrix_world;rig=A.evaluated_get(dg).matrix_world
            delta=pair.common_world_delta(flat(camera),flat(C0));normalized=pair.remove_common_motion(flat(rig),delta)
            pair.verify_armature_motion(flat(rig),delta,flat(R0))
            max_rig_residual=max(max_rig_residual,max(abs(x-y) for x,y in zip(normalized,flat(R0))))
            depth=(C0.translation.z-camera.translation.z)/1.26
            result.append({'candidate_frame':f,'time_seconds':i/3840,'normalized_depth_fraction':depth,
                           'camera_world':mat(camera),'common_world_delta':[list(delta[j:j+4]) for j in range(0,16,4)]})
            if i%512==0:print('R15_CAMERA',i,4353,flush=True)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==pair.R15_SOURCE_SHA
    document={'schema':pair.R15_SIDECAR_SCHEMA,'candidate_sha256':pair.R15_SOURCE_SHA,
              'action_fingerprints':dict(pair.R15_FINGERPRINTS),'units':'metres and radians; Blender world +Z up',
              'camera_local_axes':'+X right, +Y up, -Z forward','initial_camera_world':mat(C0),
              'fps':60,'sample_hz':3840,'duration_key_span_seconds':68/60,
              'height_contract':{'mode':'replace_stance_height_during_clip','allow_impact_overshoot':True,
               'source_endpoint_descent_m':1.26,'runtime_target_prone_eye_height_m':.2794},
              'source_frame_range':[1,69],'reference_frame_range_half_open':[2241,2310],
              'source_unchanged':True,'source_saved':False,'rendered':False,
              'maximum_common_rig_residual':max_rig_residual,'rows':result}
    data=(json.dumps(document,separators=(',',':'))+'\n').encode()
    from fractions import Fraction
    pair.load_camera_pair(data,expected_sidecar_sha256=hashlib.sha256(data).hexdigest(),
       candidate_sha256=pair.R15_SOURCE_SHA,action_fingerprints=dict(pair.R15_FINGERPRINTS),
       native_start=0,native_end=68,fps=Fraction(60),candidate_frame_offset=1,
       frames=[Fraction(i,64) for i in range(4353)])
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('xb') as stream:stream.write(data)
    print('R15_CAMERA_COMPLETE',len(data),hashlib.sha256(data).hexdigest(),flush=True)

if __name__=='__main__':main()

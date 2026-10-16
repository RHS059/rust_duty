"""Source-pinned, foreground-only Eevee viewport adapters. Never explicitly saves a canonical source BLEND.

Run from factory-startup Blender 4.3.2, autoexec disabled. Background mode is
allowed ONLY with --validate-all/--validate-only, which cannot call a renderer.
"""
import argparse
import faulthandler
import json
import os
from pathlib import Path
import socket
import sys
import time
import traceback
from datetime import datetime, timezone

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from capture_common import (configure_input_root,CONTRACTS,TAKES,sha,digest,source_path,validate_contract,
                            frame_map,pixel_evidence,primer_review_valid)
import bpy
HELPERS=HERE/'helpers'
sys.path.insert(0,str(HELPERS))
from source_integrity import snapshot
from validate_source_structure import extra_snapshot
ENGINE='BLENDER_EEVEE_NEXT'
PROTECTED=('actions_metadata','actions_extended','meshes','armatures','objects_and_bindings','materials','cameras')

def utc(): return datetime.now(timezone.utc).isoformat()
def matrix(value): return [list(row) for row in value]
def camera_state(camera):
    return dict(name=camera.name,matrix_world=matrix(camera.matrix_world),
                **{k:getattr(camera.data,k) for k in ('lens','sensor_width','sensor_height',
                   'sensor_fit','shift_x','shift_y','clip_start','clip_end')})
def static_structure():
    value=extra_snapshot()
    return {k:value[k] for k in PROTECTED}

def open_take(take):
    validate_contract(take)
    assert bpy.app.version_string==CONTRACTS['blender']
    bpy.ops.wm.open_mainfile(filepath=str(source_path(take)),load_ui=False,use_scripts=False)
    scene=bpy.context.scene
    # Factory UI remains SOLID while the exact source is opened with load_ui=False.
    # Set Eevee before any rendered shading/redraw can be requested.
    scene.render.engine=ENGINE
    assert Path(bpy.data.filepath).resolve()==source_path(take).resolve()
    assert len(bpy.data.actions)==take['action_count']
    assert list(bpy.data.actions[take['action']].frame_range)==take['frames_inclusive']
    assert camera_state(scene.camera)==take['camera']
    assert [scene.render.resolution_x,scene.render.resolution_y]==take['resolution']
    assert scene.render.resolution_percentage==100
    assert scene.render.fps/scene.render.fps_base==60
    for name,action in [('hk416_weapon','hk416_weaponAction.001'),('hk416_magazine','hk416_magazineAction')]:
        data=bpy.data.objects[name].animation_data
        assert data.action.name==action and data.use_nla and not data.nla_tracks
    assert CONTRACTS['reset_action'] in bpy.data.actions
    scene.frame_set(1); bpy.context.view_layer.update()
    return scene,bpy.data.objects['Arms']

def select_action(scene,rig,take):
    # Match recovered capture recipes. These are in-memory playback selections,
    # never authoring edits, and are restored before final preservation checks.
    for obj in bpy.data.objects:
        if obj.animation_data:
            for track in obj.animation_data.nla_tracks:
                track.mute=True;track.is_solo=False
    rig.animation_data.use_nla=False
    rig.animation_data.action=bpy.data.actions[CONTRACTS['reset_action']]
    scene.frame_set(1);bpy.context.view_layer.update()
    rig.animation_data.action=bpy.data.actions[take['action']]
    scene.frame_set(1);bpy.context.view_layer.update()
    assert camera_state(scene.camera)==take['camera']

def restore_bindings(scene,before):
    for name,state in before['nla'].items():
        data=bpy.data.objects[name].animation_data
        data.action=bpy.data.actions[state['action']] if state['action'] else None
        data.use_nla=state['use_nla']
        assert len(data.nla_tracks)==len(state['tracks'])
        for track,old in zip(data.nla_tracks,state['tracks']):
            assert track.name==old['name']
            track.mute=old['mute'];track.is_solo=old['is_solo']
    scene.frame_set(1);bpy.context.view_layer.update()

def verify_preservation(scene,rig,take,before,structure,rig_world):
    after=snapshot(bpy)
    checks=dict(source_bytes_unchanged=sha(source_path(take))==take['source_sha256'],
        camera_unchanged=camera_state(scene.camera)==take['camera'],
        world_root_unchanged=matrix(rig.matrix_world)==rig_world,
        action_curves_unchanged=before['actions']==after['actions'],
        source_structure_unchanged=structure==static_structure(),
        drivers_unchanged=before['drivers']==after['drivers'],
        packed_images_unchanged=before['packed_images']==after['packed_images'],
        restored_nla_and_companions_unchanged=before['nla']==after['nla'])
    assert all(checks.values()),checks
    return checks

def validate_only(takes,output):
    assert not output.exists(),'Refuse to overwrite validation evidence'
    results=[]
    for take in takes:
        scene,rig=open_take(take)
        before=snapshot(bpy);structure=static_structure();world=matrix(rig.matrix_world)
        select_action(scene,rig,take)
        selected=dict(rig_action=rig.animation_data.action.name,camera=camera_state(scene.camera),
                      background=bpy.app.background,frame=scene.frame_current)
        # Test range endpoints, without rendering or changing keys/timing.
        scene.frame_set(take['frames_inclusive'][1]);bpy.context.view_layer.update()
        assert camera_state(scene.camera)==take['camera']
        restore_bindings(scene,before)
        checks=verify_preservation(scene,rig,take,before,structure,world)
        results.append(dict(take=take['id'],source_sha256=take['source_sha256'],selected=selected,
            checks=checks,frame_map=frame_map(take),action_curve_digest=digest(before['actions']),
            protected_structure_digest=digest(structure)))
        print('VALIDATED_NO_RENDER',take['id'],flush=True)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(dict(schema='rust-duty-adapter-no-render-validation/v1',
        blender=bpy.app.version_string,rendered=False,source_saved=False,passed=True,takes=results),indent=2)+'\n')

def capture(take,out,probe_only=False):
    assert not bpy.app.background,'Actual capture needs graphical Blender, never --background'
    assert bpy.context.window_manager.windows,'No graphical Blender windows'
    assert not out.exists(),'Refuse to overwrite any prior capture or evidence'
    out.mkdir(parents=True)
    proof=dict(schema='rust-duty-fixed-source-foreground-viewport/v1',take=take['id'],
        source_path=str(source_path(take)),source_sha256=take['source_sha256'],
        action=take['action'],blender=bpy.app.version_string,pid=os.getpid(),hostname=socket.gethostname(),
        display=os.environ.get('DISPLAY'),background=bpy.app.background,engine=ENGINE,
        transient_resource_environment={'LP_NUM_THREADS':os.environ.get('LP_NUM_THREADS')},
        operator='bpy.ops.render.opengl',source_saved=False,regular_offline_render_operator_used=False,
        completed=False,status='opening',started_utc=utc(),camera=take['camera'],
        fps=take['fps'],resolution=take['resolution'],frame_map=frame_map(take),
        unique_frame_count=take['unique_frame_count'],primers=[],artistic_review='pending',
        scripts_sha256={p.name:sha(p) for p in HERE.glob('*.py')},contracts_sha256=sha(HERE/'contracts.json'))
    def persist(): (out/'viewport_process_proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    # Keep crash logging alive beyond setup and flush stage markers before native
    # GPU/viewport operations, which cannot be caught as Python exceptions.
    global _FAULT_LOG
    _FAULT_LOG=(out/'python-fault.log').open('w')
    faulthandler.enable(file=_FAULT_LOG,all_threads=True)
    def event(name,**fields):
        row=dict(event=name,utc=utc(),**fields)
        with (out/'events.jsonl').open('a') as handle:
            handle.write(json.dumps(row,sort_keys=True)+'\n');handle.flush();os.fsync(handle.fileno())
        proof['last_event']=row;persist()
        print('VIEWPORT_STAGE',json.dumps(row,sort_keys=True),flush=True)
    def quit_soon(): bpy.app.timers.register(lambda:bpy.ops.wm.quit_blender() and None,first_interval=1.)
    event('before_open_source')
    scene,rig=open_take(take)
    event('source_opened')
    before=snapshot(bpy);structure=static_structure();world=matrix(rig.matrix_world)
    event('protected_snapshot_recorded')
    select_action(scene,rig,take)
    event('exact_action_selected')
    candidates=[(window,area) for window in bpy.context.window_manager.windows for area in window.screen.areas if area.type=='VIEW_3D']
    if not candidates:
        # Console launch can replace the sole factory VIEW_3D editor. Restore a
        # genuine editor in that foreground window; do not create an offscreen view.
        window=bpy.context.window or next(iter(bpy.context.window_manager.windows))
        area=max(window.screen.areas,key=lambda item:item.width*item.height)
        event('before_console_editor_change',from_type=area.type)
        area.type='VIEW_3D'
        event('after_console_editor_change',to_type=area.type)
        candidates=[(window,area)]
    window,area=max(candidates,key=lambda pair:pair[1].width*pair[1].height)
    window.scene=scene
    region=next(x for x in area.regions if x.type=='WINDOW');space=area.spaces.active
    import gpu
    proof['gpu']=dict(vendor=gpu.platform.vendor_get(),renderer=gpu.platform.renderer_get(),
        version=gpu.platform.version_get(),backend=gpu.platform.backend_type_get())
    event('graphics_context_recorded',gpu=proof['gpu'])
    space.shading.use_scene_world_render=True;space.shading.use_scene_lights_render=True
    space.overlay.show_overlays=False;space.show_gizmo=False;space.use_local_camera=False
    space.region_3d.view_perspective='CAMERA'
    scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGBA'
    scene.render.image_settings.color_depth='8';scene.render.image_settings.compression=15
    scene.render.use_file_extension=True;scene.render.use_border=False
    scene.frame_start,scene.frame_end=take['frames_inclusive'];scene.frame_step=1
    scene.eevee.taa_samples=take['taa_samples']
    event('before_rendered_shading')
    space.shading.type='RENDERED'
    event('rendered_shading_set')
    proof.update(status='priming',window_pointer=window.as_pointer(),area_type=area.type,region_type=region.type,
        viewport_shading=space.shading.type,camera_view=space.region_3d.view_perspective,
        scene_world=True,scene_lights=True,action_curve_digest_before=digest(before['actions']),
        protected_structure_digest_before=digest(structure),taa_samples=scene.eevee.taa_samples,
        object_action_bindings={o.name:o.animation_data.action.name if o.animation_data and o.animation_data.action else None for o in bpy.data.objects})
    (out/'primer').mkdir();(out/'frames').mkdir();persist()
    state={'stage':'prime','review_started':None}
    def fail():
        proof.update(status='failed',error=traceback.format_exc(),failed_utc=utc());persist()
        traceback.print_exc();quit_soon()
    def guard():
        assert not bpy.app.background and scene.render.engine==ENGINE
        assert space.shading.type=='RENDERED' and space.region_3d.view_perspective=='CAMERA'
        assert camera_state(scene.camera)==take['camera']
        assert rig.animation_data.action.name==take['action']
        assert [scene.render.resolution_x,scene.render.resolution_y]==take['resolution']
        assert scene.render.resolution_percentage==100 and scene.render.fps/scene.render.fps_base==60
    def tick():
        try:
            event('timer_entered',stage=state['stage'])
            import gpu
            guard()
            proof['gpu']=dict(vendor=gpu.platform.vendor_get(),renderer=gpu.platform.renderer_get(),
                version=gpu.platform.version_get(),backend=gpu.platform.backend_type_get())
            if state['stage']=='prime':
                assert scene.frame_current==1
                path=out/'primer'/f'frame1_repeat_{len(proof["primers"])+1:02d}.png'
                assert not path.exists();scene.render.filepath=str(path)
                start=time.monotonic()
                event('before_primer_operator',path=str(path),frame=scene.frame_current)
                with bpy.context.temp_override(window=window,area=area,region=region):
                    result=bpy.ops.render.opengl('EXEC_DEFAULT',write_still=True,view_context=True,sequencer=False)
                event('after_primer_operator',operator_result=sorted(result))
                assert result=={'FINISHED'}
                record=pixel_evidence(path);record.update(action_frame=1,seconds=time.monotonic()-start)
                proof['primers'].append(record)
                if len(proof['primers'])>=3 and proof['primers'][-1]['pixel_sha256']==proof['primers'][-2]['pixel_sha256']:
                    proof.update(status='awaiting_primer_visual_review',stable_same_pose_pixels=True)
                    state['stage']='review';state['review_started']=time.monotonic()
                    template=dict(accepted=False,take=take['id'],source_sha256=take['source_sha256'],
                        primer_sha256=[p['sha256'] for p in proof['primers']],review_note='Inspect actual cold and repeated same-pose PNGs for full materials and stable geometry before setting accepted true.')
                    (out/'primer_review.template.json').write_text(json.dumps(template,indent=2)+'\n')
                    persist();print('PRIMER_REVIEW_REQUIRED',str(out),flush=True)
                    if probe_only:
                        restore_bindings(scene,before)
                        proof.update(verify_preservation(scene,rig,take,before,structure,world))
                        proof.update(status='probe_complete_no_animation',ended_utc=utc());persist();quit_soon();return None
                else:
                    assert len(proof['primers'])<8,'Same-pose image did not stabilize; keep evidence and investigate'
                    persist()
                area.tag_redraw();return 3.
            if state['stage']=='review':
                path=out/'primer_review.json'
                if not path.exists():
                    assert time.monotonic()-state['review_started']<3600,'Primer review not supplied within one hour'
                    return 2.
                review=json.loads(path.read_text())
                assert primer_review_valid(review,take,proof['primers']),'Primer review must match exact current images/take and accept stable textures'
                proof['primer_review']=review;proof['status']='capturing';state['stage']='capture';persist()
                return 0.5
            if state['stage']=='capture':
                assert scene.frame_current==1,'No pose/time change permitted between primer and capture'
                scene.render.filepath=str(out/'frames'/'f')
                proof['operator_arguments']=dict(animation=True,view_context=True,render_keyed_only=False,sequencer=False)
                persist();start=time.monotonic()
                event('before_animation_operator')
                with bpy.context.temp_override(window=window,area=area,region=region):
                    result=bpy.ops.render.opengl('EXEC_DEFAULT',**proof['operator_arguments'])
                event('after_animation_operator',operator_result=sorted(result))
                assert result=={'FINISHED'};proof['capture_seconds']=time.monotonic()-start
                paths=sorted((out/'frames').glob('*.png'))
                assert [p.name for p in paths]==[f'f{f:04d}.png' for f in range(1,take['frames_inclusive'][1]+1)]
                proof['output_files']=[pixel_evidence(p) for p in paths]
                # A cold first-frame material failure must not silently enter the sequence.
                assert proof['output_files'][0]['pixel_sha256']==proof['primers'][-1]['pixel_sha256'],'Recorded frame1 differs from stable warm primer; investigate, never substitute'
                restore_bindings(scene,before)
                proof.update(verify_preservation(scene,rig,take,before,structure,world))
                proof.update(status='capture_complete_review_pending',completed=True,operator_result=sorted(result),ended_utc=utc())
                persist();print('VIEWPORT_CAPTURE_COMPLETE',str(out),flush=True);quit_soon();return None
        except BaseException:
            fail();return None
    event('before_timer_registration')
    bpy.app.timers.register(tick,first_interval=3.)
    event('timer_registered_setup_complete')

def main(argv):
    parser=argparse.ArgumentParser()
    parser.add_argument('--input-root',type=Path,help='Private input directory; overrides RUST_DUTY_CAPTURE_INPUT_ROOT')
    parser.add_argument('--take',choices=list(TAKES))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--validate-only',action='store_true')
    parser.add_argument('--validate-all',action='store_true')
    parser.add_argument('--probe-only',action='store_true',help='Only stable frame1 primers; no animation')
    args=parser.parse_args(argv)
    if args.input_root is not None:
        configure_input_root(args.input_root)
    if args.validate_all:
        assert not args.take and not args.probe_only
        validate_only(list(TAKES.values()),args.output)
    elif args.validate_only:
        assert args.take and not args.probe_only
        validate_only([TAKES[args.take]],args.output)
    else:
        assert args.take
        capture(TAKES[args.take],args.output,args.probe_only)

if __name__=='__main__':
    main(sys.argv[sys.argv.index('--')+1:])

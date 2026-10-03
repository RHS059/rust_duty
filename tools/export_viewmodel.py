#!/usr/bin/env python3
"""Run in Blender 4.3+: export independently selected NLA clips without saving.

Example:
 blender --background master.blend --python tools/export_viewmodel.py -- \
   --registry clips.json --output-dir /tmp/viewmodel --name viewmodel

Registry schema rust-duty-viewmodel-export/v1:
 {"schema": "rust-duty-viewmodel-export/v1", "armature": "Arms Rig",
  "export_objects": ["Arms Rig", "Arms", "Weapon", "Muzzle"],
  "clips": [{"name":"neutral", "frame_start":1, "frame_end":1,
             "loop":false, "tracks":{}},
            {"name":"release", "frame_start":1, "frame_end":25,
             "loop":false, "tracks":{"Arms Rig":["release"]}}]}

Objects omitted from export still evaluate as IK/constraint/driver dependencies.
Visibility is a STEP track of evaluated hide_render on rigid actors. An optional
actors list can restrict empty/socket actors; all rigid meshes must be present.
No .blend is saved, no input Action is rewritten, and no runtime pose is read.
"""
from __future__ import annotations
import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import vrview
from vrpack import AssetError, require


def _copy(value):
    if hasattr(value,'to_list'): return value.to_list()
    if hasattr(value,'copy'): return value.copy()
    return copy.deepcopy(value)


def _property_target(owner,path):
    """Resolve Blender RNA paths without evaluating arbitrary Python code."""
    if path.endswith(']'):
        match=re.match(r'^(.*)\[((?:"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[0-9]+))\]$',path)
        require(match is not None, f'unsupported animated property path: {path}')
        parent=owner.path_resolve(match[1]) if match[1] else owner
        key=ast.literal_eval(match[2]); return parent,key,True
    prefix,dot,key=path.rpartition('.')
    require(re.fullmatch(r'[A-Za-z_]\w*',key) is not None,f'unsupported animated property path: {path}')
    return owner.path_resolve(prefix) if dot else owner,key,False


def _set_property(owner,path,value):
    parent,key,item=_property_target(owner,path)
    if item: parent[key]=_copy(value)
    else: setattr(parent,key,_copy(value))


def _animation_owners(bpy):
    seen=set()
    for collection in ('objects','armatures','meshes','shape_keys','materials','cameras','lights','worlds','scenes','node_groups','curves'):
        for owner in getattr(bpy.data,collection,[]):
            for item in (owner,getattr(owner,'node_tree',None)):
                if item is not None and item.as_pointer() not in seen:
                    seen.add(item.as_pointer()); yield item


class SceneSnapshot:
    """Capture loaded evaluated defaults, including custom/constraint channels.

    Restoring only keyed transforms is insufficient: a previous clip's influence,
    visibility, custom IK blend or unkeyed finger can otherwise contaminate the
    next clip. This snapshots every bound Action/NLA property's whole value.
    """
    def __init__(self,bpy):
        self.bpy=bpy; scene=bpy.context.scene
        scene.frame_set(scene.frame_current,subframe=scene.frame_subframe)
        bpy.context.view_layer.update()
        self.frame=(scene.frame_current,scene.frame_subframe)
        self.bounds=(scene.frame_start,scene.frame_end)
        self.active=bpy.context.view_layer.objects.active
        self.selected=list(bpy.context.selected_objects)
        self.owners=[]; self.properties=[]
        for owner in _animation_owners(bpy):
            ad=getattr(owner,'animation_data',None)
            if ad is None: continue
            require(not ad.use_tweak_mode,'exit NLA tweak mode before exporting')
            tracks=[(t,t.mute,t.is_solo) for t in ad.nla_tracks]
            self.owners.append((owner,ad.action,ad.use_nla,tracks))
            actions=[ad.action] if ad.action else []
            for track,_,_ in tracks:
                for strip in track.strips:
                    if strip.action: actions.append(strip.action)
            paths={fc.data_path for action in actions for fc in action.fcurves}
            for path in sorted(paths):
                try: value=_copy(owner.path_resolve(path)); _property_target(owner,path)
                except (ValueError,AttributeError,TypeError) as exc:
                    raise AssetError(f'cannot snapshot animated property {owner.name}: {path}') from exc
                self.properties.append((owner,path,value))
        self.objects=[]
        for obj in bpy.data.objects:
            bones=[(p,p.matrix_basis.copy(),p.rotation_mode) for p in obj.pose.bones] if obj.pose else []
            self.objects.append((obj,obj.matrix_basis.copy(),obj.rotation_mode,obj.hide_viewport,obj.hide_render,obj.hide_get(),bones))
        self.collections=[(c,c.hide_viewport,c.hide_render) for c in bpy.data.collections]

    def isolate(self,tracks):
        bpy=self.bpy
        # Disable all source actions/NLA before restoring captured values. Drivers
        # and constraints remain enabled and reevaluate from these defaults.
        for owner,_,_,saved in self.owners:
            ad=owner.animation_data; ad.action=None; ad.use_nla=True
            for track,_,_ in saved: track.is_solo=False; track.mute=True
        for obj,basis,rotation,viewport,render,hidden,bones in self.objects:
            obj.rotation_mode=rotation; obj.matrix_basis=basis.copy()
            obj.hide_viewport=False; obj.hide_render=render; obj.hide_set(False)
            for pose,matrix,mode in bones: pose.rotation_mode=mode; pose.matrix_basis=matrix.copy()
        for owner,path,value in self.properties: _set_property(owner,path,value)
        for collection,_,_ in self.collections: collection.hide_viewport=False
        for name,track_names in tracks.items():
            obj=bpy.data.objects.get(name)
            require(obj is not None and obj.animation_data is not None,f'animation owner does not exist: {name}')
            ad=obj.animation_data
            for track_name in track_names:
                matches=[t for t in ad.nla_tracks if t.name==track_name]
                require(len(matches)==1,f'unknown or ambiguous NLA track {name}: {track_name}')
                matches[0].mute=False
        bpy.context.view_layer.update()

    def restore(self):
        self.isolate({})
        for obj,basis,rotation,viewport,render,hidden,bones in self.objects:
            obj.hide_viewport=viewport; obj.hide_render=render; obj.hide_set(hidden)
        for collection,viewport,render in self.collections:
            collection.hide_viewport=viewport; collection.hide_render=render
        for owner,action,use_nla,tracks in self.owners:
            ad=owner.animation_data; ad.action=action; ad.use_nla=use_nla
            for track,mute,solo in tracks: track.mute=mute; track.is_solo=solo
        scene=self.bpy.context.scene; scene.frame_start,scene.frame_end=self.bounds
        scene.frame_set(self.frame[0],subframe=self.frame[1])
        for obj in self.bpy.context.view_layer.objects: obj.select_set(False)
        for obj in self.selected: obj.select_set(True)
        self.bpy.context.view_layer.objects.active=self.active
        self.bpy.context.view_layer.update()


def validate_registry(bpy,registry):
    require(isinstance(registry,dict) and registry.get('schema')==vrview.SCHEMA,'invalid registry schema')
    require(isinstance(registry.get('armature'),str),'registry armature must be a name')
    arm=bpy.data.objects.get(registry.get('armature',''))
    require(arm is not None and arm.type=='ARMATURE','registry armature must name an armature object')
    names=registry.get('export_objects')
    require(isinstance(names,list) and names and all(isinstance(n,str) for n in names) and len(set(names))==len(names),'export_objects must be unique explicit names')
    require(arm.name in names,'deform armature must be in export_objects')
    objects=[]
    for name in names:
        obj=bpy.data.objects.get(name)
        require(obj is not None and obj.name in bpy.context.scene.objects,f'export object absent from active scene: {name}')
        require(obj.type in ('MESH','ARMATURE','EMPTY'),f'unsupported runtime object type: {name}')
        objects.append(obj)
    rigid=registry.get('rigid_armatures',[])
    require(isinstance(rigid,list) and all(isinstance(n,str) for n in rigid) and len(set(rigid))==len(rigid) and all(n in names and bpy.data.objects[n].type=='ARMATURE' and n!=arm.name for n in rigid),'rigid_armatures must explicitly name additional exported armatures')
    actors=registry.get('actors')
    if actors is None:
        actors=[o.name for o in objects if o.type=='EMPTY' or (o.type=='MESH' and not any(m.type=='ARMATURE' and m.object is not None and m.object.name not in rigid for m in o.modifiers))]
    require(isinstance(actors,list) and len(actors)<=256 and all(isinstance(n,str) and n in names for n in actors) and len(set(actors))==len(actors),'invalid actor selection')
    clips=registry.get('clips')
    require(isinstance(clips,list) and 1<=len(clips)<=128,'registry requires 1..128 clips')
    seen=set()
    for clip in clips:
        require(isinstance(clip,dict),'clip must be an object'); name=vrview.string(clip.get('name'),'clip name')
        require(name not in seen,'duplicate clip name'); seen.add(name)
        start,end=clip.get('frame_start'),clip.get('frame_end')
        require(type(start) is int and type(end) is int and 0<=start<=end and end-start<65536,'clip needs inclusive nonnegative integer frame range of at most 65536 frames')
        require(type(clip.get('loop')) is bool,'clip loop must be boolean')
        tracks=clip.get('tracks')
        require(isinstance(tracks,dict),'clip tracks must map object names to NLA track arrays')
        require(all(isinstance(k,str) and isinstance(v,list) and all(isinstance(t,str) for t in v) and len(v)==len(set(v)) for k,v in tracks.items()),'invalid NLA track selection')
        if not any(tracks.values()): require(start==end,'neutral/default clip must contain exactly one frame')
    return objects,actors


def export_glb(bpy,path,*,animation):
    # Names/options audited against installed Blender 4.3.2 io_scene_gltf2.
    # SCENE internally samples dependencies. Do not mute hidden FK/IK helpers or
    # optimize their viewport evaluation. Keep every influence; compiler rejects
    # >8 influences explicitly rather than truncating a private asset silently.
    result=bpy.ops.export_scene.gltf(filepath=str(path),export_format='GLB',
        use_selection=True,use_visible=False,use_renderable=False,use_active_scene=True,
        export_yup=True,export_apply=False,export_extras=False,export_cameras=False,export_lights=False,
        export_texcoords=True,export_normals=True,export_tangents=False,export_morph=False,
        export_skins=True,export_all_influences=True,export_def_bones=False,
        export_rest_position_armature=True,export_current_frame=True,
        export_animations=animation,export_animation_mode='SCENE',export_anim_scene_split_object=False,
        export_frame_range=True,export_frame_step=1,export_force_sampling=True,
        export_bake_animation=True,export_anim_slide_to_zero=True,
        export_optimize_animation_size=False,export_optimize_animation_keep_anim_armature=True,
        export_optimize_animation_keep_anim_object=True,export_optimize_disable_viewport=False,
        export_reset_pose_bones=False,export_armature_object_remove=False,export_leaf_bone=False)
    require('FINISHED' in result and path.is_file(),f'Blender glTF export failed: {path.name}')


def export(registry_path,output_dir,name,*,base_color_only=False,single_sided_materials=False,force=False):
    import bpy
    registry_path=Path(registry_path); registry=vrview.read_json(registry_path)
    objects,actors=validate_registry(bpy,registry); vrview.string(name,'output name')
    require(Path(name).name==name and name not in ('.','..'),'name must be a single filename component')
    require(bpy.context.mode=='OBJECT','switch to Object Mode before exporting')
    output_dir=Path(output_dir).resolve(); output_dir.mkdir(parents=True,exist_ok=True)
    prefix=output_dir/name; manifest_path=output_dir/(name+'.export.json')
    rest_path=output_dir/(name+'.rest.glb')
    paths=[prefix.with_suffix(e) for e in ('.vrs','.vrm','.vra')]+[manifest_path,rest_path]
    paths += [output_dir/f'{name}.clip-{i:03d}.glb' for i in range(len(registry['clips']))]
    require(force or all(not p.exists() for p in paths),'output exists; use --force')
    source=Path(bpy.data.filepath) if bpy.data.filepath else None
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest() if source else None
    snapshot=SceneSnapshot(bpy); scene=bpy.context.scene; fps=scene.render.fps/scene.render.fps_base
    require(fps>0,'scene FPS must be positive')
    manifest={'schema':vrview.SCHEMA,'blender_version':bpy.app.version_string,
              'source_sha256':source_hash,'source_axes':'+Z up, -Y forward',
              'export_axes':'glTF +Y up; runtime applies Ry(pi) exactly once',
              'armature':registry['armature'],'rigid_armatures':registry.get('rigid_armatures',[]),'export_objects':registry['export_objects'],
              'rest_glb':rest_path.name,'actors':actors,'fps':fps,'material_compatibility':{'base_color_only':base_color_only,'single_sided_materials':single_sided_materials},'clips':[]}
    sentinel=None
    try:
        # Blender 4.3 SCENE gathering otherwise returns before evaluating even
        # a posed neutral armature when the file has zero Actions. This empty,
        # unbound sentinel carries no authored poses and is never saved.
        if len(bpy.data.actions)==0: sentinel=bpy.data.actions.new('__vrview_sampling_sentinel__')
        snapshot.isolate({})
        for obj in bpy.context.view_layer.objects: obj.select_set(False)
        for obj in objects: obj.select_set(True)
        bpy.context.view_layer.objects.active=bpy.data.objects[registry['armature']]
        # Export authoritative geometry/rest binds once from loaded defaults.
        # Export-current-frame prevents the add-on jumping to a different rest.
        export_glb(bpy,rest_path,animation=False)
        for i,clip in enumerate(registry['clips']):
            snapshot.isolate(clip['tracks'])
            scene.frame_start=clip['frame_start']; scene.frame_end=clip['frame_end']
            scene.frame_set(snapshot.frame[0],subframe=snapshot.frame[1])
            path=output_dir/f'{name}.clip-{i:03d}.glb'
            export_glb(bpy,path,animation=True)
            visibility=[]
            for frame in range(clip['frame_start'],clip['frame_end']+1):
                scene.frame_set(frame); deps=bpy.context.evaluated_depsgraph_get(); deps.update()
                visibility.append([int(not bpy.data.objects[n].evaluated_get(deps).hide_render) for n in actors])
            metadata={k:copy.deepcopy(clip[k]) for k in ('name','frame_start','frame_end','loop','tracks')}
            metadata.update({'path':path.name,'times':[(f-clip['frame_start'])/fps for f in range(clip['frame_start'],clip['frame_end']+1)],'visibility':visibility})
            manifest['clips'].append(metadata)
        manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
        outputs=vrview.compile_manifest(manifest_path,prefix,base_color_only=base_color_only,single_sided_materials=single_sided_materials,force=force)
        require(source is None or hashlib.sha256(source.read_bytes()).hexdigest()==source_hash,'source .blend changed during export')
        return {'manifest':str(manifest_path),'outputs':[str(prefix.with_suffix(e)) for e in ('.vrs','.vrm','.vra')],
                'bytes':[len(v) for v in outputs],'source_unchanged':True}
    finally:
        snapshot.restore()
        if sentinel is not None: bpy.data.actions.remove(sentinel)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry',type=Path,required=True); parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--name',default='viewmodel'); parser.add_argument('--base-color-only',action='store_true'); parser.add_argument('--single-sided-materials',action='store_true'); parser.add_argument('--force',action='store_true')
    args=parser.parse_args(argv)
    try:
        print(json.dumps(export(args.registry,args.output_dir,args.name,base_color_only=args.base_color_only,single_sided_materials=args.single_sided_materials,force=args.force),indent=2)); return 0
    except (AssetError,OSError,ValueError,RuntimeError,TypeError,AttributeError) as exc:
        print(f'export_viewmodel: {exc}',file=sys.stderr); return 1


if __name__=='__main__':
    argv=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    sys.exit(main(argv))

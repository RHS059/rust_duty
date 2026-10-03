"""Compare original Action channels/modifiers, rig rest data and geometry to canonical source."""
import bpy,json,sys,hashlib
from pathlib import Path
P=Path(__file__).resolve().parent
sys.dont_write_bytecode=True;sys.path.insert(0,str(P))
from source_integrity import snapshot,digest

def rna_values(x,excluded=()):
 out={}
 for p in x.bl_rna.properties:
  if p.identifier in set(excluded)|{'rna_type'} or p.is_readonly:continue
  v=getattr(x,p.identifier)
  if p.type in {'BOOLEAN','INT','FLOAT','STRING','ENUM'}:out[p.identifier]=list(v) if getattr(p,'is_array',False) else sorted(v) if isinstance(v,set) else v
 return out

def frozen():
 a=bpy.data.objects['Arms']
 return {'actions':{act.name:digest([{'curve':rna_values(fc),'keys':[rna_values(k) for k in fc.keyframe_points],'modifiers':[{'type':m.type,'values':rna_values(m)} for m in fc.modifiers]} for fc in act.fcurves]) for act in bpy.data.actions},'meshes':{o.name:digest({'vertices':[list(v.co) for v in o.data.vertices],'faces':[(list(p.vertices),p.material_index,p.use_smooth) for p in o.data.polygons],'uv':{u.name:[list(x.uv) for x in u.data] for u in o.data.uv_layers},'weights':[[(g.group,g.weight) for g in v.groups] for v in o.data.vertices],'vertex_groups':[g.name for g in o.vertex_groups],'modifiers':[(m.name,m.type,rna_values(m)) for m in o.modifiers],'material_slots':[m.name if m else None for m in o.data.materials]}) for o in bpy.data.objects if o.type=='MESH'},'rest_rig':digest([(b.name,b.parent.name if b.parent else None,b.use_deform,[list(r) for r in b.matrix_local]) for b in a.data.bones]),'armature_matrix':[list(r) for r in a.matrix_world],'object_bindings':{o.name:(o.parent.name if o.parent else None,o.parent_type,o.parent_bone,[list(r) for r in o.matrix_parent_inverse]) for o in bpy.data.objects},'camera':{o.name:{'matrix':[list(r) for r in o.matrix_world],'data':rna_values(o.data)} for o in bpy.data.objects if o.type=='CAMERA'},'snapshot':snapshot(bpy)}
base=P.parent/'locomotion'/'locomotion.blend';bpy.ops.wm.open_mainfile(filepath=str(base),use_scripts=False);before=frozen();bpy.ops.wm.open_mainfile(filepath=str(P/'ads.blend'),use_scripts=False);after=frozen()
for n,h in before['actions'].items():assert after['actions'][n]==h,('action',n)
for k in ['meshes','rest_rig','armature_matrix','object_bindings','camera']:assert before[k]==after[k],k
for k in ['packed_images','drivers']:assert before['snapshot'][k]==after['snapshot'][k],k
for owner,obj in before['snapshot']['nla'].items():assert after['snapshot']['nla'][owner]['tracks'][:len(obj['tracks'])]==obj['tracks'],owner
report={'canonical_source_sha256':hashlib.sha256(base.read_bytes()).hexdigest(),'ads_source_sha256':hashlib.sha256((P/'ads.blend').read_bytes()).hexdigest(),'original_action_count':len(before['actions']),'full_original_fcurve_rna_keyframes_handles_modifiers_match':True,'original_meshes_topology_materials_uvs_skin_weights_modifiers_match':True,'rest_rig_hierarchy_matrices_and_deform_flags_match':True,'object_parent_bindings_match':True,'camera_data_and_transform_match':True,'original_nla_tracks_match':True,'packed_images_and_drivers_match':True,'original_full_action_digests':before['actions']}
(P/'frozen_source_validation.json').write_text(json.dumps(report,indent=2)+'\n');print('FROZEN_SOURCE_VERIFIED',len(before['actions']))

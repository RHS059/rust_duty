"""One bounded elbow-swivel family, fixed shoulder/wrist/pole radius. No save/render."""
import bpy,json,math
from pathlib import Path
from mathutils import Quaternion
A=bpy.data.objects['Arms'];S=bpy.context.scene;p=A.pose.bones
for t in A.animation_data.nla_tracks:t.mute=True
A.animation_data.use_nla=False;A.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];S.frame_set(1);bpy.context.view_layer.update();basis={b.name:b.matrix_basis.copy() for b in p}
rows=[]
for n in [8518,8522,8526,8530,8540,8550,8561]:
 for deg in [-90,-60,-30,0,30,60,90]:
  A.animation_data.action=None
  for b in p:b.matrix_basis=basis[b.name]
  A.animation_data.action=bpy.data.actions['aella_climb_roof_r1'];S.frame_set(n-8507+1);bpy.context.view_layer.update()
  shoulder=p['MCH_upperarm_l'].head.copy();goal=p['righthand_prop_lefthand'].matrix.translation.copy();axis=(goal-shoulder).normalized();m=p['elbow_pole_l'].matrix.copy();m.translation=shoulder+Quaternion(axis,math.radians(deg))@(m.translation-shoulder);p['elbow_pole_l'].matrix=m;A.update_tag();bpy.context.view_layer.update()
  raw=(p['MCH_attach_forearm_l'].matrix.inverted()@p['MCH_attach_goal_l'].matrix).to_euler('XYZ');angle=math.degrees(p['MCH_hand_guarded_l'].matrix.to_quaternion().rotation_difference(p['MCH_attach_goal_l'].matrix.to_quaternion()).angle)
  wrist=(p['hand_l'].matrix.translation-p['righthand_prop_lefthand'].matrix.translation).length*1000
  rows.append({'native':n,'swivel_deg':deg,'guard_deg':min(angle,360-angle),'raw_axes_deg':[math.degrees(v) for v in raw],'wrist_error_mm':wrist,'pole_location':list(p['elbow_pole_l'].location)})
P=Path(__file__).resolve().parent;(P/'elbow_swivel_probe.json').write_text(json.dumps(rows,indent=2)+'\n');print('SWIVEL_PROBE',len(rows))

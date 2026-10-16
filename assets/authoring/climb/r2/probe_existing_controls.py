"""Bounded control response for the high-obstacle r1 defects. No source save/render."""
import bpy,json,math
from pathlib import Path
A=bpy.data.objects['Arms'];S=bpy.context.scene;p=A.pose.bones
for t in A.animation_data.nla_tracks:t.mute=True
A.animation_data.use_nla=False;A.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];S.frame_set(1);bpy.context.view_layer.update();basis={b.name:b.matrix_basis.copy() for b in p}
rows=[]
controls=[('clavicle_l',.08),('elbow_pole_l',.12),('clavicle_r',.04)]
for n in [8518,8522,8526,8530,8540,8550,8561]:
 for bone,axis,amount in [('clavicle_l',0,0)]+[(b,k,v) for b,limit in controls for k in range(3) for v in [-limit,limit]]:
  A.animation_data.action=None
  for b in p:b.matrix_basis=basis[b.name]
  A.animation_data.action=bpy.data.actions['aella_climb_roof_r1'];S.frame_set(n-8507+1);bpy.context.view_layer.update();m=p[bone].matrix.copy();m.translation[axis]+=amount;p[bone].matrix=m;A.update_tag();bpy.context.view_layer.update()
  hands={}
  for side,word in [('l','left'),('r','right')]:
   raw=(p['MCH_attach_forearm_'+side].matrix.inverted()@p['MCH_attach_goal_'+side].matrix).to_euler('XYZ');angle=math.degrees(p['MCH_hand_guarded_'+side].matrix.to_quaternion().rotation_difference(p['MCH_attach_goal_'+side].matrix.to_quaternion()).angle)
   hand=A.matrix_world@p['hand_'+side].matrix;goal=A.matrix_world@p['righthand_prop_'+word+'hand'].matrix
   hands[side]={'guard_deg':min(angle,360-angle),'raw_guard_deg':angle,'raw_axes_deg':[math.degrees(v) for v in raw],'wrist_error_mm':(hand.translation-goal.translation).length*1000,'reach_margin_mm':(p['MCH_upperarm_'+side].bone.length+p['MCH_lowerarm_'+side].bone.length-(goal.translation-A.matrix_world@p['MCH_upperarm_'+side].head).length)*1000}
  rows.append({'native':n,'control':bone,'axis':axis,'offset_m':amount,'hands':hands})
P=Path(__file__).resolve().parent;(P/'control_probe.json').write_text(json.dumps(rows,indent=2)+'\n')
print('CONTROL_PROBE',len(rows))

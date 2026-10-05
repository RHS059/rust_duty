"""Bounded seven-point elbow-pole diagnostic; no save or rendering."""
import bpy,json,math
from mathutils import Vector
A=bpy.data.objects['Arms'];S=bpy.context.scene;p=A.pose.bones
for t in A.animation_data.nla_tracks:t.mute=True
A.animation_data.use_nla=False;A.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];S.frame_set(1);bpy.context.view_layer.update();basis={b.name:b.matrix_basis.copy() for b in p}
rows=[]
for n in [7329,7330,7331,7332,7333]:
 for axis,amount in [(0,0),(0,.04),(0,-.04),(1,.04),(1,-.04),(2,.04),(2,-.04)]:
  A.animation_data.action=None
  for b in p:b.matrix_basis=basis[b.name]
  A.animation_data.action=bpy.data.actions['aella_vault_low_r1'];S.frame_set(n-7284+1);bpy.context.view_layer.update();m=p['elbow_pole_l'].matrix.copy();m.translation[axis]+=amount;p['elbow_pole_l'].matrix=m;A.update_tag();bpy.context.view_layer.update()
  r=(p['MCH_attach_forearm_l'].matrix.inverted()@p['MCH_attach_goal_l'].matrix).to_euler('XYZ');err=math.degrees(p['MCH_hand_guarded_l'].matrix.to_quaternion().rotation_difference(p['MCH_attach_goal_l'].matrix.to_quaternion()).angle)
  rows.append({'native':n,'axis':axis,'amount':amount,'raw':[math.degrees(v) for v in r],'error':err})
print('PROBE',json.dumps(rows))

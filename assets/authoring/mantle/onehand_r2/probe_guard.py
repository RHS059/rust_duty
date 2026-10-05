"""Bounded existing control diagnostic; no rendering or source save."""
import bpy,json,math
A=bpy.data.objects['Arms'];S=bpy.context.scene;p=A.pose.bones
for t in A.animation_data.nla_tracks:t.mute=True
A.animation_data.use_nla=False;A.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];S.frame_set(1);bpy.context.view_layer.update();basis={b.name:b.matrix_basis.copy() for b in p}
rows=[]
for n in [7806,7818,7828,7832,7843,7873]:
 for bone,axis,amount in [('elbow_pole_l',0,0)]+[(bone,axis,amount) for bone,limit in [('elbow_pole_l',.12),('clavicle_l',.06)] for axis in range(3) for amount in [-limit,limit]]:
  A.animation_data.action=None
  for b in p:b.matrix_basis=basis[b.name]
  A.animation_data.action=bpy.data.actions['aella_mantle_onehand_r1'];S.frame_set(n-7787+1);bpy.context.view_layer.update();m=p[bone].matrix.copy();m.translation[axis]+=amount;p[bone].matrix=m;A.update_tag();bpy.context.view_layer.update()
  raw=(p['MCH_attach_forearm_l'].matrix.inverted()@p['MCH_attach_goal_l'].matrix).to_euler('XYZ');err=math.degrees(p['MCH_hand_guarded_l'].matrix.to_quaternion().rotation_difference(p['MCH_attach_goal_l'].matrix.to_quaternion()).angle)
  rows.append({'native':n,'bone':bone,'axis':axis,'amount':amount,'raw':[math.degrees(v) for v in raw],'error':err})
print('ONEHAND_PROBE',json.dumps(rows))

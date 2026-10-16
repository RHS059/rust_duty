"""One bounded shoulder-plane hypothesis, seven fixed yz combinations; no save/render."""
import bpy,json,math
A=bpy.data.objects['Arms'];S=bpy.context.scene;p=A.pose.bones
for t in A.animation_data.nla_tracks:t.mute=True
A.animation_data.use_nla=False;A.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];S.frame_set(1);bpy.context.view_layer.update();basis={b.name:b.matrix_basis.copy() for b in p}
rows=[]
for n in [7802,7804,7806,7808,7810,7814,7818,7824,7828,7830,7832,7834,7836]:
 for y,z in [(0,.06),(.015,.06),(.03,.06),(.045,.04),(.06,.03),(.06,.04),(.06,.06)]:
  A.animation_data.action=None
  for b in p:b.matrix_basis=basis[b.name]
  A.animation_data.action=bpy.data.actions['aella_mantle_onehand_r1'];S.frame_set(n-7787+1);bpy.context.view_layer.update();m=p['clavicle_l'].matrix.copy();m.translation.y+=y;m.translation.z+=z;p['clavicle_l'].matrix=m;A.update_tag();bpy.context.view_layer.update()
  raw=(p['MCH_attach_forearm_l'].matrix.inverted()@p['MCH_attach_goal_l'].matrix).to_euler('XYZ');err=math.degrees(p['MCH_hand_guarded_l'].matrix.to_quaternion().rotation_difference(p['MCH_attach_goal_l'].matrix.to_quaternion()).angle)
  rows.append({'native':n,'shoulder_y':y,'shoulder_z':z,'raw':[math.degrees(v) for v in raw],'error':err})
print('FAMILY',json.dumps(rows))

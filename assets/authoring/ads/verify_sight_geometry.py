"""Measure actual unmodified sight features and camera-ray clearance in saved ADS pose."""
import bpy,json,math,base64,sys
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras.object_utils import world_to_camera_view
P=Path(__file__).resolve().parent;D=json.loads((P/'sight_alignment.json').read_text());L=json.loads((P/'sight_landmarks.json').read_text());S=bpy.context.scene;A=bpy.data.objects['Arms'];W=bpy.data.objects['hk416_weapon'];C=bpy.data.objects['RD First Person Review']
A.animation_data.use_nla=False
for t in A.animation_data.nla_tracks:t.mute=True
A.animation_data.action=bpy.data.actions['RD_00_Supplied_Base_Guarded_Recovered'];S.frame_set(1);bpy.context.view_layer.update();A.animation_data.action=bpy.data.actions['ads_hold_r1'];S.frame_set(1);bpy.context.view_layer.update()
vertices=[v.co.copy() for v in W.data.vertices];bvh=BVHTree.FromPolygons(vertices,[list(p.vertices) for p in W.data.polygons]);inv=W.matrix_world.inverted();origin=inv@C.matrix_world.translation
points={}
for name,key in [('near_sight_post_tip','rear'),('far_sight_aperture_center','front')]:
 v=Vector(D[key+'_landmark_local']);world=W.matrix_world@v;camera=C.matrix_world.inverted()@world;q=world_to_camera_view(S,C,world)
 points[name]={'mesh_local':list(v),'blender_world':list(world),'camera_local':list(camera),'pixel_1280x720':[q.x*1280,(1-q.y)*720],'radial_distance_to_optical_ray_m':math.hypot(camera.x,camera.y),'depth_along_optical_ray_m':-camera.z}
# The supplied model has a narrow solid near central stem whose tip reaches the
# sight axis, and an EMPTY far aperture. Record the top-tip mesh vertices, not a
# presumed physical layout. No real-weapon functional inference is made.
center=Vector(D['front_landmark_local']);far_ids=[v.index for v in W.data.vertices if -.3161<v.co.z<-.3108 and .153<v.co.y<.166]
inside=[i for i in far_ids if math.hypot(vertices[i].x-center.x,vertices[i].y-center.y)<.0024]
assert not inside
rays={};fx=640/math.tan(math.radians(76)/2)
for name,px,py in [('optical_center',640,360),('above_tip_0_1px',640,359.9),('above_tip_0_5px',640,359.5),('below_tip_0_5px',640,360.5),('left_of_tip_3px',637,360),('right_of_tip_3px',643,360)]:
 dc=Vector(((px-640)/fx,(360-py)/fx,-1)).normalized();direction=(inv.to_3x3()@C.matrix_world.to_3x3()@dc).normalized();hit,normal,index,distance=bvh.ray_cast(origin,direction,10)
 rays[name]={'pixel':[px,py],'hit':hit is not None,'first_hit_local':list(hit) if hit is not None else None,'distance_m':distance,'triangle_or_polygon_index':index}
assert not rays['above_tip_0_1px']['hit'];assert not rays['above_tip_0_5px']['hit']
D['verified_visual_sight_roles']={'near_sight':'Circular surround with a central solid post/bridge. The actual top edge of that central post is at the optical center. Inherited source geometry places this assembly nearer the camera.','far_sight':'Circular aperture with no central post inside its approximately 2.43 mm artistic local-space inner radius. The aperture center is coaxial with the near post tip.','claim_limit':'The visual model does not have a conventional far-post/near-empty-aperture arrangement. This is a source-geometry fact, not a functional real-weapon specification. No missing post is invented and geometry is unchanged.'}
D['measured_landmark_evidence']=points;D['optical_ray_blender_world']={'origin':list(C.matrix_world.translation),'direction':list((C.matrix_world.to_3x3()@Vector((0,0,-1))).normalized())};D['local_sight_clearance_ray_tests']=rays;D['far_aperture_interior_vertex_count_within_local_radius_0_0024']=len(inside);D['sight_geometry_verified_without_source_modification']=True
(P/'sight_alignment.json').write_text(json.dumps(D,indent=2)+'\n')
# SVG overlays leave the native source pixels intact. The SVG viewBox provides a
# labelled enlarged crop, plus a plain diagram explaining depth/landmark roles.
image_data=base64.b64encode((P/'renders'/'aimed_hold.png').read_bytes()).decode()
svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="780" viewBox="0 0 1280 780"><rect width="1280" height="780" fill="#141a20"/><style>text{{fill:#edf2f7;font:18px sans-serif}} .small{{font-size:15px}} .line{{stroke:#67e8f9;stroke-width:2;fill:none}}</style><text x="32" y="35" font-size="25">ADS r1: actual source sights at the unchanged optical center</text><text x="32" y="64" class="small">Native Blender crop, 76° horizontal FOV. The original model has a near post and a far circular aperture.</text><defs><clipPath id="cropClip"><rect x="32" y="94" width="640" height="560"/></clipPath></defs><g clip-path="url(#cropClip)"><g transform="translate(32,94) scale(3.555555556,3.544303797) translate(-560,-290)"><image href="data:image/png;base64,{image_data}" x="0" y="0" width="1280" height="720"/><path d="M630 360H637 M643 360H650 M640 350V357 M640 363V370" stroke="#67e8f9" fill="none" stroke-width="0.3"/><circle cx="640" cy="360" r="0.7" fill="none" stroke="#ffd36d" stroke-width="0.3"/></g></g><path class="line" d="M316 342L720 160H760"/><text x="775" y="165">Optical ray: pixel (640, 360)</text><text x="720" y="215">Near central post TIP</text><text x="720" y="243" class="small">Depth: {points['near_sight_post_tip']['depth_along_optical_ray_m']:.6f} m</text><text x="720" y="270" class="small">Measured pixel: ({points['near_sight_post_tip']['pixel_1280x720'][0]:.6f}, {points['near_sight_post_tip']['pixel_1280x720'][1]:.6f})</text><text x="720" y="321">Far circular APERTURE CENTER</text><text x="720" y="349" class="small">Depth: {points['far_sight_aperture_center']['depth_along_optical_ray_m']:.6f} m</text><text x="720" y="376" class="small">Measured pixel: ({points['far_sight_aperture_center']['pixel_1280x720'][0]:.6f}, {points['far_sight_aperture_center']['pixel_1280x720'][1]:.6f})</text><text x="720" y="425" class="small">Both landmarks project to the same point.</text><text x="720" y="453" class="small">The optical ray grazes the near post top edge.</text><text x="720" y="481" class="small">0.1 pixel above: no weapon intersection.</text><text x="720" y="531" class="small">No far central post exists in the supplied mesh.</text><text x="720" y="559" class="small">No geometry or camera was changed to add one.</text><text x="32" y="700">Labels describe the existing visual model, not a real weapon's functional sight arrangement.</text><text x="32" y="735" class="small">Exact coordinates, original vertex indices, and BVH ray tests are in sight_alignment.json and sight_landmarks.json.</text></svg>'''
(P/'renders'/'sight_alignment_annotated.svg').write_text(svg)
print(json.dumps({'points':points,'rays':rays,'far_empty_aperture':True},indent=2))

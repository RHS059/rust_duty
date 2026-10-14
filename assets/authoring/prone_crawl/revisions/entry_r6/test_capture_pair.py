"""Run inside a fresh candidate Blender; confirms pair helper restores source."""
import bpy,sys,json
from pathlib import Path
P=Path(__file__).resolve().parent;sys.path.insert(0,str(P))
from source_integrity import snapshot
from validate_source_structure import extra_snapshot
from capture_pair import bind_pair,select_frame,restore_pair
before={'snapshot':snapshot(bpy),'extra':extra_snapshot()}
obj={o.name:{k:list(getattr(o,k)) for k in ('location','rotation_euler','rotation_quaternion','rotation_axis_angle','scale')} for o in bpy.data.objects}
s=bpy.context.scene;scene=(s.frame_start,s.frame_end,s.frame_current,s.frame_subframe,s.render.fps,s.render.fps_base,s.camera.name)
fm=bind_pair();rows=[]
for f in range(1,70):rows.append(select_frame(f))
restore_pair()
after={'snapshot':snapshot(bpy),'extra':extra_snapshot()}
checks={section+'.'+key:after[section][key]==value for section,values in before.items() for key,value in values.items()}
checks['object_defaults']=all(all(list(getattr(bpy.data.objects[n],k))==v for k,v in vals.items()) for n,vals in obj.items())
checks['scene']=(s.frame_start,s.frame_end,s.frame_current,s.frame_subframe,s.render.fps,s.render.fps_base,s.camera.name)==scene
checks['camera_unbound']=bpy.data.objects['RD First Person Review'].animation_data is None
checks['depth'] = abs(rows[34]['camera_world'][2][3]+1.3)<1e-6
assert all(checks.values()),checks
(P/'capture_pair_checks.json').write_text(json.dumps({'checks':checks,'rendered':False,'frames_exercised':69},indent=2));print(json.dumps(checks))

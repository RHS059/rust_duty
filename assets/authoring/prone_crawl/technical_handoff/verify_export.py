"""Verify isolated FBX take inventory, exact bake schedule and native loop seams."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
from io_scene_fbx import parse_fbx

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--directory',required=True,type=Path)
p.add_argument('--config',required=True,type=Path)
p.add_argument('--output',required=True,type=Path)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
c=json.loads(a.config.read_text()); root,version=parse_fbx.parse(str(a.directory/'prone_handoff.fbx'))
objects=next(e for e in root.elems if e.id==b'Objects').elems
by_id={e.props[0]:e for e in objects}
links=next(e for e in root.elems if e.id==b'Connections').elems
children={}
for e in links:children.setdefault(e.props[2],[]).append(e.props[1])
stacks=[e for e in objects if e.id==b'AnimationStack']
TICKS=46186158000
rows={}
for stack in stacks:
 name=stack.props[1].split(b'\x00')[0].decode();take=next(t for t in c['source_takes'] if t['name']==name)
 descendants=[];todo=children.get(stack.props[0],[])[:]
 while todo:
  n=todo.pop();descendants.append(by_id[n]);todo.extend(children.get(n,[]))
 curves=[e for e in descendants if e.id==b'AnimationCurve']
 expected=(take['frame_end']-take['frame_start'])*8+1
 key_counts=[];durations=[];step_error=[]
 for curve in curves:
  time=np.asarray(next(e.props[0] for e in curve.elems if e.id==b'KeyTime'),dtype=np.float64)/TICKS
  values=np.asarray(next(e.props[0] for e in curve.elems if e.id==b'KeyValueFloat'),dtype=np.float64)
  assert np.isfinite(time).all() and np.isfinite(values).all(), 'Nonfinite FBX animation data'
  key_counts.append(len(time));durations.append(float(time[-1]-time[0]));step_error.append(float(np.max(np.abs(np.diff(time)-1/480))))
 rows[name]={'curve_count':len(curves),'key_counts':dict(Counter(key_counts)), 'expected_keys_per_curve':expected,
             'duration_seconds':durations[0],'duration_matches':all(abs(d-take['duration_seconds'])<1e-8 for d in durations),
             'max_step_error_seconds':max(step_error),'sample_count_matches':all(k==expected for k in key_counts)}
 assert len(curves)==675 and rows[name]['duration_matches'] and rows[name]['sample_count_matches'] and max(step_error)<1e-9
assert set(rows)=={t['name'] for t in c['source_takes']}
meta=json.loads((a.directory/'native_oracle.json').read_text());data=np.load(a.directory/'native_oracle.npz');seams={}
for name in rows:
 for suffix in ('bones','actors','skin_0','skin_1','skin_2'):
  arr=data[name+'__'+suffix];seams[name+'__'+suffix]={'exact_endpoint_repeat':np.array_equal(arr[0],arr[-1]),'maximum_absolute_endpoint_difference':float(np.max(np.abs(arr[0]-arr[-1])))}
assert all(not row['loop'] for row in c['source_takes']), 'Unfinished segments must not activate as loops'
report={'schema':'rust-duty-prone-technical-fbx-validation/v1','fbx_version':version,'source_sha256':meta['source_files_sha256'],
 'fbx_sha256':hashlib.sha256((a.directory/'prone_handoff.fbx').read_bytes()).hexdigest(),'blender':meta['blender'],'source_fps':60,'bake_hz':480,
 'deform_bone_count':len(meta['deform_bones']),'skin_objects':meta['skin_objects'],'actors':meta['actors'],'takes':rows,'native_endpoint_seams':seams,
 'passed':True,'scope':'FBX inventory/bake schedule and descriptive native endpoint differences for nonloop segments. No loop/visual/gameplay approval. No runtime conversion or integration.'}
report['all_sampled_arrays_finite']=all(bool(np.isfinite(data[k]).all()) for k in data.files)
assert report['all_sampled_arrays_finite']
report['contact_sampling_hz']=480
report['contact']={name:{'samples':len(values),'max_wrist_solve_error_m':{side:max(row['wrist_solve_error_m'][side] for row in values) for side in ['l','r']},'all_samples_finite':all(np.isfinite(v) for row in values for v in row['wrist_solve_error_m'].values())} for name,values in meta['contact_samples'].items()}
report['contact_240hz']={name:{'samples':len(values[::2]),'max_wrist_solve_error_m':{side:max(row['wrist_solve_error_m'][side] for row in values[::2]) for side in ['l','r']}} for name,values in meta['contact_samples'].items()}
report['contact_acceptance']=False
report['inventory_and_bake_passed']=report.pop('passed')
report['contact_threshold_m']=0.0001
report['contact_numeric_threshold_passed']=all(max(row['max_wrist_solve_error_m'].values())<=report['contact_threshold_m'] for row in report['contact'].values())
report['passed']=report['inventory_and_bake_passed'] and report['all_sampled_arrays_finite'] and report['contact_numeric_threshold_passed']
report['production_activation_allowed']=False
report['all_fbx_curve_keys_finite']=True
report['render_performed']=False
report['source_saved']=False
a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

"""Recover pinned public project inputs to NEW paths, checking bytes before write."""
import argparse,hashlib,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--kind',choices=['baseline','reference'],required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
assert not a.output.exists(),'Refuse overwrite'
if a.kind=='baseline':
 commit='e9317f90ea171976306e2f17c111325d948ea357';paths=['assets/authoring/jump/halcyon_jump.blend'];expected='a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b'
else:
 commit='58dad13f51db3dd951f43f3fd7ddc3fbd020ad00';paths=[f'references/movement/modern_warfare_2022_movement_reference.mp4.parts/part-{i:03}.bin' for i in range(7)];expected='491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46'
raw=b''.join(subprocess.check_output(['git','-C',str(a.repo),'show',commit+':'+path]) for path in paths);actual=hashlib.sha256(raw).hexdigest();assert actual==expected,(actual,expected)
a.output.parent.mkdir(parents=True,exist_ok=True)
with a.output.open('xb') as f:f.write(raw)
assert hashlib.sha256(a.output.read_bytes()).hexdigest()==expected
print(a.kind,len(raw),actual,a.output)

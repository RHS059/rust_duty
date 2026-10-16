"""Exact bounded storage of LINEAR curve neighbors, after full transformation."""
from pathlib import Path
import bisect,hashlib,json,math,struct
import numpy as np
HERE=Path(__file__).resolve().parent;WORK=HERE.parent;ROOT=WORK.parent
SOURCE_SHA='b5cae854b1e5e21c44e60a0672dd18c26e7b38acb239f4730b681482bc409d77'
OLD_FBX=ROOT/'onehand-runtime-20261016/dense-output-v1/aella_onehand_camera_reconstructed_v6.fbx'
OLD_SHA='17608683c81465964b5890b4d9869774a0f35122cf62ebd6e564cedf1b1ddbe4'
NEW_FBX=WORK/'dense-output-v1/aella_onehand_camera_reconstructed_v6.fbx'
NEW_SHA='5b847bf47cfafdf9a4b4d32f3d5972e677698db3f47cdc7a4a36a4b7698ee2c2'
FULL_CONTROL=ROOT/'onehand-runtime-20261016/diagnostics/chunk036-scalar-v1/native-job/import.json'
FOCUS=tuple(55.65625+i/512 for i in range(9))
KEY_CAP=4096
RAW_CURVES=1379
LIMIT=1e-4

def require(ok,message):
 if not ok:raise ValueError(message)

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(1024**2),b''):h.update(block)
 return h.hexdigest()

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def array_hash(value,dtype):return hashlib.sha256(np.asarray(value,dtype=dtype).tobytes()).hexdigest()
def native_grid(n):return 1+np.arange(95*n+1,dtype=np.float32)/n

def selection(frames,n):
 require(type(n) is int and n in (64,256),'unsupported immutable grid')
 require(frames and all(type(f) in (float,int) and math.isfinite(f) and 1<=f<=96 for f in frames),'invalid requested frame')
 require(list(frames)==sorted(set(frames)),'requested samples must be ordered unique')
 keep={0,95*n};brackets=[]
 for f in frames:
  pos=(f-1)*n;lo=math.floor(pos);hi=math.ceil(pos);keep.update((lo,hi))
  brackets.append({'source_frame':f,'lower_index':lo,'upper_index':hi,'lower_frame':1+lo/n,'upper_frame':1+hi/n})
 indices=sorted(keep);require(len(indices)<=KEY_CAP,'retained key cap exceeded')
 return {'requested_source_frames':list(frames),'allowed_evaluation_frames':sorted(set([1.,*frames])),
         'retained_indices':indices,'retained_source_frames':[1+i/n for i in indices],
         'sample_brackets':brackets,'retained_key_count':len(indices),'full_key_count':95*n+1,'subdivisions':n}

def validate_arrays(times,values,n,flags=(24836,),refs=None):
 count=95*n+1;t=np.asarray(times);v=np.asarray(values)
 require(t.ndim==v.ndim==1 and len(t)==len(v)==count,'raw array count/shape differs')
 require(np.issubdtype(t.dtype,np.integer) and np.all(np.diff(t)>0),'raw times invalid')
 require(np.isfinite(v).all(),'nonfinite raw values')
 require(list(flags)==[24836] and list(refs or [count])==[count],'nonlinear or malformed attribute/refcount')
 frames=t.astype(np.float64)*60/46186158000
 require(np.max(np.abs(frames-native_grid(n).astype(np.float64)))<=2*60/46186158000,'raw rational grid differs')
 return {'key_count':count,'time_sha256':array_hash(t,'<i8'),'value_sha256':array_hash(v,'<f4')}

def verify_pins():
 pins=json.loads((HERE/'pins.json').read_text())
 for name,value in pins['files'].items():require(sha(ROOT/name)==value,'window input/code pin differs: '+name)
 for name,value in pins['installed_files'].items():require(sha(name)==value,'installed module differs: '+name)
 return sha(HERE/'pins.json')

def linear_value(times,values,f):
 i=bisect.bisect_left(times,f)
 if i<len(times) and times[i]==f:return values[i]
 require(0<i<len(times),'sample outside interpolation coverage')
 a,b=times[i-1:i+1];v,w=values[i-1:i+1]
 return v+(w-v)*((f-a)/(b-a))

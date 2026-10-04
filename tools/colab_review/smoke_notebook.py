import json, sys, types
from pathlib import Path
nb=json.loads((Path(__file__).parent/'Rust_Duty_Animation_Review.ipynb').read_text())
# Stub only the download UI, never analysis or GPU execution.
google=types.ModuleType('google'); colab=types.ModuleType('google.colab')
colab.files=types.SimpleNamespace(download=lambda p:print('DOWNLOAD READY',p))
sys.modules['google']=google; sys.modules['google.colab']=colab
namespace={}
for i,c in enumerate(nb['cells']):
 if c['cell_type']!='code':continue
 source=''.join(c['source'])
 if '%pip' in source:continue # Installed local environment, versions recorded in output
 print('CELL',i)
 exec(compile(source,f'cell-{i}','exec'),namespace)
assert namespace['result']['status']=='diagnostic'
assert namespace['report']['clips'][0]['bones']['endpoint_gap']['translation_max']==0
assert not namespace['result']['artistic_approval']
try:
 import nbformat
 nbformat.validate(nb)
 print('NBFORMAT VALID')
except ImportError:print('nbformat unavailable')

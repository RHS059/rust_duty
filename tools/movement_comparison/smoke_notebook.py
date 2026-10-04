"""Execute the real embedded CPU demo, stubbing only Colab download UI."""
import json
from pathlib import Path
import sys
import types
root=Path(__file__).parent
nb=json.loads((root/'Weapon_Motion_Measurements.ipynb').read_text())
google=types.ModuleType('google');colab=types.ModuleType('google.colab')
colab.files=types.SimpleNamespace(download=lambda path:print('DOWNLOAD READY',path))
sys.modules['google']=google;sys.modules['google.colab']=colab
namespace={}
for cell in nb['cells']:
    if cell['cell_type']=='code':
        exec(compile(''.join(cell['source']),cell['id'],'exec'),namespace)
assert namespace['result']['score'] is None
assert not namespace['result']['artistic_approval']
assert namespace['result']['execution']['synthetic'] is True
assert namespace['result']['aggregate']['raw']['max']==0
assert namespace['archive'].is_file()
print('Synthetic CPU notebook smoke passed; no real clip review or Colab session implied.')

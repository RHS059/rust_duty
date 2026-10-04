"""Build an isolated CPU-only notebook without changing PR31's review notebook."""
import json
from pathlib import Path
root=Path(__file__).parent
module=(root/'compare.py').read_text()
example=(root/'example.synthetic.json').read_text()
cells=[]
def cell(kind,id,source):
    value={'cell_type':kind,'id':id,'metadata':{},'source':source.splitlines(True)}
    if kind=='code':value.update(execution_count=None,outputs=[])
    cells.append(value)
cell('markdown','weapon-intro','''# Weapon motion measurements · CPU batch
Measurement-only, no similarity percentage or artistic approval. Use a CPU runtime.
No GPU, tracker model, rendering, Drive mount, repository fetch or credentials.
Supply one JSON per action with original source pixels, exact decoded PTS,
evaluated candidate pixels and explicit visibility/uncertainty. Physical anchor
and phase definitions must be independently checked before using any result.
This does not modify the general animation review notebook.
''')
cell('code','weapon-module',"import types,sys,hashlib,json,tempfile,zipfile\nfrom pathlib import Path\nMODULE_SOURCE = "+repr(module)+"\nmodule=types.ModuleType('weapon_compare'); module.__file__='<embedded:weapon_compare>'\nsys.modules['weapon_compare']=module\nexec(compile(MODULE_SOURCE,module.__file__,'exec'),module.__dict__)\nCODE_SHA256=hashlib.sha256(MODULE_SOURCE.encode()).hexdigest()\nprint('Module SHA256:',CODE_SHA256)\n")
cell('code','weapon-input',"DEMO=True # False: upload one bounded comparison JSON; do not upload private assets.\nDECODED_PTS_JSON='' # Optional exact filename of independently decoded ffprobe frame map.\nif DEMO:\n    INPUTS={'example.synthetic.json':"+repr(example.encode())+"}\n    INPUT_JSON='example.synthetic.json'\nelse:\n    from google.colab import files\n    INPUTS=files.upload()\n    if not 1 <= len(INPUTS) <= 2 or any(not n.endswith('.json') or len(b)>module.MAX_BYTES for n,b in INPUTS.items()):\n        raise ValueError('Select comparison JSON and optional decoded PTS JSON only, max32MiB each')\n    INPUT_JSON=next(n for n in INPUTS if n!=DECODED_PTS_JSON)\n    if len(INPUTS)==2 and not DECODED_PTS_JSON:\n        raise ValueError('Set DECODED_PTS_JSON to the exact second file name before running')\n    print('Selected comparison:',INPUT_JSON)\n")
cell('code','weapon-compare',"doc=module.strict_json(INPUTS[INPUT_JSON])\npts=INPUTS[DECODED_PTS_JSON] if DECODED_PTS_JSON else None\nresult=module.compare(doc,decoded_pts=pts)\nresult['code_sha256']=CODE_SHA256\nresult['input_file_sha256']=module.sha256(INPUTS[INPUT_JSON])\nresult['execution']={'backend':'CPU','synthetic':DEMO,'scope':'weapon measurements only'}\nOUTPUT=Path(tempfile.mkdtemp(prefix='weapon-motion-'))\n(OUTPUT/'report.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\\n')\nmodule.plot_report(result,OUTPUT/'residuals.png')\nfrom IPython.display import display,Image\ndisplay(Image(filename=str(OUTPUT/'residuals.png')))\nprint(json.dumps({'action':result['action'],'score':result['score'],'unsupported':result['unsupported'],'hard_gate_findings':result['hard_gate_findings']},indent=2))\n")
cell('code','weapon-export',"archive=OUTPUT.parent/(OUTPUT.name+'.zip')\nwith zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:\n    for p in sorted(OUTPUT.iterdir()):z.write(p,p.name)\nARCHIVE_SHA256=module.sha256(archive.read_bytes())\nprint('Result ZIP SHA256:',ARCHIVE_SHA256)\nfrom google.colab import files\nfiles.download(str(archive))\n")
cell('markdown','weapon-preserve','''Save and independently hash-check the downloaded ZIP before releasing a runtime.
A download request does not prove durable preservation. After saving, use
Runtime → Disconnect and delete runtime; verify no active entry remains in
Manage sessions. No automatic GPU allocation or automatic teardown is performed.
All source/candidate artifact hashes remain declared unless their bytes were
verified separately. This notebook verifies an optional PTS map, not video pixels.
''')
nb={'nbformat':4,'nbformat_minor':5,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python'},'colab':{'name':'Weapon_Motion_Measurements.ipynb'}},'cells':cells}
(root/'Weapon_Motion_Measurements.ipynb').write_text(json.dumps(nb,indent=1)+'\n')

import json, hashlib
from pathlib import Path
root=Path(__file__).parent
cells=[]
def md(s): cells.append({'cell_type':'markdown','metadata':{},'source':s.splitlines(True)})
def code(s): cells.append({'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],'source':s.splitlines(True)})
md('''# Rust Duty · animation review / Colab
Status: diagnostic. Technical measurements never grant artistic approval.

1. Open this notebook in Colab. Runtime → Change runtime type → A100 GPU, if available. CPU is sufficient for pack checks/plots. An A100 only runs the optional explicitly enabled contact-array calculation; no ML model, training, video rendering or Blender installation is performed.
2. Run setup, then the synthetic demo once. Set DEMO=False and upload a ZIP containing only authorized `.vra` and optional matching `.vrs`/`.vrm`, JSON telemetry, and source/candidate PNG/JPEG stills. Never upload private soldier assets. You choose inputs; this notebook does not clone repositories, mount Drive, request credentials, or send files anywhere else.
3. Select a pack, clip, channel and explicit transitions. Run the review and download the results ZIP.
4. Save the results before Runtime → Disconnect and delete runtime. Do not leave A100 allocated for CPU work. Availability, runtime limits and compute-unit consumption vary; no fixed cost promise is made.

[Official Colab FAQ](https://research.google.com/colaboratory/faq.html). Notebook sharing includes saved outputs: clear them before sharing.

## Scope
VRANIM01 validated with the project's embedded original parsers. Companion checks verify structure/checksums/bone identity/rigid assignments when companions exist, not evaluated skin or contact. Curves are stored parent-local bone TRS and scene-global actor TRS, glTF Y-up. Runtime applies Ry(pi); runtime blend logic is not reproduced. Translation units require source verification. Loop endpoints and selected end-to-start joins are diagnostics, never an automatic failure threshold. Speed statistics are sampled segment-average values; shortest-arc rotations can alias motion over 180 degrees between samples. They are not continuous-time peak speeds.
''')
code('''# Pinned direct dependencies from the standard PyPI registry. No shell installer scripts.
%pip -q install numpy==2.2.6 matplotlib==3.10.8 Pillow==12.3.0
# NumPy 2.2.6 satisfies Colab's observed Numba 0.61.2 (<2.3) constraint.
# Do not analyze with an older NumPy module still loaded after changing its wheel.
import sys, importlib.metadata
installed_numpy=importlib.metadata.version('numpy')
loaded_numpy=getattr(sys.modules.get('numpy'),'__version__',installed_numpy)
if installed_numpy!='2.2.6': raise RuntimeError('NumPy installation did not match the 2.2.6 pin')
if loaded_numpy!=installed_numpy:
    raise RuntimeError('NumPy changed while already imported. Restart the session, then rerun from setup before analysis.')
try:
    from packaging.requirements import Requirement
    for item in importlib.metadata.requires('numba') or []:
        req=Requirement(item)
        if req.name.lower()=='numpy' and (req.marker is None or req.marker.evaluate()):
            if installed_numpy not in req.specifier:
                raise RuntimeError('Installed Numba requires '+str(req)+'; stop before analysis')
except importlib.metadata.PackageNotFoundError:
    pass # Numba is optional and not installed by this notebook.
''')
parser_dir=root/'vendor' if (root/'vendor').is_dir() else root.parent
sources={name:(parser_dir/f'{name}.py').read_text() for name in ('vrpack','vrskin','vrview')}
sources['review']=(root/'review.py').read_text()
code('''# Frozen original source modules; no remote code fetch and no uploaded code execution.
import sys, types, hashlib, json, platform, tempfile, zipfile, importlib.metadata
from pathlib import Path
SOURCES = '''+repr(sources)+'''
CODE_HASHES = {name: hashlib.sha256(s.encode()).hexdigest() for name,s in SOURCES.items()}
for name, source in SOURCES.items():
    module=types.ModuleType(name); module.__file__='<embedded:'+name+'>'
    sys.modules[name]=module; exec(compile(source,module.__file__,'exec'),module.__dict__)
import review
import numpy as np
from IPython.display import display, Image
OUTPUT=Path(tempfile.mkdtemp(prefix='rust-duty-review-'))
print('Output folder:', OUTPUT)
print('Python:',platform.python_version())
try:
    import torch
    print('Torch:',torch.__version__,'CUDA:',torch.cuda.is_available())
    if torch.cuda.is_available(): print('Actual GPU:',torch.cuda.get_device_name(0))
except ImportError:
    print('PyTorch unavailable. CPU review works. No GPU package is installed automatically.')
''')
md('''## Inputs
ZIPs are read into bounded memory without extraction. Supported files only; paths, symlinks, duplicate names, encrypted files and oversize archives are rejected. Lowercase extensions only; plain `.vra`, not `.gz`.

Each pack may have same-prefix companions (`ads/asset.vra`, `ads/asset.vrs`, `ads/asset.vrm`). Companion assets are optional: omit anything private. Reports contain filenames/hashes/measurements, not copies of uploaded assets.
''')
code('''DEMO = True # Change to False for your own authorized review ZIP.
if DEMO:
    import struct, zlib
    name=b'demo_loop'
    payload=struct.pack('<IIIH',0,0,1,4)+b'root'+struct.pack('<iII',-1,0,1)
    payload+=struct.pack('<H',len(name))+name+struct.pack('<II',1,3)
    for t,x in [(0.,0.),(.5,.01),(1.,0.)]:
        payload+=struct.pack('<f10f',t,x,0,0,0,0,0,1,1,1,1)
    demo=struct.pack('<8sIIII',b'VRANIM01',1,len(payload),zlib.crc32(payload),0)+payload
    INPUTS={'demo.vra':demo}
    INPUT_ORIGIN='synthetic diagnostic fixture, not game or approved motion'
else:
    from google.colab import files
    upload=files.upload()
    if len(upload)!=1 or not next(iter(upload)).lower().endswith('.zip'):
        raise ValueError('Select exactly one authorized review ZIP')
    INPUTS=review.safe_inputs(next(iter(upload.values())))
    INPUT_ORIGIN='user-selected ZIP; ownership and source provenance not independently verified'
print('Available packs:',[p for p in INPUTS if p.endswith('.vra')])
''')
code('''PACK = 'demo.vra' # Use an exact available pack path.
TRANSITIONS = [] # Explicit [(from_clip, to_clip), ...], same pack only.
if PACK not in INPUTS: raise ValueError('Select an available PACK above')
OUTPUT=Path(tempfile.mkdtemp(prefix='rust-duty-review-')) # Fresh per pack review; no stale evidence
cuda_smoke={'status':'not run','scope':'synthetic numerical smoke, not game animation approval'}
contact={'status':'not measured','reason':'No evaluated world-space contact samples supplied'}
visual={'status':'not reviewed','artistic_approval':False}
prefix=PACK[:-4]
pack,report=review.analyze_pack(INPUTS[PACK],INPUTS.get(prefix+'.vrs'),INPUTS.get(prefix+'.vrm'),TRANSITIONS)
print(json.dumps(report,indent=2))
print('Bone channels:',list(enumerate(b[0] for b in pack['bones'])))
print('Actor channels:',list(enumerate(a['name'] for a in pack['actors'])))
''')
code('''CLIP = pack['clips'][0]['name']
CHANNEL_KIND = 'bones' # 'bones' or 'actors'
CHANNEL_INDEX = 0
review.plot_motion(pack,CLIP,CHANNEL_KIND,CHANNEL_INDEX,OUTPUT/'motion.png')
display(Image(filename=str(OUTPUT/'motion.png')))
''')
md('''## Optional evaluated contact telemetry
Set CONTACT_JSON to a uploaded JSON name. Required schema:
`{"schema":"rust-duty-contact-samples/v1","units":"metres","space":"evaluated-world","source_sha256":"64 lowercase hex characters","pairs":[{"name":"index pad to fixed magazine anchor","time_seconds":[0,0.25],"a":[[0,0,0],[0,0,0]],"b":[[0,0,0],[0.001,0,0]],"observed":[true,false]}]}`

Coordinates are bounded to +/-10000 metres per axis. Supply evaluated corresponding world-space points from a known exported source, with named physical anchors. Do not substitute raw local bones for contact, invent landmarks or infer occluded samples. Sample switch neighborhoods and quarter frames in the authoring/export workflow. This tool only measures supplied point separation and observable coverage. It does not establish surface clearance, penetration, grip orientation or anatomy. If source bytes are absent, source hash remains declared, unverified.

CUDA is optional using Colab's existing PyTorch. Small arrays are usually faster/cheaper on CPU. Enabling CUDA records the actual backend and verifies against float64 CPU results (rtol 1e-9, atol 1e-10); lack of CUDA is an explicit error rather than a silent fallback. No speedup or A100 execution is claimed until this cell succeeds.
''')
code('''CONTACT_JSON = '' # Empty means missing, not passed.
USE_CUDA_CONTACT = False
contact={'status':'not measured','reason':'No evaluated world-space contact samples supplied'}
if CONTACT_JSON:
    doc=review.strict_json(INPUTS[CONTACT_JSON])
    contact=review.contact_report(doc,use_cuda=USE_CUDA_CONTACT)
    contact['source_hash_verified']=doc['source_sha256'] in [review.digest(b) for b in INPUTS.values()]
print(json.dumps(contact,indent=2))
''')
md('''## Optional reference comparison
Use unwarped stills from the actual reference and the same candidate time. Fill in exact source frame/PTS and candidate sample time below. Images are separately aspect-preserving downscaled for display, never registered, cropped or stretched. No similarity score is computed. Inspect silhouette, wrist/finger anatomy, contact, camera and visibility yourself. This is a still comparison, not a complete clip review. No video decoding/timing is inferred.
''')
code('''(OUTPUT/'comparison.png').unlink(missing_ok=True)
REFERENCE_IMAGE = ''
CANDIDATE_IMAGE = ''
REFERENCE_FRAME_AND_PTS = '' # Example: frame 123, PTS 4100/1000 seconds; observed, not inferred
CANDIDATE_SAMPLE_TIME = '' # Example: 4.1 seconds
visual={'status':'not reviewed','artistic_approval':False}
if REFERENCE_IMAGE or CANDIDATE_IMAGE:
    if not all((REFERENCE_IMAGE,CANDIDATE_IMAGE,REFERENCE_FRAME_AND_PTS,CANDIDATE_SAMPLE_TIME)):
        raise ValueError('Specify both images and exact frame/time labels')
    review.compare_images(INPUTS[REFERENCE_IMAGE],INPUTS[CANDIDATE_IMAGE],OUTPUT/'comparison.png',
                          'Reference: '+REFERENCE_FRAME_AND_PTS,'Candidate: '+CANDIDATE_SAMPLE_TIME)
    display(Image(filename=str(OUTPUT/'comparison.png')))
    visual.update(status='paired stills prepared; human inspection required',reference=REFERENCE_IMAGE,
                  candidate=CANDIDATE_IMAGE,reference_frame_pts=REFERENCE_FRAME_AND_PTS,candidate_time=CANDIDATE_SAMPLE_TIME)
''')
code('''# Reproducible, evidence-scoped result; no raw uploaded assets included.
if not (OUTPUT/'motion.png').exists(): raise ValueError('Run the motion plot for this pack before exporting')
versions={p:importlib.metadata.version(p) for p in ('numpy','matplotlib','Pillow')}
try: versions['torch']=importlib.metadata.version('torch')
except importlib.metadata.PackageNotFoundError: pass
result={'schema':'rust-duty-colab-review/v1','status':'diagnostic','artistic_approval':False,
        'input_origin':INPUT_ORIGIN,'inputs':{n:{'sha256':review.digest(b),'bytes':len(b)} for n,b in INPUTS.items()},
        'code_sha256':CODE_HASHES,'python':platform.python_version(),'dependencies':versions,
        'selection':{'pack':PACK,'clip':CLIP,'channel_kind':CHANNEL_KIND,'channel_index':CHANNEL_INDEX,'transitions':TRANSITIONS},
        'pack':report,'contact':contact,'visual':visual,
        'cuda_smoke':globals().get('cuda_smoke',{'status':'not run'}),
        'remaining_gates':['evaluated skin and full-motion visual inspection','source timing/camera verification',
                           'Blender evaluated bake/export/reimport parity','target game runtime verification']}
(OUTPUT/'report.json').write_text(json.dumps(result,indent=2,allow_nan=False))
archive=OUTPUT.parent/(OUTPUT.name+'.zip')
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
    for path in sorted(OUTPUT.iterdir()): z.write(path,path.name)
EXPORTED_OUTPUT_HASHES={p.name:review.digest(p.read_bytes()) for p in OUTPUT.iterdir() if p.is_file()}
ARCHIVE_SHA256=review.digest(archive.read_bytes())
print('Saved:',archive,'SHA256:',ARCHIVE_SHA256)
from google.colab import files
files.download(str(archive))
''')
md('''## Stop the paid session
After the ZIP download completes, use **Runtime → Disconnect and delete runtime**. Closing this tab alone is not the explicit runtime teardown. Save the notebook separately if desired, with sensitive outputs omitted. Do not use keepalive scripts or background loops.

Validation of this delivered notebook: local synthetic and repository pack CPU checks are documented with the source changes. A100 execution and this account's Colab environment require an actual session run; they are not implied by notebook preparation.
''')
nb={'nbformat':4,'nbformat_minor':5,'metadata':{'colab':{'name':'Rust_Duty_Animation_Review.ipynb'},'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python'},'accelerator':'GPU'},'cells':cells}
for i,c in enumerate(cells): c['id']=f'review-{i:02d}'
# Keep all original cell IDs unchanged when adding the batch lifecycle.
from batch_cells import CUDA_SMOKE, TEARDOWN, TEARDOWN_DOC
cells.insert(11, {'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],
                  'source':CUDA_SMOKE.splitlines(True),'id':'batch-cuda-smoke-v1'})
cells[-1]['source']=TEARDOWN_DOC.splitlines(True) # existing review-12 markdown ID
cells.append({'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],
              'source':TEARDOWN.splitlines(True),'id':'batch-teardown-v1'})
(root/'Rust_Duty_Animation_Review.ipynb').write_text(json.dumps(nb,indent=1)+'\n')

"""Rust Duty offline animation diagnostics. No artistic approval or rendering."""
import hashlib, io, json, math, platform, stat, zipfile
from pathlib import Path, PurePosixPath
import numpy as np
import vrview

MAX_INPUT = 128 * 1024 * 1024
ALLOWED = {'.vra', '.vrs', '.vrm', '.json', '.png', '.jpg', '.jpeg'}

def digest(data): return hashlib.sha256(data).hexdigest()

def safe_inputs(data):
    """Read ZIP into memory, never extract or execute its contents."""
    if len(data) > MAX_INPUT: raise ValueError('ZIP exceeds 128 MiB')
    result = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = z.infolist()
        if len(infos) > 512: raise ValueError('Too many ZIP members')
        if sum(i.file_size for i in infos) > 256 * 1024 * 1024:
            raise ValueError('Expanded ZIP exceeds 256 MiB')
        for i in infos:
            p = PurePosixPath(i.filename)
            if (p.is_absolute() or '..' in p.parts or '\\' in i.filename or ':' in i.filename
                or stat.S_ISLNK(i.external_attr >> 16) or i.flag_bits & 1):
                raise ValueError('Unsafe/encrypted ZIP member')
            if i.is_dir(): continue
            if p.suffix not in ALLOWED: raise ValueError('Unsupported ZIP member: ' + i.filename)
            if i.filename in result or i.file_size > MAX_INPUT: raise ValueError('Duplicate/oversize input')
            with z.open(i) as f: b = f.read(MAX_INPUT + 1)
            if len(b) != i.file_size or len(b) > MAX_INPUT: raise ValueError('Input size mismatch')
            result[i.filename] = b
    return result

def strict_json(data):
    def reject(x): raise ValueError('Nonfinite JSON: ' + x)
    def unique(pairs):
        d = {}
        for k,v in pairs:
            if k in d: raise ValueError('Duplicate JSON key')
            d[k] = v
        return d
    def finite_float(x):
        f=float(x)
        if not math.isfinite(f): raise ValueError('Nonfinite JSON number')
        return f
    return json.loads(data, parse_constant=reject, parse_float=finite_float, object_pairs_hook=unique)

def angle(a, b):
    a = np.asarray(a, dtype=np.float64); b = np.asarray(b, dtype=np.float64)
    a = a / np.linalg.norm(a, axis=-1, keepdims=True)
    b = b / np.linalg.norm(b, axis=-1, keepdims=True)
    # atan2 is stable for near-identical rotations and invariant to quaternion sign.
    sign = np.where(np.sum(a*b, axis=-1, keepdims=True) < 0, -1., 1.)
    b = b * sign
    return np.degrees(4 * np.arctan2(np.linalg.norm(a-b, axis=-1), np.linalg.norm(a+b, axis=-1)))

def endpoint(a,b):
    a=np.asarray(a); b=np.asarray(b)
    if not a.size: return {'translation_max': None, 'rotation_degrees_max': None, 'scale_max': None}
    return {'translation_max':float(np.linalg.norm(a[:,:3]-b[:,:3],axis=1).max()),
            'rotation_degrees_max':float(angle(a[:,3:7],b[:,3:7]).max()),
            'scale_max':float(np.abs(a[:,7:]-b[:,7:]).max())}

def channels(clip, kind): return np.asarray([f[kind] for f in clip['frames']], dtype=np.float64)

def analyze_pack(data, skin=None, mesh=None, transitions=()):
    pack=vrview.decode_vra(data, vrs=skin, vrm=mesh)
    result={'sha256':digest(data), 'status':'diagnostic',
        'coordinates':'glTF Y-up; bone TRS parent-local, actors scene-global; runtime Ry(pi) not applied',
        'units':'export translation units; do not assume metres without source declaration',
        'binding':{'skin_structure_crc_skeleton_checked':skin is not None,
                   'rigid_structure_crc_assignment_checked':mesh is not None,
                   'skin_deformation_contact_or_runtime_verified':False},
        'clips':[], 'transitions':[]}
    for c in pack['clips']:
        times=np.asarray([f['time'] for f in c['frames']]); dt=np.diff(times)
        row={'name':c['name'],'frames':len(times),'duration_seconds':float(times[-1]),'loop':c['loop']}
        for kind in ('bones','actors'):
            x=channels(c,kind)
            values={'endpoint_gap': endpoint(x[-1],x[0]) if c['loop'] else None}
            if len(times)>1 and x.size:
                speed=np.linalg.norm(np.diff(x[:,:,:3],axis=0),axis=2)/dt[:,None]
                angular=angle(x[:-1,:,3:7],x[1:,:,3:7])/dt[:,None]
                values.update(maximum_sampled_translation_speed=float(speed.max()),maximum_sampled_shortest_arc_rotation_deg_s=float(angular.max()))
            row[kind]=values
        v=np.asarray([f['visible'] for f in c['frames']])
        row['visibility_change_count']=int(np.count_nonzero(np.diff(v,axis=0))) if len(times)>1 else 0
        result['clips'].append(row)
    lookup={c['name']:c for c in pack['clips']}
    for pair in transitions:
        if not isinstance(pair,(list,tuple)) or len(pair)!=2 or any(n not in lookup for n in pair):
            raise ValueError('Transitions must name two existing clips in this pack')
        a,b=(lookup[n] for n in pair); row={'from':pair[0],'to':pair[1], 'scope':'unblended end-to-start; runtime blend is not modeled'}
        for kind in ('bones','actors'): row[kind]=endpoint(a['frames'][-1][kind],b['frames'][0][kind])
        row['visibility_mismatch_count']=sum(x!=y for x,y in zip(a['frames'][-1]['visible'],b['frames'][0]['visible']))
        result['transitions'].append(row)
    return pack,result

def plot_motion(pack, clip_name, kind, index, output):
    import matplotlib.pyplot as plt
    c=next(c for c in pack['clips'] if c['name']==clip_name)
    x=channels(c,kind); t=np.array([f['time'] for f in c['frames']])
    if kind not in ('bones','actors') or not 0<=index<x.shape[1]: raise ValueError('Invalid channel')
    fig,axes=plt.subplots(3,1,figsize=(11,8),sharex=True)
    for k,label in enumerate('XYZ'): axes[0].plot(t,x[:,index,k],label=label)
    axes[0].set_ylabel('Translation (export units)'); axes[0].legend()
    if len(t)>1:
        axes[1].plot((t[1:]+t[:-1])/2,np.linalg.norm(np.diff(x[:,index,:3],axis=0),axis=1)/np.diff(t))
        axes[2].plot((t[1:]+t[:-1])/2,angle(x[:-1,index,3:7],x[1:,index,3:7])/np.diff(t))
    axes[1].set_ylabel('Translation units / s'); axes[2].set_ylabel('Rotation deg / s'); axes[2].set_xlabel('Clip seconds')
    space='parent-local' if kind=='bones' else 'scene-global'
    fig.suptitle(f'{clip_name} / {kind}[{index}] / {space} / diagnostic')
    fig.tight_layout(); fig.savefig(output,dpi=130); plt.close(fig)

def contact_report(doc, use_cuda=False):
    """Explicit corresponding evaluated points only, not nearest mesh or inferred anatomy."""
    if doc.get('schema')!='rust-duty-contact-samples/v1' or doc.get('units')!='metres':
        raise ValueError('Expected contact schema with metres')
    if not doc.get('source_sha256') or len(doc['source_sha256'])!=64 or any(c not in '0123456789abcdef' for c in doc['source_sha256']):
        raise ValueError('Require source artifact SHA256')
    if doc.get('space')!='evaluated-world' or not isinstance(doc.get('pairs'),list) or not 1<=len(doc['pairs'])<=64:
        raise ValueError('Require evaluated-world points and 1..64 named pairs')
    report={'status':'diagnostic','source_sha256':doc['source_sha256'],'source_hash_verified':False,
        'backend':'numpy-float64','pairs':[], 'limitation':'Point separation only. No surface penetration, finger orientation, anatomical or artistic approval.'}
    for p in doc['pairs']:
        if not isinstance(p.get('name'),str) or not p['name']: raise ValueError('Pair needs name')
        t=np.asarray(p['time_seconds'],dtype=np.float64); a=np.asarray(p['a'],dtype=np.float64); b=np.asarray(p['b'],dtype=np.float64)
        mask=np.asarray(p['observed'])
        if (t.ndim!=1 or not 1<=len(t)<=200000 or a.shape!=(len(t),3) or b.shape!=a.shape
            or mask.shape!=t.shape or mask.dtype!=np.bool_ or not np.isfinite(t).all()
            or not np.isfinite(a).all() or not np.isfinite(b).all() or np.any(np.abs(a)>10000) or np.any(np.abs(b)>10000) or np.any(np.diff(t)<=0)):
            raise ValueError('Invalid point samples/time/observability')
        cpu=np.linalg.norm(a-b,axis=1); distances=cpu
        if use_cuda:
            import torch
            if not torch.cuda.is_available(): raise RuntimeError('CUDA requested but unavailable; choose CPU explicitly')
            with torch.no_grad():
                distances=torch.linalg.vector_norm(torch.as_tensor(a,device='cuda',dtype=torch.float64)-torch.as_tensor(b,device='cuda',dtype=torch.float64),dim=1).cpu().numpy()
            if not np.allclose(distances,cpu,rtol=1e-9,atol=1e-10): raise ValueError('CPU/CUDA disagreement')
            report['backend']='torch-cuda-float64; CPU equivalence checked (rtol=1e-9, atol=1e-10)'
        observed=distances[mask]
        report['pairs'].append({'name':p['name'],'samples':len(t),'observed_samples':int(mask.sum()),
            'coverage':float(mask.mean()),'max_observed_separation_m':float(observed.max()) if len(observed) else None,
            'rms_observed_separation_m':float(np.sqrt(np.mean(observed**2))) if len(observed) else None})
    return report

def compare_images(a_bytes,b_bytes,output,source_label,candidate_label):
    from PIL import Image, ImageDraw
    images=[]
    for blob in (a_bytes,b_bytes):
        if len(blob)>32*1024*1024: raise ValueError('Image too large')
        im=Image.open(io.BytesIO(blob))
        if im.width*im.height>16_000_000: raise ValueError('Image dimensions too large')
        im.load(); im=im.convert('RGB'); im.thumbnail((1200,900)); images.append(im)
    # Separate panels, no registration, stretch, crop, or automatic visual score.
    canvas=Image.new('RGB',(sum(i.width for i in images),max(i.height for i in images)+60),'white')
    d=ImageDraw.Draw(canvas); x=0
    for im,label in zip(images,(source_label,candidate_label)):
        canvas.paste(im,(x,60)); d.text((x+8,8),label,fill='black'); x+=im.width
    canvas.save(output)

def verify_preserved_archive(archive, output, downloaded, expected_hash, expected_outputs):
    """Validate a browser-returned saved copy and reject stale/changed output before teardown."""
    archive=Path(archive); output=Path(output)
    if not isinstance(downloaded,bytes) or digest(downloaded)!=expected_hash:
        raise ValueError('Downloaded copy SHA256 mismatch; runtime retained')
    current={p.name:digest(p.read_bytes()) for p in output.iterdir() if p.is_file()}
    if any(p.is_dir() for p in output.iterdir()) or current!=expected_outputs:
        raise ValueError('Outputs changed after export; export and preserve a new ZIP first')
    if digest(archive.read_bytes())!=expected_hash:
        raise ValueError('Local ZIP changed after export; runtime retained')
    with zipfile.ZipFile(io.BytesIO(downloaded)) as z:
        if z.testzip() is not None or set(z.namelist())!=set(expected_outputs):
            raise ValueError('Invalid result ZIP; runtime retained')
        if any(digest(z.read(n))!=sha for n,sha in expected_outputs.items()):
            raise ValueError('Result contents differ; runtime retained')
    return {'sha256':expected_hash,'bytes':len(downloaded),'preservation':'downloaded copy re-uploaded and byte-verified'}

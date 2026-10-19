"""New Windows evidence layer around unchanged strict high-ONTO numerical gates."""
from pathlib import Path
import math,re
from continuation_core import ACTION,need,read,sha,record
WARP='Microsoft Basic Render Driver'
KNOWN_BASE_WARNING='Authored WIP: empty reload, fire, mantle clips unavailable; reload pose crossfades'

def renderer_evidence(logs,metadata):
    lines=[]
    for text in logs:lines+=text.splitlines()
    identities=[x for x in lines if x.startswith('renderer requested=')]
    need(identities and all(x==f'renderer requested=dx12 backend=Dx12 adapter={WARP}' for x in identities),'actual DX12 WARP renderer identity required')
    compiler=[x for x in lines if x.startswith('renderer dx12_shader_compiler=')]
    need(compiler and all(x=='renderer dx12_shader_compiler=Fxc' for x in compiler),'actual FXC identity required')
    # No warning whitelist is inferred from a successful exit; all warnings fail.
    need(not any(re.search(r'\b(warn(?:ing)?|error|panic|failed|fallback to)\b',x,re.I) for x in lines),'unreviewed warning/error in actual game log')
    need(metadata,'actual frame metadata required')
    for m in metadata:
        need(m.get('capture')=='native window','offscreen substitute forbidden')
        need(m.get('requested')=='dx12' and m.get('backend')=='Dx12' and m.get('adapter')==WARP,'frame backend differs from required DX12 WARP')
        need(type(m.get('width')) is int and type(m.get('height')) is int and 0<m['width']<=1440 and 0<m['height']<=900,'frame extent invalid')
    return {'requested':'dx12','backend':'Dx12','adapter':WARP,'shader_compiler':'Fxc'}

def candidate_visual_rows(rows,binding):
    observed=0;active=0
    for row in rows:
        if 'renderer_failed' not in row:continue
        need(row['renderer_failed'] is False and 'warning' in row and row['warning'] in (None,KNOWN_BASE_WARNING),'main viewmodel unknown warning/failure')
        value=row.get('candidate_visual');need(type(value) is dict,'actual candidate renderer observation missing')
        need(value.get('clip')==ACTION,'actual bound clip differs')
        need(value.get('asset_sha256')==binding['asset_sha256'] and value.get('receipt_sha256')==binding['receipt_sha256'],'actual renderer binding differs')
        need(value.get('warning') is None and value.get('renderer_failed') is False,'candidate renderer warning/failure')
        observed+=1
        high=row.get('high')
        if row.get('kind')=='frame' and high is not None:
            pose=value.get('pose');need(type(pose) is dict,'actual rendered source pose missing')
            expected=high['seconds'];actual=pose.get('source_pose_seconds')
            need(type(actual) in (int,float) and math.isfinite(actual) and abs(actual-expected)<=2e-5,'actual bound clip sample differs from committed native clock')
            active+=1
    need(observed>0 and active>0,'no actual candidate gameplay samples')
    return {'actual_renderer_rows':observed,'actual_sampled_frames':active,'actual_bound_clip':ACTION}

def verify(folder,binding,hz,identity,logs,original):
    folder=Path(folder)
    # This original function still enforces every 324-tick, 30/60-Hz, endpoint,
    # frame witness, return-weight and live ADS/walk requirement unchanged.
    base=original.verify(folder,binding,hz,identity)
    rows=original.v.read_trace(folder/'observer.jsonl')
    visual=candidate_visual_rows(rows,binding)
    metadata=[read(folder/(r['png']+'.json')) for r in rows if 'png' in r]
    backend=renderer_evidence([Path(p).read_text(encoding='utf-8',errors='strict') for p in logs],metadata)
    return {'schema':'rust-duty-onehand-windows-dx12-capture/v1','passed':True,'sampling_hz':hz,
        'frame_witness':identity,'binding':binding,'renderer':backend,'original_verification':base,
        'candidate_visual':visual,'logs':[record(p) for p in logs],
        'platform_hotkeys_verified':False,'real_time_performance_verified':False,'artistic_approval':False}

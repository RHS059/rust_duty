"""Replace existing runtime names and update their ordinary file hash bindings."""
import re,shutil
from pathlib import Path
from common import *
ACTION='aella_mantle_onehand_r6_camera_reconstructed_v6'
APPROVED='b5cae854b1e5e21c44e60a0672dd18c26e7b38acb239f4730b681482bc409d77'
FINGERPRINT='c7ca6383364e055afe1d0246f443d33689ce86c56677570ba694a924c983ea01'

def replace_file(source,target):
    source=ordinary(source,True);target=ordinary(target);expected=sha(source);target.parent.mkdir(parents=True,exist_ok=True)
    if source!=target:shutil.copyfile(source,target)
    pin(target,expected)

def bind_manifest(text,bindings):
    # Replace each established key in place, preserving unrelated lines and comments.
    lines=[];remaining=dict(bindings)
    for line in text.splitlines():
        key=line.split('=',1)[0].strip() if '=' in line else None
        if key in bindings:
            if key in remaining:lines.append(key+'='+remaining.pop(key))
        else:lines.append(line)
    lines.extend(k+'='+v for k,v in remaining.items())
    return '\n'.join(lines)+'\n'

def install(root,runtime,source,fbx):
    root=ordinary(root,True);folder=root/'assets/onehand';folder.mkdir(parents=True,exist_ok=True)
    for ext in ('vra','vrs','vrm'):replace_file(Path(runtime)/('asset.'+ext),folder/('asset.'+ext))
    value={'schema':'rust-duty-high-onto-onehand/v1','presentation_policy':'high_onto_onehand_v6_native',
        'clip_name':ACTION,'source_action':ACTION,'export_take':ACTION,'candidate_sha256':APPROVED,
        'approved_source_sha256':APPROVED,'generated_source_sha256':sha(source),'source_action_fingerprint':FINGERPRINT,
        'source_fbx_sha256':sha(fbx),**{'asset_'+e+'_sha256':sha(folder/('asset.'+e)) for e in ('vra','vrs','vrm')},
        'native_processes_complete':True,'candidate_frame_range':[1,96],'reference_frame_range_half_open':[7787,7883],
        'native_fps':[60,1],'native_crop':[0,95],'imported_frame_offset':1,'subdivisions':256,
        'camera_and_rig_basis':'static','camera_motion_removal':'none','actor_basis':'reload_mesh_local',
        'anchor_actor':'hk416_weapon','return_seconds':0.2}
    receipt=folder/'runtime-receipt.json';receipt.write_bytes(canonical(value));receipt_sha=sha(receipt)
    source_file=root/'src/authored_high_mantle.rs';text=source_file.read_text()
    pattern=r"const APPROVED_RUNTIME_PINS: Option<RuntimePins<'static>> = (?:None|Some\(RuntimePins \{.*?\}\));"
    pins={'receipt':receipt_sha,'fbx':sha(fbx),**{e:sha(folder/('asset.'+e)) for e in ('vra','vrs','vrm')}}
    declaration="const APPROVED_RUNTIME_PINS: Option<RuntimePins<'static>> = Some(RuntimePins {\n"+''.join('    '+k+': "'+v+'",\n' for k,v in pins.items())+'});'
    text,count=re.subn(pattern,lambda _:declaration,text,flags=re.S);need(count==1,'runtime pin declaration missing/ambiguous')
    source_file.write_text(text,encoding='utf-8',newline='\n')
    manifest=root/'assets/animations.cfg'
    manifest.write_text(bind_manifest(manifest.read_text(),{'high_mantle.policy':'high_onto_onehand_v6_native','high_mantle.asset':'onehand/asset.vra','high_mantle.clip':ACTION,'high_mantle.receipt':'onehand/runtime-receipt.json','high_mantle.receipt_sha256':receipt_sha}),encoding='utf-8',newline='\n')
    return record(receipt)

def bind_existing(root):
    """Use the published portable pack as-is; historical receipt fields stay intact."""
    root=ordinary(root,True);folder=root/'assets/onehand';receipt=folder/'runtime-receipt.json'
    value=read(receipt);pins={'receipt':sha(receipt),'fbx':value['source_fbx_sha256'],**{e:sha(folder/('asset.'+e)) for e in ('vra','vrs','vrm')}}
    for e in ('vra','vrs','vrm'):need(value['asset_'+e+'_sha256']==pins[e],'existing onehand asset identity differs')
    need(re.fullmatch('[0-9a-f]{64}',pins['fbx']),'existing FBX digest missing')
    source=root/'src/authored_high_mantle.rs';text=source.read_text();source_before=sha(source)
    manifest=root/'assets/animations.cfg';manifest_before=sha(manifest)
    pattern=r"const APPROVED_RUNTIME_PINS: Option<RuntimePins<'static>> = (?:None|Some\(RuntimePins \{.*?\}\));"
    replacement="const APPROVED_RUNTIME_PINS: Option<RuntimePins<'static>> = Some(RuntimePins {\n"+''.join('    '+k+': "'+v+'",\n' for k,v in pins.items())+'});'
    text,count=re.subn(pattern,lambda _:replacement,text,flags=re.S);need(count==1,'runtime pin declaration missing/ambiguous')
    source.write_text(text,encoding='utf-8',newline='\n')
    manifest=root/'assets/animations.cfg'
    manifest.write_text(bind_manifest(manifest.read_text(),{'high_mantle.policy':'high_onto_onehand_v6_native','high_mantle.asset':'onehand/asset.vra','high_mantle.clip':ACTION,'high_mantle.receipt':'onehand/runtime-receipt.json','high_mantle.receipt_sha256':pins['receipt']}),encoding='utf-8',newline='\n')
    changes=[]
    for path,before in ((source,source_before),(manifest,manifest_before)):
        after=sha(path)
        if before!=after:changes.append({'path':path.relative_to(root).as_posix(),'before_sha256':before,'after_sha256':after})
    return {'receipt':record(receipt),'changed_source_files':changes}

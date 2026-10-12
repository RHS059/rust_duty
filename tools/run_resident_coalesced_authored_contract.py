#!/usr/bin/env python3
"""Strictly validate the separate actual-loader resident batching contract.

Compilation and native execution are owned by the source-bound controller. This
reader never launches a GPU, changes the historical CPU/resident gate, or relaxes
pixel equality. Example CLI: --manifest PATH --output-dir FRESH_DIRECTORY.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
from PIL import Image
import run_authored_loader_pair as original

SCHEMA = 'rust-duty-resident-coalesced-authored-contract/v1'
EXAMPLE = 'resident_coalesced_authored_contract'
MAX_REPORT_BYTES = 64 * 1024 * 1024
MAX_STREAM_BYTES = 600 * 1024 * 1024
CASE_NAMES = original.CASE_NAMES
EXTENT = original.EXTENT
require = original.require
uint = original.integer

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()

def read_report(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_REPORT_BYTES,
            'unsafe/unbounded coalesced report')
    return json.loads(path.read_bytes())

def checked_bytes(path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_STREAM_BYTES,
            'unsafe/unbounded ordered stream')
    return path.read_bytes()

def words(value, count):
    return isinstance(value, list) and len(value) == count and all(uint(x, 0, 2**32-1) for x in value) and all(math.isfinite(struct.unpack('<f', struct.pack('<I', x))[0]) for x in value)

def texture(value):
    require(value is None or isinstance(value, dict) and set(value) == {'width','height','filter','wrap_x','wrap_y','rgba_sha256'} and uint(value['width'],1,16384) and uint(value['height'],1,16384) and value['filter']=='Linear' and value['wrap_x']==value['wrap_y']=='Repeat' and original.digest_string(value['rgba_sha256']), 'material texture state differs')

def source_stride(layout):
    require(isinstance(layout,dict) and layout.get('kind') in ('rigid','skin'), 'invalid immutable source kind')
    if layout['kind']=='rigid':
        require(set(layout)=={'kind'},'rigid layout fields differ')
        return 32
    require(set(layout)=={'kind','bones'} and uint(layout['bones'],1,128),'skin palette layout differs')
    return 80

def source_corner(raw, layout):
    require(len(raw)==source_stride(layout) and all(math.isfinite(x) for x in struct.unpack_from('<8f',raw)), 'nonfinite or truncated source corner')
    if layout['kind']=='skin':
        require(all(j<layout['bones'] for j in struct.unpack_from('<8H',raw,32)), 'source joint outside palette')
        weights=struct.unpack_from('<8f',raw,48)
        require(all(math.isfinite(x) and 0<=x<=1 for x in weights) and .9999<=sum(weights)<=1.0001,'invalid ordered source weights')

def validate_layout(groups, raw, legacy):
    require(isinstance(groups,list) and 0<len(groups)<=8192,'empty/unbounded source layout')
    cursors={};offset=0;corners=0;parts={}
    for group in groups:
        require(isinstance(group,dict) and set(group)=={'model_key','kind','source_chunks','sources','source_parts','part','layout','texture','vertices','indices'},'source group fields differ')
        key=(group['model_key'],group['kind']);require(isinstance(key[0],str) and 0<len(key[0])<=256 and key[1] in ('rigid','skin'),'source model/kind invalid')
        require(uint(group['source_chunks'],1,8192) and isinstance(group['sources'],list) and len(group['sources'])==2 and all(uint(x,0,8192) for x in group['sources']),'source chunk range invalid')
        start,end=group['sources'];previous,total=cursors.get(key,(0,group['source_chunks']))
        require(start==previous and start<end<=total==group['source_chunks'],'source ranges skip/overlap/reorder')
        ids=group['source_parts'];require(isinstance(ids,list) and len(ids)==end-start and all(uint(x,0,4095) and x==ids[0] for x in ids),'source group crosses original part')
        require(not legacy or end-start==1,'legacy chunk boundaries changed');cursors[key]=(end,total)
        require(group['part']==f'{key[0]}/{key[1]}/{ids[0]}' and group['layout']['kind']==key[1],'source part label differs')
        require(uint(group['vertices'],1,65536) and uint(group['indices'],3,4998 if legacy else 65535) and group['indices']%3==0 and group['vertices']<=group['indices'],'source geometry bounds differ')
        texture(group['texture']);stride=source_stride(group['layout']);tag=digest(encoded({k:group[k] for k in ('part','layout','texture')})).encode()
        for _ in range(group['indices']//3):
            require(raw[offset:offset+64]==tag,'ordered source part/material tag differs');offset+=64
            for _ in range(3):source_corner(raw[offset:offset+stride],group['layout']);offset+=stride
        corners+=group['indices'];require(corners<=4_000_000,'source corner bound exceeded')
        part=parts.setdefault((key[0],key[1],ids[0]),{'indices':0,'vertices':0,'chunks':0})
        part['indices']+=group['indices'];part['vertices']+=group['vertices'];part['chunks']+=end-start
    require(all(end==total for end,total in cursors.values()) and offset==len(raw),'trailing source chunks/bytes omitted')
    return parts

def validate_ordered(commands, raw, legacy):
    require(isinstance(commands,list) and 0<len(commands)<=2048,'empty/unbounded resident commands')
    offset=0;counts=[0,0,0];corners=0
    for command in commands:
        require(isinstance(command,dict) and set(command)=={'state','vertices','indices'},'ordered command fields differ')
        state=command['state'];require(isinstance(state,dict) and set(state)=={'part','layout','model','root','normal','blend','texture','light_direction','ambient','diffuse','albedo','alpha','palette'},'draw state fields differ')
        require(isinstance(state['part'],str) and 0<len(state['part'])<=300 and state['blend']=='Alpha','part/blend differs')
        require(all(words(state[k],16) for k in ('model','root','normal')) and words(state['light_direction'],3) and words(state['albedo'],4) and all(words([state[k]],1) for k in ('ambient','diffuse','alpha')),'draw state words invalid')
        texture(state['texture']);stride=source_stride(state['layout']);kind=state['layout']['kind'];counts[1 if kind=='rigid' else 2]+=1
        palette=state['palette']
        if kind=='rigid':require(palette is None,'rigid draw has palette')
        else:require(isinstance(palette,dict) and set(palette)=={'positions','normals'} and all(isinstance(palette[k],list) and len(palette[k])==state['layout']['bones'] and all(words(m,16) for m in palette[k]) for k in palette),'skin pose palette differs')
        require(uint(command['vertices'],1,65536) and uint(command['indices'],3,4998 if legacy else 65535) and command['indices']%3==0 and command['vertices']<=command['indices'],'ordered geometry bounds differ')
        tag=digest(encoded(state)).encode()
        for _ in range(command['indices']//3):
            require(raw[offset:offset+64]==tag,'ordered material/part/pose state tag differs');offset+=64
            for _ in range(3):
                source_corner(raw[offset:offset+stride],state['layout']);offset+=stride
                corner=raw[offset:offset+40];require(len(corner)==40 and all(math.isfinite(x) for x in struct.unpack_from('<5f',corner)) and corner[24:]==bytes(16),'invalid CPU-reference corner');offset+=40
        corners+=command['indices'];require(corners<=4_000_000,'ordered corner bound exceeded')
    require(offset==len(raw),'ordered byte extent differs')
    return counts

def validate_metadata(report, receipt):
    # Preserve the original strict metadata/source-count rules separately; the
    # historical command-array/4998-index validator is not invoked or altered.
    require(original.digest_string(receipt) and report.get('source_receipt_sha256')==receipt,'compiled source receipt differs')
    camera=report.get('camera',{});require(camera.get('extent')==EXTENT and words(camera.get('view_projection_bits'),16),'camera words/extent differ')
    cases=report.get('cases');require(isinstance(cases,list) and all(isinstance(c,dict) for c in cases) and [c.get('name') for c in cases]==CASE_NAMES,'22-case inventory differs')
    for c in cases:
        name,m=c['name'],c.get('metadata');require(isinstance(m,dict),'metadata missing')
        if name.startswith('manifest-'):
            steps=int(name.split('-')[-1]);require(m.get('route')=='load_manifest/committed_step/draw' and m.get('fixed_steps')==steps and uint(m.get('simulation_time_bits'),0,2**64-1),'manifest route differs')
            dt=struct.unpack('<f',struct.pack('<f',1/120))[0];require(struct.unpack('<d',struct.pack('<Q',m['simulation_time_bits']))[0]==sum(dt for _ in range(steps)),'committed time differs')
            require(isinstance(m.get('warning'),str) and m['warning'].startswith('Authored WIP: ') and len(m['warning'].encode())<=512,'WIP notice differs')
        elif name.startswith('rigid-alpha-'):require(m=={'route':'draw_authored_parts','alpha':[.5,.25,.5][int(name[-1])]},'alpha route differs')
        else:
            require(m.get('route')=='load/draw' and isinstance(m.get('clip'),str) and m['clip'] and m.get('cant_bits')==0 and m.get('fraction_tenths')==[0,5,9,0][int(name[-1])] and uint(m.get('duration_bits'),1,2**32-1) and uint(m.get('time_bits'),0,2**32-1),'clip route differs')
            duration=original.float_word(m['duration_bits']);fraction=struct.unpack('<f',struct.pack('<f',m['fraction_tenths']/10))[0]
            require(math.isfinite(duration) and duration>0 and original.float_word(m['time_bits'])==struct.unpack('<f',struct.pack('<f',duration*fraction))[0],'clip sample time differs')
    require(len({c['metadata']['warning'] for c in cases[16:19]})==1,'manifest warning changed')
    for start in (0,4,8,12):require(len({c['metadata']['clip'] for c in cases[start:start+4]})==len({c['metadata']['duration_bits'] for c in cases[start:start+4]})==1,'clip instance changed')
    counts=report.get('source_counts');require(isinstance(counts,dict) and set(counts)=={'ready','walk','ads','reload'},'decoded source inventory differs')
    for group in counts.values():
        require(isinstance(group,dict) and set(group)=={'skin','rigid'},'decoded classes differ')
        for meshes in group.values():
            require(isinstance(meshes,list) and 0<len(meshes)<=4096,'decoded source parts invalid')
            for row in meshes:require(isinstance(row,dict) and set(row)=={'old_vertices','deduplicated_vertices','indices'} and all(uint(n,1,4_000_000) for n in row.values()) and row['indices']%3==0 and row['deduplicated_vertices']<=row['old_vertices']<=row['indices'],'decoded source counts differ')

def validate_outputs(directory, report, receipt_sha256):
    directory=Path(directory);require(directory.is_dir() and not directory.is_symlink(),'unsafe capture directory')
    require(report.get('schema')==SCHEMA and report.get('passed') is True and report.get('draw_reduction_observed') is True,'coalesced producer did not pass')
    validate_metadata(report,receipt_sha256);require(read_report(directory/'report.json')==report and read_report(directory/'camera.json')==report['camera'],'retained report/camera changed')
    expected={'report.json','camera.json'};reduction=False
    for case in report['cases']:
        require(case.get('ordered_source_state_and_corners_equal') is True,'source/state/corner comparison failed')
        pixels=[];streams=[];layouts=[];paths=[]
        for label in ('legacy','coalesced'):
            hashes=[case.get(label+'_'+kind+'_sha256') for kind in ('ordered','layout')];require(all(original.digest_string(h) for h in hashes),'invalid stream hash')
            names=[f'{kind}-{h}.bin' for kind,h in zip(('ordered','layout'),hashes)];expected.update(names)
            ordered,layout=[checked_bytes(directory/n) for n in names];require([digest(x) for x in (ordered,layout)]==hashes,'retained stream hash differs')
            groups=case.get(label+'_layout_groups');parts=validate_layout(groups,layout,label=='legacy');path=validate_ordered(case.get(label+'_commands'),ordered,label=='legacy')
            require(path==case.get(label+'_paths') and path[1]>0 and (path[2]==0 if case['name'].startswith('rigid-alpha-') else path[2]>0),'actual resident paths missing')
            group_labels={g['part'] for g in groups};require(all(c['state']['part'] in group_labels for c in case[label+'_commands']),'draw part absent from all-loaded source layout')
            clip=case['name'].split('-')[0]
            if clip in report['source_counts']:
                for kind,meshes in report['source_counts'][clip].items():
                    require({part for model,k,part in parts if model==clip and k==kind}==set(range(len(meshes))),'decoded original part inventory changed')
                    for i,source in enumerate(meshes):require(parts[(clip,kind,i)]=={'indices':source['indices'],'vertices':source['deduplicated_vertices'],'chunks':(source['indices']+4997)//4998},'source decoded triangles/vertices/chunks differ')
            stats=case.get(label+'_stats');require(isinstance(stats,dict) and all(uint(x,0,2**64-1) for x in stats.values()) and stats.get('draws')==sum(path) and stats.get('rigid_draws')==path[1] and stats.get('skinned_draws')==path[2] and stats.get('transient_meshes')==0,'native resident execution differs')
            image_name=f'{case["name"]}-{label}.png';expected.add(image_name)
            with Image.open(directory/image_name) as image:require(image.mode=='RGBA' and list(image.size)==EXTENT,'native image format differs');pixel=image.tobytes()
            require(all(pixel[i]==255 for i in range(3,len(pixel),4)),'nonopaque final image')
            foreground=sum(any(abs(pixel[i+j]-v)>4 for j,v in enumerate((8,16,24))) for i in range(0,len(pixel),4))
            require(foreground==case.get('foreground_pixels') and foreground>100,'foreground coverage differs')
            pixels.append(pixel);streams.append(ordered);layouts.append(layout);paths.append(path)
        require(streams[0]==streams[1] and layouts[0]==layouts[1] and pixels[0]==pixels[1] and case.get('differing_pixels')==case.get('maximum_channel_delta')==0,'strict ordered-stream or full RGBA equality failed')
        require(all(a<=b for a,b in zip(paths[1],paths[0])),'coalescing increased draw count');reduction|=sum(paths[1])<sum(paths[0])
    require(reduction,'no actual draw reduction')
    for a,b in ((0,3),(4,7),(8,11),(12,15),(19,21)):
        for label in ('legacy','coalesced'):require(report['cases'][a][label+'_ordered_sha256']==report['cases'][b][label+'_ordered_sha256'],'same-instance revisit changed')
    require({p.name for p in directory.iterdir()}==expected and all(p.is_file() and not p.is_symlink() for p in directory.iterdir()),'capture inventory differs')
    require(report.get('backend') in ({'requested':'vulkan','backend':'Vulkan','adapter':'NVIDIA A100-SXM4-40GB'},{'requested':'dx12','backend':'Dx12','adapter':'Microsoft Basic Render Driver'}),'unexpected native backend')
    return {'passed':True,'exact_pairs':22,'ordered_source_part_material_pose_and_corners':True,'strict_full_rgba_equality':True,'actual_resident_draw_reduction':True,'unique_ordered_stream_bytes':sum((directory/n).stat().st_size for n in expected if n.startswith('ordered-')),'unique_layout_stream_bytes':sum((directory/n).stat().st_size for n in expected if n.startswith('layout-')),'scope':'Separate legacy-resident/coalesced-resident correctness gate; historical CPU/resident gate unchanged; no performance acceptance.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--captures',type=Path,required=True);parser.add_argument('--source-receipt-sha256',required=True);a=parser.parse_args()
    try:print(json.dumps(validate_outputs(a.captures,read_report(a.captures/'report.json'),a.source_receipt_sha256),indent=2));return 0
    except (ValueError,RuntimeError,OSError,KeyError,TypeError,struct.error) as error:print(str(error),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())

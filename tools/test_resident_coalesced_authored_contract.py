import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest
from PIL import Image
import run_resident_coalesced_authored_contract as gate

RECEIPT = 'a' * 64
IDENTITY = [0x3f800000 if i % 5 == 0 else 0 for i in range(16)]
def word(value): return struct.unpack('<I', struct.pack('<f', value))[0]
def source_vertex(x, kind):
    raw = struct.pack('<8f', x, 0, 0, 0, 1, 0, 0, 0)
    return raw if kind == 'rigid' else raw + struct.pack('<8H8f', *([0]*8), 1, *([0]*7))
def output_vertex(x, alpha): return struct.pack('<5f4B4f', x, 0, 0, 0, 0, 255, 255, 255, round(alpha*255), 0, 0, 0, 0)
def state(part, kind, alpha):
    return dict(part=part, layout={'kind':kind, **({'bones':1} if kind=='skin' else {})}, model=IDENTITY, root=IDENTITY, normal=IDENTITY,
        blend='Alpha', texture=None, light_direction=[0,word(1),0], ambient=word(.5), diffuse=word(.5), albedo=[word(1)]*4, alpha=word(alpha),
        palette={'positions':[IDENTITY], 'normals':[IDENTITY]} if kind=='skin' else None)
def blocks(model, kind, legacy, alpha=1):
    part=f'{model}/{kind}/0'; s=state(part,kind,alpha)
    counts=[3] if kind=='skin' else ([4998,3] if legacy else [5001])
    groups=[]; commands=[]; source=b''; ordered=b''; cursor=0
    for count in counts:
        span=1 if legacy or kind=='skin' else 2
        group=dict(model_key=model,kind=kind,source_chunks=1 if kind=='skin' else 2,sources=[cursor,cursor+span],source_parts=[0]*span,part=part,layout=s['layout'],texture=None,vertices=2*span,indices=count)
        groups.append(group);commands.append(dict(state=copy.deepcopy(s),vertices=2*span,indices=count));cursor+=span
        tag=gate.digest(gate.encoded({k:group[k] for k in ('part','layout','texture')})).encode()
        source+=(tag+b''.join(source_vertex(x,kind) for x in (0,1,0)))*(count//3)
        ordered+=(gate.digest(gate.encoded(s)).encode()+b''.join(source_vertex(x,kind)+output_vertex(x,alpha) for x in (0,1,0)))*(count//3)
    return groups, commands, source, ordered

def fixture(root):
    report=dict(schema=gate.SCHEMA,source_receipt_sha256=RECEIPT,passed=True,draw_reduction_observed=True,
        camera={'extent':gate.EXTENT,'view_projection_bits':IDENTITY,'derivation':'test'},
        source_counts={clip:{'skin':[dict(old_vertices=3,deduplicated_vertices=2,indices=3)],'rigid':[dict(old_vertices=6,deduplicated_vertices=4,indices=5001)]} for clip in ('ready','walk','ads','reload')},
        backend={'requested':'vulkan','backend':'Vulkan','adapter':'NVIDIA A100-SXM4-40GB'},cases=[])
    picture=Image.new('RGBA',tuple(gate.EXTENT),(8,16,24,255))
    for y in range(16):
        for x in range(16): picture.putpixel((x,y),(60+x%8,80,100,255))
    for name in gate.CASE_NAMES:
        alpha=1
        if name.startswith('manifest-'):
            steps=int(name.split('-')[-1]);dt=struct.unpack('<f',struct.pack('<f',1/120))[0]
            metadata=dict(route='load_manifest/committed_step/draw',fixed_steps=steps,simulation_time_bits=struct.unpack('<Q',struct.pack('<d',sum(dt for _ in range(steps))))[0],warning='Authored WIP: synthetic validator fixture');model='manifest'
        elif name.startswith('rigid-alpha-'):
            alpha=[.5,.25,.5][int(name[-1])];metadata=dict(route='draw_authored_parts',alpha=alpha);model='rigid-alpha'
        else:
            model=name.split('-')[0];fraction=[0,5,9,0][int(name[-1])]
            metadata=dict(route='load/draw',clip=model,cant_bits=0,fraction_tenths=fraction,duration_bits=word(1),time_bits=word(fraction/10))
        case=dict(name=name,metadata=metadata,ordered_source_state_and_corners_equal=True,differing_pixels=0,maximum_channel_delta=0,foreground_pixels=256)
        for label in ('legacy','coalesced'):
            rows=[];commands=[];source=b'';ordered=b''
            for kind in (('rigid',) if name.startswith('rigid-alpha-') else ('skin','rigid')):
                g,c,s,o=blocks(model,kind,label=='legacy',alpha);rows+=g;commands+=c;source+=s;ordered+=o
            paths=[0,sum(c['state']['layout']['kind']=='rigid' for c in commands),sum(c['state']['layout']['kind']=='skin' for c in commands)]
            case[label+'_commands']=commands;case[label+'_layout_groups']=rows;case[label+'_paths']=paths
            case[label+'_stats']=dict(draws=sum(paths),rigid_draws=paths[1],skinned_draws=paths[2],transient_meshes=0)
            for kind,raw in (('layout',source),('ordered',ordered)):
                digest=gate.digest(raw);case[label+'_'+kind+'_sha256']=digest;(root/f'{kind}-{digest}.bin').write_bytes(raw)
            picture.save(root/f'{name}-{label}.png')
        report['cases'].append(case)
    (root/'camera.json').write_text(json.dumps(report['camera']));(root/'report.json').write_text(json.dumps(report))
    return report

class ContractValidatorTests(unittest.TestCase):
    def test_full_22_pairs_and_hash_dedup(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);report=fixture(root);result=gate.validate_outputs(root,report,RECEIPT)
            self.assertEqual(result['exact_pairs'],22);self.assertTrue(result['strict_full_rgba_equality'])
            self.assertGreater(result['unique_ordered_stream_bytes'],0);self.assertGreater(result['unique_layout_stream_bytes'],0)
            self.assertLess(len(list(root.glob('ordered-*.bin'))),44)
    def test_original_parts_ranges_and_legacy_boundaries(self):
        groups,_,raw,_=blocks('ready','rigid',False)
        for field,value in [('source_parts',[0,1]),('sources',[1,2])]:
            bad=copy.deepcopy(groups);bad[0][field]=value
            with self.assertRaises(ValueError):gate.validate_layout(bad,raw,False)
        with self.assertRaises(ValueError):gate.validate_layout(groups,raw,True)
    def test_order_state_weight_extent_and_bounds(self):
        _,commands,_,raw=blocks('ready','skin',True)
        bad=copy.deepcopy(commands);bad[0]['state']['alpha']=word(.5)
        with self.assertRaises(ValueError):gate.validate_ordered(bad,raw,True)
        corrupt=bytearray(raw);struct.pack_into('<f',corrupt,64+48,float('nan'))
        with self.assertRaises(ValueError):gate.validate_ordered(commands,corrupt,True)
        with self.assertRaises(ValueError):gate.validate_ordered(commands,raw+b'x',True)
        bad=copy.deepcopy(commands);bad[0]['indices']=65538
        with self.assertRaises(ValueError):gate.validate_ordered(bad,raw,False)
    def test_hidden_loaded_texture_part_tag(self):
        groups,_,raw,_=blocks('ready','rigid',False)
        groups[0]['texture']=dict(width=1,height=1,filter='Linear',wrap_x='Repeat',wrap_y='Repeat',rgba_sha256='b'*64)
        with self.assertRaises(ValueError):gate.validate_layout(groups,raw,False)
    def test_exact_pixels_and_extra_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);report=fixture(root);path=root/'ready-0-coalesced.png'
            with Image.open(path) as image:
                image.putpixel((0,0),(61,80,100,255));image.save(path)
            with self.assertRaises(ValueError):gate.validate_outputs(root,report,RECEIPT)
            with Image.open(root/'ready-0-legacy.png') as image:image.save(path)
            (root/'extra.txt').write_text('unexpected')
            with self.assertRaises(ValueError):gate.validate_outputs(root,report,RECEIPT)
    def test_source_pin_and_failed_producer(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);report=fixture(root)
            with self.assertRaises(ValueError):gate.validate_outputs(root,report,'b'*64)
            report['passed']=False
            with self.assertRaises(ValueError):gate.validate_outputs(root,report,RECEIPT)

if __name__=='__main__':unittest.main()

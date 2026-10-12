"""Independent v2 skin-stage reader regressions; no GPU, build or asset run."""
import copy
import json
from pathlib import Path
import struct
import unittest

import run_resident_authored_contract as resident
import test_resident_authored_contract as parent
import test_resident_vertex_probe as previous


class SkinProbeTests(unittest.TestCase):
    def setUp(self):
        self.base = previous.VertexProbeTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.root, self.directory = self.base.root, self.base.directory
        self.report, self.rows, self.result = self.base.report, self.base.rows, self.base.result
        self.captures = self.directory.parent / 'captures'
        self.captures.mkdir()
        self.result['schema'] = 'rust-duty-resident-vertex-probe-result/v2'
        for case in self.report['cases']:
            raw = b''.join(parent.chunks(case))
            (self.captures / (case['name'] + '-cpu.corners.bin')).write_bytes(raw)
            row = self.rows[case['name']]
            row.update(schema='rust-duty-resident-vertex-probe/v2', skin_intermediate_errors=[])
            for draw in row['draws']:
                draw['kind'] = 'skin'
                for route, key in [('cpu','cpu_probe_shader_sha256'), ('current','current_probe_shader_sha256'), ('historical','historical_probe_shader_sha256')]:
                    draw[key] = self.base.shader_hash(route, 'skin', draw['vertex_count'])
                count = draw['vertex_count']
                positions = [list(struct.unpack_from('<3I',raw,j*40)) for corner in draw['triangle_corner_offsets'] for j in range(corner,corner+3)]
                vertex = struct.pack('<8f8H8f',1.,2.,3.,0.,0.,0.,0.,1.,*[0]*8,1.,*[0.]*7)
                uniforms = bytearray(240)
                for offset in (0,64,128):
                    struct.pack_into('<16I',uniforms,offset,*parent.old.IDENTITY)
                palette = bytearray(16384)
                for offset in (0,8192):
                    struct.pack_into('<16I',palette,offset,*parent.old.IDENTITY)
                value = {'schema':'rust-duty-skin-intermediates/v1',
                         'shader_sha256':resident.pair.controls.digest(resident.skin_stage_shader(self.root,count).encode()),
                         'bone_count':1,'vertex_stride':80,'cpu_world_position_bits':positions,
                         'samples':[{'source_vertex':v['source_vertex'],'skin_position_bits':p+[0x3f800000],
                                     'world_position_bits':p+[0x3f800000],
                                     'skin_route_clip_bits':v['clip_bits'].copy(),
                                     'world_route_clip_bits':v['clip_bits'].copy()}
                                    for v,p in zip(draw['current_vertex_stage'],positions)]}
                for name, payload in [('uploaded_vertices',vertex*count*2),('draw_uniforms',bytes(uniforms)),('palette',bytes(palette))]:
                    value[name+'_hex']=payload.hex();value[name+'_sha256']=resident.pair.controls.digest(payload)
                draw['skin_intermediates']=value
        self.save()

    def save(self):
        self.base.save()

    def validate(self, **kw):
        return resident.validate_vertex_probe(self.directory,self.report,parent.RECEIPT,self.root,**kw)

    def first(self):
        return self.rows['ready-0']['draws'][0]

    def change_payload(self,name,offset,raw,rehash=True):
        v=self.first()['skin_intermediates'];data=bytearray.fromhex(v[name+'_hex']);data[offset:offset+len(raw)]=raw
        v[name+'_hex']=data.hex()
        if rehash:v[name+'_sha256']=resident.pair.controls.digest(data)

    def reject(self,change):
        saved=copy.deepcopy((self.rows,self.report,self.result))
        try:
            change();self.save()
            with self.assertRaises(ValueError):self.validate()
        finally:
            self.base.rows,self.base.report,self.base.result=copy.deepcopy(saved)
            self.rows,self.report,self.result=self.base.rows,self.base.report,self.base.result
            self.save()

    def test_complete_v2_joins_raw_original_positions_and_preserves_parent(self):
        before=copy.deepcopy((self.rows,self.report,self.result))
        value=self.validate()
        self.assertEqual(value['schema'],'rust-duty-resident-vertex-probe-summary/v2')
        self.assertTrue(value['image_gate_passed'])
        self.assertEqual(value['intermediate_vertices'],value['selected_vertices'])
        for key in ('skin_route_clip_differences','world_route_clip_differences','intermediate_route_clip_differences','world_cpu_position_differences'):
            self.assertEqual(value[key],0)
        self.assertEqual((self.rows,self.report,self.result),before)

    def test_explicit_capture_directory_and_missing_default(self):
        moved=self.captures.with_name('separate-captures');self.captures.rename(moved)
        with self.assertRaises(ValueError):self.validate()
        self.assertTrue(self.validate(capture_directory=moved)['diagnostic_completed'])

    def test_v1_remains_replayable_without_raw_corners(self):
        self.result['schema']='rust-duty-resident-vertex-probe-result/v1'
        for row in self.rows.values():
            row['schema']='rust-duty-resident-vertex-probe/v1';row.pop('skin_intermediate_errors')
            for draw in row['draws']:draw.pop('skin_intermediates')
        self.save();self.captures.rename(self.captures.with_name('unavailable'))
        value=self.validate();self.assertTrue(value['diagnostic_completed']);self.assertNotIn('intermediate_vertices',value)

    def test_numeric_stage_disagreement_is_diagnostic_not_an_acceptance_tolerance(self):
        sample=self.first()['skin_intermediates']['samples'][0]
        sample['skin_route_clip_bits'][0]+=1;sample['world_route_clip_bits'][1]+=2;sample['world_position_bits'][0]+=1
        self.save();value=self.validate()
        self.assertEqual(value['skin_route_clip_differences'],1);self.assertEqual(value['world_route_clip_differences'],1)
        self.assertEqual(value['intermediate_route_clip_differences'],1);self.assertEqual(value['world_cpu_position_differences'],1)
        self.assertTrue(value['image_gate_passed'])

    def test_failed_image_verdict_remains_false_with_complete_diagnostics(self):
        self.report['passed']=False;self.result['image_gate_passed']=False
        self.report['cases'][0].update(differing_pixels=1,maximum_channel_delta=1)
        self.rows['ready-0']['changed_pixel_count']=1
        self.save();self.assertFalse(self.validate()['image_gate_passed'])

    def test_version_error_and_rigid_stage_inventories(self):
        changes=[lambda:self.result.update(schema='rust-duty-resident-vertex-probe-result/v9'),
                 lambda:self.rows['ready-0'].update(schema='rust-duty-resident-vertex-probe/v1'),
                 lambda:self.rows['ready-0'].update(skin_intermediate_errors=['map failed']),
                 lambda:self.first().pop('skin_intermediates'),
                 lambda:self.first().update(skin_intermediates=None)]
        for change in changes:
            with self.subTest(change=change):self.reject(change)
        draw=self.first();draw['kind']='rigid'
        for route,key in [('cpu','cpu_probe_shader_sha256'),('current','current_probe_shader_sha256'),('historical','historical_probe_shader_sha256')]:draw[key]=self.base.shader_hash(route,'rigid',6)
        self.save()
        with self.assertRaises(ValueError):self.validate()
        draw['skin_intermediates']=None;self.save();self.assertEqual(self.validate()['intermediate_vertices'],self.validate()['selected_vertices']-6)

    def test_closed_stage_fields_layout_types_and_shader_identity(self):
        for key,val in [('schema','wrong'),('bone_count',True),('bone_count',0),('bone_count',129),('vertex_stride',True),('vertex_stride',79),('shader_sha256','0'*64),('extra',0)]:
            with self.subTest(key=key,val=val):self.reject(lambda:self.first()['skin_intermediates'].update({key:val}))

    def test_payload_length_encoding_and_digest_are_bound(self):
        for name in ('uploaded_vertices','draw_uniforms','palette'):
            for bad in ('','zz',None,[],False):
                with self.subTest(name=name,bad=bad):self.reject(lambda:self.first()['skin_intermediates'].update({name+'_hex':bad}))
            self.reject(lambda:self.first()['skin_intermediates'].update({name+'_sha256':'a'*64}))
        self.reject(lambda:self.change_payload('uploaded_vertices',0,struct.pack('<f',7),rehash=False))

    def test_duplicate_inputs_must_match_even_with_honest_rehash(self):
        self.reject(lambda:self.change_payload('uploaded_vertices',80,struct.pack('<f',7)))

    def test_finite_vertex_uniform_and_palette_inputs(self):
        for name,offset in [('uploaded_vertices',0),('draw_uniforms',0),('palette',0),('palette',8192)]:
            with self.subTest(name=name,offset=offset):
                def change():
                    self.change_payload(name,offset,struct.pack('<I',0x7f800000))
                    if name=='uploaded_vertices':self.change_payload(name,offset+80,struct.pack('<I',0x7f800000))
                self.reject(change)

    def test_all_joint_slots_and_weights_are_validated_after_rehash(self):
        for offset,data in [(46,struct.pack('<H',1)),(48,struct.pack('<f',0.)),(48,struct.pack('<f',-1.)),(52,struct.pack('<I',0x7fc00000)),(52,struct.pack('<f',.25))]:
            with self.subTest(offset=offset,data=data):
                def change():
                    self.change_payload('uploaded_vertices',offset,data);self.change_payload('uploaded_vertices',offset+80,data)
                self.reject(change)

    def test_cpu_position_words_bind_order_and_original_corner_bytes(self):
        for change in [lambda:self.first()['skin_intermediates']['cpu_world_position_bits'][0].__setitem__(0,123),
                       lambda:self.first()['skin_intermediates']['cpu_world_position_bits'].pop(),
                       lambda:self.first()['skin_intermediates']['cpu_world_position_bits'][0].__setitem__(0,True)]:
            self.reject(change)
        path=self.captures/'ready-0-cpu.corners.bin';raw=path.read_bytes();path.write_bytes(raw[:-1])
        with self.assertRaises(ValueError):self.validate()
        path.write_bytes(raw)

    def test_per_command_raw_hashes_cannot_disagree_with_rehashed_case_aggregate(self):
        path=self.captures/'ready-0-cpu.corners.bin';raw=bytearray(path.read_bytes());raw[-1]^=1;path.write_bytes(raw)
        case=self.report['cases'][0];h=resident.pair.controls.digest(raw);case.update(cpu_expanded_sha256=h,resident_expanded_sha256=h)
        self.save()
        with self.assertRaises(ValueError):self.validate()

    def test_sample_count_order_types_and_unwritten_homogeneous_words(self):
        changes=[lambda:self.first()['skin_intermediates']['samples'].pop(),
                 lambda:self.first()['skin_intermediates']['samples'][0].update(source_vertex=True),
                 lambda:self.first()['skin_intermediates']['samples'][0].update(source_vertex=5),
                 lambda:self.first()['skin_intermediates']['samples'][0].update(extra=1),
                 lambda:self.first()['skin_intermediates']['samples'][0].update(skin_position_bits=[2**32-1]*4),
                 lambda:self.first()['skin_intermediates']['samples'][0]['world_position_bits'].__setitem__(3,0),
                 lambda:self.first()['skin_intermediates']['samples'][0]['skin_route_clip_bits'].__setitem__(0,True),
                 lambda:self.first()['skin_intermediates']['samples'][0]['world_route_clip_bits'].__setitem__(0,2**32)]
        for change in changes:
            with self.subTest(change=change):self.reject(change)

    def test_nonfinite_observed_xyz_remains_visible_as_diagnostic(self):
        self.first()['skin_intermediates']['samples'][0]['world_position_bits'][0]=0x7f800000
        self.save();self.assertEqual(self.validate()['world_cpu_position_differences'],1)

    def test_nonidentity_per_command_models_are_rejected(self):
        for key in ('cpu_model_bits','resident_model_bits'):
            self.reject(lambda:self.first()[key].__setitem__(12,0x3f800000))

    def test_stage_shader_reconstruction_is_bounded_and_input_specific(self):
        for count in (True,0,-1,193,1.5):
            with self.subTest(count=count),self.assertRaises(ValueError):resident.skin_stage_shader(self.root,count)
        value=resident.skin_stage_shader(self.root,6)
        self.assertIn('select(actual.skin_position, actual.world_position, (index & 1u) != 0u)',value)
        self.assertIn('(2.0 / 12.0)',value)


if __name__=='__main__':unittest.main()

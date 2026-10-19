import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_vrview import fixture
import vrpack
import vrview
from runtime import load_map, plan, replace_clips, INHERITS, BASIS, conversion_command

class RuntimeMapTests(unittest.TestCase):
    def setUp(self):
        self.mapping=load_map(Path(__file__).with_name('runtime_map.json'))
    def test_existing_coverage_and_stable_ids(self):
        rows={r['id']:r for r in self.mapping['clips']}
        self.assertEqual(len(rows),55)
        self.assertEqual(rows['hip_walk_forward_r5']['name'],'hip_walk_forward_r1')
        self.assertEqual(rows['reload_current_wip']['status'],'wip')
        self.assertEqual(rows['normal_settle']['bundle'],'locomotion')
        self.assertEqual(len(self.mapping['excluded']),12)
        for key in ['low_vault','onehand_mantle','prone_entry','ads_walk_forward_v9_diagnostic']:
            self.assertIn(key,self.mapping['excluded'])
    def manifest(self):
        return {'schema':'rust-duty-weapon-fbx/v1','clips':[
            dict(id=key,file=key+'.fbx',take=key,frame_start=55,frame_end=65,fps=60,fps_base=1.001,objects=['hk416_weapon','hk416_magazine','hk416_magazine_outgoing'])
            for key in [r['id'] for r in self.mapping['clips']]+list(self.mapping['excluded'])]}
    def test_native_timing_and_no_source_crop(self):
        result=plan(self.mapping,self.manifest())
        self.assertEqual(result[0]['end'],10)
        self.assertEqual(result[0]['fps'],'60000/1001')
    def test_canonical_fbx_origin_is_not_legacy_zero_origin(self):
        entry=plan(self.mapping,self.manifest())[0]
        entry['export'].update(sha256='hash',exported_rig='Arms')
        cmd=conversion_command(Path('.'),Path('fbx'),Path('source'),{'source_sha256':'source'},entry,Path('out'),'blender')
        self.assertEqual(cmd[cmd.index('--imported-frame-offset')+1],'55')
        self.assertEqual(cmd[cmd.index('--native-start')+1],'0')
        self.assertEqual(cmd[cmd.index('--native-end')+1],'10')
    def test_missing_reload_outgoing_actor_rejected_before_conversion(self):
        m=self.manifest()
        c=next(c for c in m['clips'] if c['id']=='reload_current_wip')
        c['objects'].remove('hk416_magazine_outgoing')
        with self.assertRaisesRegex(ValueError,'missing required runtime actor'):plan(self.mapping,m)
    def test_unknown_export_is_not_silently_bound(self):
        m=self.manifest();m['clips'].append(dict(id='new_clip'))
        with self.assertRaises(ValueError):plan(self.mapping,m)
    def test_path_traversal_rejected(self):
        m=self.manifest();m['clips'][0]['file']='../bad.fbx'
        with self.assertRaises(ValueError):plan(self.mapping,m)
    def test_inherited_bundles_refresh_locomotion(self):
        for key in ['walk','directional','ads','jump']:
            self.assertIn('locomotion',INHERITS[key])

class ReplacementTests(unittest.TestCase):
    def setUp(self):
        doc,blob,_=fixture();s=vrview.Scene(doc,blob)
        self.vrs,self.vrm,self.actors=s.companions(['gun'])
        self.bones=[(b[0],b[1]) for b in s.skin.bones]
        values,worlds=s.sample(0)
        self.frames=[dict(time=t,bones=values,actors=[vrview.decompose(worlds[5])],visible=[1]) for t in (0.,1.)]
        self.base=self.encode([self.clip('active'),self.clip('preserved')])
    def clip(self,name):return dict(name=name,loop=False,frames=copy.deepcopy(self.frames))
    def encode(self,clips):return vrview.encode_vra(self.bones,self.actors,clips,self.vrs,self.vrm)
    def test_replacement_idempotent_no_duplicates_and_unselected_preserved(self):
        updated=self.clip('active');updated['frames'][-1]['time']=2.
        incoming=self.encode([updated])
        first=replace_clips(self.base,{'active':incoming},self.vrs,self.vrm)
        second=replace_clips(first,{'active':incoming},self.vrs,self.vrm)
        self.assertEqual(first,second)
        clips=vrview.decode_vra(first,vrs=self.vrs,vrm=self.vrm)['clips']
        self.assertEqual([c['name'] for c in clips],['active','preserved'])
        self.assertEqual(clips[0]['frames'][-1]['time'],2.)
        self.assertEqual(clips[1],vrview.decode_vra(self.base)['clips'][1])
        actual=vrview.matrix(clips[0]['frames'][0]['actors'][0])
        expected=vrpack.matmul(vrview.matrix(updated['frames'][0]['actors'][0]),BASIS)
        self.assertLess(max(abs(a-b) for a,b in zip(actual,expected)),1e-6)
    def test_new_gameplay_slot_is_rejected(self):
        with self.assertRaises(ValueError):replace_clips(self.base,{'new':self.encode([self.clip('new')])},self.vrs,self.vrm)
    def test_changed_loop_setting_is_rejected(self):
        clip=self.clip('active');clip['loop']=True
        with self.assertRaises(ValueError):replace_clips(self.base,{'active':self.encode([clip])},self.vrs,self.vrm)

if __name__=='__main__':unittest.main()

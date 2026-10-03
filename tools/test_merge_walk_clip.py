"""Synthetic tests: binary preservation, name mapping, and explicit rigid basis."""
import copy
import unittest
import vrpack
import vrview
import vrskin
from test_vrview import fixture
from merge_walk_clip import BASIS, clip_offset, merge

class WalkMergeTests(unittest.TestCase):
    def setUp(self):
        doc,blob,_=fixture();scene=vrview.Scene(doc,blob);self.scene=scene
        self.vrs,self.vrm,self.actors=scene.companions(['gun'])
        self.bones=[(b[0],b[1]) for b in scene.skin.bones]
        values,globals_=scene.sample(0)
        self.frames=[{'time':t,'bones':values,'actors':[vrview.decompose(globals_[5])],'visible':[1]} for t in (0.,1.)]
        self.base=vrview.encode_vra(self.bones,self.actors,[{'name':'normal_settle','loop':False,'frames':self.frames}],self.vrs,self.vrm)
    def incoming(self,loop=True,name='normal_walk_r1'):
        return vrview.encode_vra(self.bones,self.actors,[{'name':name,'loop':loop,'frames':self.frames}],self.vrs,self.vrm)
    def test_keeps_legacy_bytes_and_companion_checksums(self):
        raw=merge(self.base,self.incoming(),self.vrs,self.vrm)
        p=clip_offset(self.base);q=clip_offset(raw)
        self.assertEqual(raw[q+4:q+4+len(self.base)-p-4],self.base[p+4:])
        result=vrview.decode_vra(raw,vrs=self.vrs,vrm=self.vrm)
        self.assertEqual([c['name'] for c in result['clips']],['normal_settle','normal_walk_r1'])
        actual=vrview.matrix(result['clips'][1]['frames'][0]['actors'][0])
        expected=vrpack.matmul(vrview.matrix(self.frames[0]['actors'][0]),BASIS)
        self.assertLess(max(abs(x-y) for x,y in zip(actual,expected)),1e-6)
    def test_nonloop_rejected(self):
        with self.assertRaisesRegex(vrpack.AssetError,'must loop'):merge(self.base,self.incoming(False),self.vrs,self.vrm)
    def test_nonloop_ads_can_append_without_altering_old_payloads(self):
        raw = merge(self.base, self.incoming(False, 'ads_entry_r1'), self.vrs, self.vrm,
                    name='ads_entry_r1', expected_loop=False)
        before, after = clip_offset(self.base), clip_offset(raw)
        self.assertEqual(raw[after+4:after+len(self.base)-before], self.base[before+4:])
        self.assertFalse(vrview.decode_vra(raw)['clips'][-1]['loop'])
    def test_ads_loop_contract_rejects_unexpected_loop(self):
        with self.assertRaisesRegex(vrpack.AssetError, 'must not loop'):
            merge(self.base, self.incoming(True, 'ads_entry_r1'), self.vrs, self.vrm,
                  name='ads_entry_r1', expected_loop=False)
    def test_duplicate_rejected(self):
        with self.assertRaisesRegex(vrpack.AssetError,'already exists'):merge(self.incoming(),self.incoming(),self.vrs,self.vrm)
    def test_wrong_name_rejected(self):
        with self.assertRaisesRegex(vrpack.AssetError,'missing'):merge(self.base,self.incoming(name='run'),self.vrs,self.vrm)
    def test_reorders_bones_by_name(self):
        newbones=[self.bones[1],self.bones[0]]
        newbones=[(newbones[0][0],-1),(newbones[1][0],0)]
        frames=copy.deepcopy(self.frames)
        for f in frames:f['bones']=list(reversed(f['bones']))
        skin_bones=[(b[0],p,*b[2:]) for b,p in zip(reversed(self.scene.skin.bones),[-1,0])]
        skin=vrskin.encode_vrs(skin_bones,self.scene.skin.output_meshes)
        incoming=vrview.encode_vra(newbones,self.actors,[{'name':'normal_walk_r1','loop':True,'frames':frames}],skin,self.vrm)
        result=vrview.decode_vra(merge(self.base,incoming,self.vrs,self.vrm))
        self.assertEqual(result['clips'][1]['frames'][0]['bones'],vrview.decode_vra(self.base)['clips'][0]['frames'][0]['bones'])

if __name__=='__main__':unittest.main()

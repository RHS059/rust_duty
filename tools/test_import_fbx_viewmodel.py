import unittest
from fractions import Fraction
import import_fbx_viewmodel as importer
import vrpack
import vrview

class FbxTimingTests(unittest.TestCase):
    def test_native_rate_and_inclusive_crop(self):
        f,t=importer.sample_grid(48,156,64)
        self.assertEqual((f[0],f[-1]),(48,156))
        self.assertEqual(len(f),108*64+1)
        self.assertEqual(t[0],0)
        self.assertEqual(t[-1],vrpack.f32(108*1001/60000))
    def test_single_frame_reset_is_supported(self):
        frames,times=importer.sample_grid(0,0)
        self.assertEqual(frames,[Fraction(0)]);self.assertEqual(times,[0.])
    def test_switch_neighbors_survive_float32(self):
        f,t=importer.sample_grid(48,156,64,['111.98','112'])
        i=f.index(Fraction(112))
        self.assertEqual(f[i-1],112-Fraction(1,65536))
        self.assertLess(t[i-1],t[i]);self.assertLess(t[i],t[i+1])
        self.assertIn(Fraction('111.98'),f)
    def test_dense_collision_is_rejected_not_deduplicated(self):
        with self.assertRaisesRegex(vrpack.AssetError,'collide'):
            importer.sample_grid(0,60000,1,['59999'])
    def test_no_join_inferred(self):
        opening,_=importer.sample_grid(0,30,1)
        returning,_=importer.sample_grid(48,156,1)
        self.assertFalse(set(opening)&set(returning))
        self.assertNotIn(31,opening);self.assertNotIn(47,returning)
    def test_invalid_crop_and_switch_fail(self):
        for args in [(30,0),(-1,3)]:
            with self.assertRaises(vrpack.AssetError):importer.sample_grid(*args)
        with self.assertRaises(vrpack.AssetError):importer.sample_grid(0,30,64,['30'])

class FbxVisibilityTests(unittest.TestCase):
    def test_zero_scale_is_invisible(self):
        m=list(vrpack.IDENTITY);m[0]=m[5]=m[10]=0;m[3]=9
        trs,mask=importer.rigid_transform(tuple(m))
        self.assertEqual(mask,0);self.assertEqual(vrview.matrix(trs),vrpack.IDENTITY)
    def test_identity_stays_visible(self):
        _,mask=importer.rigid_transform(vrpack.IDENTITY)
        self.assertEqual(mask,1)
    def test_hidden_identity_does_not_interpolate_visibility(self):
        trs,_=importer.rigid_transform(vrpack.IDENTITY)
        frames=[{'time':0.,'bones':[],'actors':[trs],'visible':[0]},
                {'time':1.,'bones':[],'actors':[trs],'visible':[1]}]
        pack={'clips':[{'name':'visibility','loop':False,'frames':frames}]}
        self.assertEqual(vrview.sample(pack,'visibility',.999)['visible'],[0])
        self.assertEqual(vrview.sample(pack,'visibility',1.)['visible'],[1])
    def test_partially_singular_rejected(self):
        m=list(vrpack.IDENTITY);m[0]=0
        with self.assertRaises(vrpack.AssetError):importer.rigid_transform(tuple(m))


class LocomotionTimingTests(unittest.TestCase):
    def test_sixty_hz_walk_loop(self):
        frames,times=importer.sample_grid(0,44,8,fps=Fraction(60))
        self.assertEqual(len(frames),353)
        self.assertEqual(times[-1],vrpack.f32(44/60))
    def test_bad_rate_rejected(self):
        with self.assertRaises(vrpack.AssetError):
            importer.sample_grid(0,44,8,fps=Fraction(0))

if __name__=='__main__':unittest.main()

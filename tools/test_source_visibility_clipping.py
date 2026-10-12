import unittest
from source_visibility_clipping import I, Unresolved, clip_xy, clip_xy_variants, project, samples

def vertex(x,y,w=1):return [[x,x],[y,y],[0,0],[w,w]]
class ClipTests(unittest.TestCase):
 def test_crossing_generates_and_bounds_vertices(self):
  p,n=clip_xy([vertex(-.4,-.3),vertex(.4,-.3),vertex(0,-2)])
  self.assertEqual(len(p),4);self.assertEqual(n,2)
  generated=[v for v in p if v[1].lo<=-1<=v[1].hi]
  self.assertEqual(len(generated),2)
  self.assertTrue(all(project(v)[0][1].lo<540<project(v)[0][1].hi for v in generated))
 def test_outside_triangle_stays_empty(self):
  p,n=clip_xy([vertex(-.4,-2),vertex(.4,-2),vertex(0,-3)])
  self.assertEqual(p,[])
 def test_near_eye_and_far_fail(self):
  for w in (0,-1):
   with self.assertRaises(Unresolved):clip_xy([vertex(0,0,w)]*3)
 def test_ambiguous_clipping_branch_fails(self):
  v=vertex(0,0);v[0]=[.999999,1.000001]
  with self.assertRaises(Unresolved):clip_xy([v,vertex(0,0),vertex(0,.1)])
 def test_pixel_center_near_clipped_boundary_is_interior(self):
  p,_=clip_xy([vertex(-.8,-2),vertex(.8,-2),vertex(0,.9)])
  screen=[project(v)[0] for v in p]
  r,q=samples(screen,[539*960+480,100*960+100])
  self.assertIn(539*960+480,r);self.assertNotIn(100*960+100,q)
class BranchTests(unittest.TestCase):
 def test_empty_branch_survives_later_certain_clip_plane(self):
  vs=[vertex(1,y) for y in [-2,0,.5]]
  for v in vs:v[0]=[.9,1.1]
  states=clip_xy_variants(vs)
  self.assertTrue(any(len(poly)<3 for poly,_ in states))
  self.assertTrue(any(len(poly)>=3 for poly,_ in states))

 def test_uncertain_original_clip_mask_enumerates_skip_and_clip(self):
  v=vertex(0,0);v[0]=[.999999,1.000001]
  states=clip_xy_variants([v,vertex(0,0),vertex(0,.1)])
  self.assertGreater(len(states),1)
  self.assertTrue(any(n==0 for _,n in states))
  self.assertTrue(any(n>0 for _,n in states))
 def test_strict_original_inside_plane_stays_unclipped(self):
  states=clip_xy_variants([vertex(-.1,-.1),vertex(.1,-.1),vertex(0,.1)])
  self.assertEqual(len(states),1);self.assertEqual(states[0][1],0)
 def test_small_w_exits_fail_closed(self):
  with self.assertRaises(Unresolved):clip_xy_variants([vertex(0,0,2**-21)]*3)
 def test_generated_color_enclosure_contains_source_constant(self):
  states=clip_xy_variants([vertex(-.4,-.3),vertex(.4,-.3),vertex(0,-2)],[[64,128,192,255]]*3)
  for poly,_ in states:
   for v in poly:
    for b,c in zip(v[4:],[64,128,192]):self.assertLessEqual(b.lo,c/255);self.assertGreaterEqual(b.hi,c/255)
if __name__=='__main__':unittest.main()

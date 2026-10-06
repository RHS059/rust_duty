import io, json, struct, unittest, zipfile, zlib
import numpy as np
import review

def fixture():
 p=struct.pack('<IIIH',0,0,1,4)+b'root'+struct.pack('<iII',-1,0,1)
 p+=struct.pack('<H',4)+b'loop'+struct.pack('<II',1,3)
 for t,x in [(0.,0.),(.5,.1),(1.,0.)]:p+=struct.pack('<f10f',t,x,0,0,0,0,0,1,1,1,1)
 return struct.pack('<8sIIII',b'VRANIM01',1,len(p),zlib.crc32(p),0)+p

def zipbytes(name,data=b'a'):
 b=io.BytesIO()
 with zipfile.ZipFile(b,'w') as z:z.writestr(name,data)
 return b.getvalue()

def contact():return {'schema':'rust-duty-contact-samples/v1','units':'metres','space':'evaluated-world','source_sha256':'0'*64,'pairs':[{'name':'pad-anchor','time_seconds':[0.,.25], 'a':[[0,0,0],[0,0,0]],'b':[[.01,0,0],[9,0,0]],'observed':[True,False]}]}

class TestReview(unittest.TestCase):
 def test_pack(self):
  p,r=review.analyze_pack(fixture(),transitions=[('loop','loop')]);self.assertEqual(r['clips'][0]['bones']['endpoint_gap']['translation_max'],0);self.assertAlmostEqual(r['clips'][0]['bones']['maximum_sampled_translation_speed'],.2);self.assertFalse(r['binding']['skin_structure_crc_skeleton_checked'])
 def test_checksum(self):
  with self.assertRaises(ValueError):review.analyze_pack(fixture()[:-1]+b'x')
 def test_transition(self):
  with self.assertRaises(ValueError):review.analyze_pack(fixture(),transitions=[('missing','loop')])
 def test_quaternion_sign(self):self.assertEqual(float(review.angle([0,0,0,1],[0,0,0,-1])),0)
 def test_quaternion_half_turn(self):self.assertAlmostEqual(float(review.angle([0,0,0,1],[1,0,0,0])),180)
 def test_safe_zip(self):self.assertEqual(review.safe_inputs(zipbytes('ads/asset.vra')),{'ads/asset.vra':b'a'})
 def test_paths(self):
  for name in ('../a.json','/a.json','a\\b.json','C:a.json','a.py'):
   with self.subTest(name=name),self.assertRaises(ValueError):review.safe_inputs(zipbytes(name))
 def test_duplicate_zip(self):
  b=io.BytesIO()
  with zipfile.ZipFile(b,'w') as z:z.writestr('a.json','1');z.writestr('a.json','2')
  with self.assertRaises(ValueError):review.safe_inputs(b.getvalue())
 def test_json(self):
  for b in ('{"a":NaN}','{"a":1e999}','{"a":1,"a":2}'):
   with self.assertRaises(ValueError):review.strict_json(b)
 def test_observed(self):
  r=review.contact_report(contact());self.assertEqual(r['pairs'][0]['coverage'],.5);self.assertAlmostEqual(r['pairs'][0]['max_observed_separation_m'],.01)
 def test_unobserved(self):
  c=contact();c['pairs'][0]['observed']=[False,False];self.assertIsNone(review.contact_report(c)['pairs'][0]['max_observed_separation_m'])
 def test_boolean_mask(self):
  c=contact();c['pairs'][0]['observed']=[1,0]
  with self.assertRaises(ValueError):review.contact_report(c)
 def test_time_order(self):
  c=contact();c['pairs'][0]['time_seconds']=[1.,0.]
  with self.assertRaises(ValueError):review.contact_report(c)
 def test_invalid_hash(self):
  c=contact();c['source_sha256']='?'*64
  with self.assertRaises(ValueError):review.contact_report(c)
 def test_huge_coordinate(self):
  c=contact();c['pairs'][0]['a'][0][0]=1e200
  with self.assertRaises(ValueError):review.contact_report(c)
 def test_nonfinite(self):
  c=contact();c['pairs'][0]['a'][0][0]=float('nan')
  with self.assertRaises(ValueError):review.contact_report(c)

if __name__=='__main__':unittest.main()

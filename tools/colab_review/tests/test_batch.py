import tempfile, unittest, zipfile
from pathlib import Path
import review

class TestPreservation(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  root=Path(self.temp.name);self.out=root/'out';self.out.mkdir()
  (self.out/'report.json').write_text('{"status":"diagnostic"}')
  self.archive=root/'result.zip'
  with zipfile.ZipFile(self.archive,'w') as z:z.write(self.out/'report.json','report.json')
  self.data=self.archive.read_bytes();self.sha=review.digest(self.data)
  self.hashes={'report.json':review.digest((self.out/'report.json').read_bytes())}
 def verify(self,data=None):return review.verify_preserved_archive(self.archive,self.out,self.data if data is None else data,self.sha,self.hashes)
 def test_verified_copy(self):self.assertEqual(self.verify()['sha256'],self.sha)
 def test_wrong_download(self):
  with self.assertRaises(ValueError):self.verify(b'wrong')
 def test_changed_output(self):
  (self.out/'report.json').write_text('changed')
  with self.assertRaises(ValueError):self.verify()
 def test_added_output(self):
  (self.out/'new.txt').write_text('unpreserved')
  with self.assertRaises(ValueError):self.verify()
 def test_changed_archive(self):
  self.archive.write_bytes(b'changed')
  with self.assertRaises(ValueError):self.verify()
 def test_subdirectory(self):
  (self.out/'nested').mkdir()
  with self.assertRaises(ValueError):self.verify()
 def test_default_teardown_inert(self):
  from batch_cells import TEARDOWN
  exec(TEARDOWN,{}) # No Colab imports or unassignment on default Run All.
 def test_ids_preserved(self):
  import json
  nb=json.loads((Path(__file__).parents[1]/'Rust_Duty_Animation_Review.ipynb').read_text())
  old=[c['id'] for c in nb['cells'] if c['id'].startswith('review-')]
  self.assertEqual(old,[f'review-{i:02d}' for i in range(13)])

if __name__=='__main__':unittest.main()

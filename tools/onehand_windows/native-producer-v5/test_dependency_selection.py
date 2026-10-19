"""Portable dependency mutations and exact predecessor-byte preservation. No native work."""
import hashlib, json, shutil, tempfile, unittest
from pathlib import Path
HERE=Path(__file__).absolute().parent
ROOT=HERE.parent
CONTEXT=ROOT/'windows-context-preparation-v3'
if not CONTEXT.is_dir():CONTEXT=ROOT/'context-v3'
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_bytes())

import pinned_code as p
import native_stages as n
class DependencySelection(unittest.TestCase):
 def test_exact_context_and_unchanged_loaded_patch_receipts(self):
  cc=p.load_context(CONTEXT)
  self.assertEqual(cc.SCHEMA,'rust-duty-windows-candidate-context/v2')
  resolver=p.isolated_module('addon_resolver',CONTEXT/'addon_resolver.py',{'candidate_context':cc})
  profile=resolver.official_pins()
  self.assertEqual(profile['schema'],'rust-duty-windows-official-fbx-pins/v2')
  self.assertEqual(profile['loaded_functions_sha256']['import_fbx.py'],n.PATCH_SHA)
  self.assertNotEqual(profile['raw_functions_sha256']['import_fbx.py'],n.PATCH_SHA)
 def test_changed_context_manifest_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'context';shutil.copytree(CONTEXT,root)
   with (root/'PINS.json').open('ab') as f:f.write(b' ')
   with self.assertRaisesRegex(ValueError,'exact context'):p.load_context(root)
 def test_changed_profile_resolver_or_context_rejected(self):
  for name in ('OFFICIAL_ADDON_PINS.json','addon_resolver.py','candidate_context.py'):
   with self.subTest(name=name),tempfile.TemporaryDirectory() as d:
    root=Path(d)/'context';shutil.copytree(CONTEXT,root)
    with (root/name).open('ab') as f:f.write(b'\n')
    with self.assertRaisesRegex(ValueError,'context freeze differs'):p.load_context(root)
 def test_production_source_is_only_context_pin_and_diagnostic(self):
  old=read(HERE/'PREDECESSOR_SELECTED_SOURCE.json')
  raw=(HERE/'pinned_code.py').read_bytes().replace(p.CONTEXT_PINS_SHA.encode(),b'3162a4c5bbc50daa13ec1c84972b0e4b56c2221a909d1aa2c10617c912b0d801').replace(b'exact context v3 freeze required',b'exact context v2 freeze required')
  self.assertEqual(hashlib.sha256(raw).hexdigest(),old['files']['pinned_code.py'])
  for name,want in old['files'].items():
   if name!='pinned_code.py':self.assertEqual(sha(HERE/name),want,name)
 def test_full_grid_stage_math_and_receipts_remain_exact(self):
  cc=p.load_context(CONTEXT)
  self.assertEqual(cc.INVARIANTS['source_samples'],4240)
  self.assertEqual(len(cc.FOCUS),9)
  self.assertEqual(sum(f*256!=int(f*256) for f in cc.FOCUS),4)
  self.assertEqual(n.PATCH_SHA,{'blen_read_animations':'757bd21550d94e2190881ec6b0eb0ce80b275d2a230055cf7702044fe6dcc6e2','blen_store_keyframes_multi':'793a389ebde0e71ec3cec54e731c861753aa08015355904777a8c39b70da3a4e'})
if __name__=='__main__':unittest.main(verbosity=2)

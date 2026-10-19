"""Portable dependency mutations and exact predecessor-byte preservation. No native work."""
import builtins, hashlib, json, shutil, sys, tempfile, unittest
from pathlib import Path
from types import ModuleType,SimpleNamespace
from unittest import mock
HERE=Path(__file__).absolute().parent
ROOT=HERE.parent
CONTEXT=ROOT/'windows-context-preparation-v3'
if not CONTEXT.is_dir():CONTEXT=ROOT/'context-v3'
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_bytes())

import pinned_math as p
import runtime_context as r
class DependencySelection(unittest.TestCase):
 def test_exact_context_and_loaded_patch_receipts(self):
  p.context_module(CONTEXT)
  profile=read(CONTEXT/'OFFICIAL_ADDON_PINS.json')
  self.assertEqual(profile['loaded_functions_sha256']['import_fbx.py'],p.AUDITED_PATCHES)
  self.assertNotEqual(profile['raw_functions_sha256']['import_fbx.py'],p.AUDITED_PATCHES)
 def test_context_manifest_profile_and_code_mutations_rejected(self):
  for name in ('PINS.json','OFFICIAL_ADDON_PINS.json','addon_resolver.py','candidate_context.py'):
   with self.subTest(name=name),tempfile.TemporaryDirectory() as d:
    root=Path(d)/'context';shutil.copytree(CONTEXT,root)
    with (root/name).open('ab') as f:f.write(b'\n')
    with self.assertRaises(ValueError):p.context_module(root)
 def test_producer_pin_is_exact_and_mutations_rejected(self):
  producer=ROOT/'windows-native-producer-v7'
  if not producer.is_dir():producer=ROOT/'native-producer-reviewed'
  p.pin(producer/'PINS.json',r.SELECTED_PRODUCER_PINS_SHA)
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'PINS.json';path.write_bytes((producer/'PINS.json').read_bytes()+b' ')
   with self.assertRaises(ValueError):p.pin(path,r.SELECTED_PRODUCER_PINS_SHA)
  import evidence
  ctx=SimpleNamespace(root=lambda _:producer,raw={'dependencies':{'producer_pins_sha256':r.SELECTED_PRODUCER_PINS_SHA}})
  original_import=builtins.__import__
  def ambient_trap(name,*args,**kwargs):
   if name in ('host_identity','fragment_ast'):raise AssertionError('ambient reviewed helper import forbidden')
   return original_import(name,*args,**kwargs)
  ambient=ModuleType('host_identity');ambient.require_native_host=lambda *args:(_ for _ in ()).throw(AssertionError('ambient helper selected'))
  with mock.patch.dict(sys.modules,{'host_identity':ambient,'fragment_ast':ModuleType('fragment_ast')}),mock.patch('builtins.__import__',side_effect=ambient_trap):
   admission=evidence.producer(ctx)
   self.assertEqual(admission.require_native_host.__module__,'_windows_runtime_host_identity')
 def test_only_exact_producer_pin_changes_production(self):
  old=read(HERE/'AST_DEPENDENCY_PREDECESSOR.json')
  for name,want in old['production_files'].items():
   raw=(HERE/name).read_bytes()
   if name=='runtime_context.py':raw=raw.replace(r.SELECTED_PRODUCER_PINS_SHA.encode(),old['selected_producer_pins_sha256'].encode())
   self.assertEqual(hashlib.sha256(raw).hexdigest(),want,name)
 def test_source_selection_is_not_independent_acceptance(self):
  v=read(HERE/'DEPENDENCY_REVIEW.json')
  self.assertEqual(v['decision'],'prepared-independent-review-required')
  self.assertFalse(v['native_admission']);self.assertFalse(v['actual_windows_provenance'])
  self.assertTrue(v['historical_review_does_not_approve_successor'])
  self.assertEqual(v['selected_context_pins_sha256'],p.CONTEXT_PINS_SHA)
  self.assertEqual(v['selected_producer_pins_sha256'],r.SELECTED_PRODUCER_PINS_SHA)
 def test_numerical_thresholds_and_source_selection_unchanged(self):
  self.assertEqual(p.LIMIT,1e-4);self.assertEqual(p.RAY_LIMIT,1e-5)
  self.assertEqual(len(p.FOCUS),9);self.assertEqual(sum(f*256!=int(f*256) for f in p.FOCUS),4)
  v=read(HERE/'SOURCE_CLOSURE.json');self.assertEqual(v['commit'],'c61dbd67039a4961d0c56f0a3c7e478c431d1ced');self.assertEqual(len(v['files']),213)
if __name__=='__main__':unittest.main(verbosity=2)

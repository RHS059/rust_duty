"""Tiny synthetic receipt boundary checks; real native output is never fabricated."""
import copy,hashlib,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import authored_bridge as b
SOURCE=Path(__file__).absolute().parents[1]/'source-producer-privacy-v1'

class BridgeTests(unittest.TestCase):
 def setUp(self):
  self.deps=b.load_dependencies(SOURCE)
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)
  self.target=root/'generated.blend';self.target.write_bytes(b'SYNTHETIC, NOT BLEND')
  self.replay_path=root/'replay.json';self.replay_path.write_bytes(b'{}')
  self.args=SimpleNamespace(generated_source=self.target,generated_source_sha256=b.sha(self.target),target_replay=self.replay_path,target_replay_sha256=b.sha(self.replay_path),baseline=root/'base',delta=root/'delta',reference_replay_sha256='4'*64,reference_index_sha256='5'*64,reference_proof_sha256='6'*64)
  self.replay={'action_hashes':{'legacy':'a'*64,'complete':'b'*64,'metadata':'c'*64,'auxiliary':'d'*64},'static_hashes':{'static':'e'*64},'metadata_projection':self.deps.core.privacy.binding('c'*64)}
  self.reference={'static_state_sha256':self.deps.core.delta.digest(self.replay['static_hashes']),'generated_source_sha256':'9'*64}
 def admit(self):
  with patch.object(b,'verify_inputs',return_value={'recipe':'synthetic'}),patch.object(b,'verify_reference',return_value=self.reference),patch.object(b,'bounded_json',return_value=self.replay),patch.object(self.deps.core.runner,'validate_replay',return_value=self.args.generated_source_sha256):
   return b.admit_authored(self.deps,self.args)
 def test_strict_projection_carried_into_bridge_v2(self):
  got=self.admit();self.assertEqual(got['schema'],'rust-duty-onehand-authored-input-bridge/v2');self.assertEqual(got['metadata_projection'],self.replay['metadata_projection']);self.assertEqual(got['source_relation'],self.deps.core.privacy.SOURCE_RELATION)
  for name in ('cross_platform_float64_equality_proved','windows_execution_proved','runtime_equivalence_proved','activation_authorized','target_evaluated_source_equivalence_proved'):self.assertIs(got[name],False)
 def test_generated_identity_pin_not_optional(self):
  self.args.generated_source_sha256='f'*64
  with self.assertRaises(ValueError):self.admit()
 def test_target_replay_pin_rechecked(self):
  self.args.target_replay_sha256='f'*64
  with self.assertRaises(ValueError):self.admit()
 def test_static_historical_identity_not_dropped(self):
  self.reference['static_state_sha256']='f'*64
  with self.assertRaises(ValueError):self.admit()
 def test_exact_source_and_portable_pins(self):
  self.assertEqual(b.sha(SOURCE/'PINS.json'),b.SOURCE_PINS_SHA);self.assertEqual(self.deps.core.privacy.manifest()[1],self.replay['metadata_projection']['projection_sha256']);self.deps.portable.cache_free_execution_package(SOURCE)
 def test_no_native_import_or_execution(self):self.assertNotIn('bpy',sys.modules)
 def test_same_buffer_rejects_changed_json(self):
  path=Path(self.tmp.name)/'j';path.write_bytes(b'{"x":1}');sha=b.sha(path);self.assertEqual(b.bounded_json(self.deps,path,sha),{'x':1});path.write_bytes(b'{"x":2}')
  with self.assertRaises(ValueError):b.bounded_json(self.deps,path,sha)
 def test_unknown_or_duplicate_json_rejected(self):
  path=Path(self.tmp.name)/'j'
  for raw in (b'{"x":1,"x":2}',b'{"x":Infinity}'):
   path.write_bytes(raw)
   with self.assertRaises(ValueError):b.bounded_json(self.deps,path,b.sha(path))
 def test_linux_cannot_claim_windows(self):
  with patch.object(sys,'platform','linux'),self.assertRaises(ValueError):b.host_snapshot(self.deps,SimpleNamespace())
if __name__=='__main__':unittest.main()

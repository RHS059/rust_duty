"""Synthetic envelope checks; does not manufacture a genuine native receipt."""
import copy,unittest
from unittest.mock import patch
import onehand_v6_source_delta as d
import onehand_v6_source_native as n
import privacy_projection as p
import run_onehand_v6_source_proof as r

class ReceiptTests(unittest.TestCase):
 def setUp(self):
  self.recipe={'action':{'target_complete_sha256':'b'*64},'action_auxiliary_sha256':'c'*64,'approved_static_hashes':{'objects':'d'*64},'producer_sha256':{'synthetic':'e'*64}}
  self.value={'schema':'rust-duty-onehand-v6-projected-source-replay/v1','passed':True,'fresh_reopen_passed':True,'base_sha256':d.BASE_SHA,'approved_source_sha256':d.APPROVED_SHA,'generated_source_sha256':'1'*64,'delta_sha256':'2'*64,'prior_actions_preserved':88,'created_actions':[d.RIG_ACTION],'result_action_count':89,'action_hashes':r.expected_action_hashes(self.recipe,'3'*64),'static_hashes':self.recipe['approved_static_hashes'],'original_scalar_corrections_applied':12,'unchanged_driven_outputs_recomputed':4,'producer_sha256':self.recipe['producer_sha256'],'blender_version':d.BLENDER_VERSION,'source_byte_identity_with_approved':False,'evaluated_equivalence_proved':False,'runtime_equivalence_proved':False,'rendered':False,'limits':['Fresh Windows full 4240-sample source-to-FBX-to-actual-Rust fidelity remains required.','The regenerated private BLEND is never a source-only publication artifact.'],'metadata_projection':p.binding('3'*64)}
  self.fake=patch.object(n,'validate_recipe');self.fake.start();self.addCleanup(self.fake.stop)
 def validate(self,v):return r.validate_replay(self.recipe,v,'2'*64)
 def test_complete_synthetic_envelope(self):self.assertEqual(self.validate(self.value),'1'*64)
 def test_projection_identities_cannot_be_replaced(self):
  for key in ('projection_sha256','original_delta_sha256','original_metadata_sha256','metadata_recipe_sha256','projected_metadata_sha256'):
   v=copy.deepcopy(self.value);v['metadata_projection'][key]='f'*64
   with self.assertRaises(ValueError):self.validate(v)
 def test_omitted_inventory_and_sampling_claim_cannot_change(self):
  for key,new in (('omitted_keys',[]),('historical_reference_resampled',True),('historical_reference_resampled',0),('schema','old')):
   v=copy.deepcopy(self.value);v['metadata_projection'][key]=new
   with self.assertRaises(ValueError):self.validate(v)
 def test_action_hash_identity_cannot_change(self):
  for key in ('legacy','complete','metadata','auxiliary'):
   v=copy.deepcopy(self.value);v['action_hashes'][key]='f'*64
   with self.assertRaises(ValueError):self.validate(v)
 def test_historical_full_metadata_schema_is_rejected(self):
  v=copy.deepcopy(self.value);v['schema']='rust-duty-onehand-v6-source-replay/v1';del v['metadata_projection']
  with self.assertRaises(ValueError):self.validate(v)
 def test_replay_extra_private_fields_rejected(self):
  for key in ('review','geometry','rest'):
   v=copy.deepcopy(self.value);v[key]={}
   with self.assertRaises(ValueError):self.validate(v)
 def test_static_and_counts_cannot_change(self):
  for key,new in (('static_hashes',{}),('prior_actions_preserved',87),('original_scalar_corrections_applied',11),('unchanged_driven_outputs_recomputed',3),('created_actions',[])):
   v=copy.deepcopy(self.value);v[key]=new
   with self.assertRaises(ValueError):self.validate(v)
 def test_false_execution_equivalence_flags_remain_false(self):
  for key in ('evaluated_equivalence_proved','runtime_equivalence_proved','rendered','source_byte_identity_with_approved'):
   v=copy.deepcopy(self.value);v[key]=True
   with self.assertRaises(ValueError):self.validate(v)
 def test_target_cannot_reuse_approved_or_baseline_identity(self):
  for sha in (d.BASE_SHA,d.APPROVED_SHA):
   v=copy.deepcopy(self.value);v['generated_source_sha256']=sha
   with self.assertRaises(ValueError):self.validate(v)
 def test_recipe_validation_always_called(self):
  self.validate(self.value);n.validate_recipe.assert_called_once_with(self.recipe)
if __name__=='__main__':unittest.main()

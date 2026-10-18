"""Small synthetic metadata only; real baseline values never enter fixtures."""
import ast,copy,hashlib,json,unittest
from pathlib import Path
from unittest.mock import patch
import privacy_projection as p
import onehand_v6_source_native as native

class ProjectionTests(unittest.TestCase):
 def setUp(self):
  self.base={'use_fake_user':True,'properties':{'hand_contact_status':'synthetic older text','render_status':'synthetic older render','kept_inherited':31,'baseline_action_count':1,'hidden_motion_inferred':False,'source_end_frame':2,'source_start_frame':0}}
  vals={'base_action':'synthetic-base','baseline_action_count':88,'baseline_sha256':'a'*64,'hidden_motion_inferred':True,'source_end_frame':96,'source_range_convention':'synthetic-inclusive','source_start_frame':1}
  self.meta={'schema':p.META_SCHEMA,'before_sha256':p.digest(self.base),'after_sha256':None,'properties':{k:{'before_sha256':p.digest(self.base['properties'][k]) if k in self.base['properties'] else None,'value':vals[k]} for k in p.RETAINED},'remove_properties':{k:{'before_sha256':p.digest(self.base['properties'][k]) if k in self.base['properties'] else None} for k in p.OMITTED},'use_fake_user':None}
  self.m={'original_metadata_before_sha256':p.digest(self.base),'use_fake_user_operation':None,'retained_operations':{k:{'before_sha256':v['before_sha256'],'value_sha256':p.digest(v['value']),'value_type':type(v['value']).__name__} for k,v in self.meta['properties'].items()},'omitted_operations':self.meta['remove_properties'],'metadata_recipe_sha256':p.digest(self.meta)}
  self.override=patch.object(p,'manifest',return_value=(self.m,'b'*64));self.override.start();self.addCleanup(self.override.stop)
 def test_explicit_removals_and_complete_inherited_inventory(self):
  before=copy.deepcopy(self.base);out=p.apply(self.base,self.meta)
  self.assertEqual(self.base,before);self.assertEqual(set(out['properties']),set(p.RETAINED)|{'kept_inherited'});self.assertEqual(out['properties']['kept_inherited'],31);self.assertTrue(out['use_fake_user'])
 def test_each_omission_is_required(self):
  for k in p.OMITTED:
   m=copy.deepcopy(self.meta);del m['remove_properties'][k]
   with self.assertRaises(ValueError):p.apply(self.base,m)
 def test_each_retained_operation_is_required(self):
  for k in p.RETAINED:
   m=copy.deepcopy(self.meta);del m['properties'][k]
   with self.assertRaises(ValueError):p.apply(self.base,m)
 def test_retained_value_mutation(self):
  for k in p.RETAINED:
   m=copy.deepcopy(self.meta);m['properties'][k]['value']='changed'
   with self.assertRaises(ValueError):p.apply(self.base,m)
 def test_private_review_values_rejected(self):
  for k in p.OMITTED:
   m=copy.deepcopy(self.meta);m['properties'][k]={'before_sha256':None,'value':'synthetic private comment'}
   with self.assertRaises(ValueError):p.apply(self.base,m)
 def test_removal_cannot_carry_value(self):
  m=copy.deepcopy(self.meta);m['remove_properties']['acceptance']['value']='synthetic'
  with self.assertRaises(ValueError):p.apply(self.base,m)
 def test_preconditions_cannot_change(self):
  for k in p.OMITTED:
   m=copy.deepcopy(self.meta);m['remove_properties'][k]['before_sha256']='c'*64
   with self.assertRaises(ValueError):p.apply(self.base,m)
 def test_baseline_metadata_mutation_fails(self):
  b=copy.deepcopy(self.base);b['properties']['kept_inherited']=32
  with self.assertRaises(ValueError):p.apply(b,self.meta)
 def test_fake_user_override_fails(self):
  m=copy.deepcopy(self.meta);m['use_fake_user']=False
  with self.assertRaises(ValueError):p.apply(self.base,m)
 def test_preclaimed_full_metadata_hash_fails(self):
  m=copy.deepcopy(self.meta);m['after_sha256']='a'*64
  with self.assertRaises(ValueError):p.apply(self.base,m)
 def test_unknown_metadata_fields_fail(self):
  for key in ('geometry','rest','review','drivers'):
   m=copy.deepcopy(self.meta);m[key]=[]
   with self.assertRaises(ValueError):p.apply(self.base,m)
 def test_native_target_removes_inherited_comment_keys(self):
  class Action(dict):pass
  a=Action(copy.deepcopy(self.base['properties']));a.use_fake_user=True;target=p.apply(self.base,self.meta)
  native.install_projected_metadata(a,target,{'metadata':self.meta})
  self.assertEqual(dict(a),target['properties']);self.assertEqual(a.use_fake_user,target['use_fake_user'])
 def test_bool_cannot_impersonate_integer(self):
  m=copy.deepcopy(self.meta);m['properties']['source_start_frame']['value']=True
  with self.assertRaises(ValueError):p.apply(self.base,m)

 def test_each_inherited_omitted_value_mutation_fails(self):
  for k in ('hand_contact_status','render_status'):
   b=copy.deepcopy(self.base);b['properties'][k]='changed synthetic prior value'
   with self.assertRaises(ValueError):p.apply(b,self.meta)
 def test_missing_inherited_omission_precondition_fails(self):
  for k in ('hand_contact_status','render_status'):
   b=copy.deepcopy(self.base);del b['properties'][k]
   with self.assertRaises(ValueError):p.apply(b,self.meta)
 def test_actual_inventory_dropped_or_extra_field_fails(self):
  expected=p.apply(self.base,self.meta)
  for k in expected['properties']:
   bad=copy.deepcopy(expected);del bad['properties'][k]
   with self.assertRaises(ValueError):p.verify_actual(bad,expected)
  for k in p.OMITTED:
   bad=copy.deepcopy(expected);bad['properties'][k]='synthetic'
   with self.assertRaises(ValueError):p.verify_actual(bad,expected)
 def test_actual_metadata_wrong_fake_user_fails(self):
  expected=p.apply(self.base,self.meta);bad=copy.deepcopy(expected);bad['use_fake_user']=False
  with self.assertRaises(ValueError):p.verify_actual(bad,expected)

class SourceBoundaries(unittest.TestCase):
 def test_historical_numeric_comparison_asts_unchanged(self):
  root=Path(__file__).parent;want=json.loads((root/'UNCHANGED_MATH.json').read_bytes())['historical_reference_functions_ast_sha256'];text=(root/'historical_reference.py').read_text();nodes={n.name:n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef)}
  for name,sha in want.items():self.assertEqual(hashlib.sha256(ast.dump(ast.parse(ast.get_source_segment(text,nodes[name])),include_attributes=False).encode()).hexdigest(),sha)
 def test_projected_source_cannot_claim_historical_equivalence(self):
  import run_onehand_v6_source_proof as runner
  with self.assertRaisesRegex(ValueError,'no historical'):runner.build_equivalence_result(None)
 def test_strict_json_duplicates_nonfinite(self):
  for raw in (b'{"x":1,"x":2}',b'{"x":NaN}'):
   with self.assertRaises(ValueError):p.strict(raw)
 def test_same_read_hash_parse(self):
  import tempfile
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'p';raw=b'{"x":1}';path.write_bytes(raw)
   self.assertEqual(p.pinned_json(path,hashlib.sha256(raw).hexdigest(),32),{'x':1})
   with self.assertRaises(ValueError):p.pinned_json(path,'0'*64,32)
   with self.assertRaises(ValueError):p.pinned_json(path,hashlib.sha256(raw).hexdigest(),2)
if __name__=='__main__':unittest.main()

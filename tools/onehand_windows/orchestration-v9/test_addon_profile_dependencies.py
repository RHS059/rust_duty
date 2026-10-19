"""Portable profile dependency propagation and preservation checks; no native execution."""
import hashlib,json,shutil,tempfile,unittest
from pathlib import Path
import workflow_core as w,orchestrate as o,command_contract as c,preinstall_admission as a
HERE=Path(__file__).absolute().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_bytes())
class AddonProfileDependencies(unittest.TestCase):
 def test_exact_dependency_contract_is_coherent(self):
  d=read(HERE/'DEPENDENCIES.json');r=o.reviewed_dependencies()
  self.assertEqual(d['frozen_inspected_interfaces']['native_v6'],r['native_producer_pins_sha256'])
  self.assertEqual(d['frozen_inspected_interfaces']['consumer_v7'],r['runtime_consumer_pins_sha256'])
  self.assertEqual(c.PRODUCER_SHA,r['native_producer_pins_sha256'])
  self.assertEqual(read(HERE/'controller-layout.template.json')['roots']['context_package'],'context-v3')
 def test_null_admission_cannot_claim_native_permission(self):
  v=read(HERE/'admission.template.json');self.assertEqual(a.admission_state(v),'blocked-incomplete-admission')
  self.assertTrue(all(value is None for key,value in v.items() if key!='schema'))
 def test_predecessor_acceptance_cannot_approve_successor(self):
  value={'schema':'rust-duty-onehand-workflow-independent-acceptance/v4','decision':'accepted-for-guarded-native-proof','orchestration_pins_sha256':'04b7d2a2d1f7bf913ae360f365e88877675cf13e5f56ddbd5b6ac66f19efff7f','reviewed_dependencies_sha256':'a'*64,'proof_inputs_sha256':'b'*64,'controller_layout_sha256':'c'*64,'source_transport_parts_sha256':'d'*64,'rust_source_selection_sha256':'e'*64,'source_projection_sha256':'f'*64,'metadata_recipe_sha256':'0'*64,'blocking_findings':[],'animation_proof':False}
  with self.assertRaisesRegex(ValueError,'independent acceptance identities differ'):
   a.verify_acceptance(value,sha(HERE/'PINS.json'),'a'*64,'b'*64,'c'*64)
 def test_only_declared_host_and_version_bindings_change(self):
  p=read(HERE/'PREDECESSOR_SELECTED_SOURCE.json')
  changes=read(HERE/'HOST_BINDING_SOURCE_CHANGES.json')['files']
  self.assertEqual(set(changes),set(p['allowed_host_or_version_binding_changes']))
  self.assertEqual(set(changes),{'command_contract.py','host_tools.py','orchestrate.py','prepare_controller.py','probe_blender.py','run_source_tests.py','source_checkout.py','onehand-windows-proof.yml'})
  for name,want in p['files'].items():
   lines=(HERE/name).read_text().splitlines(keepends=True)
   for hunk in reversed(changes.get(name,[])):
    start=hunk['new_start'];new=hunk['new_lines']
    self.assertEqual(lines[start:start+len(new)],new,name)
    lines[start:start+len(new)]=hunk['old_lines']
   self.assertEqual(hashlib.sha256(''.join(lines).encode()).hexdigest(),want,name)
 def test_full_native_schedule_remains_222_and_no_renderer(self):
  sequence=w.sequence();self.assertEqual(len(sequence),222)
  self.assertEqual([i for n,i in sequence if n=='block'],list(range(12)))
  for stage in ('source-chunk','chunk-import','rigid-chunk'):self.assertEqual([i for n,i in sequence if n==stage],list(range(67)))
  self.assertFalse(any('render' in name for name,index in sequence))
 def test_context_profile_inventory_is_exact_and_versioned(self):
  rows=read(HERE/'PUBLICATION_LAYOUT.json')['files'];ctx=[r for r in rows if r['repository_path'].startswith('tools/onehand_windows/context-v3/')]
  self.assertTrue(ctx);self.assertEqual(len({r['materialized_path'] for r in ctx}),len(ctx))
  names={r['source'].split('/')[-1] for r in ctx}
  self.assertIn('OFFICIAL_ADDON_PINS.json',names);self.assertIn('addon_resolver.py',names)
  self.assertFalse(any(r['materialized_path'] and r['materialized_path'].startswith('context-v2/') for r in rows))
 def test_profile_source_suites_are_isolated_and_before_installers(self):
  text=(HERE/'onehand-windows-proof.yml').read_text()
  boundary=text.index('Verify official vendor checksum and install Blender and Rust')
  for fragment in ("'native-producer-reviewed') 'test_host_identity' 27", "'test_host_identity_collection' 27", "'context-v3') 'test_windows_addon_profile' 27", "'native-producer-reviewed') 'test_dependency_selection' 5", "'runtime-consumer-reviewed') 'test_dependency_selection' 6"):
   self.assertLess(text.index(fragment),boundary)
  self.assertEqual(text.count("python -I -B -c 'import sys,unittest;"),5)
  self.assertIn('suite.countTestCases()==int(sys.argv[3])',text)
  self.assertIn('result.wasSuccessful() or bool(result.skipped)',text)
  self.assertIn("'run_source_tests.py'",text)
 def test_wrong_native_and_consumer_dependency_selections_reject(self):
  base=HERE.parent
  def locate(*names):
   return next(base/name for name in names if (base/name).is_dir())
  roots={'context_package':str(locate('windows-context-preparation-v3','context-v3')),'source_package':str(locate('source-producer','published-pr77/tools/onehand_windows/source-producer')),'native_producer':str(locate('windows-native-producer-v6','native-producer-reviewed')),'runtime_consumer':str(locate('windows-runtime-consumer-v7','runtime-consumer-reviewed')),'process_adapter':str(locate('process-v2','published-pr77/tools/onehand_windows/process-v2'))}
  for key,bad in [('native_producer_pins_sha256','69df50d663778b43c4512b81b92edd3cf9ed0e560e0779fef1587de7c7370fa2'),('runtime_consumer_pins_sha256','ce25429351c948921aefab783a9a6378c6801a0a1df1469ad8d35f3e0c2be8b4')]:
   review=o.reviewed_dependencies();review[key]=bad
   with self.subTest(key=key),self.assertRaisesRegex(ValueError,'file pin differs: PINS.json'):
    o.load_packages({'roots':roots},review)
  for role,name in [('native_producer','native_stages.py'),('runtime_consumer','consumer.py')]:
   with self.subTest(role=role),tempfile.TemporaryDirectory() as d:
    root=Path(d)/'package';shutil.copytree(roots[role],root)
    with (root/name).open('ab') as f:f.write(b'\n')
    changed=dict(roots);changed[role]=str(root)
    with self.assertRaisesRegex(ValueError,'file pin differs: '+name):o.load_packages({'roots':changed},o.reviewed_dependencies())
if __name__=='__main__':unittest.main(verbosity=2)

"""Actual isolated dependency and early parser-role wiring; source-only."""
import builtins,hashlib,json,sys,types,unittest
from pathlib import Path
from unittest.mock import patch
import orchestrate,workflow_core as w
HERE=Path(__file__).absolute().parent
class FragmentDependency(unittest.TestCase):
 def test_actual_private_package_routes_without_ambient_ast_helper(self):
  layout=w.strict_json(HERE/'controller-layout.template.json');base=HERE.parent
  config={'roots':{k:str(base/v) for k,v in layout['roots'].items()},'authored_bridge':str(base/layout['authored_bridge'])}
  real=builtins.__import__;attempts=[]
  def guarded(name,*args,**kwargs):
   if name in ('fragment_ast','host_identity'):attempts.append(name);raise AssertionError('ambient reviewed helper selected')
   return real(name,*args,**kwargs)
  with patch.dict(sys.modules,{'fragment_ast':types.ModuleType('fragment_ast'),'host_identity':types.ModuleType('host_identity')}),patch.object(builtins,'__import__',guarded):
   p=orchestrate.load_packages(config,orchestrate.reviewed_dependencies())
   ctx=types.SimpleNamespace(root=lambda _:Path(config['roots']['native_producer']),raw={'dependencies':{'producer_pins_sha256':orchestrate.reviewed_dependencies()['native_producer_pins_sha256']}})
   result=p.consumer.evidence.producer(ctx)
  self.assertEqual(attempts,[]);self.assertEqual(result.require_native_host.__module__,'_windows_runtime_host_identity')
 def test_interpreters_and_exact_exported_native_root(self):
  t=(HERE/'onehand-windows-proof.yml').read_text()
  for literal in ("python-version: '3.12.10'","python-version: '3.11.9'","update-environment: false","${{ steps.native_ast_python311.outputs.python-path }}","${{ steps.controller_python312.outputs.python-path }}","os.path.samefile(sys.executable,sys.argv[1])","$native=Join-Path (Split-Path -Parent $env:ONEHAND_SOURCE_PACKAGE) 'native-producer-reviewed'"):
   self.assertIn(literal,t)
  self.assertEqual(t.count("(Join-Path $native 'run_fragment_compatibility.py')"),2)
 def test_early_checks_precede_full_controller_tests_and_installers(self):
  t=(HERE/'onehand-windows-proof.yml').read_text()
  self.assertLess(t.index('Export exact source-only PR bytes'),t.index('Verify all frozen native fragment identities'))
  self.assertLess(t.index('Verify all frozen native fragment identities'),t.index('Run bounded Windows source tests'))
  self.assertLess(t.index('Run bounded Windows source tests'),t.index('Verify official vendor checksum and install Blender and Rust'))
  self.assertIn('$native311Exit=$LASTEXITCODE',t);self.assertIn('$native312Exit=$LASTEXITCODE',t)
  for version in ('311','312'):self.assertEqual(t.count('source-evidence/native-fragments-python'+version+'.json'),2)
 def test_exact_original_fragment_sources_and_hashes_preserved(self):
  root=HERE.parent/'native-producer-reviewed';raw=(root/'AUDITED_FRAGMENTS.json').read_bytes()
  self.assertEqual(hashlib.sha256(raw).hexdigest(),'3a2d0c7ea5fcc0dfab7ec615dbb78e0b7d9f907c1d1a48bc2f90da14933952b5')
  self.assertEqual(len(json.loads(raw)['fragments']),34)
  code=(root/'run_fragment_compatibility.py').read_text();self.assertIn('discovered == result.testsRun == 23',code);self.assertIn('len(fragments) == 34',code);self.assertIn('len(result.skipped) == 0',code)
if __name__=='__main__':unittest.main(verbosity=2)

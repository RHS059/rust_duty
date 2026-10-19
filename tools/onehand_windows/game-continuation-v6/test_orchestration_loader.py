"""Real pinned orchestration import-edge regressions; no native execution."""
import argparse,builtins,shutil,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).absolute().parent))
import continuation_core as c

ROOT=None
class OrchestrationLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).absolute()/'orchestration'
        shutil.copytree(ROOT,self.root)
    def test_actual_pinned_helper_loads_without_ambient_import(self):
        self.assertNotIn(str(self.root),sys.path)
        original=builtins.__import__
        def guarded(name,*args,**kwargs):
            if name=='failure_diagnostics':raise AssertionError('ambient diagnostics import forbidden')
            return original(name,*args,**kwargs)
        sentinel=types.ModuleType('failure_diagnostics')
        with patch.dict(sys.modules,{'failure_diagnostics':sentinel}),patch.object(builtins,'__import__',guarded):
            loaded=c.load_orchestration(self.root)
        self.assertIsNot(loaded.failure_diagnostics,sentinel)
        self.assertIs(loaded.owned_commands.failure_diagnostics,loaded.failure_diagnostics)
        self.assertIs(loaded.orchestrate.failure_diagnostics,loaded.failure_diagnostics)
        self.assertIs(loaded.failure_diagnostics.w,loaded.workflow_core)
        self.assertEqual(Path(loaded.failure_diagnostics.__file__),self.root/'failure_diagnostics.py')
    def assert_rejected_before_import(self):
        with patch.object(c,'compile',create=True) as compile_source:
            with self.assertRaises((ValueError,FileNotFoundError)):c.load_orchestration(self.root)
            compile_source.assert_not_called()
    def test_changed_helper_rejected_before_import(self):
        with (self.root/'failure_diagnostics.py').open('ab') as f:f.write(b'\n# changed\n')
        self.assert_rejected_before_import()
    def test_missing_helper_cannot_use_ambient_module(self):
        (self.root/'failure_diagnostics.py').unlink()
        with patch.dict(sys.modules,{'failure_diagnostics':types.ModuleType('failure_diagnostics')}):
            self.assert_rejected_before_import()
    def test_missing_diagnostic_source_pins_rejected_before_import(self):
        (self.root/'DIAGNOSTIC_SOURCE_PINS.json').unlink()
        self.assert_rejected_before_import()
    def test_extra_sibling_rejected_before_import(self):
        (self.root/'unreviewed_helper.py').write_bytes(b'raise AssertionError("must not execute")\n')
        self.assert_rejected_before_import()
    def test_changed_manifest_rejected_before_import(self):
        with (self.root/'PINS.json').open('ab') as f:f.write(b' ')
        self.assert_rejected_before_import()

def main():
    global ROOT
    parser=argparse.ArgumentParser();parser.add_argument('--orchestration',required=True);args=parser.parse_args()
    ROOT=Path(args.orchestration).absolute();c.verify_package(ROOT,c.ORCHESTRATION_SHA)
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(OrchestrationLoaderTests)
    if suite.countTestCases()!=6:raise ValueError('exact six loader regressions required')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    return int(not result.wasSuccessful() or bool(result.skipped) or result.testsRun!=6)
if __name__=='__main__':raise SystemExit(main())

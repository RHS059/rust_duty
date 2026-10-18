"""CPU-only exact dependency tests; no native execution or external effects."""
import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).absolute().parent))
import continuation_core as c
import preflight_game as p

class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).absolute()
    def test_only_version_nine_bootstrap_selected(self):
        self.assertEqual(p.PREFIX,'tools/onehand_windows/game-continuation-v9/')
        self.assertEqual(p.ADMISSION,'tools/onehand_windows/game-admission-v1/')
    def test_new_exact_orchestration_pin_forwarded(self):
        self.assertNotEqual(c.ORCHESTRATION_SHA,'04b7d2a2d1f7bf913ae360f365e88877675cf13e5f56ddbd5b6ac66f19efff7f')
        with patch.object(c,'verify_package',side_effect=ValueError('dependency stop')) as verify:
            with self.assertRaisesRegex(ValueError,'dependency stop'):c.load_orchestration(self.root)
        verify.assert_called_once_with(self.root,c.ORCHESTRATION_SHA)
    def test_manifest_mutation_rejected_before_import(self):
        (self.root/'PINS.json').write_bytes(b'{"workflow_core.py":"changed"}\n')
        with patch.object(c,'compile',create=True) as compile_source:
            with self.assertRaisesRegex(ValueError,'file identity differs: PINS.json'):c.load_orchestration(self.root)
            compile_source.assert_not_called()
    def test_pinned_dependency_source_mutation_rejected(self):
        source=self.root/'workflow_core.py';source.write_bytes(b'# nonexecuted synthetic fixture\n')
        manifest=self.root/'PINS.json';manifest.write_bytes(c.canonical({'workflow_core.py':c.sha(source)}))
        pin=c.sha(manifest);c.verify_package(self.root,pin)
        source.write_bytes(b'# changed\n')
        with self.assertRaisesRegex(ValueError,'file identity differs: workflow_core.py'):c.verify_package(self.root,pin)
    def test_unlisted_dependency_source_rejected(self):
        source=self.root/'workflow_core.py';source.write_bytes(b'# nonexecuted\n')
        manifest=self.root/'PINS.json';manifest.write_bytes(c.canonical({'workflow_core.py':c.sha(source)}))
        pin=c.sha(manifest);(self.root/'unexpected.py').write_bytes(b'# extra\n')
        with self.assertRaisesRegex(ValueError,'unexpected/missing package file'):c.verify_package(self.root,pin)
if __name__=='__main__':unittest.main(verbosity=2)

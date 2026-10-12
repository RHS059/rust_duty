"""Guard the explicitly executed resident native contract, not a hardware speed claim."""
from pathlib import Path
import unittest
import yaml
ROOT = Path(__file__).resolve().parents[1]
class WorkflowTests(unittest.TestCase):
    def test_bounded_native_execution_and_retention(self):
        text = (ROOT / '.github/workflows/resident-mesh-contract.yml').read_text()
        value = yaml.safe_load(text)
        job = value['jobs']['native-resident-mesh']
        self.assertEqual(job['runs-on'], 'windows-latest')
        self.assertEqual(job['timeout-minutes'], 30)
        self.assertEqual(value['permissions'], {'contents': 'read'})
        self.assertFalse(value['concurrency']['cancel-in-progress'])
        self.assertEqual(value['env']['PYTHONDONTWRITEBYTECODE'], '1')
        self.assertEqual(value['env']['RUSTUP_TOOLCHAIN'], '1.99.0')
        commands='\n'.join(s.get('run','') for s in job['steps'])
        self.assertIn('--exact --ignored --nocapture --test-threads=1', commands)
        self.assertIn("Select-String -Path resident-mesh-evidence/native-tests.txt -SimpleMatch -Pattern 'test result: ok. 1 passed; 0 failed; 0 ignored;'", commands)
        self.assertNotIn('Select-String resident-mesh-evidence', commands)
        self.assertIn("Select-String -Path resident-mesh-evidence/rustc.txt -Pattern '^release: 1\\.99\\.0$'", commands)
        self.assertIn('Native source changed', commands)
        self.assertIn('Native executable changed', commands)
        self.assertIn('assets/weapons', commands)
        self.assertIn('run_renderer_contract.py',commands)
        self.assertIn('run_renderer_contract.py --executable $exe --root .', commands)
        self.assertIn('$control.executable_sha256 -ne $before', commands)
        self.assertIn('Control executable changed', commands)
        self.assertIn('test_renderer_contract test_dx12_contract_process', commands)
        self.assertIn('control-outputs.zip',commands)
        self.assertIn('Env:VR_WEAPON_ASSET', commands)
        steps=job['steps']
        install=next(i for i,s in enumerate(steps) if 'pip install' in s.get('run',''))
        guards=next(i for i,s in enumerate(steps) if '-m unittest' in s.get('run',''))
        self.assertLess(install,guards)
        self.assertTrue(any(s.get('uses')=='dtolnay/rust-toolchain@1.99.0' for s in steps))
        artifact=steps[-1]
        self.assertEqual(artifact['if'],'always()')
        self.assertEqual(artifact['with']['path'],'resident-mesh-evidence/**')
    def test_actual_native_test_keeps_waits_after_the_changing_frames(self):
        source=(ROOT/'src/render/resident_tests.rs').read_text()
        self.assertIn('for step in 0..12',source)
        self.assertIn('result.resident.draws, 2',source)
        self.assertIn('renderer.submit(&captures)',source)
        self.assertIn('54',source)
        self.assertIn('disable_retention_for_test',source)
        self.assertIn('DeviceType::DiscreteGpu',source)
        self.assertIn('max_channel_delta',source)
if __name__ == '__main__': unittest.main()

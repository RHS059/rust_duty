"""Portable parser/clock/capture checks, independent of shipped asset approval."""
import importlib.util
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import struct
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
import run_high_mantle_inputs as platform_runner
import run_high_mantle_deterministic as replay_runner
from verify_high_mantle_observer import EvidenceError


class RevisionContractTests(unittest.TestCase):
    def test_source_preserves_native_runtime_timestamp_contract(self):
        text = (ROOT/'src/authored_high_mantle.rs').read_text()
        self.assertIn('pub const SUBDIVISIONS: usize = 256;', text)
        self.assertIn('pub const SAMPLE_HZ: usize = 60 * SUBDIVISIONS;', text)
        self.assertIn('pub const SAMPLE_COUNT: usize = 95 * SUBDIVISIONS + 1;', text)
        self.assertIn('t.to_bits() == ((i as f64 / SAMPLE_HZ as f64) as f32).to_bits()', text)
        self.assertIn('native64_payload_and_receipt_cannot_be_relabeled_as_native256', text)
        self.assertNotIn('/ 3840.', text)

    def test_grid_preserves_native_duration_and_float32_order(self):
        hz, count = 60*256, 95*256+1
        samples = [struct.unpack('<f', struct.pack('<f', i/hz))[0] for i in range(count)]
        self.assertEqual((hz, count), (15360, 24321))
        self.assertTrue(all(a < b for a,b in zip(samples, samples[1:])))
        self.assertEqual(samples[-1], struct.unpack('<f', struct.pack('<f', 95/60))[0])
        self.assertEqual((count-1)/hz, 95/60)

    def test_legacy_and_return_regression_tests_remain_present(self):
        text = (ROOT/'src/authored_high_mantle.rs').read_text()
        for contract in ('(0.6, false, 72, 0.6)', '(0.6, true, 72, 0.6)',
                         '(1.8, false, 102, 0.85)', '(1.8, true, 190, NATIVE_SECONDS as f32)',
                         'p.outgoing.unwrap().duration, 0.2', 'for enabled in [false, true]',
                         's.timings.get(ActionSlot::PullUp).duration'):
            self.assertIn(contract, text)

    def test_platform_invocation_handles_both_path_syntaxes(self):
        for root in (PurePosixPath('/root'), PureWindowsPath('C:/root')):
            with self.subTest(path_type=type(root).__name__):
                command = platform_runner.invocation(root/'app', root/'manifest', root/'out', 'a'*64)
                self.assertEqual(command[0], str(root/'app'))
                self.assertIn('--animation-manifest='+str(root/'manifest'), command)
                self.assertIn('--onehand-observer='+str(root/'out'), command)
                self.assertFalse(any(arg.startswith('--capture') for arg in command))

    def test_windows_source_import_never_requires_unix_resource_module(self):
        spec = importlib.util.spec_from_file_location('_high_mantle_no_resource',
                                                     ROOT/'tools/run_high_mantle_inputs.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'resource': None}):
            spec.loader.exec_module(module)
        self.assertIsNone(module.resource)
        self.assertIn('--no-update', module.invocation('/app', '/manifest', '/out', 'a'*64))
        with self.assertRaisesRegex(EvidenceError, 'requires Linux'):
            module.require_native_platform()

    def test_native_execution_is_explicitly_linux_only(self):
        with patch.object(platform_runner.sys, 'platform', 'win32'):
            with self.assertRaisesRegex(EvidenceError, 'requires Linux'):
                platform_runner.require_native_platform()
        self.assertIs(replay_runner.require_native_platform, platform_runner.require_native_platform)
        for name in ('run_high_mantle_inputs.py', 'run_high_mantle_deterministic.py'):
            text = (ROOT/'tools'/name).read_text()
            self.assertLess(text.index('require_native_platform()\n    from platform_x11_input'),
                            text.index("output.mkdir(mode=0o700)"))

    def test_capture_cannot_configure_or_mutate_runtime_admission(self):
        # Shipped exports can change independently of this read-only observer.
        text = (ROOT/'src/high_mantle_capture.rs').read_text()
        self.assertNotIn('set_high_mantle_binding(', text)
        self.assertNotIn('APPROVED_RUNTIME_PINS', text)
        self.assertIn('sim: &Simulation', text)
        self.assertNotIn('&mut Simulation', text)


if __name__ == '__main__':
    unittest.main()

"""CPU-only Windows path/locale/newline regressions; no native evidence."""
from contextlib import contextmanager
import hashlib
import io
from pathlib import Path, PureWindowsPath
import tempfile
import unittest
from unittest.mock import patch

import test_app_edge_startup as startup
import test_app_edges as edges
from test_app_edge_receipts import ReceiptFixture
import verify_app_edges as verifier


@contextmanager
def windows_relative_paths():
    """Project real local paths through Windows relative-path serialization."""
    original = Path.relative_to

    def relative(path, *other, **kwargs):
        return PureWindowsPath(*original(path, *other, **kwargs).parts)

    with patch.object(Path, 'relative_to', relative):
        yield


@contextmanager
def windows_text_reads(crlf=False, mutation=None):
    """Emulate a cp1252 default and normal universal-newline text reads.

    Only text reads are emulated. Raw source/receipt pins still read exact bytes.
    The optional CRLF stream exercises text decoding, not acceptance of altered
    raw byte-pinned source files.
    """
    def read_text(path, encoding=None, errors=None):
        raw = path.read_bytes()
        if crlf and path.suffix == '.rs':
            raw = raw.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        with io.TextIOWrapper(io.BytesIO(raw), encoding=encoding or 'cp1252',
                                errors=errors) as stream:
            text = stream.read()
        return mutation(path, text) if mutation else text

    with patch.object(Path, 'read_text', read_text):
        yield


class WindowsPortabilityTests(unittest.TestCase):
    def test_source_receipt_accepts_windows_paths_without_changing_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = ReceiptFixture(Path(directory))
            expected = fixture.config['source_fingerprint']
            with windows_relative_paths():
                config, *_ = fixture.verify()
            self.assertEqual(config['source_fingerprint'], expected)
            self.assertEqual(config['source_files'][0]['path'], 'source/example.rs')

    def test_windows_source_inventory_still_rejects_extra_files_and_changed_bytes(self):
        for change, reason in ((lambda f: f.file('source/extra.rs', '// Extra.\n'),
                                'source inventory omits/adds actual files'),
                               (lambda f: (f.root / 'source/example.rs').write_bytes(b'changed'),
                                'pinned bytes changed')):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                fixture = ReceiptFixture(Path(directory))
                change(fixture)
                with windows_relative_paths(), self.assertRaisesRegex(verifier.Rejected, reason):
                    fixture.verify()

    def test_native_output_inventory_accepts_windows_paths_and_rejects_extras(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = ['run.json', 'pause/observer.jsonl', 'pause/stdout.log',
                     'pause/stderr.log', 'pause/0000.png', 'pause/0000.png.json']
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'CPU inventory placeholder; not native output.\n')
            expected = sum((root / name).stat().st_size for name in names)
            with windows_relative_paths():
                self.assertEqual(verifier.native_output_inventory(root, {'pause': 1},
                                                                   'run.json', 4096), expected)
                for extra, is_directory in (('pause/extra.txt', False), ('pause/extra-dir', True)):
                    path = root / extra
                    path.mkdir() if is_directory else path.write_bytes(b'extra')
                    with self.assertRaisesRegex(verifier.Rejected, 'native output inventory'):
                        verifier.native_output_inventory(root, {'pause': 1}, 'run.json', 4096)
                    path.rmdir() if is_directory else path.unlink()
                with self.assertRaisesRegex(verifier.Rejected, 'complete native output exceeds'):
                    verifier.native_output_inventory(root, {'pause': 1}, 'run.json', expected - 1)

    def test_startup_callsite_inventory_uses_portable_windows_names(self):
        with windows_relative_paths():
            startup.StartupSourceTests('test_complete_production_choose_callsite_inventory').test_complete_production_choose_callsite_inventory()

    def test_literal_source_hashes_hold_under_cp1252_default_and_crlf_text_streams(self):
        edges.SourceTests.setUpClass()
        cases = ((startup.StartupSourceTests, 'test_only_call_argument_and_menu_policy_changed'),
                 (edges.SourceTests, 'test_capture_flags_remain_rejected_and_direct_delivery_composition_is_exact'))
        for crlf in (False, True):
            for case, method in cases:
                with self.subTest(crlf=crlf, method=method), windows_text_reads(crlf=crlf):
                    getattr(case(method), method)()

    def test_reverse_source_contracts_still_reject_real_text_mutations(self):
        edges.SourceTests.setUpClass()
        for name, case, method in (
            ('level_menu.rs', startup.StartupSourceTests, 'test_only_call_argument_and_menu_policy_changed'),
            ('sim.rs', edges.SourceTests, 'test_capture_flags_remain_rejected_and_direct_delivery_composition_is_exact'),
        ):
            def mutation(path, text):
                return text + '// Unreviewed source change.\n' if path.name == name else text
            with self.subTest(name=name), windows_text_reads(crlf=True, mutation=mutation):
                with self.assertRaises(AssertionError):
                    getattr(case(method), method)()

    def test_crlf_bytes_do_not_bypass_exact_file_pins_or_backslash_path_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'source.rs'
            path.write_bytes(b'// Exact UTF-8 source.\n')
            pin = dict(path='source.rs', bytes=path.stat().st_size, sha256=verifier.sha(path))
            path.write_bytes(b'// Exact UTF-8 source.\r\n')
            with self.assertRaisesRegex(verifier.Rejected, 'pinned bytes changed'):
                verifier.ref(root, pin)
            with self.assertRaisesRegex(verifier.Rejected, 'relative path required'):
                verifier.path(root, r'source\example.rs')

    def test_cp1252_reproduces_both_exact_windows_ci_hashes(self):
        menu = (startup.NEW / 'src/level_menu.rs').read_bytes().decode('cp1252')
        menu = menu.replace(startup.SIGNATURE, '').replace(startup.NEW_DECISION, startup.OLD_DECISION)
        sim = (startup.NEW / 'src/sim.rs').read_bytes().decode('cp1252')
        begin = sim.index('    /// The admitted pair identity, never raw unvalidated manifest fields.')
        end = sim.index('    pub fn prone_sample(', begin)
        sim = (sim[:begin] + sim[end:]).replace('        crate::combined_observer::accepted(self);\n', '')
        self.assertEqual(hashlib.sha256(menu.encode('utf-8')).hexdigest(),
                         '38dac69c61f6038981898534f253b61f0b5e130135e1aa8c60f2e893b4e82e68')
        self.assertEqual(hashlib.sha256(sim.encode('utf-8')).hexdigest(),
                         'f8d2ff0efb344af2508da9085f43f5e8c652510eca82d52612920ec40d7b5866')


if __name__ == '__main__':
    unittest.main(verbosity=2)

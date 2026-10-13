"""Exact new source inventory without relabeling historical timing evidence."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

import performance_matrix as matrix
from historical_source_test_fixture import skin_stage_sources

ROOT = Path(__file__).resolve().parents[1]
OLD_CANDIDATE = '9b7ae93be3a4d4aed9b662d0c27ff18d0b1e12e99c4dc916422c98e0c5eae3c6'
OLD_BASELINE = 'dbabe2822dd73410a7f05c0f03807aa80d5720351c4a9c13ebdee1276fecc195'


def commit(root):
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=Synthetic Test',
                    '-c', 'user.email=synthetic@example.invalid', 'commit', '-qm', 'Synthetic source fixture'],
                   check=True, capture_output=True)


class CpuEncodeDetailSourceTests(unittest.TestCase):
    def historical_files(self):
        # Original committed source bytes, never an allowlist patched to admit
        # today's checkout. The fixture also works with shallow CI history.
        files = skin_stage_sources()
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
        self.assertEqual(matrix.canonical_hash(hashes), matrix.AUDITED_SKIN_STAGE_CANDIDATE_MANIFEST)
        return files

    def checkout(self, *, current=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(root), 'config', 'core.autocrlf', 'false'],
                       check=True, capture_output=True)
        files = ({name: (ROOT / name).read_bytes() for name in matrix.ARITHMETIC_SOURCE_PATHS}
                 if current else self.historical_files())
        for name, data in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        commit(root)
        return root

    def test_historical_detail_inventory_keeps_its_exact_digest(self):
        hashes = {name: hashlib.sha256(data).hexdigest()
                  for name, data in self.historical_files().items()}
        self.assertEqual(len(hashes), len(matrix.ARITHMETIC_SOURCE_PATHS))
        self.assertEqual(matrix.AUDITED_SKIN_STAGE_CANDIDATE_MANIFEST,
                         'b531276d331ff2addea10aec89eea7eb743cbab89858709194cdc8286fc32a96')
        self.assertEqual(matrix.canonical_hash(hashes), matrix.AUDITED_SKIN_STAGE_CANDIDATE_MANIFEST)
        self.assertEqual(matrix.audited_inventory(matrix.AUDITED_SKIN_STAGE_CANDIDATE_MANIFEST),
                         matrix.ARITHMETIC_SOURCE_PATHS)
        self.assertIn('src/frame_encode_detail.rs', hashes)
        self.assertIn('src/render/arena.rs', hashes)
        self.assertIn('Cargo.toml', hashes)
        self.assertIn('Cargo.lock', hashes)
        self.assertIn('src/frame_upload_policy.rs', hashes)
        self.assertIn('src/render/upload_cache.rs', hashes)

    def test_current_source_cannot_inherit_or_export_historical_admission(self):
        root = self.checkout(current=True)
        hashes = {name: matrix.sha256(root / name) for name in matrix.ARITHMETIC_SOURCE_PATHS}
        self.assertNotEqual(matrix.canonical_hash(hashes), matrix.AUDITED_SKIN_STAGE_CANDIDATE_MANIFEST)
        self.assertIsNone(matrix.audited_inventory(matrix.canonical_hash(hashes)))
        with self.assertRaisesRegex(ValueError, 'Arithmetic source changed; cannot fall back'):
            matrix.source_identity(root)
        output = root / 'witness'
        with self.assertRaisesRegex(ValueError, 'Arithmetic source changed; cannot fall back'):
            matrix.export_witness(root, output)
        self.assertFalse(output.exists())

    def test_historical_pins_and_paired_matrix_scope_stay_exact(self):
        self.assertEqual(matrix.AUDITED_GPU_CANDIDATE_MANIFEST, OLD_CANDIDATE)
        self.assertEqual(matrix.AUDITED_GPU_CPU_BASELINE_MANIFEST, OLD_BASELINE)
        for digest in (OLD_CANDIDATE, OLD_BASELINE):
            self.assertEqual(matrix.audited_inventory(digest), matrix.GPU_CANDIDATE_SOURCE_PATHS)
        self.assertEqual(matrix.AUDITED_ENCODE_DETAIL_INITIAL_MANIFEST,
                         'bd33a722405c3ec0073ebd28dc390c7cddffcf84ab48b2ba1833d9b97ed862e4')
        self.assertEqual(matrix.audited_inventory(matrix.AUDITED_ENCODE_DETAIL_INITIAL_MANIFEST),
                         matrix.ENCODE_DETAIL_SOURCE_PATHS)
        self.assertEqual(matrix.AUDITED_ENCODE_DETAIL_FORMATTED_MANIFEST,
                         '480e05173ad3ad42879fc1620e01fd4e9035148fadebbb2acb5b1b0cc21c8bf7')
        self.assertEqual(matrix.audited_inventory(matrix.AUDITED_ENCODE_DETAIL_FORMATTED_MANIFEST),
                         matrix.ENCODE_DETAIL_SOURCE_PATHS)
        source = matrix.source_identity(self.checkout())
        with self.assertRaisesRegex(ValueError, 'exact reviewed DX12'):
            matrix.make_plan(source, gpu_timestamps=True)

    def test_initial_reuse_artifact_pins_remain_replayable(self):
        self.assertEqual(matrix.AUDITED_UPLOAD_REUSE_INITIAL_MANIFEST,
                         '30034419d16eaf4cfa336e5bde862dd660a54ff3736dbc30cfd1f47b0d896460')
        self.assertEqual(matrix.AUDITED_UPLOAD_IMMUTABLE_INITIAL_CONTROL_MANIFEST,
                         'dd7325d511b76829660abe3cd8d0bb4a5c17ae970a68025d888eafe8e74fcfcc')
        for pin in (matrix.AUDITED_UPLOAD_REUSE_INITIAL_MANIFEST,
                    matrix.AUDITED_UPLOAD_IMMUTABLE_INITIAL_CONTROL_MANIFEST):
            self.assertEqual(matrix.audited_inventory(pin), matrix.UPLOAD_REUSE_SOURCE_PATHS)

    def test_new_serializer_cannot_adopt_historical_immutable_control(self):
        root = self.checkout()
        policy = root / 'src/frame_upload_policy.rs'
        original = policy.read_bytes()
        self.assertEqual(original.count(b'REUSE_ENABLED: bool = true;'), 1)
        policy.write_bytes(original.replace(b'REUSE_ENABLED: bool = true;', b'REUSE_ENABLED: bool = false;'))
        commit(root)
        # The new serializer has only its explicitly reviewed reuse-on class.
        # A two-change combination must not inherit the old immutable witness.
        with self.assertRaisesRegex(ValueError, 'cannot fall back'):
            matrix.source_identity(root)
        self.assertEqual(matrix.AUDITED_UPLOAD_REUSE_MANIFEST,
                         '2dbfe6bbab145c675e2517eee8c2ec2476e467e32ec66b8c8938c05d55434493')
        self.assertEqual(matrix.AUDITED_UPLOAD_IMMUTABLE_CONTROL_MANIFEST,
                         'd80012eb4d1d4a5e669b98aae8910fc24302f1fc38bd92ed8a3593a0fae70dd7')
        for pin in (matrix.AUDITED_UPLOAD_REUSE_MANIFEST,
                    matrix.AUDITED_UPLOAD_IMMUTABLE_CONTROL_MANIFEST):
            self.assertEqual(matrix.audited_inventory(pin), matrix.UPLOAD_REUSE_SOURCE_PATHS)

    def test_reuse_inventory_cannot_drop_policy_or_cache(self):
        for name in ('src/frame_upload_policy.rs', 'src/render/upload_cache.rs'):
            with self.subTest(name=name):
                root = self.checkout()
                (root / name).unlink()
                commit(root)
                with self.assertRaisesRegex(ValueError, 'inventory is missing'):
                    matrix.source_identity(root)

    def test_committed_historical_source_witness_roundtrip(self):
        root = self.checkout()
        source = matrix.source_identity(root)
        output = root / 'witness'
        matrix.export_witness(root, output)
        restored = matrix.artifact_source(output, matrix.sha256(output / 'SOURCE_WITNESS.json'))
        self.assertEqual(restored, source)

    def test_dirty_or_committed_unreviewed_detail_cannot_fall_back(self):
        root = self.checkout()
        path = root / 'src/frame_encode_detail.rs'
        path.write_bytes(path.read_bytes() + b'\n// Synthetic unreviewed change.\n')
        with self.assertRaisesRegex(ValueError, 'Uncommitted arithmetic source'):
            matrix.source_identity(root)
        commit(root)
        with self.assertRaisesRegex(ValueError, 'cannot fall back'):
            matrix.source_identity(root)

    def test_missing_new_module_does_not_adopt_historical_source_pin(self):
        root = self.checkout()
        (root / 'src/frame_encode_detail.rs').unlink()
        commit(root)
        with self.assertRaisesRegex(ValueError, 'cannot fall back'):
            matrix.source_identity(root)


if __name__ == '__main__':
    unittest.main()

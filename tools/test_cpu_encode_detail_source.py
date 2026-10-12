"""Exact new source inventory without relabeling historical timing evidence."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

import performance_matrix as matrix

ROOT = Path(__file__).resolve().parents[1]
OLD_CANDIDATE = '9b7ae93be3a4d4aed9b662d0c27ff18d0b1e12e99c4dc916422c98e0c5eae3c6'
OLD_BASELINE = 'dbabe2822dd73410a7f05c0f03807aa80d5720351c4a9c13ebdee1276fecc195'


def commit(root):
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=Synthetic Test',
                    '-c', 'user.email=synthetic@example.invalid', 'commit', '-qm', 'Synthetic source fixture'],
                   check=True, capture_output=True)


class CpuEncodeDetailSourceTests(unittest.TestCase):
    def checkout(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(root), 'config', 'core.autocrlf', 'false'],
                       check=True, capture_output=True)
        for name in matrix.UPLOAD_REUSE_SOURCE_PATHS:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / name).read_bytes())
        commit(root)
        return root

    def test_current_detail_inventory_has_its_own_exact_digest(self):
        hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                  for name in matrix.UPLOAD_REUSE_SOURCE_PATHS}
        self.assertEqual(len(hashes), len(matrix.UPLOAD_REUSE_SOURCE_PATHS))
        self.assertEqual(matrix.canonical_hash(hashes), matrix.AUDITED_UPLOAD_REUSE_MANIFEST)
        self.assertEqual(matrix.audited_inventory(matrix.AUDITED_UPLOAD_REUSE_MANIFEST),
                         matrix.UPLOAD_REUSE_SOURCE_PATHS)
        self.assertIn('src/frame_encode_detail.rs', hashes)
        self.assertIn('src/render/arena.rs', hashes)
        self.assertIn('Cargo.toml', hashes)
        self.assertIn('Cargo.lock', hashes)
        self.assertIn('src/frame_upload_policy.rs', hashes)
        self.assertIn('src/render/upload_cache.rs', hashes)

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

    def test_one_line_immutable_control_keeps_all_other_inventory_bytes(self):
        root = self.checkout()
        before = matrix.source_identity(root)
        policy = root / 'src/frame_upload_policy.rs'
        original = policy.read_bytes()
        self.assertEqual(original.count(b'REUSE_ENABLED: bool = true;'), 1)
        policy.write_bytes(original.replace(b'REUSE_ENABLED: bool = true;', b'REUSE_ENABLED: bool = false;'))
        commit(root)
        after = matrix.source_identity(root)
        self.assertEqual(matrix.canonical_hash(after['runtime_files_sha256']),
                         matrix.AUDITED_UPLOAD_IMMUTABLE_CONTROL_MANIFEST)
        changed = [name for name in before['runtime_files_sha256']
                   if before['runtime_files_sha256'][name] != after['runtime_files_sha256'][name]]
        self.assertEqual(changed, ['src/frame_upload_policy.rs'])

    def test_reuse_inventory_cannot_drop_policy_or_cache(self):
        for name in ('src/frame_upload_policy.rs', 'src/render/upload_cache.rs'):
            with self.subTest(name=name):
                root = self.checkout()
                (root / name).unlink()
                commit(root)
                with self.assertRaisesRegex(ValueError, 'upload-reuse inventory is missing'):
                    matrix.source_identity(root)

    def test_committed_current_source_witness_roundtrip(self):
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
        with self.assertRaisesRegex(ValueError, 'Uncommitted encode-detail'):
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

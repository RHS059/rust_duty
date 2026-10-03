import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from restore_movement_reference import restore


class RestoreReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.parts = [b'first exact bytes\x00', b'\xffsecond exact bytes']
        self.rows = []
        for index, data in enumerate(self.parts):
            name = f'part-{index:03}.bin'
            (self.base / name).write_bytes(data)
            self.rows.append({'path': name, 'bytes': len(data),
                              'sha256': hashlib.sha256(data).hexdigest()})
        complete = b''.join(self.parts)
        self.manifest = {'schema': 'rust-duty-reference-binary-parts/v1',
                         'output': 'reference.mp4', 'bytes': len(complete),
                         'sha256': hashlib.sha256(complete).hexdigest(),
                         'parts': self.rows}
        self.manifest_path = self.base / 'manifest.json'
        self.save_manifest()

    def save_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest))

    def run_restore(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return restore(self.manifest_path)

    def test_exact_reassembly_and_repeat_verification(self):
        output = self.run_restore()
        self.assertEqual(output.read_bytes(), b''.join(self.parts))
        self.assertEqual(self.run_restore(), output)

    def test_corrupt_part_rejected_without_final_or_partial(self):
        (self.base / self.rows[0]['path']).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'Part size/hash mismatch'):
            self.run_restore()
        self.assertFalse((self.base / 'reference.mp4').exists())
        self.assertEqual(list(self.base.glob('*.partial')), [])

    def test_wrong_full_hash_rejected(self):
        self.manifest['sha256'] = '0' * 64
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'Full reference size/hash mismatch'):
            self.run_restore()
        self.assertFalse((self.base / 'reference.mp4').exists())

    def test_existing_different_output_never_overwritten(self):
        output = self.base / 'reference.mp4'
        output.write_bytes(b'keep me')
        with self.assertRaises(FileExistsError):
            self.run_restore()
        self.assertEqual(output.read_bytes(), b'keep me')

    def test_path_escape_rejected(self):
        self.manifest['parts'][0]['path'] = '../outside.bin'
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'escapes reference directory'):
            self.run_restore()
        self.assertFalse((self.base / 'reference.mp4').exists())


if __name__ == '__main__':
    unittest.main()

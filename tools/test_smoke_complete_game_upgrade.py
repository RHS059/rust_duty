"""Guard against false-success full-download and managed-asset smoke reports."""
import json
from pathlib import Path
import tempfile
import unittest

import release_update
from smoke_complete_game_upgrade import REQUIRED_ASSETS, bundle_records, verify_version_root


class CompleteUpgradeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.version = self.root / "versions/5-0.1.5"
        self.version.mkdir(parents=True)
        self.source = self.root / "source"
        self.source.mkdir()
        for relative in ["vector-range", *REQUIRED_ASSETS]:
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(relative.encode())
        payload = self.version / "payload.rdb"
        release_update.pack(self.source, payload, "vector-range")
        import shutil
        shutil.copytree(self.source, self.version, dirs_exist_ok=True)
        self.manifest = dict(version="0.1.5", sequence=5, entrypoint="vector-range",
                             bundle=release_update.asset(payload))
        active = dict(version="0.1.5", sequence=5, entrypoint="vector-range",
                      bundle_sha256=self.manifest["bundle"]["sha256"])
        (self.root / "install.json").write_text(json.dumps(dict(
            active=active, highest_sequence=5, pending_launch=False)))

    def test_exact_complete_runtime_passes(self):
        directory, records, state = verify_version_root(self.root, self.manifest)
        self.assertEqual(directory, self.version)
        self.assertEqual(len(records), 1 + len(REQUIRED_ASSETS))
        self.assertEqual(state['active']['version'], '0.1.5')

    def test_missing_and_mutated_runtime_fail(self):
        path = self.version / "assets/animations.cfg"
        path.write_bytes(b"mutated")
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            verify_version_root(self.root, self.manifest)
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'regular file'):
            verify_version_root(self.root, self.manifest)

    def test_bundle_change_fails_integrity(self):
        with (self.version / 'payload.rdb').open('ab') as stream:
            stream.write(b'trailing')
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            verify_version_root(self.root, self.manifest)
        with self.assertRaisesRegex(ValueError, 'trailing'):
            bundle_records(self.version / 'payload.rdb')

    def test_code_only_bundle_is_not_complete(self):
        import shutil
        shutil.rmtree(self.source / 'assets')
        release_update.pack(self.source, self.version / 'payload.rdb', 'vector-range')
        self.manifest['bundle'] = release_update.asset(self.version / 'payload.rdb')
        state = json.loads((self.root / 'install.json').read_text())
        state['active']['bundle_sha256'] = self.manifest['bundle']['sha256']
        (self.root / 'install.json').write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, 'complete bundle lacks'):
            verify_version_root(self.root, self.manifest)

    def test_wrong_activated_version_is_not_success(self):
        state = json.loads((self.root / 'install.json').read_text())
        state['active']['version'] = '0.1.4'
        (self.root / 'install.json').write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, 'version mismatch'):
            verify_version_root(self.root, self.manifest)


if __name__ == '__main__':
    unittest.main()

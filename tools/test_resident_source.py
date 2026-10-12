"""Exact current resident inventory and one-line counterfactual admission."""
import tempfile
from pathlib import Path
import subprocess
import unittest
import performance_matrix as matrix
ROOT=Path(__file__).resolve().parents[1]
def git(root,*args): return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True)
def commit(root):
    git(root,'add','.')
    git(root,'-c','user.name=Synthetic Test','-c','user.email=test@example.invalid','commit','-qm','Synthetic source')
class SourceTests(unittest.TestCase):
    def checkout(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        git(root,'init','-q');git(root,'config','core.autocrlf','false')
        for name in matrix.RESIDENT_SOURCE_PATHS:
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/name).read_bytes())
        commit(root);return root
    def test_exact_candidate_and_control_witnesses(self):
        root=self.checkout()
        source=matrix.source_identity(root)
        self.assertEqual(len(source['runtime_files_sha256']),43)
        self.assertEqual(matrix.canonical_hash(source['runtime_files_sha256']),matrix.AUDITED_RESIDENT_CANDIDATE_MANIFEST)
        matrix.export_witness(root,root/'candidate-witness')
        self.assertEqual(matrix.artifact_source(root/'candidate-witness',matrix.sha256(root/'candidate-witness/SOURCE_WITNESS.json')),source)
        path=root/'src/frame_resident_policy.rs';raw=path.read_bytes()
        self.assertEqual(raw.count(b'ENABLED: bool = true;'),1)
        path.write_bytes(raw.replace(b'ENABLED: bool = true;',b'ENABLED: bool = false;'));commit(root)
        control=matrix.source_identity(root)
        self.assertEqual(matrix.canonical_hash(control['runtime_files_sha256']),matrix.AUDITED_RESIDENT_CONTROL_MANIFEST)
        self.assertEqual({n for n in source['runtime_files_sha256'] if source['runtime_files_sha256'][n]!=control['runtime_files_sha256'][n]},{'src/frame_resident_policy.rs'})
    def test_new_or_previously_unbound_files_never_use_narrow_fallback(self):
        for name in matrix.RESIDENT_SOURCE_PATHS[len(matrix.LOADER_SOURCE_PATHS):]:
            with self.subTest(name=name):
                root=self.checkout();path=root/name;raw=path.read_bytes();path.write_bytes(raw+b'\n// Unreviewed mutation\n')
                with self.assertRaisesRegex(ValueError,'Uncommitted resident source'):matrix.source_identity(root)
                commit(root)
                with self.assertRaisesRegex(ValueError,'cannot fall back'):matrix.source_identity(root)
    def test_missing_module_and_changed_old_runtime_are_rejected(self):
        for name in ('src/render/resident.wgsl','src/render/frame.rs','src/authored_viewmodel.rs'):
            with self.subTest(name=name):
                root=self.checkout();(root/name).unlink();commit(root)
                with self.assertRaisesRegex(ValueError,'cannot fall back'):matrix.source_identity(root)
    def test_historical_loader_and_renderer_classes_keep_their_pins(self):
        self.assertEqual(matrix.AUDITED_AUTHORED_DEDUP_MANIFEST,'fff66052fe41e445d50eaf2ae689a29cc68b7d3c3d4502d21d147424c60d3e06')
        self.assertEqual(matrix.audited_inventory(matrix.AUDITED_AUTHORED_DEDUP_MANIFEST),matrix.LOADER_SOURCE_PATHS)
        self.assertEqual(matrix.audited_inventory(matrix.AUDITED_ARENA_SERIALIZATION_MANIFEST),matrix.UPLOAD_REUSE_SOURCE_PATHS)
class HistoricalResidentGuardTests(unittest.TestCase):
    import test_performance_matrix as protocol
    setUp=protocol.SourceWitnessTests.setUp
    tearDown=protocol.SourceWitnessTests.tearDown
    def test_facade_and_legacy_cannot_hide_behind_narrow_witness(self):
        original_source=matrix.source_identity(self.repository)
        for name in matrix.RESIDENT_BASELINE:
            path=self.repository/name;original=path.read_bytes()
            path.write_bytes(original+b'// Changed facade or legacy support\n')
            with self.subTest(name=name,state='dirty'),self.assertRaisesRegex(ValueError,'Uncommitted resident support'):matrix.source_identity(self.repository)
            commit(self.repository)
            with self.subTest(name=name,state='committed'),self.assertRaisesRegex(ValueError,'cannot fall back'):matrix.source_identity(self.repository)
            path.write_bytes(original);commit(self.repository)
            path.unlink()
            with self.subTest(name=name,state='missing'),self.assertRaisesRegex(ValueError,'Missing/unsafe historical resident support'):matrix.source_identity(self.repository)
            path.write_bytes(original)
        self.assertEqual(matrix.source_identity(self.repository)['runtime_files_sha256'],original_source['runtime_files_sha256'])
        self.assertEqual(matrix.artifact_source(self.witness,self.digest)['runtime_files_sha256'],original_source['runtime_files_sha256'])

if __name__=='__main__':unittest.main()

"""Exact combined resident/staging inventory, control and historical admission."""
import tempfile
from pathlib import Path
import subprocess
import unittest
import hashlib
import performance_matrix as matrix
from historical_source_test_fixture import skin_stage_sources
ROOT=Path(__file__).resolve().parents[1]
def git(root,*args): return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True)
def commit(root):
    git(root,'add','.')
    git(root,'-c','user.name=Synthetic Test','-c','user.email=test@example.invalid','commit','-qm','Synthetic source')
class SourceTests(unittest.TestCase):
    def checkout(self, *, current=False):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        git(root,'init','-q');git(root,'config','core.autocrlf','false')
        files=({name:(ROOT/name).read_bytes() for name in matrix.ARITHMETIC_SOURCE_PATHS}
               if current else skin_stage_sources())
        for name,data in files.items():
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        commit(root);return root
    def test_current_source_cannot_adopt_or_export_historical_resident_identity(self):
        root=self.checkout(current=True)
        with self.assertRaisesRegex(ValueError,'Arithmetic source changed; cannot fall back'):
            matrix.source_identity(root)
        with self.assertRaisesRegex(ValueError,'Arithmetic source changed; cannot fall back'):
            matrix.export_witness(root,root/'witness')
        self.assertFalse((root/'witness').exists())
    def test_exact_candidate_and_control_witnesses(self):
        root=self.checkout()
        source=matrix.source_identity(root)
        self.assertEqual(len(source['runtime_files_sha256']),48)
        self.assertEqual(matrix.canonical_hash(source['runtime_files_sha256']),matrix.AUDITED_SKIN_STAGE_CANDIDATE_MANIFEST)
        matrix.export_witness(root,root/'candidate-witness')
        self.assertEqual(matrix.artifact_source(root/'candidate-witness',matrix.sha256(root/'candidate-witness/SOURCE_WITNESS.json')),source)
        path=root/'src/frame_staging_policy.rs';raw=path.read_bytes()
        self.assertEqual(raw.count(b'STAGING_REUSE_ENABLED: bool = true;'),1)
        path.write_bytes(raw.replace(b'STAGING_REUSE_ENABLED: bool = true;',b'STAGING_REUSE_ENABLED: bool = false;'));commit(root)
        control=matrix.source_identity(root)
        self.assertEqual(matrix.canonical_hash(control['runtime_files_sha256']),matrix.AUDITED_SKIN_STAGE_STAGING_CONTROL_MANIFEST)
        self.assertEqual({n for n in source['runtime_files_sha256'] if source['runtime_files_sha256'][n]!=control['runtime_files_sha256'][n]},{'src/frame_staging_policy.rs'})
    def test_new_or_previously_unbound_files_never_use_narrow_fallback(self):
        for name in matrix.ARITHMETIC_SOURCE_PATHS[len(matrix.LOADER_SOURCE_PATHS):]:
            with self.subTest(name=name):
                root=self.checkout();path=root/name;raw=path.read_bytes();path.write_bytes(raw+b'\n// Unreviewed mutation\n')
                with self.assertRaisesRegex(ValueError,'Uncommitted arithmetic source'):matrix.source_identity(root)
                commit(root)
                with self.assertRaisesRegex(ValueError,'cannot fall back'):matrix.source_identity(root)
    def test_missing_module_and_changed_old_runtime_are_rejected(self):
        for name in ('src/render/resident.wgsl','src/render/frame.rs','src/authored_viewmodel.rs'):
            with self.subTest(name=name):
                root=self.checkout();(root/name).unlink();commit(root)
                with self.assertRaisesRegex(ValueError,'cannot fall back'):matrix.source_identity(root)
    def test_separate_resident_cpu_control_preserves_enabled_staging(self):
        root=self.checkout();candidate=matrix.source_identity(root);path=root/'src/frame_resident_policy.rs'
        path.write_bytes(path.read_bytes().replace(b'ENABLED: bool = true;',b'ENABLED: bool = false;'));commit(root)
        control=matrix.source_identity(root)
        self.assertEqual(matrix.canonical_hash(control['runtime_files_sha256']),
                         matrix.AUDITED_SKIN_STAGE_RESIDENT_CPU_CONTROL_MANIFEST)
        self.assertEqual({name for name in candidate['runtime_files_sha256']
                          if candidate['runtime_files_sha256'][name]!=control['runtime_files_sha256'][name]},
                         {'src/frame_resident_policy.rs'})
        matrix.export_witness(root,root/'resident-control-witness')
        self.assertEqual(matrix.artifact_source(root/'resident-control-witness',
                         matrix.sha256(root/'resident-control-witness/SOURCE_WITNESS.json')),control)
        path=root/'src/frame_staging_policy.rs'
        path.write_bytes(path.read_bytes().replace(b'STAGING_REUSE_ENABLED: bool = true;',
                                                   b'STAGING_REUSE_ENABLED: bool = false;'));commit(root)
        with self.assertRaisesRegex(ValueError,'cannot fall back'): matrix.source_identity(root)
        self.assertEqual(matrix.AUDITED_RESIDENT_CANDIDATE_MANIFEST,'c754f89052fc3812dbbdc9675a452b056a881696d3cf9fbd7398fc580bcbfe6f')
        self.assertEqual(matrix.AUDITED_RESIDENT_CONTROL_MANIFEST,'4eeea34f29b7d20a24060af152e7cd2170322674a3d2c0abaad8603497a6ac6b')
        for pin in (matrix.AUDITED_RESIDENT_CANDIDATE_MANIFEST,matrix.AUDITED_RESIDENT_CONTROL_MANIFEST):
            self.assertEqual(matrix.audited_inventory(pin),matrix.RESIDENT_SOURCE_PATHS)
    def test_historical_loader_and_renderer_classes_keep_their_pins(self):
        self.assertEqual(matrix.AUDITED_AUTHORED_DEDUP_MANIFEST,'fff66052fe41e445d50eaf2ae689a29cc68b7d3c3d4502d21d147424c60d3e06')
        self.assertEqual(matrix.audited_inventory(matrix.AUDITED_AUTHORED_DEDUP_MANIFEST),matrix.LOADER_SOURCE_PATHS)
        self.assertEqual(matrix.audited_inventory(matrix.AUDITED_ARENA_SERIALIZATION_MANIFEST),matrix.UPLOAD_REUSE_SOURCE_PATHS)
    def test_measured_exact_unorm_classes_keep_exact_historical_bytes(self):
        files=skin_stage_sources()
        hashes={name:hashlib.sha256(files[name]).hexdigest() for name in matrix.ARITHMETIC_SOURCE_PATHS}
        hashes['src/render/resident_vertex_probe.rs']='e18bd71b9836fe9398050873da1458383f2c3e0b2468bad02f291bc0f8255179'
        self.assertEqual(matrix.canonical_hash(hashes), matrix.AUDITED_EXACT_UNORM_CANDIDATE_MANIFEST)
        self.assertEqual(matrix.AUDITED_EXACT_UNORM_CANDIDATE_MANIFEST,
                         '03f75a80585a5c26dacbf5b7c7f51804ab7bdce8ba0dabab65d5660f37c6615b')
        for name, expected in (
            ('src/frame_staging_policy.rs', matrix.AUDITED_EXACT_UNORM_STAGING_CONTROL_MANIFEST),
            ('src/frame_resident_policy.rs', matrix.AUDITED_EXACT_UNORM_RESIDENT_CPU_CONTROL_MANIFEST),
        ):
            control=hashes.copy();raw=files[name]
            self.assertEqual(raw.count(b'ENABLED: bool = true;'),1)
            control[name]=hashlib.sha256(raw.replace(b'ENABLED: bool = true;',b'ENABLED: bool = false;')).hexdigest()
            self.assertEqual(matrix.canonical_hash(control),expected)
            self.assertEqual(matrix.audited_inventory(expected),matrix.ARITHMETIC_SOURCE_PATHS)
        self.assertEqual(matrix.audited_inventory(matrix.AUDITED_EXACT_UNORM_CANDIDATE_MANIFEST),
                         matrix.ARITHMETIC_SOURCE_PATHS)

    def test_measured_arithmetic_classes_keep_exact_historical_bytes(self):
        files=skin_stage_sources()
        hashes={name:hashlib.sha256(files[name]).hexdigest() for name in matrix.ARITHMETIC_SOURCE_PATHS}
        hashes.update({
            'src/render/resident.rs':'8d1c10b1f51e60d1db6e6260f6dfdc1c4f7511a5fb827dd966bdb87b84888887',
            'src/render/resident.wgsl':'90acbcd974685c4f0cf18c67a4efd0b6b980b86f554181fcc7b0a1f67d5db25a',
            'src/render/resident_vertex_probe.rs':'c3ebb9f6fb002fbdb0b18e5420caff0fde5a581c5baa63d34735a1e03c15dc33',
        })
        self.assertEqual(matrix.canonical_hash(hashes), matrix.AUDITED_ARITHMETIC_CANDIDATE_MANIFEST)
        self.assertEqual(matrix.AUDITED_ARITHMETIC_CANDIDATE_MANIFEST,
                         'b5120632999e1c599f89740ec8550432da06575b9175d3ba937f9474a5a707d0')
        for name, token, expected in (
            ('src/frame_staging_policy.rs', b'STAGING_REUSE_ENABLED: bool = true;',
             matrix.AUDITED_ARITHMETIC_STAGING_CONTROL_MANIFEST),
            ('src/frame_resident_policy.rs', b'ENABLED: bool = true;',
             matrix.AUDITED_ARITHMETIC_RESIDENT_CPU_CONTROL_MANIFEST),
        ):
            control=hashes.copy(); raw=files[name]
            self.assertEqual(raw.count(token), 1)
            control[name]=hashlib.sha256(raw.replace(token,token.replace(b'true',b'false'))).hexdigest()
            self.assertEqual(matrix.canonical_hash(control), expected)
            self.assertEqual(matrix.audited_inventory(expected), matrix.ARITHMETIC_SOURCE_PATHS)
        self.assertEqual(matrix.audited_inventory(matrix.AUDITED_ARITHMETIC_CANDIDATE_MANIFEST),
                         matrix.ARITHMETIC_SOURCE_PATHS)
    def test_historical_staging_digest_is_not_rebound_to_arithmetic_bytes(self):
        # These immutable old file hashes make this test independent of Git fetch
        # depth while retaining the exact previous inventory and class identity.
        files=skin_stage_sources()
        hashes={name:hashlib.sha256(files[name]).hexdigest() for name in matrix.STAGING_SOURCE_PATHS}
        hashes.update({
            'src/render/mod.rs':'b4784d74d2a8623bce0ac22f1c261662e4a76b3efdb7e834fece61fde320c153',
            'src/render/resident.rs':'5f5d286ea67f26b2bacc24a0f79c19f3e39bec1bdb691f3042a501bb303deef4',
            'src/render/resident.wgsl':'2550ae502da2dc8283c70ae2d29281c3ab7fe27afa01ef8ef924bf36952baa13',
        })
        self.assertEqual(len(hashes),46)
        self.assertEqual(matrix.canonical_hash(hashes),matrix.AUDITED_STAGING_CANDIDATE_MANIFEST)
        self.assertEqual(matrix.AUDITED_STAGING_CANDIDATE_MANIFEST,
                         'fc6c5bc8b09562dea007388988dc610b8f3b91c479be4eb4ba1cedb3d0953402')
        for pin in (matrix.AUDITED_STAGING_CANDIDATE_MANIFEST,matrix.AUDITED_STAGING_CONTROL_MANIFEST,
                    matrix.AUDITED_STAGING_RESIDENT_CPU_CONTROL_MANIFEST):
            self.assertEqual(matrix.audited_inventory(pin),matrix.STAGING_SOURCE_PATHS)
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

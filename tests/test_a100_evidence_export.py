"""Evidence preservation and notebook reconstruction tests; no runtime/network."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import time
import unittest
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import a100_public_build as b
import prepare_public_a100 as entry
import prepare_a100_text_export as transfer


class EvidenceExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='a100-evidence-test-')
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def fixture(self, extra_bytes=b''):
        raw = {
            'runtime/smoke/r01/game.log': b'driver/runtime error preserved\n',
            'runtime/smoke/r01/driver.log': b'exact owned window fixture\n',
            'runtime/smoke/r01/session/frames.json': b'{"complete":false,"fixture":true}' + extra_bytes,
            'runtime/smoke/r01/session/CSV_STATUS.json': b'{"state":"stopped"}',
            'runtime/smoke/r01/session/GPU_STATUS.json': b'{"state":"stopped"}',
            'runtime/smoke/r01/session/IDENTITY.json': b'{"fixture":"identity"}',
            'runtime/smoke/r01/session/GPU_METADATA.json': b'{"fixture":"no GPU duration"}',
            'runtime/smoke/r01/session/gameplay.csv': b'time,x,y,z\n1,0,0,0\n',
            'runtime/smoke/r01/session/gpu.jsonl': b'{"sample":0}\n',
            'runtime/pilot/r01/session/frames.json': b'{incomplete data retained verbatim',
            'runtime/pilot/r01/START.json': b'{"fixture":"started only"}',
            'build/evidence/validation.json': b'{"fixture":"validation log"}',
            'build/logs/validate-public-release-assets.log': b'validator stdout fixture\n',
            'logs/surface-smoke-pilot.log': b'supervisor fixture\n',
        }
        for name, data in raw.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        for name, data in {'build/package/vector-range': b'ELF FIXTURE NEVER EXECUTED', 'build/package/assets/reload/raw.vra': b'RAW ASSET EXCLUDED',
                           'build/package/BUILD_IDENTITY.json': b'{"fixture":"build"}', 'build/package/ACTUAL_GAME_HARNESS_RECEIPT.json': b'{"fixture":"harness"}'}.items():
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        now = time.time()
        result = {'status': 'failed', 'deadline_unix': now + 90, 'allocation_clock': entry.Budget(now, now + 90).clock_receipt(), 'export_status': 'pending'}
        b.save(self.root / 'RESULT.json', result)
        receipt = entry.export_evidence(self.root)
        result.update(export_status='verified', export=receipt)
        b.save(self.root / 'RESULT.json', result)
        return raw, receipt

    def transcript(self):
        manifest, chunks = transfer.prepare_transport(self.root)
        lines = list(transfer.transport_lines(manifest, chunks))
        digest = transfer.sha(transfer.compact(manifest).encode())
        return manifest, lines, digest

    def test_evidence_archive_preserves_every_raw_file_and_excludes_payloads(self):
        raw, receipt = self.fixture()
        self.assertFalse(receipt['includes_executable']); self.assertFalse(receipt['includes_raw_assets'])
        with tarfile.open(self.root / receipt['file'], 'r:gz') as archive:
            entries = {item.name: archive.extractfile(item).read() for item in archive}
        self.assertNotIn('build/package/vector-range', entries)
        self.assertFalse(any(name.startswith('build/package/assets/') for name in entries))
        for name, value in raw.items():
            self.assertEqual(entries[name], value)
            self.assertEqual(receipt['archived_files'][name], {'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()})
        self.assertEqual(set(entries), set(receipt['archived_files']))
        self.assertEqual(receipt['raw_runtime_files'], sum(name.startswith('runtime/') for name in raw))
        self.assertFalse((self.root / 'a100-executable-optional.tar.gz').exists())

    def test_optional_executable_export_is_separate(self):
        self.fixture()
        receipt = entry.export_executable(self.root)
        with tarfile.open(self.root / receipt['file'], 'r:gz') as archive:
            self.assertEqual(set(archive.getnames()), {'build/package/vector-range', 'build/package/BUILD_IDENTITY.json', 'build/package/ACTUAL_GAME_HARNESS_RECEIPT.json'})
        self.assertTrue((self.root / 'a100-evidence-only.tar.gz').is_file())

    def test_text_roundtrip_is_exact_and_can_materialize_after_deadline(self):
        self.fixture(extra_bytes=os.urandom(transfer.CHUNK_BYTES * 3))
        manifest, lines, digest = self.transcript()
        self.assertGreater(manifest['chunk_count'], 1)
        captured = self.root / 'saved-notebook-text.txt'
        captured.write_text('\n'.join(lines) + '\n')
        output = self.root / 'recovered'
        with mock.patch.object(transfer.time, 'time', return_value=time.time() + 7200):
            result = transfer.materialize(captured, digest, output)
        self.assertEqual((output / 'a100-evidence-only.tar.gz').read_bytes(), (self.root / 'a100-evidence-only.tar.gz').read_bytes())
        self.assertEqual((output / 'EVIDENCE_EXPORT_RECEIPT.json').read_bytes(), (self.root / 'EVIDENCE_EXPORT_RECEIPT.json').read_bytes())
        self.assertEqual((output / 'FINAL_RESULT.json').read_bytes(), (self.root / 'RESULT.json').read_bytes())
        self.assertFalse(result['archive_extracted']); self.assertFalse(result['gpu_shutdown_confirmed'])

    def test_repeated_exports_preserve_existing_verified_archives_and_receipts(self):
        self.fixture()
        entry.export_executable(self.root)
        for function, archive, receipt in ((entry.export_evidence, 'a100-evidence-only.tar.gz', 'EVIDENCE_EXPORT_RECEIPT.json'),
                                            (entry.export_executable, 'a100-executable-optional.tar.gz', 'EXECUTABLE_EXPORT_RECEIPT.json')):
            before_archive = (self.root / archive).read_bytes(); before_receipt = (self.root / receipt).read_bytes()
            with self.assertRaisesRegex(ValueError, 'already exists'): function(self.root)
            self.assertEqual((self.root / archive).read_bytes(), before_archive)
            self.assertEqual((self.root / receipt).read_bytes(), before_receipt)

    def test_text_emission_reports_only_emission(self):
        self.fixture()
        emitted = []
        result = transfer.emit_index(self.root, emitted.append)
        self.assertEqual(result['status'], 'one_output_emitted_not_persistence_verified')
        self.assertEqual(len(emitted), 1)
        manifest, chunks = transfer.prepare_transport(self.root)
        for i, chunk in enumerate(chunks):
            transfer.emit_chunk(self.root, i, result['manifest_sha256'], transfer.sha(chunk), i - 1, emitted.append)
        transfer.emit_finish(self.root, result['manifest_sha256'], len(chunks) - 1, emitted.append)
        self.assertFalse(result['gpu_shutdown_confirmed'])
        transfer.decode_transcript('\n'.join(emitted), result['manifest_sha256'])

    def test_missing_duplicate_mixed_and_truncated_chunks_rejected(self):
        self.fixture()
        manifest, lines, digest = self.transcript()
        row = json.loads(lines[1].partition(' ')[2])
        mixed = dict(row, export_id='0' * 64)
        truncated = dict(row, data=row['data'][:-1])
        oversized = dict(row, data='A' * (4 * transfer.CHUNK_BYTES + 1024))
        variants = [lines[:1] + lines[2:], [lines[0], lines[1], *lines[1:]], lines[:-1],
                    [lines[0], transfer.PREFIX + 'CHUNK ' + transfer.compact(mixed), *lines[2:]],
                    [lines[0], transfer.PREFIX + 'CHUNK ' + transfer.compact(truncated), *lines[2:]],
                    [lines[0], transfer.PREFIX + 'CHUNK ' + transfer.compact(oversized), *lines[2:]]]
        for index, variant in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(ValueError): transfer.decode_transcript('\n'.join(variant), digest)

    def test_next_chunk_requires_separate_request_with_digest_and_acknowledgement(self):
        self.fixture()
        manifest, chunks = transfer.prepare_transport(self.root)
        digest = transfer.sha(transfer.compact(manifest).encode())
        emitted = []
        for ack, chunk_digest in ((0, transfer.sha(chunks[0])), (-1, '0' * 64)):
            with self.assertRaises(ValueError): transfer.emit_chunk(self.root, 0, digest, chunk_digest, ack, emitted.append)
        self.assertEqual(emitted, [])
        with self.assertRaises(ValueError): transfer.emit_finish(self.root, digest, -1, emitted.append)

    def test_manifest_mismatch_never_creates_output(self):
        self.fixture()
        manifest, lines, digest = self.transcript()
        transcript = self.root / 'text.txt'; transcript.write_text('\n'.join(lines))
        output = self.root / 'must-not-exist'
        with self.assertRaisesRegex(ValueError, 'manifest digest'): transfer.materialize(transcript, '0' * 64, output)
        self.assertFalse(output.exists())

    def test_text_size_limit_does_not_drop_or_modify_raw_evidence(self):
        raw, receipt = self.fixture()
        before = (self.root / receipt['file']).read_bytes()
        with mock.patch.object(transfer, 'MAX_ARCHIVE_BYTES', 1), self.assertRaisesRegex(ValueError, 'size bound'):
            transfer.prepare_transport(self.root)
        self.assertEqual(before, (self.root / receipt['file']).read_bytes())
        for name, value in raw.items(): self.assertEqual((self.root / name).read_bytes(), value)

    def test_expired_emission_leaves_disconnect_margin_and_emits_nothing(self):
        self.fixture()
        result = json.loads((self.root / 'RESULT.json').read_text()); result['deadline_unix'] = time.time() + 14
        b.save(self.root / 'RESULT.json', result)
        emitted = []
        with self.assertRaisesRegex(ValueError, 'disconnect now'): transfer.emit_index(self.root, emitted.append)
        self.assertEqual(emitted, [])

    def test_clock_rollback_cannot_extend_text_emission(self):
        self.fixture()
        path = self.root / 'RESULT.json'; result = json.loads(path.read_text())
        result['allocation_clock']['monotonic_deadline'] = time.monotonic() + 14
        b.save(path, result)
        emitted = []
        with mock.patch.object(transfer.time, 'time', return_value=time.time() - 10000), self.assertRaisesRegex(ValueError, 'disconnect now'):
            transfer.emit_index(self.root, emitted.append)
        self.assertEqual(emitted, [])

    def test_different_boot_cannot_resume_notebook_emission(self):
        self.fixture()
        path = self.root / 'RESULT.json'; result = json.loads(path.read_text())
        result['allocation_clock']['boot_id'] = 'different-runtime'
        b.save(path, result)
        with self.assertRaisesRegex(ValueError, 'boot identity changed'): transfer.emit_index(self.root, lambda line: None)

    def test_corrupted_archive_is_rejected_before_emission(self):
        self.fixture()
        archive = self.root / 'a100-evidence-only.tar.gz'
        archive.write_bytes(archive.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'differs from receipt'): transfer.prepare_transport(self.root)

    def test_claiming_executable_export_cannot_use_evidence_text_channel(self):
        self.fixture()
        path = self.root / 'EVIDENCE_EXPORT_RECEIPT.json'
        receipt = json.loads(path.read_text()); receipt['includes_executable'] = True; b.save(path, receipt)
        with self.assertRaisesRegex(ValueError, 'Only verified evidence-only'): transfer.prepare_transport(self.root)


if __name__ == '__main__': unittest.main()

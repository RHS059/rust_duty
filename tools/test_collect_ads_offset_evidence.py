"""Collection-only controls using complete synthetic native capture inventories."""
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import collect_ads_offset_evidence as collector
import test_revalidate_ads_offset as fixtures
from verify_capture_telemetry import read_record

BLOCKED = 'ValueError: blocked by a failed required capture or input check'


class CollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.RevalidationCallerTests.setUpClass()
        cls.addClassCleanup(fixtures.RevalidationCallerTests.doClassCleanups)
        source = fixtures.RevalidationCallerTests
        cls.root, cls.folder, cls.binding, cls.context = source.root, source.folders['ads-offset'], source.f.native, source.capture
        report = read_record(cls.folder / 'summary.json')
        for row in report['checks']:
            if row['name'].endswith('/finite-images'):
                role = row['name'].split('/')[0]
                path = cls.folder / report['capture_paths'][role] / '0000.png'
                try:
                    collector.verify(path, collector.authored.EXTENT, collector.authored.BACKGROUND, .01, 8, None)
                except collector.CaptureStructureError as error:
                    row['error'] = 'CaptureStructureError: ' + str(error)
            elif not row['passed']:
                row['error'] = BLOCKED
        collector.authored.write_json(cls.folder / 'summary.json', collector.aggregate.plain(report))

    def restore(self, path):
        raw = path.read_bytes()
        self.addCleanup(path.write_bytes, raw)
        return raw

    def report(self):
        path = self.folder / 'summary.json'
        self.restore(path)
        return read_record(path)

    def save(self, report):
        collector.authored.write_json(self.folder / 'summary.json', collector.aggregate.plain(report))

    def reseal(self):
        report = self.report()
        report['files'] = collector.shared.inventory_files(self.folder)
        self.save(report)

    def inspect(self):
        return collector.inspect_offset_collection(self.folder, self.binding, expected_context=self.context)

    def test_complete_typed_failure_is_only_collectable_and_original_bytes_stay_failed(self):
        original = (self.folder / 'summary.json').read_bytes()
        result = self.inspect()
        self.assertTrue(result['collection_ready'])
        self.assertTrue(result['needs_supplement'])
        self.assertTrue(result['acceptance_deferred'])
        self.assertFalse(result['acceptance_complete'])
        self.assertFalse(result['original_passed'])
        self.assertEqual(result['exact_telemetry']['files'], 1106)
        for role in collector.aggregate.ROLES:
            self.assertEqual(result['images'][role]['frames'], 553)
            self.assertEqual([row['frame'] for row in result['images'][role]['typed_structure_failures']], [0])
        self.assertEqual((self.folder / 'summary.json').read_bytes(), original)

    def test_unrelated_original_failure_timeout_incomplete_and_unexpected_dependent_rejected(self):
        original = self.report()
        mutations = [
            lambda report: report.update(budget_exhausted=True),
            lambda report: report.update(status='interrupted'),
            lambda report: report.update(fatal_error='interrupted after cleanup'),
            lambda report: report['checks'].pop(),
            lambda report: report['checks'][2].update(passed=False, error='process failed'),
            lambda report: report['checks'][3].update(error='CaptureError: PNG CRC mismatch'),
            lambda report: report['checks'][4].update(error='ValueError: real validator rejection'),
        ]
        for change in mutations:
            with self.subTest(change=change):
                report = deepcopy(original)
                change(report)
                self.save(report)
                with self.assertRaises(ValueError):
                    self.inspect()

    def test_late_corrupt_png_rejected_even_though_first_frame_is_eligible(self):
        path = self.folder / collector.shared.capture_paths('ads-offset')['dx12'] / '0552.png'
        self.restore(path)
        path.write_bytes(b'corrupt PNG after the first known coverage failure')
        self.reseal()
        with self.assertRaises(ValueError):
            self.inspect()

    def test_late_nonfinite_sidecar_rejected(self):
        path = self.folder / collector.shared.capture_paths('ads-offset')['dx12'] / '0552.png.gameplay.json'
        self.restore(path)
        path.write_text('{"simulation_time": 1e9999}')
        self.reseal()
        with self.assertRaisesRegex(ValueError, 'non-finite'):
            self.inspect()

    def test_deferred_image_must_really_be_rgba8(self):
        from PIL import Image
        path = self.folder / collector.shared.capture_paths('ads-offset')['windows-legacy'] / '0000.png'
        self.restore(path)
        with Image.open(path) as source:
            image = source.convert('RGB')
        image.save(path)
        self.reseal()
        with self.assertRaisesRegex(ValueError, 'RGBA8'):
            self.inspect()

    def test_wrong_native_frame_identity_rejected(self):
        path = self.folder / collector.shared.capture_paths('ads-offset')['windows-legacy'] / '0552.png.json'
        self.restore(path)
        record = read_record(path)
        record['frame_witness']['capture_identity'] = '0' * 64
        collector.authored.write_json(path, collector.aggregate.plain(record))
        self.reseal()
        with self.assertRaises(ValueError):
            self.inspect()

    def test_full_capture_context_and_closed_bytes_are_required(self):
        with self.assertRaises(ValueError):
            collector.inspect_offset_collection(self.folder, self.binding,
                expected_context={**self.context, 'run_attempt': '99'})
        path = self.folder / 'unrecorded-patch.txt'
        path.write_text('unrelated file')
        self.addCleanup(path.unlink)
        with self.assertRaises(ValueError):
            self.inspect()

    def test_collector_rejects_other_repo_branch_and_workflow_contexts(self):
        environment = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'RHS059/rust_duty', 'GITHUB_REF': 'refs/heads/main',
                       'GITHUB_WORKFLOW_REF': 'RHS059/rust_duty/.github/workflows/build.yml@refs/heads/main',
                       'GITHUB_SHA': self.context['source_commit'], 'GITHUB_WORKFLOW_SHA': self.context['source_commit'],
                       'GITHUB_RUN_ID': self.context['run_id'],
                       'GITHUB_RUN_ATTEMPT': self.context['run_attempt']}
        with patch.dict(os.environ, environment):
            self.assertEqual(collector.current_context(), self.context)
        for key, value in [('GITHUB_ACTIONS', 'false'), ('GITHUB_WORKFLOW_SHA', '9' * 40),
                           ('GITHUB_REPOSITORY', 'other/repo'), ('GITHUB_REF', 'refs/heads/other'),
                           ('GITHUB_WORKFLOW_REF', 'RHS059/rust_duty/.github/workflows/other.yml@refs/heads/main')]:
            with patch.dict(os.environ, {**environment, key: value}):
                with self.assertRaises(ValueError):
                    collector.current_context()


class CollectionCommandTests(unittest.TestCase):
    def test_exit_code_must_exactly_match_retained_verdict_and_no_receipt_on_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / 'manifest.json'
            manifest.write_text('{"fixture":true}')
            for deferred, exit_code in [(False, 1), (True, 0), (True, 137), (True, 124)]:
                receipt = root / 'receipt.json'
                with self.subTest(deferred=deferred, exit_code=exit_code), \
                     patch.object(collector.sys, 'platform', 'win32'), \
                     patch.object(collector, 'current_context', return_value={}), \
                     patch.object(collector.leaf, 'manifest_binding', return_value={}), \
                     patch.object(collector.shared, 'verify_input_manifest', return_value={}), \
                     patch.object(collector, 'inspect_offset_collection', return_value={'needs_supplement': deferred}):
                    with self.assertRaisesRegex(ValueError, 'exit status'):
                        collector.run(root=root, input_manifest=manifest, evidence=root / 'offset',
                                      receipt=receipt, capture_exit_code=exit_code)
                    self.assertFalse(receipt.exists())

    def test_collection_receipt_cannot_be_inserted_into_original_artifact(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(collector.sys, 'platform', 'win32'), \
             patch.object(collector, 'current_context', return_value={}):
            root = Path(temp)
            with self.assertRaisesRegex(ValueError, 'outside the immutable shard'):
                collector.run(root=root, input_manifest=root / 'manifest', evidence=root / 'offset',
                              receipt=root / 'offset/subdir/../receipt.json', capture_exit_code=1)


if __name__ == '__main__':
    unittest.main()

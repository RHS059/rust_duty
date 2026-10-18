"""Exact diagnostic successor/history regressions; source-only, no native claims."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import app_edge_renderer_overlay_v1 as overlay
import verify_app_edges as verifier


class RendererOverlayChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.current = (cls.root / 'src/authored_viewmodel.rs').read_bytes()
        cls.provenance = (cls.root / 'tools/combined_source_contracts.json').read_bytes()
        cls.contract = overlay.load_overlay()
        cls.parent = overlay.restore_renderer_overlay(cls.current, cls.provenance)

    def test_exact_two_insertion_round_trip_preserves_historical_endpoints(self):
        self.assertEqual(self.contract['schema'], 'rust-duty-app-edge-renderer-diagnostic-overlay/v1')
        self.assertEqual([row['name'] for row in self.contract['insertions']],
                         ['read-only-candidate-observation', 'inactive-binding-test'])
        self.assertEqual(len(self.current) - len(self.parent), 1040)
        self.assertEqual(overlay.apply_renderer_overlay(self.parent, self.provenance), self.current)
        history = json.loads(self.provenance)
        self.assertEqual(hashlib.sha256(self.parent).hexdigest(), history['repository_renderer_sha256'])
        self.assertEqual(history['renderer_before_app_edge_sha256'],
                         '07242fcab1d23d92a23748e27525efa8440fe11724115c562c6c477fb1d6c23e')
        self.assertEqual(history['historical_native_renderer_sha256'], verifier.STATUS_SOURCE_SHA256)
        self.assertEqual(history['native_manifest_sha256'], verifier.STATUS_MANIFEST_SHA256)
        self.assertEqual(history['exact_required_real_visual_status'], verifier.REQUIRED_RENDER_STATUS)

    def test_missing_duplicated_or_altered_diagnostics_are_rejected(self):
        for row in self.contract['insertions']:
            block = row['insert'].encode('utf-8')
            self.assertEqual(self.current.count(block), 1)
            for replacement in (b'', block + block, block.replace(b'    ', b'     ', 1)):
                changed = self.current.replace(block, replacement, 1)
                with self.subTest(insertion=row['name'], replacement_length=len(replacement)):
                    with self.assertRaisesRegex(AssertionError, 'current renderer bytes changed'):
                        overlay.restore_renderer_overlay(changed, self.provenance)

    def test_moved_diagnostics_and_changed_anchors_are_rejected(self):
        for row in self.contract['insertions']:
            block = row['insert'].encode('utf-8')
            anchor = row['before'].encode('utf-8')
            for changed in (self.current.replace(block, b'', 1) + block,
                            self.current.replace(anchor, anchor + b'\n', 1)):
                with self.subTest(insertion=row['name']):
                    with self.assertRaises(AssertionError):
                        overlay.restore_renderer_overlay(changed, self.provenance)

    def test_non_diagnostic_motion_changes_and_old_source_are_rejected(self):
        # An actual renderer motion assignment, outside either diagnostic insertion.
        old = b'visual.pose = Some(pose);'
        self.assertIn(old, self.parent)
        self.assertIn(old, self.current)
        changed = b'visual.pose = None;'
        with self.assertRaises(AssertionError):
            overlay.restore_renderer_overlay(self.current.replace(old, changed, 1), self.provenance)
        with self.assertRaises(AssertionError):
            overlay.apply_renderer_overlay(self.parent.replace(old, changed, 1), self.provenance)
        with self.assertRaises(AssertionError):
            overlay.restore_renderer_overlay(self.parent, self.provenance)
        with self.assertRaises(AssertionError):
            overlay.apply_renderer_overlay(self.current, self.provenance)

    def test_historical_provenance_cannot_be_replaced_with_current_hash(self):
        changed = json.loads(self.provenance)
        changed['repository_renderer_sha256'] = self.contract['current_sha256']
        raw = (json.dumps(changed, indent=2) + '\n').encode('utf-8')
        for operation, source in ((overlay.restore_renderer_overlay, self.current),
                                  (overlay.apply_renderer_overlay, self.parent)):
            with self.subTest(operation=operation.__name__):
                with self.assertRaisesRegex(AssertionError, 'historical consolidated source contract bytes changed'):
                    operation(source, raw)

    def test_overlay_receipt_cannot_be_rewritten_or_partially_redefined(self):
        real_read = Path.read_bytes
        receipt = Path(overlay.__file__).with_suffix('.json')
        for field in ('current_sha256', 'parent_sha256', 'insertions', 'historical_contract_sha256'):
            changed = copy.deepcopy(self.contract)
            changed[field] = [] if field == 'insertions' else 'f' * 64
            altered = (json.dumps(changed, indent=2) + '\n').encode('utf-8')
            def read_bytes(path):
                return altered if path == receipt else real_read(path)
            with self.subTest(field=field), patch.object(Path, 'read_bytes', read_bytes):
                with self.assertRaisesRegex(AssertionError, 'diagnostic overlay contract bytes changed'):
                    overlay.restore_renderer_overlay(self.current, self.provenance)

    def test_raw_crlf_bytes_reject_and_ascii_locale_round_trip_is_exact(self):
        # This renderer is ASCII; cp1252 does not change its existing bytes.
        # Raw CRLF conversion does change them and must fail before reversal.
        for source, operation in ((self.current, overlay.restore_renderer_overlay),
                                  (self.parent, overlay.apply_renderer_overlay)):
            self.assertTrue(source.isascii())
            self.assertEqual(source.decode('cp1252').encode('utf-8'), source)
            with self.assertRaises(AssertionError):
                operation(source.replace(b'\n', b'\r\n'), self.provenance)

    def test_current_and_parent_renderers_remain_rejected_as_historical_native_proof(self):
        for source in (self.current, self.parent):
            config = dict(source_root='candidate',
                          source_files=[dict(path='candidate/src/authored_viewmodel.rs',
                                             sha256=hashlib.sha256(source).hexdigest())],
                          manifest=dict(sha256=verifier.STATUS_MANIFEST_SHA256))
            review = dict(renderer_status_contract=copy.deepcopy(verifier.STATUS_CONTRACT))
            with self.subTest(source_sha256=config['source_files'][0]['sha256']):
                with self.assertRaises(verifier.Rejected):
                    verifier.check_source_status_identity(config, review)


if __name__ == '__main__':
    unittest.main(verbosity=2)

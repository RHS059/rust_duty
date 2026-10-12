"""Synthetic adversarial controls; these never establish native execution/review."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import finite_ads_profile_binding as f
import test_finite_ads_profile_binding as original_tests

encoded = original_tests.encoded


class PairedSourceTests(original_tests.ProfileTests):
    """Repeat every existing packet-class control with the extension selected."""
    def setUp(self):
        super().setUp()
        self.source_bytes = {label: {name: (label + '/' + name + '\n').encode()
                                   for name in f.PASS_BATCHING_PAIRS['baseline']}
                             for label in ('baseline', 'candidate')}
        pairs = {label: {name: f._identity(raw) for name, raw in files.items()}
                 for label, files in self.source_bytes.items()}
        self.addCleanup(patch.stopall)
        patch.object(f, 'PASS_BATCHING_PAIRS', pairs).start()
        for name, raw in self.source_bytes['baseline'].items():
            self.add_file(name, raw)
            self.descriptor['equivalence']['production'][name] = f._identity(raw)
        self.descriptor['_pass_batching'] = {'comparison': {}, 'sha256': 'b' * 64}
        self.select('candidate', 'candidate')

    def select(self, frame, plan):
        for name, label in (('src/render/frame.rs', frame), ('src/render/plan.rs', plan)):
            self.add_file(name, self.source_bytes[label][name])
        self.save()

    def test_pending_descriptor_and_self_refreshed_hash_rejected(self):
        # The inherited public-entry test needs an external descriptor, not the
        # internal marker used by this class's packet-boundary fixtures.
        self.descriptor.pop('_pass_batching')
        super().test_pending_descriptor_and_self_refreshed_hash_rejected()

    def test_exact_pairs_work_but_either_mixed_pair_fails(self):
        for label in ('baseline', 'candidate'):
            self.select(label, label)
            self.bind_class()
        for labels in (('baseline', 'candidate'), ('candidate', 'baseline')):
            self.select(*labels)
            with self.subTest(labels=labels), self.assertRaisesRegex(ValueError, 'mixed or unreviewed'):
                self.bind_class()

    def test_unrecognized_bytes_reject_even_after_candidate_refreshes_inventory(self):
        for name in self.source_bytes['candidate']:
            self.select('candidate', 'candidate')
            self.add_file(name, self.source_bytes['candidate'][name] + b'// changed\n')
            self.save()
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'mixed or unreviewed'):
                self.bind_class()

    def test_original_descriptor_still_rejects_candidate_pair(self):
        self.select('candidate', 'candidate')
        del self.descriptor['_pass_batching']
        with self.assertRaisesRegex(ValueError, 'unreviewed additive/source'):
            self.bind_class()

    def test_missing_pair_member_rejects(self):
        for name in ('src/render/frame.rs', 'src/render/plan.rs'):
            self.select('candidate', 'candidate')
            self.packet['files'].pop(name)
            self.receipt['inputs_and_implementation_before'].pop(name)
            self.receipt['inputs_and_implementation_after'].pop(name)
            self.save()
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'production file missing'):
                self.bind_class()

    def test_candidate_pair_retains_source_lf_mapping_and_late_mutation_checks(self):
        self.select('candidate', 'candidate')
        for name, raw in self.source_bytes['candidate'].items():
            self.add_file(name, raw.replace(b'\n', b'\r\n'))
        self.save()
        self.bind_class()
        name = 'src/render/frame.rs'
        (self.root / self.packet['files'][name]).write_bytes(b'changed after binding')
        with self.assertRaisesRegex(ValueError, 'late mutation'):
            self.bound.verify_unchanged()


class NativeComparisonTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).with_name('finite_ads_reviewed_class.json')
        self.original_bytes = path.read_bytes()
        self.reviewed = f.source._parse(self.original_bytes, 'original reviewed class')
        original_native = f.source._parse((path.parent / self.reviewed['evidence']['native']['path']).read_bytes(),
                                         'historical native report')
        self.native = original_native['native_identity']
        identity = f._identity(b'explicitly synthetic guard fixture, never native evidence')
        names = [case[0] for case in f.renderer_contract.cases()]
        runtime = {key: self.native[key] for key in (*f.DEVICE_FIELDS, 'adapter', 'backend', 'compiler')}
        self.report = {
            'schema': 'rust-duty-pass-batching-native-review/v1', 'status': 'passed',
            'native_execution': True, 'original_class_sha256': f.ORIGINAL_CLASS_SHA256,
            'original_profile_flags_modified': False, 'acceptance_complete': False, 'acceptance_verdict': None,
            'commits': deepcopy(f.PASS_BATCHING_COMMITS),
            'artifact': {'run_id': '1', 'run_attempt': '1', 'artifact_id': '1', 'archive_sha256': 'a' * 64},
            **{name: deepcopy(identity) for name in ('summary', 'build_receipts', 'exact_pixels')},
            'comparison': {'channels': 'RGBA', 'channel_tolerance': 0, 'capture_count': 21},
            'variants': {label: {
                'source_pair': deepcopy(pair), 'compiler_sha256': self.reviewed['equivalence']['compiler_sha256'],
                'runtime_identity': deepcopy(runtime), 'process_exit_code': 0,
                **{name: deepcopy(identity) for name in ('source_receipt', 'contract_executable', 'contract_report', 'contract_log')},
                'fixed_contract_validation': {'schema': 'rust-duty-renderer-contract-validation/v1', 'passed': True,
                    'backend': 'Dx12', 'adapter': 'Microsoft Basic Render Driver', 'captures': 21,
                    'scope': f.renderer_contract.SCOPE, 'build_version': 'synthetic', 'build_number': 'synthetic'},
                'rgba_sha256': {name: 'd' * 64 for name in names},
                'png_sha256': {name: 'e' * 64 for name in names},
            } for label, pair in f.PASS_BATCHING_PAIRS.items()},
        }
        self.reviewed['_pass_batching'] = {'comparison': self.report, 'sha256': 'b' * 64}
        self.extension = {'schema': f.PASS_BATCHING_SCHEMA, 'class_id': f.PASS_BATCHING_CLASS,
                          'status': 'pending_independent_native_review',
                          'original_class': {'path': 'original.json', **f._identity(self.original_bytes)},
                          'source_pairs': deepcopy(f.PASS_BATCHING_PAIRS),
                          'native_comparison': None, 'acceptance_verdict': None}

    def check(self):
        f._pass_batching_evidence(self.reviewed, self.native)

    def change_reject(self, root, key, value):
        old = root[key]
        root[key] = value
        try:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.check()
        finally:
            root[key] = old

    def test_semantic_fixture_only_exercises_validator_and_never_enables_variant(self):
        self.check()
        self.assertNotEqual(f.PASS_BATCHING_NATIVE_REVIEW_SHA256, f._identity(encoded(self.report))['sha256'])
        self.assertEqual(hashlib.sha256(self.original_bytes).hexdigest(), f.ORIGINAL_CLASS_SHA256)

    def test_original_and_extension_anchors_disable_checkout_byte_conversion(self):
        attributes = Path(__file__).resolve().parents[1] / '.gitattributes'
        names = ['tools/finite_ads_reviewed_class.json',
                 'tools/finite_ads_reviewed_evidence/compiler/rustc-Vv-before.txt',
                 'tools/finite_ads_pass_batching_class.json',
                 'tools/finite_ads_pass_batching_evidence/native-review.json']
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.gitattributes').write_bytes(attributes.read_bytes())
            subprocess.run(['git', '-C', str(root), 'init', '--quiet'], check=True, capture_output=True)
            actual = subprocess.check_output(['git', '-C', str(root), 'check-attr', 'text', '--', *names], text=True)
            self.assertEqual(actual.splitlines(), [name + ': text: unset' for name in names])

    def test_pending_or_fabricated_self_anchored_descriptor_cannot_enable_variant(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(f, 'PASS_BATCHING_NATIVE_REVIEW_SHA256', None):
            root = Path(folder); (root / 'original.json').write_bytes(self.original_bytes)
            path = root / 'extension.json'
            for state, pattern in (('pending_independent_native_review', 'review pending'),
                                   ('reviewed', 'anchor unavailable')):
                self.extension['status'] = state
                (root / 'synthetic.json').write_bytes(encoded(self.report))
                self.extension['native_comparison'] = {'path': 'synthetic.json', **f._identity(encoded(self.report))}
                path.write_bytes(encoded(self.extension))
                with self.subTest(state=state), self.assertRaisesRegex(ValueError, pattern):
                    f.bind_finite_ads_profile(source_packet=None, source_packet_path=root / 'packet.json',
                        reviewed_class=path, expected_class_sha256=f._identity(path.read_bytes())['sha256'],
                        native_runtime_logs={})
            with self.assertRaisesRegex(ValueError, 'independent SHA'):
                f.bind_finite_ads_profile(source_packet=None, source_packet_path=root / 'packet.json',
                    reviewed_class=path, expected_class_sha256='0' * 64, native_runtime_logs={})

    def test_exact_pairs_and_original_anchor_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'original.json').write_bytes(self.original_bytes)
            extension = deepcopy(self.extension); extension['status'] = 'reviewed'
            extension['source_pairs']['candidate']['src/render/frame.rs']['sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'paired source mapping'):
                f._read_pass_batching_class(f.source.BoundSourcePacket(), root / 'extension.json', extension)
            extension = deepcopy(self.extension); extension['status'] = 'reviewed'
            extension['original_class']['sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'original finite class anchor'):
                f._read_pass_batching_class(f.source.BoundSourcePacket(), root / 'extension.json', extension)

    def test_external_reserved_state_cannot_bypass_new_schema_native_anchor(self):
        # Even an otherwise well-shaped synthetic comparison and self-refreshed
        # descriptor digest must not impersonate the verified loader's state.
        self.check()
        with tempfile.TemporaryDirectory() as folder, patch.object(f, 'PASS_BATCHING_NATIVE_REVIEW_SHA256', None):
            path = Path(folder) / 'injected.json'
            for schema in (f.SCHEMA, f.PASS_BATCHING_SCHEMA):
                for class_id in ('ads-offset-8f571464-finite-v1', f.PASS_BATCHING_CLASS):
                    injected = deepcopy(self.reviewed)
                    injected.update(schema=schema, class_id=class_id)
                    path.write_bytes(encoded(injected))
                    with self.subTest(schema=schema, class_id=class_id), patch.object(f, '_packet_class') as bind:
                        with self.assertRaisesRegex(ValueError, 'reserved internal pass-batching state'):
                            f.bind_finite_ads_profile(source_packet=None, source_packet_path=path,
                                reviewed_class=path,
                                expected_class_sha256=f._identity(path.read_bytes())['sha256'],
                                native_runtime_logs={})
                        bind.assert_not_called()

    def test_legacy_schema_cannot_select_new_class_without_verified_loader(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'wrong-class.json'
            descriptor = deepcopy(self.reviewed)
            descriptor.pop('_pass_batching')
            descriptor['class_id'] = f.PASS_BATCHING_CLASS
            path.write_bytes(encoded(descriptor))
            with patch.object(f, '_packet_class') as bind, self.assertRaisesRegex(ValueError, 'unknown reviewed'):
                f.bind_finite_ads_profile(source_packet=None, source_packet_path=path,
                    reviewed_class=path, expected_class_sha256=f._identity(path.read_bytes())['sha256'],
                    native_runtime_logs={})
            bind.assert_not_called()

    def test_native_anchor_and_late_receipt_mutation_are_independent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'original.json').write_bytes(self.original_bytes)
            report_path = root / 'synthetic.json'; report_path.write_bytes(encoded(self.report))
            extension = deepcopy(self.extension); extension['status'] = 'reviewed'
            extension['native_comparison'] = {'path': report_path.name, **f._identity(report_path.read_bytes())}
            with patch.object(f, 'PASS_BATCHING_NATIVE_REVIEW_SHA256', '0' * 64):
                with self.assertRaisesRegex(ValueError, 'native comparison anchor'):
                    f._read_pass_batching_class(f.source.BoundSourcePacket(), root / 'extension.json', extension)
            # Only this unit test substitutes an explicit synthetic trust anchor.
            with patch.object(f, 'PASS_BATCHING_NATIVE_REVIEW_SHA256', extension['native_comparison']['sha256']):
                ledger = f.source.BoundSourcePacket()
                reviewed = f._read_pass_batching_class(ledger, root / 'extension.json', extension)
                self.assertEqual(reviewed['evidence'], self.reviewed['evidence'])
                self.assertEqual(reviewed['equivalence'], self.reviewed['equivalence'])
                report_path.write_bytes(report_path.read_bytes() + b' ')
                with self.assertRaisesRegex(ValueError, 'late mutation'):
                    ledger.verify_unchanged()

    def test_plans_failed_partial_or_different_native_executions_reject(self):
        for key, value in (('status', 'failed'), ('native_execution', False), ('acceptance_complete', True),
                           ('acceptance_verdict', 'passed'), ('original_profile_flags_modified', True),
                           ('original_class_sha256', '0' * 64)):
            self.change_reject(self.report, key, value)
        self.change_reject(self.report['commits'], 'candidate', '0' * 40)
        for key, value in (('channels', 'RGB'), ('channel_tolerance', 1), ('capture_count', 20)):
            self.change_reject(self.report['comparison'], key, value)
        for label, variant in self.report['variants'].items():
            for key, value in (('compiler_sha256', '0' * 64), ('process_exit_code', 1), ('process_exit_code', False)):
                self.change_reject(variant, key, value)
            for key in (*f.DEVICE_FIELDS, 'adapter', 'backend', 'compiler'):
                self.change_reject(variant['runtime_identity'], key, 'changed')
            for key, value in (('passed', False), ('captures', 20), ('scope', 'synthetic fixture only')):
                self.change_reject(variant['fixed_contract_validation'], key, value)
            for key in ('source_receipt', 'contract_executable', 'contract_report', 'contract_log'):
                self.change_reject(variant, key, None)
            for key in ('rgba_sha256', 'png_sha256'):
                missing = dict(variant[key]); missing.pop(next(iter(missing)))
                self.change_reject(variant, key, missing)
            name = next(iter(variant['rgba_sha256']))
            self.change_reject(variant['rgba_sha256'], name, 'f' * 64)
            self.change_reject(variant['source_pair']['src/render/plan.rs'], 'sha256', '0' * 64)
        for key in ('summary', 'build_receipts', 'exact_pixels'):
            self.change_reject(self.report, key, None)
        for key in ('run_id', 'run_attempt', 'artifact_id'):
            self.change_reject(self.report['artifact'], key, '')

    def test_summary_keeps_historical_proof_and_distinct_native_review(self):
        original = deepcopy(self.reviewed); original.pop('_pass_batching')
        args = (None, f.source.BoundSourcePacket(), original, f.ORIGINAL_CLASS_SHA256, {}, {}, {}, 'C:/source')
        historical = f.BoundFiniteAdsProfile(*args).summary()
        self.assertNotIn('source_equivalence', historical)
        self.reviewed['class_id'] = f.PASS_BATCHING_CLASS
        current = f.BoundFiniteAdsProfile(None, f.source.BoundSourcePacket(), self.reviewed,
                                         'c' * 64, {}, {}, {}, 'C:/source').summary()
        self.assertEqual(current['evidence_sha256'], historical['evidence_sha256'])
        self.assertEqual(current['source_equivalence']['original_class_sha256'], f.ORIGINAL_CLASS_SHA256)
        self.assertFalse(current['native_profile_binding_verified'])
        self.assertFalse(current['profile_native_verified'])
        self.assertFalse(current['acceptance_complete'])
        current['source_equivalence']['source_pairs']['candidate'].clear()
        self.assertEqual(len(f.PASS_BATCHING_PAIRS['candidate']), 2)


class ReviewedActivationTests(unittest.TestCase):
    """Bind the retained actual review, without claiming a new native execution."""
    CLASS_SHA256 = '2895c1f4f0039f5a850c7b30196c5d77f4b2e563bc211f8b9fb51ca15f639c4c'
    REVIEW_SHA256 = '4c2ae5f087ac1e548a9285f635fbb17de9de3defbaa4fab0da014fdb5c976699'

    def setUp(self):
        self.path = Path(__file__).with_name('finite_ads_pass_batching_class.json')
        self.ledger = f.source.BoundSourcePacket()
        self.assertEqual(self.ledger._remember(self.path)['sha256'], self.CLASS_SHA256)
        self.extension = self.ledger._json(self.path)

    def test_actual_review_preserves_original_class_and_native_runtime_boundary(self):
        self.assertEqual(f.PASS_BATCHING_NATIVE_REVIEW_SHA256, self.REVIEW_SHA256)
        reviewed = f._read_pass_batching_class(self.ledger, self.path, self.extension)
        original = f.source._parse(self.path.with_name('finite_ads_reviewed_class.json').read_bytes(), 'original class')
        for key in original:
            if key != 'class_id':
                self.assertEqual(reviewed[key], original[key], key)
        self.assertEqual(reviewed['class_id'], f.PASS_BATCHING_CLASS)
        evidence = f._read_evidence(self.ledger, self.path, reviewed)
        f._pass_batching_evidence(reviewed, evidence['native']['native_identity'])
        self.assertEqual(reviewed['_pass_batching']['sha256'], self.REVIEW_SHA256)
        self.assertEqual(reviewed['_pass_batching']['comparison']['artifact'], {
            'run_id': '37482428571', 'run_attempt': '1', 'artifact_id': '11422371812',
            'archive_sha256': 'f29ff7c9fada89478e86f3bae86e0382350d1ac249771116dc920274de5b8994'})
        self.ledger.verify_unchanged()

    def test_pending_template_stays_unavailable_after_reviewed_variant_activation(self):
        path = self.path.with_name('finite_ads_pass_batching_class.pending.json')
        with self.assertRaisesRegex(ValueError, 'review pending'):
            f.bind_finite_ads_profile(source_packet=None, source_packet_path=path,
                reviewed_class=path, expected_class_sha256=f._identity(path.read_bytes())['sha256'],
                native_runtime_logs={})

    def test_changed_review_cannot_be_authorized_by_refreshing_descriptor_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'finite_ads_reviewed_class.json').write_bytes(
                self.path.with_name('finite_ads_reviewed_class.json').read_bytes())
            name = self.extension['native_comparison']['path']
            changed = (self.path.parent / name).read_bytes() + b' '
            (root / name).parent.mkdir()
            (root / name).write_bytes(changed)
            self.extension['native_comparison'].update(f._identity(changed))
            path = root / self.path.name
            path.write_bytes(encoded(self.extension))
            with self.assertRaisesRegex(ValueError, 'native comparison anchor'):
                f.bind_finite_ads_profile(source_packet=None, source_packet_path=path,
                    reviewed_class=path, expected_class_sha256=f._identity(path.read_bytes())['sha256'],
                    native_runtime_logs={})


if __name__ == '__main__':
    unittest.main()

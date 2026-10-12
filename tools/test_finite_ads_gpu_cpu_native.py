"""Synthetic native-review semantic controls; these are never native evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import finite_ads_profile_binding as f
from test_finite_ads_profile_binding import encoded


def fixture():
    """Explicitly synthetic report. Only tests substitute its independent anchor."""
    root = Path(__file__).parent
    ledger = f.source.BoundSourcePacket()
    path = root / 'finite_ads_pass_batching_class.json'
    reviewed = f._read_pass_batching_class(ledger, path, ledger._json(path))
    native = json.loads((root / reviewed['evidence']['native']['path']).read_bytes())['native_identity']
    runtime = {key: native[key] for key in (*f.DEVICE_FIELDS, 'adapter', 'backend', 'compiler')}
    parent = reviewed['_pass_batching']['comparison']
    inherited = parent['variants']['candidate']
    def identity(label):
        return f._identity(('synthetic guard fixture only: ' + label).encode())
    receipts = {name: identity(name) for name in f.GPU_CPU_RECEIPTS}
    receipts['compiler_stdout'] = {'bytes': reviewed['evidence']['compiler_before']['bytes'],
                                   'sha256': reviewed['equivalence']['compiler_sha256']}
    report = {'schema': 'rust-duty-gpu-cpu-native-review/v1', 'status': 'passed', 'native_execution': True,
        'original_class_sha256': f.ORIGINAL_CLASS_SHA256, 'batching_class_sha256': f.PASS_BATCHING_CLASS_SHA256,
        'batching_native_review_sha256': f.PASS_BATCHING_NATIVE_REVIEW_SHA256,
        'commits': {'baseline_source': f.GPU_CPU_COMMITS['baseline'],
                    'baseline_compiled_source': f.PASS_BATCHING_COMMITS['candidate'],
                    'candidate_source': f.GPU_CPU_COMMITS['candidate']},
        'comparison': {'channels': 'RGBA', 'channel_tolerance': 0, 'capture_count': 21},
        'review_flags': deepcopy(f.GPU_CPU_REVIEW_FLAGS), 'control_order': list(f.GPU_CPU_CONTROL_MODES),
        'native_compile_inventory_counts': {'baseline': 112, 'candidate': 113},
        'archive_preservation': {'raw_files_unchanged': True,
            'omitted_empty_directories': ['baseline-renderer-contract/capture-is-directory.png',
                                          'candidate-renderer-contract/capture-is-directory.png'],
            'independent_validation_used_separate_copy': True, 'original_native_fixed_validation_passed': True},
        'artifact': {'run_id': '2', 'run_attempt': '1', 'artifact_id': '3', 'archive_sha256': 'a' * 64},
        'receipts': receipts,
        'baseline_origin': {'artifact': deepcopy(parent['artifact']), 'source_receipt': deepcopy(inherited['source_receipt']),
            'contract_executable': deepcopy(inherited['contract_executable']), 'build_receipts': deepcopy(parent['build_receipts']),
            'complete_native_compile_inventory_equal': True},
        'control_executable': identity('control executable'), 'variants': {}, 'controls': {},
    }
    for label in ('baseline', 'candidate'):
        variant = {key: identity(label + '/' + key) for key in ('source_receipt', 'contract_executable',
                                                               'contract_process', 'contract_report', 'contract_log')}
        variant.update(class_source_variant=deepcopy(f.GPU_CPU_VARIANTS[label]), process_exit_code=0,
            compiler_sha256=reviewed['equivalence']['compiler_sha256'], runtime_identity=deepcopy(runtime),
            fixed_contract_validation=deepcopy(inherited['fixed_contract_validation']),
            rgba_sha256=deepcopy(inherited['rgba_sha256']), png_sha256=deepcopy(inherited['png_sha256']))
        if label == 'baseline':
            for key in ('source_receipt', 'contract_executable'):
                variant[key] = deepcopy(inherited[key])
        else:
            variant['source_receipt'] = receipts['candidate_source_receipt']
        report['variants'][label] = variant
    fingerprint = {'backend': 'dx12', 'name': runtime['adapter'], 'vendor_id': runtime['vendor_id'],
                   'device_id': runtime['device_id'], 'device_type': runtime['device_type']}
    for mode in f.GPU_CPU_CONTROL_MODES:
        saved = mode in ('seed', 'windowed-saved', 'windowed-cpu')
        preference = identity('seed preference' if saved else mode + ' preference')
        control = {'status': 'passed', 'source_commit': f.GPU_CPU_COMMITS['candidate'],
            'source_sha256': receipts['candidate_source_receipt']['sha256'],
            'compiled_source_sha256': receipts['candidate_source_receipt']['sha256'],
            'executable': report['control_executable'], 'pid': 100, 'process_exit_code': 0,
            **{name: identity(mode + '/' + name) for name in ('process', 'report', 'log')},
            'preference_before': None if mode == 'seed' else preference, 'preference_after': preference,
            'preference_fingerprint': deepcopy(fingerprint) if saved else {
                **fingerprint, 'name': 'Rust Duty deliberately missing adapter 100',
                'vendor_id': 2**32 - 1, 'device_id': 2**32 - 1},
            'outcome': deepcopy(f.GPU_CPU_OUTCOMES[mode]), 'creations': [],
            'physical_dimensions': None, 'captures': {}}
        if mode not in ('seed', 'windowed-missing'):
            forced_flags = (False, True) if mode == 'headless-bypass' else (mode == 'windowed-forced',)
            for forced in forced_flags:
                windowed = mode != 'headless-bypass'
                control['creations'].append({'runtime_identity': deepcopy(runtime), 'windowed': windowed,
                    'force_fallback_requested': forced, 'present_mode': 'Fifo' if windowed else None,
                    'selection_mode': 'forced_fallback' if forced else ('explicit_fingerprint' if windowed else 'automatic'),
                    'requested_fingerprint': deepcopy(fingerprint) if windowed and not forced else None,
                    'actual_fingerprint': deepcopy(fingerprint)})
            control['physical_dimensions'] = [320, 180]
            for name in (('headless-auto.png', 'headless-forced.png') if mode == 'headless-bypass' else ('windowed.png',)):
                control['captures'][name] = {'png': identity(mode + '/' + name), 'rgba_sha256': 'b' * 64,
                    'dimensions': [320, 180], 'fixed_pixels_verified': True, 'opaque_alpha_verified': True}
        report['controls'][mode] = control
    report['cpu_trace'] = {'trace': identity('live CPU trace'), 'source_commit': f.GPU_CPU_COMMITS['candidate'],
        'source_sha256': receipts['candidate_source_receipt']['sha256'],
        'compiled_source_sha256': receipts['candidate_source_receipt']['sha256'],
        'executable': report['control_executable'], 'runtime_identity': deepcopy(runtime),
        'present_mode': 'Fifo', 'physical_dimensions': [320, 180], 'reader_validation': {
            'status': 'passed', 'complete_trace_validated': True, 'measurement': 'cpu_wall_clock_paired_frame_stage_ns',
            'uninstrumented_present_count': 1, 'recorded_present_count': 5, 'complete_cpu_sample_count': 4,
            'first_recorded_present_has_cpu_sample': False, 'normal_final_present_export': True,
            'integer_time_bounds_verified': True, 'ordered_disjoint_spans_verified': True,
            'dimensions_match_window': True, 'gpu_duration_measured': False, 'rtx_or_1080p60_acceptance': False,
            'acceptance_complete': False, 'acceptance_verdict': None,
            'eligible_interval_samples': {name: 3 for name in f.GPU_CPU_STAGES}}}
    reviewed['class_id'] = f.GPU_CPU_CLASS
    reviewed['_gpu_cpu'] = {'comparison': report, 'sha256': identity('synthetic native review')['sha256']}
    return reviewed, native, report


class NativeReviewTests(unittest.TestCase):
    def setUp(self):
        self.reviewed, self.native, self.report = fixture()

    def check(self):
        f._gpu_cpu_evidence(self.reviewed, self.native)

    def reject(self, target, key, value):
        old = target[key]
        target[key] = value
        try:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.check()
        finally:
            target[key] = old

    def test_valid_synthetic_semantics_never_supply_the_real_native_anchor(self):
        self.check()
        self.assertNotEqual(f.GPU_CPU_NATIVE_REVIEW_SHA256, f._identity(encoded(self.report))['sha256'])
        # All six PIDs are deliberately identical: sequential Windows PIDs may be reused.
        self.assertEqual(len({x['pid'] for x in self.report['controls'].values()}), 1)

    def test_every_object_rejects_missing_and_extra_keys(self):
        def dictionaries(value):
            if type(value) is dict:
                yield value
                for child in list(value.values()):
                    yield from dictionaries(child)
            elif type(value) is list:
                for child in value:
                    yield from dictionaries(child)
        for obj in list(dictionaries(self.report)):
            if obj:
                key = next(iter(obj)); value = obj.pop(key)
                try:
                    with self.subTest(missing=key), self.assertRaises(ValueError): self.check()
                finally: obj[key] = value
            obj['unreviewed_extra'] = True
            try:
                with self.assertRaises(ValueError): self.check()
            finally: obj.pop('unreviewed_extra')

    def test_nonempty_digests_types_partial_inventory_and_original_anchors(self):
        for key in ('original_class_sha256', 'batching_class_sha256', 'batching_native_review_sha256'):
            self.reject(self.report, key, '0' * 64)
        for key in self.report['commits']:
            self.reject(self.report['commits'], key, '0' * 40)
        for key in ('run_id', 'run_attempt', 'artifact_id'):
            for value in (1, '', '0', True): self.reject(self.report['artifact'], key, value)
        for item in self.report['receipts'].values():
            for value in (0, False, '20'): self.reject(item, 'bytes', value)
            self.reject(item, 'sha256', 'a' * 63)
        self.reject(self.report['receipts']['compiler_stdout'], 'bytes',
                    self.reviewed['evidence']['compiler_before']['bytes'] + 1)
        for key in self.report['native_compile_inventory_counts']:
            self.reject(self.report['native_compile_inventory_counts'], key, True)
        self.reject(self.report, 'control_order', list(reversed(f.GPU_CPU_CONTROL_MODES)))
        self.reject(self.report, 'native_execution', False)
        self.reject(self.report, 'status', 'pending')
        self.reject(self.report['comparison'], 'channel_tolerance', 1)
        self.reject(self.report['comparison'], 'capture_count', 20)

    def test_all_review_flags_and_masks_are_fixed(self):
        for key, value in self.report['review_flags'].items():
            self.reject(self.report['review_flags'], key, True if value is None else not value)

    def test_baseline_origin_requires_actual_parent_binary_receipt_and_complete_inventory(self):
        for name in ('source_receipt', 'contract_executable', 'build_receipts'):
            self.reject(self.report['baseline_origin'][name], 'sha256', '0' * 64)
        self.reject(self.report['baseline_origin'], 'complete_native_compile_inventory_equal', False)
        self.reject(self.report['artifact'], 'run_id', self.report['baseline_origin']['artifact']['run_id'])
        for name in ('source_receipt', 'contract_executable'):
            self.reject(self.report['variants']['baseline'][name], 'sha256', '0' * 64)

    def test_variant_source_device_compiler_pixels_process_and_fixed_expectations(self):
        for label, variant in self.report['variants'].items():
            self.reject(variant['class_source_variant']['production']['src/render/frame.rs'], 'sha256', '0' * 64)
            self.reject(variant, 'compiler_sha256', '0' * 64)
            for name in variant['runtime_identity']:
                self.reject(variant['runtime_identity'], name, 'wrong')
            for value in (False, 1): self.reject(variant, 'process_exit_code', value)
            for name in ('passed', 'captures', 'scope'):
                self.reject(variant['fixed_contract_validation'], name, 'wrong')
            name = next(iter(variant['rgba_sha256']))
            self.reject(variant['rgba_sha256'], name, 'c' * 64)
            self.reject(variant['png_sha256'], name, None)
        self.reject(self.report['variants']['candidate']['source_receipt'], 'sha256', '0' * 64)

    def test_each_control_requires_exact_outcome_linkage_preferences_and_creations(self):
        for mode, control in self.report['controls'].items():
            for name in ('source_commit', 'source_sha256', 'compiled_source_sha256'):
                self.reject(control, name, 'wrong')
            self.reject(control, 'pid', True)
            self.reject(control, 'process_exit_code', False)
            self.reject(control, 'status', 'failed')
            for name, value in control['outcome'].items():
                self.reject(control['outcome'], name, 'wrong' if type(value) is str else not value)
            if mode != 'seed':
                self.reject(control, 'preference_before', f._identity(b'different preference'))
            for creation in control['creations']:
                for name in creation:
                    self.reject(creation, name, 'wrong')
            if control['captures']:
                self.reject(control, 'physical_dimensions', [True, 180])
                for capture in control['captures'].values():
                    self.reject(capture, 'fixed_pixels_verified', False)
                    self.reject(capture, 'opaque_alpha_verified', False)
            else:
                self.reject(control, 'physical_dimensions', [320, 180])
        self.reject(self.report['controls']['seed'], 'preference_before', f._identity(b'existing'))
        self.reject(self.report['controls']['windowed-saved'], 'process', self.report['controls']['seed']['process'])
        creations = self.report['controls']['headless-bypass']['creations']
        self.reject(self.report['controls']['headless-bypass'], 'creations', creations[:1])
        self.reject(self.report['controls']['headless-bypass'], 'creations', list(reversed(creations)))

    def test_live_trace_does_not_accept_invented_first_sample_missing_stages_or_gpu_claims(self):
        trace = self.report['cpu_trace']
        for name in ('source_commit', 'source_sha256', 'compiled_source_sha256', 'present_mode'):
            self.reject(trace, name, 'wrong')
        self.reject(trace, 'physical_dimensions', [640, 360])
        for key, value in trace['reader_validation'].items():
            if key != 'eligible_interval_samples':
                self.reject(trace['reader_validation'], key, 'wrong' if type(value) is str else not value)
        self.reject(trace['reader_validation']['eligible_interval_samples'], 'surface_acquire', 2)
        for name in f.GPU_CPU_STAGES:
            for count in (True, 1, 5): self.reject(trace['reader_validation']['eligible_interval_samples'], name, count)

    def test_summary_explicitly_separates_parent_proof_and_new_source(self):
        result = f.BoundFiniteAdsProfile(None, f.source.BoundSourcePacket(), self.reviewed, 'f' * 64,
                                         {}, {}, {}, 'C:/source').summary()
        current = result['source_equivalence']
        self.assertNotIn('source_pairs', current)
        self.assertEqual(current['source_variants'], f.GPU_CPU_VARIANTS)
        self.assertEqual(current['historical_batching_parent']['source_pairs'], f.PASS_BATCHING_PAIRS)
        self.assertEqual(result['evidence_sha256'], {key: x['sha256'] for key, x in self.reviewed['evidence'].items()})
        for key in f.FALSE_FLAGS: self.assertIs(result[key], False)
        self.assertIsNone(result['acceptance_verdict'])
        current['source_variants'].clear()
        self.assertEqual(len(f.GPU_CPU_VARIANTS), 2)


class AnchoredLoaderTests(unittest.TestCase):
    def setUp(self):
        self.reviewed, self.native, self.report = fixture()
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / 'extension.json'
        self.report_path = self.root / 'synthetic-review.json'
        self.report_path.write_bytes(encoded(self.report))
        # Copy only already retained immutable descriptor/receipt files required
        # by the loader. Their bytes and fixed independent anchors remain real.
        tools = Path(__file__).parent
        for name in ('finite_ads_reviewed_class.json', 'finite_ads_pass_batching_class.json',
                     'finite_ads_pass_batching_evidence/native-review.json'):
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((tools / name).read_bytes())
        self.extension = json.loads((tools / 'finite_ads_gpu_cpu_class.pending.json').read_bytes())
        self.extension['status'] = 'reviewed'
        self.extension['native_comparison'] = {'path': self.report_path.name, **f._identity(self.report_path.read_bytes())}
        self.path.write_bytes(encoded(self.extension))

    def bind(self):
        return f.bind_finite_ads_profile(source_packet=None, source_packet_path=self.root / 'packet.json',
            reviewed_class=self.path, expected_class_sha256=f._identity(self.path.read_bytes())['sha256'],
            native_runtime_logs={})

    def test_no_real_anchor_or_wrong_independent_anchor_can_load_a_self_anchored_receipt(self):
        with patch.object(f, 'GPU_CPU_NATIVE_REVIEW_SHA256', None):
            with self.assertRaisesRegex(ValueError, 'anchor unavailable'): self.bind()
        with patch.object(f, 'GPU_CPU_NATIVE_REVIEW_SHA256', '0' * 64):
            with self.assertRaisesRegex(ValueError, 'native comparison anchor'): self.bind()

    def test_synthetic_independent_anchor_loads_chain_and_correct_dispatch_reaches_packet(self):
        digest = self.extension['native_comparison']['sha256']
        with patch.object(f, 'GPU_CPU_NATIVE_REVIEW_SHA256', digest):
            ledger = f.source.BoundSourcePacket()
            reviewed = f._read_gpu_cpu_class(ledger, self.path, self.extension)
            self.assertEqual(reviewed['class_id'], f.GPU_CPU_CLASS)
            self.assertEqual(reviewed['equivalence'], self.reviewed['equivalence'])
            self.assertEqual(reviewed['evidence'], self.reviewed['evidence'])
            f._pass_batching_evidence(reviewed, self.native)
            f._gpu_cpu_evidence(reviewed, self.native)
            with patch.object(f, '_packet_class', side_effect=RuntimeError('packet boundary reached')) as packet:
                with self.assertRaisesRegex(RuntimeError, 'packet boundary reached'): self.bind()
                self.assertEqual(packet.call_args.args[2]['class_id'], f.GPU_CPU_CLASS)
            ledger.verify_unchanged()
            self.report_path.write_bytes(self.report_path.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'late mutation'): ledger.verify_unchanged()

    def test_semantics_run_after_both_historical_native_layers(self):
        bound = f.source.BoundSourcePacket()
        empty_row = {'classification': 'expected_empty_under_profile',
            'required_contrast_runs': [], 'possible_support_runs': [], 'required_contrast_samples': 0,
            'possible_samples': 0, 'unclassified_triangles': 0, 'source_triangles': 0,
            'outside_bottom': 0, 'hidden_source_triangles': 0, 'meshes': []}
        bound.rows_by_role = {role: [deepcopy(empty_row) for _ in range(553)] for role in f.source.ROLES}
        events = []
        historical = f._pass_batching_evidence
        current = f._gpu_cpu_evidence
        def parent_evidence(reviewed, native):
            events.append('batching'); historical(reviewed, native)
        def new_evidence(reviewed, native):
            events.append('gpu_cpu'); current(reviewed, native)
        with patch.object(f, 'GPU_CPU_NATIVE_REVIEW_SHA256', self.extension['native_comparison']['sha256']), \
             patch.object(f, '_packet_class', return_value={}), \
             patch.object(f, '_read_evidence', return_value={key: {} for key in f.EVIDENCE_KEYS}) as read_evidence, \
             patch.object(f, '_comparison'), \
             patch.object(f, '_native_build', side_effect=lambda *args: events.append('native_build')), \
             patch.object(f, '_native_evidence', side_effect=lambda *args: events.append('native') or self.native), \
             patch.object(f, '_pass_batching_evidence', side_effect=parent_evidence), \
             patch.object(f, '_gpu_cpu_evidence', side_effect=new_evidence), \
             patch.object(f, '_gl_rows', side_effect=RuntimeError('later GL boundary')):
            with self.assertRaisesRegex(RuntimeError, 'later GL boundary'):
                f.bind_finite_ads_profile(source_packet=bound, source_packet_path=self.root / 'packet.json',
                    reviewed_class=self.path, expected_class_sha256=f._identity(self.path.read_bytes())['sha256'],
                    native_runtime_logs={})
            self.assertEqual(events, ['native_build', 'native', 'batching', 'gpu_cpu'])
            self.assertEqual(read_evidence.call_args.args[1], self.root / 'finite_ads_reviewed_class.json')

    def test_each_loaded_parent_or_native_receipt_is_in_late_mutation_ledger(self):
        names = ('finite_ads_reviewed_class.json', 'finite_ads_pass_batching_class.json',
                 'finite_ads_pass_batching_evidence/native-review.json', self.report_path.name)
        for name in names:
            with patch.object(f, 'GPU_CPU_NATIVE_REVIEW_SHA256', self.extension['native_comparison']['sha256']):
                ledger = f.source.BoundSourcePacket()
                f._read_gpu_cpu_class(ledger, self.path, self.extension)
                target = self.root / name; raw = target.read_bytes()
                try:
                    target.write_bytes(raw + b' ')
                    with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'late mutation'):
                        ledger.verify_unchanged()
                finally:
                    target.write_bytes(raw)

    def test_nested_reserved_markers_are_rejected_even_with_synthetic_anchor(self):
        digest = self.extension['native_comparison']['sha256']
        for marker in ('_pass_batching', '_gpu_cpu'):
            wrong = deepcopy(self.report); wrong[marker] = {}
            self.report_path.write_bytes(encoded(wrong))
            self.extension['native_comparison'].update(f._identity(self.report_path.read_bytes()))
            self.path.write_bytes(encoded(self.extension))
            with patch.object(f, 'GPU_CPU_NATIVE_REVIEW_SHA256', self.extension['native_comparison']['sha256']):
                with self.assertRaisesRegex(ValueError, 'reserved internal'): self.bind()


class ActualReviewedActivationTests(unittest.TestCase):
    CLASS_SHA256 = '91bd0030157ff8e1b4e70127b028e57543d8fc91fb3b6cc1202c4707491fb798'
    NATIVE_SHA256 = 'bbc92e18d4092dbd8a1a005fc12d7d8457411a7e821b39dc28c7ca04a90459c5'

    def test_actual_receipt_chains_historical_proofs_and_preserves_all_false_flags(self):
        root = Path(__file__).parent
        path = root / 'finite_ads_gpu_cpu_class.json'
        ledger = f.source.BoundSourcePacket()
        self.assertEqual(ledger._remember(path)['sha256'], self.CLASS_SHA256)
        self.assertEqual(f.GPU_CPU_NATIVE_REVIEW_SHA256, self.NATIVE_SHA256)
        reviewed = f._read_gpu_cpu_class(ledger, path, ledger._json(path))
        self.assertEqual(reviewed['class_id'], f.GPU_CPU_CLASS)
        original = f.source._parse((root / 'finite_ads_reviewed_class.json').read_bytes(), 'original')
        for key in original:
            if key != 'class_id': self.assertEqual(reviewed[key], original[key], key)
        evidence = f._read_evidence(ledger, reviewed['_gpu_cpu']['evidence_class_path'], reviewed)
        native = evidence['native']['native_identity']
        f._pass_batching_evidence(reviewed, native)
        f._gpu_cpu_evidence(reviewed, native)
        comparison = reviewed['_gpu_cpu']['comparison']
        self.assertEqual(comparison['artifact'], {'run_id': '37498157663', 'run_attempt': '1',
            'artifact_id': '11429256247',
            'archive_sha256': '48f20d929f43c073900ab017732e13259e7d4413da07bf844ef9b411989aa8ec'})
        self.assertEqual(comparison['cpu_trace']['reader_validation']['eligible_interval_samples'],
                         {stage: 4 for stage in f.GPU_CPU_STAGES})
        summary = f.BoundFiniteAdsProfile(None, ledger, reviewed, self.CLASS_SHA256,
                                         {}, {}, {}, 'C:/source').summary()
        for flag in f.FALSE_FLAGS: self.assertIs(summary[flag], False)
        self.assertIsNone(summary['acceptance_verdict'])
        self.assertEqual(summary['source_equivalence']['native_comparison_sha256'], self.NATIVE_SHA256)
        ledger.verify_unchanged()

    def test_activated_reader_still_requires_fresh_validated_source_packet(self):
        path = Path(__file__).with_name('finite_ads_gpu_cpu_class.json')
        with self.assertRaisesRegex(ValueError, 'complete source packet must already be bound'):
            f.bind_finite_ads_profile(source_packet=None, source_packet_path=path,
                reviewed_class=path, expected_class_sha256=self.CLASS_SHA256, native_runtime_logs={})

    def test_reviewed_and_historical_artifacts_disable_checkout_byte_conversion(self):
        root = Path(__file__).resolve().parents[1]
        names = ['tools/finite_ads_reviewed_class.json', 'tools/finite_ads_pass_batching_class.json',
                 'tools/finite_ads_gpu_cpu_class.json', 'tools/finite_ads_gpu_cpu_evidence/native-review.json']
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder); (target / '.gitattributes').write_bytes((root / '.gitattributes').read_bytes())
            subprocess.run(['git', '-C', str(target), 'init', '--quiet'], check=True, capture_output=True)
            result = subprocess.check_output(['git', '-C', str(target), 'check-attr', 'text', '--', *names], text=True)
            self.assertEqual(result.splitlines(), [name + ': text: unset' for name in names])

    def test_historical_revalidation_stays_on_its_prebatch_compatible_class(self):
        root = Path(__file__).resolve().parents[1]
        body = (root / '.github/workflows/revalidate-ads-source.yml').read_text()
        self.assertEqual(body.count('--reviewed-class verifier/tools/finite_ads_pass_batching_class.json'), 2)
        self.assertEqual(body.count('--expected-class-sha256 ' + f.PASS_BATCHING_CLASS_SHA256), 2)
        self.assertNotIn('--reviewed-class verifier/tools/finite_ads_gpu_cpu_class.json', body)


if __name__ == '__main__':
    unittest.main()

"""Independent synthetic guards for the named, one-file arena experiment.

No compiler, game, profiler, GPU, or external process is executed here.
"""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import performance_matrix as matrix
import run_cpu_image_preservation as image
import run_windows_cpu_profile as profile
import test_geometry_profile_pair as geometry_tests


class ArenaSourcePairTests(unittest.TestCase):
    def setUp(self):
        self.production = {'Cargo.toml': b'synthetic manifest',
                           'src/render/plan.rs': b'unchanged plan',
                           image.ARENA_PATH: b'new stack-packed scalar bytes',
                           image.UPLOAD_POLICY_PATH: b'pub const REUSE_ENABLED: bool = true;\n'}
        self.old = {image.ARENA_PATH: b'old scalar byte encoder'}
        self.harness = {name: ('common fixture ' + name).encode() for name in image.HARNESS_PATHS}
        for item in (patch.object(image, 'PRODUCTION_MANIFEST', matrix.canonical_hash(image.hashes(self.production))),
                     patch.object(image, 'ARENA_BASELINE_SHA256', image.controls.digest(self.old[image.ARENA_PATH]))):
            item.start()
            self.addCleanup(item.stop)

    def test_exactly_arena_changes_without_mutating_inputs_or_upload_policy(self):
        original = copy.deepcopy((self.production, self.old))
        variants = image.serialization_production_pair(self.production, self.old)
        self.assertEqual((self.production, self.old), original)
        self.assertEqual(variants['candidate'], self.production)
        self.assertEqual(variants['baseline'][image.ARENA_PATH], self.old[image.ARENA_PATH])
        self.assertEqual({key for key in self.production if variants['baseline'][key] != variants['candidate'][key]},
                         {image.ARENA_PATH})
        self.assertEqual(variants['baseline'][image.UPLOAD_POLICY_PATH], variants['candidate'][image.UPLOAD_POLICY_PATH])
        variants['candidate']['Cargo.toml'] = b'local result edit'
        self.assertEqual((self.production, self.old), original)

    def test_closed_compile_inventory_rejects_changed_added_or_missing_inputs(self):
        mutations = ({**self.production, 'src/render/plan.rs': b'changed'},
                     {**self.production, 'src/unreviewed.rs': b'added'},
                     {name: raw for name, raw in self.production.items() if name != 'Cargo.toml'})
        for production in mutations:
            with self.subTest(production=production), self.assertRaisesRegex(ValueError, 'compile inventory'):
                image.serialization_production_pair(production, self.old)

    def test_historical_overlay_must_have_one_exact_file_and_exact_bytes(self):
        for old in ({}, {image.ARENA_PATH: b'altered'},
                    {**self.old, image.UPLOAD_POLICY_PATH: image.UPLOAD_POLICY_DISABLED},
                    {'src/render/other.rs': self.old[image.ARENA_PATH]}):
            with self.subTest(old=old), self.assertRaisesRegex(ValueError, 'baseline arena'):
                image.serialization_production_pair(self.production, old)

    def test_rebound_inventory_cannot_disable_remove_or_duplicate_enabled_policy(self):
        for policy in (None, b'', image.UPLOAD_POLICY_DISABLED, image.UPLOAD_POLICY_ENABLED * 2,
                       image.UPLOAD_POLICY_ENABLED + image.UPLOAD_POLICY_DISABLED):
            production = dict(self.production)
            if policy is None:
                production.pop(image.UPLOAD_POLICY_PATH)
            else:
                production[image.UPLOAD_POLICY_PATH] = policy
            with self.subTest(policy=policy), patch.object(image, 'PRODUCTION_MANIFEST',
                    matrix.canonical_hash(image.hashes(production))):
                with self.assertRaisesRegex(ValueError, 'enabled upload reuse'):
                    image.serialization_production_pair(production, self.old)

    def test_rebound_inventory_still_requires_a_real_arena_only_delta(self):
        for production in ({**self.production, **self.old},
                           {name: raw for name, raw in self.production.items() if name != image.ARENA_PATH}):
            with self.subTest(production=production), patch.object(image, 'PRODUCTION_MANIFEST',
                    matrix.canonical_hash(image.hashes(production))):
                with self.assertRaisesRegex(ValueError, 'exactly the arena'):
                    image.serialization_production_pair(production, self.old)

    def test_metadata_distinguishes_serialization_from_historical_experiments(self):
        metadata = image.experiment_metadata('arena-serialization')
        self.assertEqual(metadata['experiment'], 'arena-serialization')
        self.assertEqual(metadata['overlay_paths'], [image.ARENA_PATH])
        self.assertEqual(metadata['baseline_arena_origin'], image.BASELINE_CPU_COMMIT)
        self.assertEqual(metadata['baseline_arena_sha256'], image.ARENA_BASELINE_SHA256)
        self.assertFalse(metadata['baseline_is_four_file_counterfactual'])
        self.assertEqual(metadata['upload_policies'], dict.fromkeys(('baseline', 'candidate'), 'bounded_reuse_v1'))
        geometry = image.geometry_production_pair(self.production)
        self.assertEqual(geometry['baseline'][image.ARENA_PATH], geometry['candidate'][image.ARENA_PATH])
        self.assertIn(image.UPLOAD_POLICY_DISABLED, geometry['baseline'][image.UPLOAD_POLICY_PATH])
        self.assertTrue(image.experiment_metadata('cpu-overlay')['baseline_is_four_file_counterfactual'])
        self.assertEqual(image.experiment_metadata('geometry-reuse')['upload_policies']['baseline'], 'immutable_per_frame_v1')

    def test_prepare_reads_only_exact_historical_arena_and_retains_full_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for name, raw in {**self.production, **self.harness}.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            calls = []
            binding = {'source_commit': 'a' * 40}

            def read_sources(actual_root, commit, paths):
                self.assertEqual(actual_root, root)
                calls.append((commit, paths))
                if commit == image.BASELINE_CPU_COMMIT:
                    self.assertEqual(paths, [image.ARENA_PATH])
                    return self.old.copy()
                self.assertEqual(commit, binding['source_commit'])
                return self.harness.copy() if paths == image.HARNESS_PATHS else self.production.copy()

            with patch.object(image, '__file__', str(root / 'tools/run_cpu_image_preservation.py')), \
                    patch.object(image.session, 'source_binding', return_value=binding), \
                    patch.object(image, 'read_sources', side_effect=read_sources), \
                    patch.object(image.subprocess, 'Popen', side_effect=AssertionError('No process is permitted')):
                actual, receipts = image.prepare(root, root / 'evidence', 'arena-serialization')
            self.assertEqual(actual, binding)
            self.assertEqual(calls.count((image.BASELINE_CPU_COMMIT, [image.ARENA_PATH])), 1)
            image.verify_sources(receipts)
            for label, receipt in receipts.items():
                saved = matrix.json_read(receipt['receipt_path'])
                self.assertEqual(saved['files_sha256'], image.controls.source_manifest(receipt['source']))
                self.assertEqual(saved['upload_policies'], dict.fromkeys(('baseline', 'candidate'), 'bounded_reuse_v1'))
                self.assertEqual(saved['integrated_source_commit'], binding['source_commit'])
                self.assertEqual(saved['variant'], label)
                for name, raw in self.harness.items():
                    self.assertEqual((receipt['source'] / name).read_bytes(), raw)
            (receipts['baseline']['source'] / image.ARENA_PATH).write_bytes(b'late source mutation')
            with self.assertRaisesRegex(ValueError, 'variant source changed'):
                image.verify_sources(receipts)


class ArenaProfileFlowTests(unittest.TestCase):
    # Reuse the genuinely wired two-build/four-process synthetic harness rather
    # than duplicating the producer, validators, or mutable receipt graph.
    flow = geometry_tests.GeometryProfilePairTests.flow

    def test_two_fresh_builds_and_abba_keep_reuse_enabled_and_bind_experiment(self):
        self.flow(experiment='arena-serialization')
        output = self.last['output']
        self.assertEqual(self.last['events'], [('build', 'baseline'), ('build', 'candidate'),
                         ('sample', 'baseline'), ('sample', 'candidate'), ('sample', 'candidate'), ('sample', 'baseline')])
        baseline = image.controls.source_manifest(output / 'sources/baseline-source')
        candidate = image.controls.source_manifest(output / 'sources/candidate-source')
        self.assertEqual({name for name in baseline if baseline[name] != candidate[name]}, {image.ARENA_PATH})
        self.assertEqual(baseline[image.UPLOAD_POLICY_PATH], candidate[image.UPLOAD_POLICY_PATH])
        summary = matrix.json_read(output / 'pair-summary.json')
        self.assertTrue(summary['passed'])
        self.assertEqual(summary['experiment'], 'arena-serialization')
        self.assertEqual(matrix.json_read(output / 'pair-inputs.json')['experiment'], 'arena-serialization')
        self.assertEqual(summary['diagnostic_runs_complete'], 4)
        self.assertIsNone(summary['performance_improvement'])
        self.assertFalse(summary['target_1080p60_proven'])
        self.assertTrue(all(row['measurements']['upload_policy'] == 'bounded_reuse_v1' for row in summary['runs']))
        for label in ('baseline', 'candidate'):
            build = matrix.json_read(output / (label + '-build/build.json'))
            receipt = output / ('sources/' + label + '-source.json')
            self.assertEqual(build['source_receipt_sha256'], matrix.sha256(receipt))
            self.assertEqual(build['compiled_files_sha256'], matrix.json_read(receipt)['files_sha256'])
            self.assertEqual(build['counterfactual'], label == 'baseline')

    def test_serialization_cannot_silently_measure_immutable_uploads(self):
        with self.assertRaisesRegex(ValueError, 'upload policy differs'):
            self.flow(mutation='policy', experiment='arena-serialization')
        self.assertFalse((self.last['output'] / 'pair-summary.json').exists())

    def test_serialization_preserves_source_binary_and_prior_capture_guards(self):
        for mutation in ('compiled_source', 'compiler', 'cargo_config', 'prior_pdb', 'source_receipt',
                         'verifier_receipt', 'assets', 'prior_record', 'prior_report', 'device', 'final_checks'):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.flow(mutation=mutation, experiment='arena-serialization')
            self.assertFalse((self.last['output'] / 'pair-summary.json').exists())
            self.assertTrue((self.last['output'] / 'pair-failure.json').is_file())

    def test_failed_normal_exits_remain_failed_with_all_four_diagnostics_retained(self):
        with self.assertRaisesRegex(ValueError, 'normal capture exits failed'):
            self.flow(failed_shutdown=True, experiment='arena-serialization')
        summary = matrix.json_read(self.last['output'] / 'pair-summary.json')
        self.assertEqual(summary['experiment'], 'arena-serialization')
        self.assertEqual(summary['diagnostic_runs_complete'], 4)
        self.assertFalse(summary['passed'])
        self.assertTrue(all(not row['capture_passed'] for row in summary['runs']))


class ArenaSelectionTests(unittest.TestCase):
    def test_explicit_cli_selection_preserves_existing_upload_default(self):
        for mode, experiment in (('compare-serialization', 'arena-serialization'),
                                 ('compare-uploads', 'geometry-reuse')):
            with self.subTest(mode=mode), patch.object(profile, 'compare_uploads') as compare:
                self.assertEqual(profile.main([mode, '--root', '.', '--output', 'synthetic-output']), 0)
                compare.assert_called_once_with(Path('.'), Path('synthetic-output'), experiment)
        self.assertEqual(profile.compare_uploads.__defaults__, ('geometry-reuse',))

    def test_historical_arena_hash_and_origin_are_explicit(self):
        self.assertEqual(image.ARENA_BASELINE_SHA256,
                         '5e39d00125b34d07ec23f845841809c0effa678980b1395988880b7d23674ddb')
        self.assertEqual(image.BASELINE_CPU_COMMIT, '70ff2933ebe69b7180e207c7defebeaeb6e240e1')


if __name__ == '__main__':
    unittest.main()

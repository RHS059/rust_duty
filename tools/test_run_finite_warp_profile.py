"""Closed workflow, state equality and later-corroboration lifecycle checks.

These tests do not execute Rust, Cargo, WARP or any original capture.
"""
from copy import deepcopy
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml

import run_finite_warp_profile as runner

ROOT = Path(__file__).resolve().parents[1]


def row(frame):
    return {'frame': frame, 'native_gameplay': {'clip': 'ads', 'ammo': 12},
            'native_time': {'sampling_hz': 59.94}, 'unsupported_clip_triangles': 0,
            'possible_support_complete': True, 'classification': 'potentially_visible_unresolved',
            'required_contrast_samples': 1, 'possible_samples': 2,
            'required_contrast_runs': [[100, 1]], 'possible_support_runs': [[100, 2]],
            'source_triangles': 1, 'outside_bottom': 0, 'hidden_source_triangles': 0,
            'unclassified_triangles': 1, 'meshes': [], 'acceptance_verdict': None}


def domain():
    return {'domain': {'normal_or_exact_zero_no_overflow': True, 'unsupported_domain_nodes': 0,
                       'checked_abstract_nodes': 50, 'minimum_nonzero_dyadic_exponent': -96,
                       'maximum_rounded_magnitude_upper': 2.2}}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def traces(self, *, empty=False):
        header = {'schema': 'rust-duty-source-visibility-certificate-diagnostic/v2',
                  'backend_profile': runner.binding.BACKEND_PROFILES['dx12'],
                  'acceptance_verdict': None, **{key: False for key in runner.extraction.UNPROVEN_FLAGS}}
        rows = [row(frame) for frame in range(553)]
        if empty:
            rows[17].update(classification='expected_empty_under_profile', required_contrast_samples=0,
                            possible_samples=0, required_contrast_runs=[], possible_support_runs=[],
                            outside_bottom=1, unclassified_triangles=0,
                            meshes=[{'state': 'enumerated', 'unclassified': 0, 'outside_bottom': 1,
                                     'triangles': 1, 'maximum_bottom_upper': -0.01}])
        current = {**deepcopy(rows[17]), 'geometry_domain': [domain()],
                   'triangle_trace': [] if empty else [{'triangle': 0}], 'original_native_observations': False}
        new_header = {**header, 'schema': 'rust-duty-source-geometry-probe/v1',
                      'source_certificate_schema': header['schema'], 'requested_frames': [17],
                      'original_native_observations': False}
        original, trace = self.root / 'original.jsonl', self.root / 'trace.jsonl'
        original.write_text('\n'.join(map(json.dumps, [header, *rows])) + '\n')
        trace.write_text('\n'.join(map(json.dumps, [new_header, current])) + '\n')
        return original, trace, new_header, current

    def compare(self, original, trace, **kwargs):
        return runner.compare_trace(trace, original, [17], 'dx12', **kwargs)

    def test_visible_and_empty_compare_all_original_state_and_domain(self):
        for empty in (False, True):
            original, trace, _, _ = self.traces(empty=empty)
            result = self.compare(original, trace, empty=empty)
            self.assertTrue(result['frames'][0]['full_original_state_equal'])
            self.assertEqual(result['frames'][0]['empty_support_separated'], empty)
            self.assertFalse(result['profile_native_verified'])
            self.assertIsNone(result['acceptance_verdict'])

    def test_proof_bound_difference_has_exact_values_and_distinct_category(self):
        report = runner.differences({'meshes': [{'maximum_bottom_upper': -0.01}]},
                                    {'meshes': [{'maximum_bottom_upper': -0.010000000000000002}]})
        self.assertEqual(report, [{'field': '/meshes/0/maximum_bottom_upper', 'category': 'derived_proof_bound',
                                   'original': -0.010000000000000002, 'later': -0.01}])
        error = runner.TraceMismatch(217, report)
        self.assertEqual(error.details['frame'], 217)
        self.assertEqual(error.details['differences'], report)

    def test_mask_gameplay_time_extra_missing_and_duplicate_frames_fail(self):
        original, trace, header, current = self.traces()
        variants = []
        changed = deepcopy(current); changed['required_contrast_runs'] = [[101, 1]]; variants.append(changed)
        changed = deepcopy(current); changed['native_gameplay']['ammo'] = 11; variants.append(changed)
        changed = deepcopy(current); changed['native_time']['sampling_hz'] = 60; variants.append(changed)
        changed = deepcopy(current); changed['extra'] = True; variants.append(changed)
        changed = deepcopy(current); del changed['native_time']; variants.append(changed)
        for changed in variants:
            trace.write_text('\n'.join(map(json.dumps, [header, changed])) + '\n')
            with self.assertRaises(ValueError):
                self.compare(original, trace, empty=False)
        for rows in ([], [current, current]):
            trace.write_text('\n'.join(map(json.dumps, [header, *rows])) + '\n')
            with self.assertRaises(ValueError):
                self.compare(original, trace, empty=False)

    def test_unsupported_or_nonfinite_domain_never_passes(self):
        original, trace, header, current = self.traces()
        for key, value in (('normal_or_exact_zero_no_overflow', False), ('unsupported_domain_nodes', 1),
                           ('minimum_nonzero_dyadic_exponent', -127), ('checked_abstract_nodes', 0),
                           ('maximum_rounded_magnitude_upper', float('inf'))):
            changed = deepcopy(current); changed['geometry_domain'][0]['domain'][key] = value
            trace.write_text('\n'.join(map(json.dumps, [header, changed])) + '\n')
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.compare(original, trace, empty=False)

    def test_empty_rows_require_negative_separator_even_with_matching_original_state(self):
        original, trace, header, current = self.traces(empty=True)
        current['meshes'][0]['maximum_bottom_upper'] = 0
        originals = [json.loads(line) for line in original.read_text().splitlines()]
        originals[18]['meshes'] = current['meshes']
        original.write_text('\n'.join(map(json.dumps, originals)) + '\n')
        trace.write_text('\n'.join(map(json.dumps, [header, current])) + '\n')
        with self.assertRaisesRegex(ValueError, 'strict empty separator'):
            self.compare(original, trace, empty=True)

    def test_original_flag_promotion_rejected_even_if_new_header_matches(self):
        original, trace, header, current = self.traces()
        originals = [json.loads(line) for line in original.read_text().splitlines()]
        originals[0]['profile_native_verified'] = True
        header['profile_native_verified'] = True
        original.write_text('\n'.join(map(json.dumps, originals)) + '\n')
        trace.write_text('\n'.join(map(json.dumps, [header, current])) + '\n')
        with self.assertRaisesRegex(ValueError, 'original flags'):
            self.compare(original, trace, empty=False)

    def test_one_build_selects_only_two_examples_and_original_configuration(self):
        cmd = runner.build_command('C:/rust/bin/cargo.exe')
        self.assertEqual(cmd.count('build'), 1)
        self.assertEqual(cmd.count('--example'), 2)
        self.assertEqual([cmd[i + 1] for i, arg in enumerate(cmd) if arg == '--example'], list(runner.EXAMPLES))
        for option in ('--locked', '--release', '--no-default-features'):
            self.assertIn(option, cmd)
        self.assertEqual(cmd[cmd.index('--features') + 1], 'legacy-macroquad,wgpu-runtime')
        self.assertEqual(cmd[cmd.index('--target') + 1], 'x86_64-pc-windows-msvc')
        self.assertNotIn('--bin', cmd)
        self.assertNotIn('--all-targets', cmd)
        source = (ROOT / 'tools/run_finite_warp_profile.py').read_text()
        self.assertIn("require(not (source / 'target').exists()", source)

    def test_output_roots_cannot_overlap_immutable_inputs_or_caller(self):
        for a, b in ((self.root, self.root), (self.root, self.root / 'child')):
            with self.assertRaisesRegex(ValueError, 'disjoint'):
                runner.distinct_roots(a, b)

    def test_companion_normalization_rejects_outside_root_or_unknown_asset(self):
        self.assertEqual(runner.companion_name('D:/later/assets\\locomotion/asset.vra', 'D:/later'),
                         'assets/locomotion/asset.vra')
        for path in ('D:/other/assets/locomotion/asset.vra', 'D:/later-escape/assets/locomotion/asset.vra',
                     'D:/later/assets/private/asset.vra', 'D:/later/assets/locomotion/asset.vrm',
                     'D:/later/../assets/locomotion/asset.vra'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                runner.companion_name(path, 'D:/later')

    def test_late_input_mutation_stops_after_single_build_and_preserves_failed_evidence(self):
        fresh, packet, verifier = (self.root / name for name in ('prepared', 'packet', 'verifier'))
        source = fresh / 'source'
        source.mkdir(parents=True); packet.mkdir(); (verifier / 'tools').mkdir(parents=True)
        workflow = verifier / runner.preparation.WORKFLOW
        workflow.parent.mkdir(parents=True); workflow.write_bytes(b'workflow')
        sentinel = source / 'settings.cfg'; sentinel.write_bytes(b'original')
        provider = self.root / 'provider.json'; provider.write_text('{}')
        cargo, rustc = self.root / 'cargo.exe', self.root / 'rustc.exe'
        cargo.write_bytes(b'cargo'); rustc.write_bytes(b'rustc')
        args = SimpleNamespace(prepared_root=fresh, packet_root=packet, verifier_root=verifier,
                               provider_metadata=provider, output_dir=self.root / 'evidence',
                               receipt_sha256='a' * 64)
        checks = []
        def verify(*args, **kwargs):
            checks.append('verify')
            if sentinel.read_bytes() != b'original':
                raise ValueError('injected late input mutation')
            return {'files': {'source/settings.cfg': runner.digest(sentinel)}}
        def command(cmd, **kwargs):
            if cmd[:2] == ['rustc', '-Vv']:
                return b'compiler'
            return str(cargo if cmd[-1] == 'cargo' else rustc)
        def process(*args, **kwargs):
            sentinel.write_bytes(b'mutated')
            return {'exit_code': 0}
        with ExitStack() as stack:
            stack.enter_context(patch.object(runner.preparation, 'caller_identity', return_value={'source_commit': 'c' * 40}))
            stack.enter_context(patch.object(runner.preparation, 'verify', side_effect=verify))
            stack.enter_context(patch.object(runner.producer, 'execution_environment', return_value={}))
            stack.enter_context(patch.object(runner.producer, 'checked_compiler'))
            stack.enter_context(patch.object(runner.subprocess, 'check_output', side_effect=command))
            execute = stack.enter_context(patch.object(runner.producer, 'process', side_effect=process))
            stack.enter_context(patch.object(runner.sys, 'platform', 'win32'))
            stack.enter_context(patch.object(runner.platform, 'machine', return_value='AMD64'))
            with self.assertRaises(ValueError):
                runner.run(args)
        self.assertEqual(execute.call_count, 1)
        self.assertGreaterEqual(len(checks), 5)
        summary = json.loads((args.output_dir / 'full/summary.json').read_text())
        self.assertEqual(summary['status'], 'failed')
        self.assertIn('injected late input mutation', summary['error'])
        self.assertIn('injected late input mutation', summary['final_integrity_error'])
        self.assertFalse(summary['profile_native_verified'])
        self.assertIsNone(summary['acceptance_verdict'])
        self.assertTrue((args.output_dir / 'review/summary.json').exists())
        self.assertFalse((args.output_dir / 'full/native/report.json').exists())

    def test_newline_conversion_preserves_raw_bytes_and_rejects_other_carriage_returns(self):
        raw, output = self.root / 'raw.json', self.root / 'canonical.json'
        raw.write_bytes(b'{"later": true}\r\n')
        record = runner.canonical_lf(raw, output)
        self.assertEqual(raw.read_bytes(), b'{"later": true}\r\n')
        self.assertEqual(output.read_bytes(), b'{"later": true}\n')
        self.assertNotEqual(record['raw'], record['canonical'])
        with self.assertRaises(FileExistsError):
            runner.canonical_lf(raw, output)
        raw.write_bytes(b'{\r}\n')
        with self.assertRaisesRegex(ValueError, 'non-CRLF'):
            runner.canonical_lf(raw, self.root / 'different.json')

    def test_large_clipping_output_is_not_limited_to_preparer_input_file_cap(self):
        raw = self.root / 'raw.jsonl'
        raw.write_bytes(b'x' * (runner.preparation.MAX_FILE + 1) + b'\r\n')
        runner.canonical_lf(raw, self.root / 'canonical.jsonl')
        self.assertEqual((self.root / 'canonical.jsonl').stat().st_size, runner.preparation.MAX_FILE + 2)

    def test_review_allowlist_excludes_original_inventory_assets_executables_and_native_buffers(self):
        full, bounded = self.root / 'full', self.root / 'review'
        names = ('summary.json', 'native/report.json', 'native/frame-0017/coverage.png',
                 'native/frame-0017/compact-0000.bin', 'native/frame-0017/draws.jsonl',
                 'inventory/src/game.rs', 'assets/locomotion/asset.vrm', 'game.exe',
                 'traces/dx12-visible.jsonl', 'logs/build/stdout.log')
        for name in names:
            path = full / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'content')
        total = runner.package_review(full, bounded)
        kept = {path.relative_to(bounded).as_posix() for path in bounded.rglob('*') if path.is_file()}
        self.assertEqual(kept, {'summary.json', 'native/report.json', 'native/frame-0017/coverage.png',
                               'logs/build/stdout.log', 'review-inventory.json'})
        self.assertLessEqual(total, runner.MAX_REVIEW)
        self.assertTrue(all((full / name).read_bytes() == b'content' for name in names))

    def test_review_large_log_retains_head_tail_and_records_truncation(self):
        full, bounded = self.root / 'full', self.root / 'review'
        log = full / 'logs/native/stderr.log'; log.parent.mkdir(parents=True)
        data = b'HEAD' + b'x' * (runner.MAX_LOG * 2) + b'TAIL'; log.write_bytes(data)
        runner.package_review(full, bounded)
        truncated = (bounded / 'logs/native/stderr.log').read_bytes()
        self.assertTrue(truncated.startswith(b'HEAD') and truncated.endswith(b'TAIL'))
        self.assertIn(b'Middle omitted', truncated)
        inventory = json.loads((bounded / 'review-inventory.json').read_text())
        self.assertTrue(inventory['files']['logs/native/stderr.log']['truncated'])
        self.assertEqual(log.read_bytes(), data)

    def test_review_excess_json_is_explicitly_omitted_and_total_is_bounded(self):
        full, bounded = self.root / 'full', self.root / 'review'
        path = full / 'native/report.json'; path.parent.mkdir(parents=True)
        path.write_bytes(b'x' * runner.MAX_REVIEW)
        total = runner.package_review(full, bounded)
        self.assertLessEqual(total, runner.MAX_REVIEW)
        self.assertFalse((bounded / 'native/report.json').exists())
        inventory = json.loads((bounded / 'review-inventory.json').read_text())
        self.assertIn('native/report.json', inventory['omitted'])

    def test_native_report_must_bind_originals_trace_executable_native_adapter_and_false_flags(self):
        trace, exe = self.root / 'trace', self.root / 'probe.exe'
        trace.write_bytes(b'trace'); exe.write_bytes(b'executable')
        report = {'schema': 'rust-duty-finite-warp-corroboration/v1', 'status': 'passed',
                  'native_execution': True, 'later_corroboration': True,
                  'original_capture_reproduced': False, 'original_native_upload_identity_verified': False,
                  'original_profile_flags_modified': False, 'universal_profile_verified': False,
                  'acceptance_verdict': None, 'required_mask_changed': False, 'possible_mask_changed': False,
                  'source_receipt_sha256': runner.extraction.FILES[runner.extraction.PACKET + 'source-receipt.json'][1],
                  'original_dx12_jsonl_sha256': runner.extraction.FILES[runner.extraction.PACKET + 'oracle-output/frames-dx12.jsonl'][1],
                  'trace_sha256': runner.digest(trace)['sha256'], 'executable_sha256': runner.digest(exe)['sha256'],
                  'frames': [{'frame': 17}], 'build_configuration': {
                      'legacy_macroquad': True, 'wgpu_runtime': True, 'audio': False,
                      'debug_assertions': False, 'required_rust_toolchain': '1.99.0'},
                  'native_identity': {'backend': 'Dx12', 'device_type': 'Cpu',
                                      'adapter': 'Microsoft Basic Render Driver', 'compiler': 'Fxc',
                                      'runtime_modules': [{'name': 'd3d12.dll'}]}}
        path = self.root / 'report.json'; path.write_text(json.dumps(report))
        runner.verify_native_report(path, trace, exe, [17])
        variants = []
        for key, value in (('native_execution', False), ('original_capture_reproduced', True),
                           ('universal_profile_verified', True), ('trace_sha256', '0' * 64),
                           ('executable_sha256', '0' * 64), ('frames', []), ('acceptance_verdict', True)):
            changed = deepcopy(report); changed[key] = value; variants.append(changed)
        changed = deepcopy(report); changed['native_identity']['device_type'] = 'DiscreteGpu'; variants.append(changed)
        changed = deepcopy(report); changed['build_configuration']['debug_assertions'] = True; variants.append(changed)
        for changed in variants:
            path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                runner.verify_native_report(path, trace, exe, [17])


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / '.github/workflows/finite-warp-profile.yml').read_text()
        cls.workflow = yaml.safe_load(cls.text)
        cls.steps = cls.workflow['jobs']['corroborate']['steps']

    def test_first_attempt_exact_main_push_read_only_non_cancelling(self):
        events = self.workflow.get('on', self.workflow.get(True))
        self.assertEqual(set(events), {'push'})
        self.assertEqual(events['push']['branches'], ['main'])
        self.assertEqual(self.workflow['permissions'], {'contents': 'read', 'actions': 'read'})
        self.assertIs(self.workflow['concurrency']['cancel-in-progress'], False)
        guard = self.workflow['jobs']['corroborate']['if']
        for text in ("github.repository == 'RHS059/rust_duty'", "github.event_name == 'push'",
                     "github.ref == 'refs/heads/main'", 'github.run_attempt == 1'):
            self.assertIn(text, guard)
        self.assertTrue(all(name.startswith(('tools/', 'examples/finite_warp_probe.rs',
                                            'src/render/finite_warp_probe.rs', '.github/workflows/finite-warp-profile.yml'))
                            for name in events['push']['paths']))
        self.assertNotIn('workflow_dispatch', self.text)
        self.assertNotIn('cancelWorkflowRun', self.text)

    def test_exact_single_download_follows_metadata_verification(self):
        downloads = [step for step in self.steps if step.get('uses') == 'actions/download-artifact@v4']
        self.assertEqual(len(downloads), 1)
        params = downloads[0]['with']
        self.assertEqual(params['artifact-ids'], '11396831337')
        self.assertEqual(params['run-id'], '37427554951')
        self.assertEqual(params['repository'], 'RHS059/rust_duty')
        verify = next(step for step in self.steps if 'verify-provider' in step.get('run', ''))
        self.assertLess(self.steps.index(verify), self.steps.index(downloads[0]))
        self.assertNotIn('name', params)
        self.assertNotIn('listWorkflowRunArtifacts', self.text)
        for denied in runner.producer.DENIED_ARTIFACT_IDS:
            self.assertNotIn(str(denied), self.text)

    def test_real_guard_dependencies_are_installed_and_checked_out(self):
        install = next(step['run'] for step in self.steps if 'pip install' in step.get('run', ''))
        for dependency in ('Pillow==11.3.0', 'numpy==2.2.6', 'PyYAML==6.0.3'):
            self.assertIn(dependency, install)
        checkout = next(step for step in self.steps if step.get('uses') == 'actions/checkout@v4')
        paths = checkout['with']['sparse-checkout'].splitlines()
        self.assertIn('/.github/workflows/native-profile-evidence.yml', paths)
        self.assertIn('/tools/*.py', paths)
        self.assertIs(checkout['with']['persist-credentials'], False)

    def test_independent_preparation_anchor_and_separate_full_bounded_uploads(self):
        execution = next(step for step in self.steps if 'run_finite_warp_profile.py' in step.get('run', ''))
        self.assertIn('--receipt-sha256 "${{ steps.prepare.outputs.receipt_sha256 }}"', execution['run'])
        self.assertIn('--prepared-root prepared', execution['run'])
        self.assertIn('--output-dir evidence/finite-warp', execution['run'])
        self.assertNotIn('cargo build', self.text)
        self.assertNotIn('actions/cache', self.text)
        uploads = [step for step in self.steps if step.get('uses') == 'actions/upload-artifact@v4']
        self.assertEqual({step['with']['path'] for step in uploads},
                         {'evidence/finite-warp/full/', 'evidence/finite-warp/review/'})
        self.assertTrue(all(step['if'] == 'always()' and step['with']['if-no-files-found'] == 'error'
                            for step in uploads))
        self.assertNotIn('continue-on-error', self.text)


if __name__ == '__main__':
    unittest.main()

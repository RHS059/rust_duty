"""Synthetic matrix/diagnostic protocol checks, never target GPU measurements."""
import copy
import json
from pathlib import Path, PureWindowsPath
import tempfile
import unittest
from unittest import mock

import performance_matrix as matrix
import summarize_cpu_substages as cpu
import summarize_gpu_timing as gpu
import test_performance_matrix as matrix_fixtures
from test_summarize_cpu_substages import fixture as cpu_fixture, span
from test_summarize_gpu_timing import fixture as gpu_fixture


SIDECARS = ('frames.cpu-substages.json', 'frames.gpu-timing.json')
LEGACY_FILES = {'frames.json', 'IDENTITY.json', 'CSV_STATUS.json', 'gameplay.csv',
                'GPU_STATUS.json', 'GPU_METADATA.json', 'gpu.jsonl'}


def write_json(path, value):
    # Exact bytes are part of the contract, including on Windows.
    path.write_bytes(json.dumps(value, allow_nan=False).encode('utf-8'))


def reviewed_source():
    # Production source-admission tests own the real closed manifests. This
    # local substitution exercises the protocol using the existing fixtures.
    return mock.patch.object(matrix, 'AUDITED_GPU_CANDIDATE_MANIFEST',
                             matrix.canonical_hash(matrix_fixtures.SOURCE['runtime_files_sha256']))


def diagnostic_pair(report):
    """Adapt strict-reader fixtures to the existing matrix's retained attempts."""
    _, detail, _, _ = cpu_fixture()
    _, timing, _, _ = gpu_fixture()
    detail['samples'] = []
    timing['samples'] = []
    timing['limits']['max_attempts'] = report['limits']['max_records']
    for attempt, parent in enumerate(report['cpu_frame_stages']['samples']):
        start = parent['spans']['renderer_submit']['started_at_ns']
        detail['samples'].append({'record_index': parent['record_index'], 'details': {
            'state': 'complete', 'error': None,
            'spans': [span('encode_submit', start, start + 10),
                      span('submit_validation_cpu', start + 10, start + 20)]}})
        timing['samples'].append({'session': timing['session'], 'attempt': attempt,
                                 'record_index': parent['record_index'], 'status': 'measured',
                                 'start_ticks': 10, 'end_ticks': 20,
                                 'timestamp_period_ns': 2.0, 'elapsed_ns': 20.0})
    return detail, timing


def write_bound_diagnostics(session, report, detail, timing):
    write_json(session / 'frames.json', report)
    digest = matrix.sha256(session / 'frames.json')
    detail.update(frame_report_sha256=digest, frame_status=copy.deepcopy(report['status']))
    timing['frame_report_sha256'] = digest
    write_json(session / SIDECARS[0], detail)
    write_json(session / SIDECARS[1], timing)


def make_unavailable(sample, status):
    sample.update(status=status, **dict.fromkeys(gpu.NUMERIC))


class MatrixGpuPlanTests(unittest.TestCase):
    def test_default_false_keywords_preserve_historical_plan_bytes(self):
        for options, digest in (
                ({}, '1c78fa3ca2323de9a0b6ca6b8d416e26cfe7057bf1566f8f484f91dadf72601a'),
                ({'smoke': True}, 'be319836c21ccce00805a6ebd7295b625b7d48d5e695c602d7f6123205799e18'),
                ({'pilot': True}, '343d547310f729d856b5bca1a847648fb433dcf2ff15035853387dc2d53a8e2a')):
            with self.subTest(options=options):
                plan = matrix.make_plan(matrix_fixtures.SOURCE, **options,
                                        gpu_timestamps=False, baseline_only=False, procedural_baseline=False)
                self.assertEqual(matrix.canonical_hash(plan), digest)
                self.assertNotIn('gpu_timestamps', plan)
                self.assertNotIn('baseline_only', plan)
                self.assertNotIn('procedural_baseline', plan)
                self.assertNotIn('gpu_timestamps', plan['fixed_runtime'])
                matrix.validate_plan(plan)

    def test_baseline_only_retains_repeats_and_1080p_statistical_selection(self):
        plan = matrix.make_plan(matrix_fixtures.SOURCE, baseline_only=True, repeats=3)
        self.assertTrue(plan['baseline_only'])
        self.assertFalse(plan['smoke'])
        self.assertEqual([item['repeat'] for item in plan['order']], [1, 2, 3])
        self.assertEqual([item['case_id'] for item in plan['order']], ['baseline'] * 3)
        self.assertEqual(len(plan['cases']), 1)
        self.assertEqual(plan['cases'][0]['settings']['surface_extent'], [1920, 1080])
        matrix.validate_plan(plan)
        for selection in ('smoke', 'pilot', 'static_diagnostics'):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                matrix.make_plan(matrix_fixtures.SOURCE, baseline_only=True, **{selection: True})

    def test_opt_in_requires_exact_reviewed_dx12_source(self):
        with self.assertRaises(ValueError):
            matrix.make_plan(matrix_fixtures.SOURCE, gpu_timestamps=True)
        with reviewed_source():
            plan = matrix.make_plan(matrix_fixtures.SOURCE, gpu_timestamps=True, baseline_only=True)
            self.assertTrue(plan['gpu_timestamps'])
            self.assertTrue(plan['fixed_runtime']['gpu_timestamps'])
            matrix.validate_plan(plan)
            for renderer in set(matrix.BACKENDS) - {'dx12'}:
                with self.subTest(renderer=renderer), self.assertRaises(ValueError):
                    matrix.make_plan(matrix_fixtures.SOURCE, renderer=renderer, gpu_timestamps=True)
        with mock.patch.object(matrix, 'AUDITED_GPU_CPU_BASELINE_MANIFEST',
                               matrix.canonical_hash(matrix_fixtures.SOURCE['runtime_files_sha256'])):
            matrix.validate_plan(matrix.make_plan(matrix_fixtures.SOURCE, gpu_timestamps=True))
        with mock.patch.object(matrix, 'AUDITED_GPU_INITIAL_MANIFEST',
                               matrix.canonical_hash(matrix_fixtures.SOURCE['runtime_files_sha256'])):
            with self.assertRaises(ValueError):
                matrix.make_plan(matrix_fixtures.SOURCE, gpu_timestamps=True)

    def test_opt_in_keywords_are_boolean_and_plan_mutations_fail(self):
        for name in ('gpu_timestamps', 'baseline_only', 'procedural_baseline'):
            for value in (0, 1, 'true', None):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    matrix.make_plan(matrix_fixtures.SOURCE, **{name: value})
        with reviewed_source():
            original = matrix.make_plan(matrix_fixtures.SOURCE, gpu_timestamps=True, baseline_only=True)
            mutations = (
                lambda p: p.update(gpu_timestamps=False),
                lambda p: p['fixed_runtime'].update(gpu_timestamps=False),
                lambda p: p.pop('gpu_timestamps'),
                lambda p: p.update(baseline_only=False),
                lambda p: p['source']['runtime_files_sha256'].update({'synthetic.rs': 'd' * 64}),
                lambda p: p.update(renderer='gl-harness'))
            for mutate in mutations:
                plan = copy.deepcopy(original)
                mutate(plan)
                with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                    matrix.validate_plan(plan)
        for name in ('gpu_timestamps', 'baseline_only', 'procedural_baseline'):
            plan = matrix.make_plan(matrix_fixtures.SOURCE)
            plan[name] = False
            with self.subTest(explicit_false=name), self.assertRaises(ValueError):
                matrix.validate_plan(plan)

    def test_procedural_baseline_is_explicit_bounded_and_has_exact_command(self):
        for options in ({}, {'smoke': True}, {'pilot': True}, {'static_diagnostics': True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                matrix.make_plan(matrix_fixtures.SOURCE, procedural_baseline=True, **options)
        with reviewed_source():
            plan = matrix.make_plan(matrix_fixtures.SOURCE, gpu_timestamps=True,
                                    baseline_only=True, procedural_baseline=True, repeats=2)
            matrix.validate_plan(plan)
            self.assertTrue(plan['procedural_baseline'])
            self.assertEqual(len(plan['cases']), 1)
            self.assertEqual(len(plan['order']), 2)
            case = plan['cases'][0]
            self.assertEqual(case['settings']['presentation'], 'procedural')
            self.assertEqual(case['settings']['surface_extent'], [1920, 1080])
            command = matrix.case_command(Path('/synthetic/game.exe'), 'dx12', Path('/synthetic/run'),
                                          case, False, gpu_timestamps=True)
            self.assertEqual(command[-2:], ['--procedural-weapon', '--gpu-timestamps'])
            plan.pop('procedural_baseline')
            with self.assertRaises(ValueError):
                matrix.validate_plan(plan)

    def test_command_only_adds_explicit_timestamp_argument(self):
        case = matrix.make_plan(matrix_fixtures.SOURCE)['cases'][0]
        executable, folder = Path('/synthetic/game.exe'), Path('/synthetic/run')
        original = matrix.case_command(executable, 'dx12', folder, case, False)
        self.assertNotIn('--gpu-timestamps', original)
        self.assertEqual(matrix.case_command(executable, 'dx12', folder, case, False,
                                             gpu_timestamps=False), original)
        self.assertEqual(matrix.case_command(executable, 'dx12', folder, case, False,
                                             gpu_timestamps=True), original + ['--gpu-timestamps'])
        for renderer, enabled in (('gl-harness', True), ('dx12', 1), ('dx12', 'true')):
            with self.subTest(renderer=renderer, enabled=enabled), self.assertRaises(ValueError):
                matrix.case_command(executable, renderer, folder, case, False, gpu_timestamps=enabled)


class MatrixGpuDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.session = Path(self.temp.name)
        self.report, self.timing, _, _ = gpu_fixture()
        _, self.detail, _, _ = cpu_fixture()
        self.write()

    def write(self):
        write_bound_diagnostics(self.session, self.report, self.detail, self.timing)

    def summarize(self):
        return matrix.summarize_diagnostics(self.session / 'frames.json',
                                            self.session / SIDECARS[0], self.session / SIDECARS[1])

    def test_wrapper_returns_unchanged_strict_reader_summaries(self):
        before = {p.name: p.read_bytes() for p in self.session.iterdir()}
        digest = matrix.sha256(self.session / 'frames.json')
        result = self.summarize()
        self.assertEqual(result, {
            'cpu_substages': cpu.summarize(self.detail, self.report, digest),
            'gpu_timing': gpu.summarize(self.timing, self.report, digest),
            'gpu_timing_readiness': {'ready': False, 'required_measured_eligible_samples': 100}})
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.session.iterdir()})

    def test_semantically_equal_primary_with_changed_bytes_rejects_both_stale_joins(self):
        primary = self.session / 'frames.json'
        primary.write_bytes(primary.read_bytes() + b'\n')
        self.assertEqual(json.loads(primary.read_bytes()), self.report)
        with self.assertRaisesRegex(ValueError, 'CPU substage binding'):
            self.summarize()
        self.detail['frame_report_sha256'] = matrix.sha256(primary)
        write_json(self.session / SIDECARS[0], self.detail)
        with self.assertRaisesRegex(ValueError, 'GPU timing binding'):
            self.summarize()

    def test_missing_truncated_duplicate_and_nonfinite_evidence_fails_closed(self):
        for name in ('frames.json', *SIDECARS):
            for invalid in (None, b'{', b'{"x":1,"x":2}', b'{"x":NaN}'):
                self.write()
                path = self.session / name
                if invalid is None:
                    path.unlink()
                else:
                    path.write_bytes(invalid)
                with self.subTest(name=name, invalid=invalid), self.assertRaises(ValueError):
                    self.summarize()

    def test_incomplete_primary_cpu_or_gpu_accounting_is_not_a_measurement(self):
        original = copy.deepcopy((self.report, self.detail, self.timing))
        for component in ('primary', 'cpu', 'gpu'):
            self.report, self.detail, self.timing = copy.deepcopy(original)
            if component == 'primary':
                self.report['status'] = {'state': 'incomplete', 'error': 'synthetic failure'}
                self.report['incomplete_at_ns'] = self.report['stop_requested_ns']
            elif component == 'cpu':
                self.detail['samples'][0]['details'].update(state='incomplete', error='unterminated_substage')
            else:
                self.timing.update(accounting_state='incomplete', error='missing CPU terminal')
                self.timing['samples'][0]['record_index'] = None
            self.write()
            with self.subTest(component=component), self.assertRaisesRegex(ValueError, 'Incomplete CPU/GPU'):
                self.summarize()

    def test_missing_or_duplicate_cpu_gpu_rows_are_rejected(self):
        originals = copy.deepcopy((self.detail, self.timing))
        for component in ('cpu', 'gpu'):
            for duplicate in (False, True):
                self.detail, self.timing = copy.deepcopy(originals)
                rows = self.detail['samples'] if component == 'cpu' else self.timing['samples']
                if duplicate:
                    rows.append(copy.deepcopy(rows[0]))
                else:
                    rows.clear()
                self.write()
                with self.subTest(component=component, duplicate=duplicate), self.assertRaises(ValueError):
                    self.summarize()

    def test_pending_rejected_and_unconfirmed_spans_remain_unavailable(self):
        for status in ('pending_at_stop', 'submission_rejected', 'validation_unconfirmed_at_stop', 'ring_full'):
            make_unavailable(self.timing['samples'][0], status)
            self.write()
            with self.subTest(status=status):
                result = self.summarize()
                self.assertEqual(result['gpu_timing']['status_counts'], {status: 1})
                self.assertEqual(result['gpu_timing']['measured_eligible_count'], 0)
                self.assertEqual(result['gpu_timing']['unavailable_eligible_count'], 1)
                self.assertIsNone(result['gpu_timing']['p99_ns'])
                self.assertFalse(result['gpu_timing_readiness']['ready'])
                self.timing['samples'][0]['elapsed_ns'] = 0
                self.write()
                with self.assertRaises(ValueError):
                    self.summarize()

    def test_unsupported_or_unenabled_features_keep_explicit_unavailability(self):
        self.report['identity']['runtime_observed']['actual_adapter']['gpu_timestamp_features_enabled'] = False
        self.timing['availability'] = {'state': 'device_features_not_enabled'}
        make_unavailable(self.timing['samples'][0], 'device_features_not_enabled')
        for supported in (False, True):
            self.timing['feature_negotiation'].update(adapter_supports_required_features=supported,
                                                      device_features_enabled=False)
            self.write()
            with self.subTest(adapter_supports=supported):
                result = self.summarize()
                self.assertEqual(result['gpu_timing']['availability'], self.timing['availability'])
                self.assertEqual(result['gpu_timing']['unavailable_eligible_count'], 1)
                self.assertFalse(result['gpu_timing_readiness']['ready'])
                self.assertIsNone(result['gpu_timing']['p50_ns'])

    def test_honestly_rebound_false_opt_in_or_feature_contradiction_fails(self):
        adapter = self.report['identity']['runtime_observed']['actual_adapter']
        for name in ('gpu_timestamps_requested', 'gpu_timestamp_features_enabled'):
            original = adapter.pop(name)
            self.write()
            with self.subTest(missing=name), self.assertRaises(ValueError):
                self.summarize()
            for value in (False, 1):
                adapter[name] = value
                self.write()
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    self.summarize()
            adapter[name] = original

    def test_missing_cpu_calls_are_unavailable_and_not_zero_filled(self):
        self.detail['samples'][0]['details']['spans'] = []
        self.write()
        for stage in self.summarize()['cpu_substages']['stages'].values():
            self.assertEqual(stage['observed_calls'], 0)
            self.assertIsNone(stage['per_frame_total_ns']['p50_ns'])


class MatrixGpuSessionTests(unittest.TestCase):
    def setUp(self):
        # Compose the existing fixture without inheriting or rediscovering its
        # independent test suite in this module.
        self.fixture = matrix_fixtures.MatrixTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def enable(self, *, procedural=False):
        fixture = self.fixture
        with reviewed_source():
            plan = matrix.make_plan(matrix_fixtures.SOURCE, gpu_timestamps=True, baseline_only=True,
                                    repeats=1, warmup=10, seconds=10, procedural_baseline=procedural)
        fixture.adapter.update(gpu_timestamps_requested=True, gpu_timestamp_features_enabled=True)
        fixture.select_case(plan, 'baseline')
        if procedural:
            fixture.report['identity']['runtime_observed']['scene']['presentation'] = 'procedural'
        fixture.manifest['executable_path'] = r'C:\synthetic\package\game.exe'
        fixture.manifest['host_observed']['system'] = 'Windows'
        folder = PureWindowsPath('C:/synthetic/evidence') / fixture.item['run_id']
        fixture.receipt['working_directory'] = str(folder)
        fixture.receipt['command'] = matrix.case_command(
            PureWindowsPath(fixture.manifest['executable_path']), 'dx12', folder, fixture.case,
            False, gpu_timestamps=True)
        self.detail, self.timing = diagnostic_pair(fixture.report)
        self.save()

    def save(self):
        fixture = self.fixture
        write_bound_diagnostics(fixture.session, fixture.report, self.detail, self.timing)
        write_json(fixture.session / 'IDENTITY.json', fixture.identity)
        write_json(fixture.folder / 'RESULT.json', fixture.receipt)
        write_json(fixture.root / 'MANIFEST.json', fixture.manifest)

    def test_completed_export_waits_for_both_sidecars_only_when_enabled(self):
        fixture = self.fixture
        self.assertEqual(matrix.sole_session(fixture.folder, complete=True), fixture.session)
        self.assertIsNone(matrix.sole_session(fixture.folder, complete=True, gpu_timestamps=True))
        self.enable()
        self.assertEqual(matrix.sole_session(fixture.folder, complete=True, gpu_timestamps=True), fixture.session)
        for name in SIDECARS:
            for invalid in (None, b'{', b'{"x":1,"x":2}'):
                self.save()
                path = fixture.session / name
                if invalid is None:
                    path.unlink()
                else:
                    path.write_bytes(invalid)
                with self.subTest(name=name, invalid=invalid):
                    self.assertIsNone(matrix.sole_session(fixture.folder, complete=True, gpu_timestamps=True))
                    self.assertEqual(matrix.sole_session(fixture.folder, complete=True), fixture.session)

    def test_measurement_hashes_bind_each_new_sidecar_only_when_enabled(self):
        fixture = self.fixture
        legacy = matrix.measurement_file_hashes(fixture.session)
        self.assertEqual(set(legacy), LEGACY_FILES)
        with self.assertRaises(ValueError):
            matrix.measurement_file_hashes(fixture.session, gpu_timestamps=True)
        self.enable()
        legacy = matrix.measurement_file_hashes(fixture.session)
        bound = matrix.measurement_file_hashes(fixture.session, gpu_timestamps=True)
        self.assertEqual(set(bound), LEGACY_FILES | set(SIDECARS))
        self.assertEqual(legacy, {key: bound[key] for key in LEGACY_FILES})
        for name in SIDECARS:
            self.save()
            path = fixture.session / name
            path.write_bytes(path.read_bytes() + b' ')
            changed = matrix.measurement_file_hashes(fixture.session, gpu_timestamps=True)
            self.assertEqual({key for key in bound if changed[key] != bound[key]}, {name})
            self.assertEqual(matrix.measurement_file_hashes(fixture.session), legacy)
            path.unlink()
            with self.assertRaises(ValueError):
                matrix.measurement_file_hashes(fixture.session, gpu_timestamps=True)

    def test_default_off_preserves_old_analysis_without_sidecar_dependencies(self):
        result = self.fixture.analyze()
        self.assertNotIn('gpu_timing', result)
        self.assertNotIn('gpu_timing_readiness', result)
        self.assertNotIn('cpu_substages', result)
        self.assertIsNone(result['gpu_frame_duration_ns'])
        write_json(self.fixture.session / SIDECARS[0], {'unconsumed': True})
        self.assertEqual(self.fixture.analyze(), result)
        write_json(self.fixture.session / SIDECARS[1], {'unexpected': True})
        with self.assertRaisesRegex(ValueError, 'Unexpected GPU sidecar'):
            self.fixture.analyze()

    def test_native_windows_command_and_diagnostic_hashes_join_into_analysis(self):
        self.enable()
        result = self.fixture.analyze()
        self.assertEqual(result['gpu_timing']['measured_eligible_count'], 200)
        self.assertTrue(result['gpu_timing_readiness']['ready'])
        self.assertEqual(result['diagnostic_files_sha256'], {
            name: matrix.sha256(self.fixture.session / name) for name in SIDECARS})
        self.assertEqual(result['cpu_substages']['stages']['encode_submit']['observed_calls'], 200)
        self.assertFalse(result['acceptance_proven'])
        self.assertIsNone(result['gpu_frame_duration_ns'])

    def test_procedural_baseline_analysis_requires_observed_procedural_scene(self):
        self.enable(procedural=True)
        result = self.fixture.analyze()
        self.assertTrue(result['gpu_timing_readiness']['ready'])
        self.assertEqual(result['runtime_observed']['scene']['presentation'], 'procedural')
        self.fixture.report['identity']['runtime_observed']['scene']['presentation'] = 'authored_viewmodel'
        self.save()
        with self.assertRaisesRegex(ValueError, 'Procedural case'):
            self.fixture.analyze()

    def test_missing_or_unbound_sidecar_blocks_complete_matrix_acceptance(self):
        self.enable()
        for name in SIDECARS:
            for missing in (False, True):
                self.save()
                path = self.fixture.session / name
                if missing:
                    path.unlink()
                else:
                    data = json.loads(path.read_bytes())
                    data['frame_report_sha256'] = '0' * 64
                    write_json(path, data)
                with reviewed_source(), self.subTest(name=name, missing=missing):
                    result = matrix.analyze_matrix(self.fixture.root)
                    self.assertEqual(result['state'], 'incomplete')
                    self.assertEqual(len(result['failures']), 1)
                    self.assertEqual(result['runs'], [])
                    self.assertFalse(result['measurement_readiness']['ready'])
                    self.assertFalse(result['pilot_sample_readiness']['ready'])

    def test_cleanup_recovery_binds_new_sidecars_and_keeps_shutdown_failure(self):
        self.enable()
        fixture = self.fixture
        fixture.recovered_receipt()
        # The historical helper deliberately binds only historical files.
        with self.assertRaisesRegex(ValueError, 'Measurement exports changed'):
            matrix.analyze_run(fixture.folder, fixture.manifest, allow_forced_cleanup=True)
        fixture.receipt['measurement_files_before_exit'] = matrix.measurement_file_hashes(
            fixture.session, gpu_timestamps=True)
        self.save()
        with reviewed_source():
            result = matrix.analyze_matrix(fixture.root)
        self.assertEqual(result['state'], 'incomplete')
        self.assertFalse(result['graceful_shutdown'])
        self.assertFalse(result['pilot_sample_readiness']['ready'])
        self.assertTrue(result['measurement_readiness']['ready'])
        self.assertEqual(result['runs'][0]['outcome'], 'measurements_valid_shutdown_failed')
        for name in SIDECARS:
            self.save()
            path = fixture.session / name
            path.write_bytes(path.read_bytes() + b'\n')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Measurement exports changed'):
                matrix.analyze_run(fixture.folder, fixture.manifest, allow_forced_cleanup=True)

    def test_99_vs_100_measured_eligible_samples_controls_matrix_readiness(self):
        self.enable()
        original = copy.deepcopy(self.timing)
        for measured in (99, 100):
            self.timing = copy.deepcopy(original)
            for sample in self.timing['samples'][measured:]:
                make_unavailable(sample, 'pending_at_stop')
            self.save()
            with reviewed_source(), self.subTest(measured=measured):
                result = matrix.analyze_matrix(self.fixture.root)
                self.assertEqual(result['state'], 'complete')
                self.assertTrue(result['graceful_shutdown'])
                self.assertEqual(result['measurement_readiness']['ready'], measured >= 100)
                self.assertEqual(result['pilot_sample_readiness']['ready'], measured >= 100)
                run = result['runs'][0]
                self.assertTrue(run['sample_quality']['tail_comparison_ready'])
                self.assertEqual(run['gpu_timing']['measured_eligible_count'], measured)
                self.assertEqual(run['gpu_timing']['unavailable_eligible_count'], 200 - measured)
                self.assertEqual(run['gpu_timing']['status_counts']['pending_at_stop'], 200 - measured)
                self.assertEqual(run['gpu_timing_readiness'], {
                    'ready': measured >= 100, 'required_measured_eligible_samples': 100})
                self.assertEqual(run['gpu_timing']['p95_ns'], 20.0)

    def test_unavailable_timer_keeps_complete_exports_but_blocks_measurement_readiness(self):
        self.enable()
        self.fixture.adapter['gpu_timestamp_features_enabled'] = False
        self.timing['feature_negotiation'].update(adapter_supports_required_features=False,
                                                  device_features_enabled=False)
        self.timing['availability'] = {'state': 'device_features_not_enabled'}
        for sample in self.timing['samples']:
            make_unavailable(sample, 'device_features_not_enabled')
        self.save()
        with reviewed_source():
            result = matrix.analyze_matrix(self.fixture.root)
        self.assertEqual(result['state'], 'complete')
        self.assertEqual(result['failures'], [])
        self.assertFalse(result['measurement_readiness']['ready'])
        self.assertFalse(result['pilot_sample_readiness']['ready'])
        self.assertEqual(result['runs'][0]['gpu_timing']['unavailable_eligible_count'], 200)

    def test_command_package_working_directory_and_opt_in_must_agree(self):
        self.enable()
        fixture = self.fixture
        original_receipt = copy.deepcopy(fixture.receipt)
        for mutation in ('missing_flag', 'extra_flag', 'executable', 'working_directory', 'relative_directory'):
            fixture.receipt = copy.deepcopy(original_receipt)
            if mutation == 'missing_flag':
                fixture.receipt['command'].remove('--gpu-timestamps')
            elif mutation == 'extra_flag':
                fixture.receipt['command'].append('--gpu-timestamps')
            elif mutation == 'executable':
                fixture.receipt['command'][0] = r'C:\other\game.exe'
            elif mutation == 'working_directory':
                fixture.receipt['working_directory'] = r'C:\synthetic\wrong-run'
            else:
                fixture.receipt['working_directory'] = fixture.item['run_id']
            self.save()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                fixture.analyze()
        fixture.receipt = original_receipt
        fixture.adapter['gpu_timestamps_requested'] = False
        self.save()  # Honest new primary/sidecar hashes cannot hide a flag mismatch.
        with self.assertRaisesRegex(ValueError, 'opt-in differs'):
            fixture.analyze()


if __name__ == '__main__':
    unittest.main()

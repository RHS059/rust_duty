"""CPU-only matrix protocol tests. All timing/game reports here are synthetic."""
import copy
import ctypes
import json
from pathlib import Path
import subprocess
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import performance_matrix as m
import performance_matrix_driver as d
import summarize_frame_performance as f
from test_summarize_frame_performance import control, present


FINGERPRINT = {'backend': 'dx12', 'name': 'Synthetic test adapter',
               'vendor_id': 123, 'device_id': 456, 'device_type': 'DiscreteGpu'}
GRAPHICS = {'schema': 'rust-duty-graphics-device/v1', 'adapter': FINGERPRINT}
SOURCE = {'commit': 'a' * 40, 'runtime_files_sha256': {'synthetic.rs': 'b' * 64}}


def dump(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


def trace(case, adapter, build, intervals=200, interval_ns=50_000_000):
    report = control()
    report['start_ns'] = 0
    report['records'] = [present(10)] + [present(10 + index * interval_ns, interval_ns)
                                        for index in range(1, intervals + 1)]
    report['successful_present_count'] = intervals + 1
    report['last_observed_ns'] = report['records'][-1]['at_ns']
    report['stop_requested_ns'] = report['stopped_at_ns'] = report['last_observed_ns']
    report['summary'] = {'interval_count': intervals, 'total_interval_ns': interval_ns * intervals,
                         'min_ns': interval_ns, 'max_ns': interval_ns,
                         'p50_ns': interval_ns, 'p95_ns': interval_ns, 'p99_ns': interval_ns,
                         'percentile_method': f.METHOD}
    size = case['settings']['surface_extent']
    scene = {'name': 'vector_range_default_range', 'reference_viewport': False,
             'diagnostic_capture': False, 'demo': False, 'capture_sequence': None,
             'profile_base': 'm4a1', 'weapon_id': 'hk416a5',
             'presentation': 'procedural' if case['id'] == 'procedural' else 'authored_viewmodel'}
    report['identity']['runtime_observed'] = {
        'actual_backend': 'Dx12', 'actual_adapter': adapter, 'build': build,
        'initial_window': {'physical_width': size[0], 'physical_height': size[1],
                           'scale_factor': 1, 'mode': 'windowed'}, 'scene': scene}
    samples = []
    for index in range(1, intervals + 1):
        start = report['records'][index - 1]['at_ns']
        end = report['records'][index]['at_ns']
        spans = {name: {'started_at_ns': start + i * 100,
                        'ended_at_ns': start + (i + 1) * 100, 'duration_ns': 100}
                 for i, name in enumerate(f.CPU_STAGE_DEFINITIONS)}
        samples.append({'record_index': index, 'started_at_ns': start, 'finished_at_ns': end,
                        'physical_width': size[0], 'physical_height': size[1], 'spans': spans})
    report['cpu_frame_stages'] = {'measurement': f.CPU_STAGE_MEASUREMENT,
                                  'interpretation': f.CPU_STAGE_INTERPRETATION,
                                  'stage_definitions': f.CPU_STAGE_DEFINITIONS, 'samples': samples}
    f.validate_report(report)
    return report


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.plan = m.make_plan(SOURCE, repeats=1, warmup=10, seconds=10, smoke=True)
        self.case = self.plan['cases'][0]
        self.item = self.plan['order'][0]
        self.folder = self.root / self.item['run_id']
        self.folder.mkdir()
        self.session = self.folder / 'telemetry-sessions' / 'session-test'
        self.session.mkdir(parents=True)
        self.settings = b'fov = 90\n'
        (self.folder / 'settings.cfg').write_bytes(self.settings)
        dump(self.folder / 'graphics-device.json', GRAPHICS)
        self.build = {'label': 'synthetic+build.test', 'version': 'synthetic', 'number': 'test'}
        self.adapter = {**FINGERPRINT, 'backend': 'Dx12', 'driver': 'synthetic', 'driver_info': 'test',
                        'present_mode': 'Fifo', 'force_fallback_requested': False,
                        'selection_mode': 'explicit_fingerprint', 'requested_fingerprint': FINGERPRINT,
                        'actual_fingerprint': FINGERPRINT}
        self.manifest = {'schema': 'rust-duty-matrix-execution/v1', 'plan': self.plan,
                         'source_origin': {'mode': 'live-git'},
                         'package': {'executable_sha256': 'c' * 64,
                                     'build': {'display_version': self.build['label']}},
                         'settings_sha256': m.sha256(self.folder / 'settings.cfg'),
                         'graphics': GRAPHICS, 'force_fallback': False,
                         'host_observed': {'system': 'synthetic'}, 'operator_hardware': None}
        self.receipt = {'schema': 'rust-duty-matrix-run/v1', 'run': self.item, 'case': self.case,
                        'completed': True, 'returncode': 0, 'session': self.session.name,
                        'started_unix_ns': 1000, 'finished_unix_ns': 100000000000,
                        'settings_before_sha256': self.manifest['settings_sha256'],
                        'settings_after_sha256': self.manifest['settings_sha256'],
                        'graphics_before_sha256': m.sha256(self.folder / 'graphics-device.json'),
                        'graphics_after_sha256': m.sha256(self.folder / 'graphics-device.json')}
        dump(self.folder / 'RESULT.json', self.receipt)
        self.report = trace(self.case, self.adapter, self.build)
        dump(self.session / 'frames.json', self.report)
        self.identity = {'schema': 'rust-duty-local-playtest-session/v1',
                         'executable_sha256': 'c' * 64,
                         'source': {'state': 'bound_to_executable_hash_and_label', 'commit': SOURCE['commit']},
                         'build': self.build, 'graphics_device': self.adapter}
        dump(self.session / 'IDENTITY.json', self.identity)
        dump(self.session / 'CSV_STATUS.json', {'state': 'stopped', 'error': None})
        dump(self.session / 'GPU_STATUS.json', {'schema': 'rust-duty-gpu-status/v1', 'state': 'stopped',
                                               'error': None, 'gpu_frame_duration_available': False,
                                               'samples_written': 1, 'samples_with_game_process_utilization': 0})
        dump(self.session / 'GPU_METADATA.json', {'schema': 'rust-duty-gpu-telemetry/v1',
                                                 'provider': 'unavailable',
                                                 'gpu_frame_duration_ms': {'value': None, 'unavailable_reason': 'No timestamp queries'}})
        dump(self.session / 'gpu.jsonl', {'sample': 0, 'sample_started_ms': 0, 'sample_finished_ms': 1,
                                        'provider_query_cpu_wall_ms': 1,
                                        'data': {'adapters': [], 'unavailable_reason': 'Synthetic unavailable provider'}})
        self.csv(speed=0, ads=0)
        dump(self.root / 'MANIFEST.json', self.manifest)

    def tearDown(self):
        self.temp.cleanup()

    def csv(self, speed, ads, times=None):
        header = 'time,x,y,z,speed,grounded,crouched,sprinting,ads,recoil_pitch_deg,ammo,shots,hits,kills,render_fps\n'
        times = [i / 10 for i in range(100)] if times is None else times
        (self.session / 'gameplay.csv').write_text(header + ''.join(
            f'{value},0,0,0,{speed},1,0,0,{ads},0,30,0,0,0,999999\n' for value in times))

    def select_case(self, plan, name):
        self.plan = plan
        self.item = next(item for item in plan['order'] if item['case_id'] == name)
        self.case = next(case for case in plan['cases'] if case['id'] == name)
        destination = self.root / self.item['run_id']
        if destination != self.folder:
            self.folder.rename(destination)
            self.folder = destination
            self.session = destination / 'telemetry-sessions' / self.session.name
        self.manifest['plan'] = plan
        self.receipt.update(run=self.item, case=self.case)
        self.report = trace(self.case, self.adapter, self.build)
        dump(self.session / 'frames.json', self.report)
        dump(self.folder / 'RESULT.json', self.receipt)
        dump(self.root / 'MANIFEST.json', self.manifest)

    def analyze(self):
        return m.analyze_run(self.folder, self.manifest)

    def test_finite_factorization_and_bracketed_repeats(self):
        plan = m.make_plan(SOURCE)
        self.assertEqual(len(plan['cases']), 10)
        self.assertEqual(len(plan['order']), 33)
        self.assertEqual(len({item['run_id'] for item in plan['order']}), 33)
        for case in plan['cases']:
            if case['kind'] == 'one_variable':
                self.assertEqual(len(case['changed_axes']), 1)
            elif case['kind'] == 'interaction':
                self.assertEqual(len(case['changed_axes']), 2)
        self.assertEqual(len(m.make_plan(SOURCE, smoke=True)['order']), 1)
        self.assertEqual([item['case_id'] for item in m.make_plan(SOURCE, pilot=True)['order']],
                         ['baseline', '720p', '1440p', 'ads', 'baseline'])
        self.assertIsNone(plan['fixed_runtime']['application_fps_cap'])
        self.assertIn('record_off_overhead', plan['unavailable_axes'])

    def test_old_plan_bytes_remain_compatible(self):
        expected = (({}, '1c78fa3ca2323de9a0b6ca6b8d416e26cfe7057bf1566f8f484f91dadf72601a'),
                    ({'smoke': True}, 'be319836c21ccce00805a6ebd7295b625b7d48d5e695c602d7f6123205799e18'),
                    ({'pilot': True}, '343d547310f729d856b5bca1a847648fb433dcf2ff15035853387dc2d53a8e2a'))
        for kwargs, digest in expected:
            plan = m.make_plan(SOURCE, **kwargs)
            self.assertNotIn('static_diagnostics', plan)
            self.assertEqual(m.canonical_hash(plan), digest)
            m.validate_plan(plan)

    def test_remaining_static_selection_is_five_existing_conditions(self):
        plan = m.make_plan(SOURCE, seconds=120, static_diagnostics=True)
        self.assertEqual([item['case_id'] for item in plan['order']],
                         ['baseline', '4k', 'debug-hud', 'procedural', 'baseline'])
        self.assertEqual(plan['repeats'], 1)
        self.assertEqual(plan['sample_seconds'], 120)
        self.assertTrue(all(case['settings']['action'] == 'stationary' for case in plan['cases']))
        self.assertIn('evolving_ads_movement', plan['unavailable_axes'])
        m.validate_plan(plan)
        for options in ({'smoke': True}, {'pilot': True}, {'static_diagnostics': 'yes'}):
            with self.assertRaises(ValueError):
                m.make_plan(SOURCE, **({'static_diagnostics': True} | options))

    def test_simulation_progression_distinguishes_stalls_and_partial_progress(self):
        for times, state, advancing in (([0.1667] * 3, 'stalled', 0),
                                         ([0, 0, 0.0833], 'intermittent_progress', 1),
                                         ([0, 0.1, 0.2], 'advancing', 2),
                                         ([0], 'unavailable_single_row', 0)):
            self.csv(0, 0, times)
            value = m.gameplay_summary(self.session / 'gameplay.csv')['simulation_time']
            self.assertEqual(value['progression'], state)
            self.assertEqual(value['advancing_pairs'], advancing)
            self.assertEqual(value['span_seconds'], times[-1] - times[0])
        for times in ([1, 0], [-1, 0], [0, float('nan')]):
            self.csv(0, 0, times)
            with self.assertRaises(ValueError):
                m.gameplay_summary(self.session / 'gameplay.csv')

    def test_static_stalled_capture_keeps_tail_gate_and_labels_simulation(self):
        plan = m.make_plan(SOURCE, warmup=10, seconds=10, static_diagnostics=True)
        self.select_case(plan, 'baseline')
        self.csv(0, 0, [0.1667] * 100)
        result = self.analyze()
        self.assertEqual(result['sample_quality']['purpose'], 'static_render_diagnostics')
        self.assertEqual(result['simulation_condition']['classification'], 'static_scene_with_stalled_simulation')
        self.assertFalse(result['simulation_condition']['evolving_gameplay_acceptance_proven'])
        self.assertEqual(result['gameplay_observed']['simulation_time']['span_seconds'], 0)
        dump(self.session / 'frames.json', trace(self.case, self.adapter, self.build, intervals=38, interval_ns=1_000_000_000))
        with self.assertRaisesRegex(ValueError, '100 intervals'):
            self.analyze()

    def test_stalled_ads_cannot_be_counted_as_evolving_gameplay(self):
        self.select_case(m.make_plan(SOURCE, warmup=10, seconds=10, pilot=True), 'ads')
        self.csv(0, 1, [0.1667] * 100)
        with self.assertRaisesRegex(ValueError, 'Simulation time did not advance'):
            self.analyze()

    def test_static_f1_requires_command_receipt_without_claiming_actual_state(self):
        self.select_case(m.make_plan(SOURCE, warmup=10, seconds=10, static_diagnostics=True), 'debug-hud')
        with self.assertRaisesRegex(ValueError, 'issued-command'):
            self.analyze()
        self.receipt['debug_hud_command'] = {'key': 'F1', 'issued': True, 'actual_state_verified': False}
        dump(self.folder / 'RESULT.json', self.receipt)
        result = self.analyze()
        self.assertTrue(result['debug_hud_evidence']['command_receipt']['issued'])
        self.assertFalse(result['debug_hud_evidence']['actual_state_verified'])

    def test_static_procedural_binds_actual_presentation(self):
        self.select_case(m.make_plan(SOURCE, warmup=10, seconds=10, static_diagnostics=True), 'procedural')
        self.assertEqual(self.analyze()['runtime_observed']['scene']['presentation'], 'procedural')
        self.report['identity']['runtime_observed']['scene']['presentation'] = 'authored_viewmodel'
        dump(self.session / 'frames.json', self.report)
        with self.assertRaisesRegex(ValueError, 'Procedural case'):
            self.analyze()

    def test_no_invented_cli_flags_or_capture(self):
        exe = self.root / 'vector-range.exe'
        for case in m.make_plan(SOURCE)['cases']:
            args = m.case_command(exe, 'dx12', self.root, case, False)
            self.assertIn('--no-update', args)
            self.assertIn('--hold-controls', args)
            self.assertFalse(any(arg.startswith(('--capture', '--fps', '--aa', '--lod', '--vsync')) for arg in args))
        args = m.case_command(exe, 'gl-harness', self.root, self.case, False)
        self.assertIn('--renderer=gl', args)
        self.assertIn('--graphics-device=auto', args)
        with self.assertRaises(ValueError):
            m.case_command(exe, 'gl-harness', self.root, self.case, True)

    def test_plan_rejects_unsupported_or_tampered_axes(self):
        for renderer in ('gl', 'auto'):
            with self.assertRaises(ValueError):
                m.make_plan(SOURCE, renderer)
        plan = m.make_plan(SOURCE)
        plan['cases'][0]['settings']['aa'] = 'taa'
        with self.assertRaises(ValueError):
            m.validate_plan(plan)
        for kw in ({'repeats': 0}, {'warmup': 0}, {'seconds': 121}, {'repeats': True}):
            with self.assertRaises(ValueError):
                m.make_plan(SOURCE, **kw)

    def test_valid_actual_schema_uses_present_intervals_not_csv_fps(self):
        result = self.analyze()
        self.assertEqual(result['effective_present_hz'], 20)
        self.assertEqual(result['frame_summary_ns']['p99_ns'], 50_000_000)
        self.assertEqual(result['cpu_stages']['summary']['renderer_submit']['p99_ns'], 100)
        self.assertFalse(result['acceptance_proven'])
        self.assertIsNone(result['gpu_frame_duration_ns'])
        self.assertIsNone(result['draw_pass_triangle_counts'])
        self.assertFalse(result['gameplay_observed']['render_fps_column_used_for_timing'])

    def test_setup_analysis_stays_scoped_even_when_complete(self):
        result = m.analyze_matrix(self.root)
        self.assertEqual(result['state'], 'setup_complete')
        self.assertFalse(result['acceptance_proven'])
        self.assertTrue(result['pilot_sample_readiness']['ready'])
        self.assertEqual(result['case_comparisons'], [])
        self.assertEqual(result['paired_baseline_comparisons'], [])

    def test_low_sample_smoke_separates_setup_from_pilot_readiness(self):
        dump(self.session / 'frames.json', trace(self.case, self.adapter, self.build, intervals=38, interval_ns=1_000_000_000))
        result = m.analyze_matrix(self.root)
        self.assertEqual(result['state'], 'setup_complete')
        self.assertFalse(result['pilot_sample_readiness']['ready'])
        self.assertEqual(result['runs'][0]['sample_quality']['required_intervals_for_tail_comparison'], 100)
        self.assertEqual(result['runs'][0]['sample_quality']['observed_intervals'], 38)
        self.assertFalse(result['runs'][0]['sample_quality']['tail_comparison_ready'])
        with mock.patch.object(m, 'analyze_matrix', return_value=result), mock.patch('builtins.print'):
            self.assertEqual(m.main(['analyze', str(self.root)]), 1)
        # Only the plan's existing smoke scope allows descriptive setup data.
        # A pilot with the same measurements still fails the original100 gate.
        self.manifest['plan']['smoke'] = False
        with self.assertRaisesRegex(ValueError, '100 intervals'):
            self.analyze()

    def test_failed_exit_receipt_cannot_be_reclassified_as_setup_success(self):
        self.receipt['completed'] = False
        self.receipt['error'] = 'close timed out'
        dump(self.folder / 'RESULT.json', self.receipt)
        result = m.analyze_matrix(self.root)
        self.assertEqual(result['state'], 'incomplete')
        self.assertFalse(result['pilot_sample_readiness']['ready'])
        self.assertFalse(result['measurement_readiness']['ready'])

    def recovered_receipt(self):
        self.manifest['continue_after_exit_timeout'] = True
        dump(self.root / 'MANIFEST.json', self.manifest)
        self.receipt.update(completed=False, graceful_shutdown=False,
                            outcome='measurements_valid_shutdown_failed', normal_exit_timed_out=True,
                            exit_wait_timeout_seconds=15, error='normal exit timed out', process_id=123,
                            measurement_validated_before_exit=True, measurement_tail_ready_before_exit=True,
                            measurement_files_before_exit=m.measurement_file_hashes(self.session),
                            input_cleanup_errors=[], cleanup={'process_id': 123, 'process_exit_verified': True,
                                                            'returncode': 1, 'termination_requested': True})
        self.receipt.pop('returncode')
        dump(self.folder / 'RESULT.json', self.receipt)

    def test_verified_cleanup_permits_measurements_but_never_correctness_success(self):
        self.recovered_receipt()
        with self.assertRaises(ValueError):
            self.analyze()
        result = m.analyze_matrix(self.root)
        self.assertEqual(result['state'], 'incomplete')
        self.assertFalse(result['graceful_shutdown'])
        self.assertFalse(result['pilot_sample_readiness']['ready'])
        self.assertTrue(result['measurement_readiness']['ready'])
        self.assertEqual(result['runs'][0]['outcome'], 'measurements_valid_shutdown_failed')
        self.assertEqual(result['failures'][0]['kind'], 'graceful_shutdown')
        with mock.patch('builtins.print'):
            self.assertEqual(m.main(['analyze', str(self.root)]), 1)
            self.assertEqual(m.main(['analyze', str(self.root), '--measurement-readiness']), 0)

    def test_cleanup_recovery_rejects_unverified_or_changed_scope_and_measurements(self):
        self.recovered_receipt()
        mutations = [('cleanup', {'process_id': 456, 'process_exit_verified': True, 'returncode': 1}),
                     ('cleanup', {'process_id': 123, 'process_exit_verified': False, 'returncode': 1}),
                     ('cleanup', {'process_id': 123, 'process_exit_verified': True, 'returncode': None}),
                     ('input_cleanup_errors', ['release failed']), ('measurement_validated_before_exit', False),
                     ('normal_exit_timed_out', False), ('exit_wait_timeout_seconds', 30)]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                dump(self.folder / 'RESULT.json', {**self.receipt, key: value})
                self.assertFalse(m.analyze_matrix(self.root)['measurement_readiness']['ready'])
        dump(self.folder / 'RESULT.json', self.receipt)
        self.manifest['continue_after_exit_timeout'] = False
        dump(self.root / 'MANIFEST.json', self.manifest)
        self.assertFalse(m.analyze_matrix(self.root)['measurement_readiness']['ready'])
        self.manifest['continue_after_exit_timeout'] = True
        dump(self.root / 'MANIFEST.json', self.manifest)
        self.report['identity']['runtime_observed']['actual_adapter']['present_mode'] = 'Immediate'
        dump(self.session / 'frames.json', self.report)
        self.assertFalse(m.analyze_matrix(self.root)['measurement_readiness']['ready'])

    def test_recovery_rejects_cleanup_time_mutation_even_when_export_remains_valid(self):
        self.recovered_receipt()
        path = self.session / 'gameplay.csv'
        path.write_text(path.read_text().replace(',999999\n', ',42\n'))
        # This unused FPS field does not change measurement validity itself.
        m.analyze_measurements(self.folder, self.manifest, self.receipt)
        result = m.analyze_matrix(self.root)
        self.assertFalse(result['measurement_readiness']['ready'])
        self.assertIn('changed after pre-exit', result['failures'][0]['error'])

    def test_missing_run_is_incomplete_and_never_zero_filled(self):
        (self.folder / 'RESULT.json').unlink()
        result = m.analyze_matrix(self.root)
        self.assertEqual(result['state'], 'incomplete')
        self.assertEqual(len(result['failures']), 1)
        self.assertEqual(result['case_comparisons'], [])

    def test_extent_backend_present_gpu_and_scene_identity_mutations_fail(self):
        paths = [(['initial_window', 'physical_width'], 1440),
                 (['actual_backend'], 'Gl'), (['actual_adapter', 'present_mode'], 'Immediate'),
                 (['actual_adapter', 'actual_fingerprint', 'device_id'], 999),
                 (['actual_adapter', 'selection_mode'], 'automatic'),
                 (['scene', 'diagnostic_capture'], True), (['scene', 'demo'], True),
                 (['scene', 'presentation'], 'unavailable'), (['scene', 'reference_viewport'], True)]
        for path, value in paths:
            with self.subTest(path=path):
                report = copy.deepcopy(self.report)
                cursor = report['identity']['runtime_observed']
                for key in path[:-1]:
                    cursor = cursor[key]
                cursor[path[-1]] = value
                dump(self.session / 'frames.json', report)
                with self.assertRaises(ValueError):
                    self.analyze()

    def test_frame_schema_tampering_is_rejected(self):
        self.report['summary']['p99_ns'] = 1
        dump(self.session / 'frames.json', self.report)
        with self.assertRaises(ValueError):
            self.analyze()

    def test_settings_and_source_mismatches_fail(self):
        (self.folder / 'settings.cfg').write_text('fov = 65\n')
        with self.assertRaisesRegex(ValueError, 'Settings'):
            self.analyze()
        (self.folder / 'settings.cfg').write_bytes(self.settings)
        self.identity['source']['commit'] = 'd' * 40
        dump(self.session / 'IDENTITY.json', self.identity)
        with self.assertRaisesRegex(ValueError, 'source'):
            self.analyze()

    def test_observed_gameplay_rejects_wrong_actions(self):
        for speed, ads in ((3, 0), (0, 1)):
            self.csv(speed, ads)
            with self.assertRaises(ValueError):
                self.analyze()

    def test_disabled_or_missing_stages_remain_unavailable(self):
        del self.report['cpu_frame_stages']
        dump(self.session / 'frames.json', self.report)
        with self.assertRaisesRegex(ValueError, 'CPU-stage'):
            self.analyze()

    def test_gpu_preference_auto_cpu_and_wrong_backend_rejected(self):
        for value in ({'schema': GRAPHICS['schema'], 'adapter': None},
                      {'schema': GRAPHICS['schema'], 'adapter': {**FINGERPRINT, 'device_type': 'Cpu'}},
                      {'schema': GRAPHICS['schema'], 'adapter': {**FINGERPRINT, 'backend': 'vulkan'}}):
            with self.assertRaises(ValueError):
                m.validate_graphics(value, 'dx12')

    def test_lock_serializes_across_output_directories(self):
        path = self.root / 'desktop.lock'
        with m.desktop_lock(path):
            with self.assertRaises(FileExistsError):
                with m.desktop_lock(path):
                    self.fail('second process entered')
        self.assertFalse(path.exists())

    def test_output_does_not_overwrite_or_follow_links(self):
        path = self.root / 'existing.json'
        m.write_json(path, {'keep': 1})
        with self.assertRaises(FileExistsError):
            m.write_json(path, {'keep': 2})
        self.assertEqual(m.json_read(path), {'keep': 1})

    def test_incomplete_json_waits_and_missing_gpu_status_is_not_complete(self):
        (self.session / 'GPU_STATUS.json').write_text('{')
        self.assertIsNone(m.sole_session(self.folder, complete=True))
        (self.session / 'GPU_STATUS.json').unlink()
        self.assertIsNone(m.sole_session(self.folder, complete=True))

    def test_gpu_export_status_and_counts_are_independently_validated(self):
        original = m.json_read(self.session / 'GPU_STATUS.json')
        for mutation in ({'state': 'interrupted'}, {'state': 'incomplete'}, {'schema': 'other'},
                         {'error': 'write failed'}, {'samples_written': 2},
                         {'gpu_frame_duration_available': True}):
            dump(self.session / 'GPU_STATUS.json', {**original, **mutation})
            with self.assertRaises(ValueError):
                self.analyze()

    def test_execution_not_implicit(self):
        args = mock.Mock(execute=False)
        with mock.patch.object(m.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(ValueError, '--execute'):
                m.run_matrix(args)
        launch.assert_not_called()

    def test_case_runner_drives_existing_controls_and_waits_for_exit(self):
        item = {**self.item, 'run_id': 'new-run'}
        driver, process = mock.Mock(), mock.Mock()
        driver.release_inputs.return_value = []
        driver.exit_status.return_value = {'synthetic': True}
        process.pid = 123
        process.poll.return_value = 0
        process.wait.return_value = 0
        with mock.patch.object(m, 'create_driver', return_value=driver), \
                mock.patch.object(m.subprocess, 'Popen', return_value=process) as launch, \
                mock.patch.object(m, 'tap') as tap, \
                mock.patch.object(m, 'replay', return_value={'elapsed_seconds': 10}), \
                mock.patch.object(m.time, 'sleep'), \
                mock.patch.object(m, 'wait_until', return_value=self.session):
            receipt = m.run_case(self.plan, item, self.case, self.root / 'vector-range',
                                 self.root, self.settings, GRAPHICS, False, 'win32')
        self.assertTrue(receipt['completed'])
        self.assertEqual(tap.call_args_list,
                         [mock.call(driver, 'Return')] * 3 + [mock.call(driver, 'F2'),
                          mock.call(driver, 'F8'), mock.call(driver, 'F8')])
        driver.configure.assert_called_once_with([1920, 1080])
        driver.close.assert_called_once()
        process.wait.assert_called_once_with(timeout=15)
        self.assertEqual(launch.call_args.kwargs['cwd'], self.root / 'new-run')
        self.assertTrue((self.root / 'new-run' / 'RESULT.json').is_file())
        driver.exit_status.assert_called_once_with(process, probe_responsiveness=False)

    def run_timed_out_case(self, *, allow=True, cleanup=True, validate_error=None):
        item = {**self.item, 'run_id': 'timeout-run'}
        folder = self.root / item['run_id']
        manifest = copy.deepcopy(self.manifest)
        manifest['plan']['order'] = [item]
        manifest['continue_after_exit_timeout'] = allow
        driver, process = mock.Mock(), mock.Mock()
        driver.release_inputs.return_value = []
        driver.exit_status.return_value = {'synthetic': True}
        process.pid, process.returncode = 123, None
        process.poll.side_effect = lambda: process.returncode
        def terminate():
            if cleanup:
                process.returncode = 1
        process.terminate.side_effect = terminate
        def wait(timeout):
            if timeout == 15:
                raise subprocess.TimeoutExpired('synthetic game', 15)
            return 1
        process.wait.side_effect = wait
        def launch(*args, **kwargs):
            shutil.copytree(self.folder / 'telemetry-sessions', folder / 'telemetry-sessions')
            return process
        session = folder / 'telemetry-sessions' / self.session.name
        original = m.analyze_measurements
        with mock.patch.object(m, 'create_driver', return_value=driver), \
                mock.patch.object(m.subprocess, 'Popen', side_effect=launch), \
                mock.patch.object(m, 'tap'), mock.patch.object(m, 'replay', return_value={}), \
                mock.patch.object(m.time, 'sleep'), mock.patch.object(m, 'wait_until', return_value=session), \
                mock.patch.object(m, 'analyze_measurements', side_effect=validate_error or original):
            try:
                value = m.run_case(manifest['plan'], item, self.case, self.root / 'vector-range',
                                   self.root, self.settings, GRAPHICS, False, 'win32',
                                   manifest=manifest, continue_after_exit_timeout=allow)
            except Exception as error:
                value = error
        return value, m.json_read(folder / 'RESULT.json'), driver, process

    def test_timeout_continuation_records_failure_after_validation_and_owned_cleanup(self):
        value, receipt, driver, process = self.run_timed_out_case()
        self.assertIsInstance(value, dict)
        self.assertFalse(receipt['completed'])
        self.assertFalse(receipt['graceful_shutdown'])
        self.assertEqual(receipt['outcome'], 'measurements_valid_shutdown_failed')
        self.assertTrue(receipt['measurement_validated_before_exit'])
        self.assertTrue(receipt['cleanup']['process_exit_verified'])
        self.assertIn('after_timeout', receipt['exit_diagnostics'])
        self.assertEqual(driver.exit_status.call_args_list,
                         [mock.call(process, probe_responsiveness=False), mock.call(process, probe_responsiveness=True)])
        self.assertEqual(process.wait.call_args_list, [mock.call(timeout=15), mock.call(timeout=5)])
        process.terminate.assert_called_once_with()
        process.kill.assert_not_called()

    def test_default_timeout_still_raises_after_retaining_diagnostics(self):
        value, receipt, _, _ = self.run_timed_out_case(allow=False)
        self.assertIsInstance(value, subprocess.TimeoutExpired)
        self.assertEqual(receipt['outcome'], 'incomplete')
        self.assertTrue(receipt['cleanup']['process_exit_verified'])

    def test_unverified_cleanup_blocks_continuation(self):
        value, receipt, _, _ = self.run_timed_out_case(cleanup=False)
        self.assertIsInstance(value, ValueError)
        self.assertIn('cleanup was not verified', str(value))
        self.assertEqual(receipt['outcome'], 'incomplete')
        self.assertFalse(receipt['cleanup']['process_exit_verified'])

    def test_continuation_never_waives_low_sample_gate(self):
        adapter = self.report['identity']['runtime_observed']['actual_adapter']
        self.report = trace(self.case, adapter, self.build, intervals=38, interval_ns=1_000_000_000)
        dump(self.session / 'frames.json', self.report)
        value, receipt, _, _ = self.run_timed_out_case()
        self.assertIsInstance(value, subprocess.TimeoutExpired)
        self.assertFalse(receipt['measurement_tail_ready_before_exit'])
        self.assertEqual(receipt['outcome'], 'incomplete')

    def test_cli_reserves_nonzero_three_for_measurement_ready_shutdown_failure(self):
        args = ['run', '--plan', 'plan.json', '--repository', '.', '--executable', 'game.exe',
                '--settings', 'settings.cfg', '--output', 'out', '--driver', 'win32', '--execute']
        for ready, expected in [(True, 3), (False, 2)]:
            with mock.patch.object(m, 'run_matrix', return_value=self.root), \
                    mock.patch.object(m, 'analyze_matrix', return_value={
                        'state': 'incomplete', 'measurement_readiness': {'ready': ready}}), \
                    mock.patch('builtins.print'):
                self.assertEqual(m.main(args), expected)

    def test_invalid_exports_prevent_exit_recovery_before_close_is_requested(self):
        value, receipt, driver, _ = self.run_timed_out_case(validate_error=ValueError('bad source digest'))
        self.assertIsInstance(value, ValueError)
        self.assertEqual(receipt['outcome'], 'incomplete')
        self.assertNotIn('measurement_validated_before_exit', receipt)
        driver.close.assert_not_called()
        driver.exit_status.assert_not_called()

    def test_driver_failure_retains_receipt_and_stops_own_process(self):
        item = {**self.item, 'run_id': 'failed-run'}
        driver, process = mock.Mock(), mock.Mock()
        driver.release_inputs.return_value = []
        driver.bind.side_effect = d.DriverError('no surface')
        process.pid = 123
        process.poll.return_value = None
        with mock.patch.object(m, 'create_driver', return_value=driver), \
                mock.patch.object(m.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(d.DriverError, 'no surface'):
                m.run_case(self.plan, item, self.case, self.root / 'vector-range',
                           self.root, self.settings, GRAPHICS, False, 'win32')
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=5)
        result = m.json_read(self.root / 'failed-run' / 'RESULT.json')
        self.assertFalse(result['completed'])
        self.assertEqual(result['error'], 'no surface')


class DriverTests(unittest.TestCase):
    def native_status_fixture(self, owner=123, exists=True):
        driver = object.__new__(d.WindowsDriver)
        driver.window, driver.user, driver.kernel = 456, mock.Mock(), mock.Mock()
        driver.user.IsWindow.return_value = exists
        driver.user.IsWindowVisible.return_value = True
        driver.user.GetForegroundWindow.return_value = 456
        def window_owner(hwnd, target):
            target._obj.value = owner
            return 789
        driver.user.GetWindowThreadProcessId.side_effect = window_owner
        def times(handle, created, exited, kernel, user):
            kernel._obj.dwLowDateTime, user._obj.dwLowDateTime = 100, 200
            return True
        driver.kernel.GetProcessTimes.side_effect = times
        def rect(hwnd, target):
            target._obj.right, target._obj.bottom = 1920, 1080
            return True
        driver.user.GetClientRect.side_effect = rect
        def gui(thread, target):
            target._obj.flags = 0x04 | 0x08
            return True
        driver.user.GetGUIThreadInfo.side_effect = gui
        driver.user.SendMessageTimeoutW.return_value = 1
        process = SimpleNamespace(pid=123, _handle=12, poll=lambda: None)
        return driver, process

    def test_exit_status_only_probes_verified_owned_hwnd_after_timeout(self):
        driver, process = self.native_status_fixture()
        before = driver.exit_status(process)
        self.assertEqual(before['cpu_time_100ns'], {'kernel': 100, 'user': 200})
        self.assertEqual(before['window']['client_extent'], [1920, 1080])
        self.assertTrue(before['window']['gui_thread']['system_menu_mode'])
        driver.user.SendMessageTimeoutW.assert_not_called()
        with mock.patch.object(ctypes, 'set_last_error', create=True):
            after = driver.exit_status(process, probe_responsiveness=True)
        self.assertTrue(after['window']['responsiveness']['responded'])
        self.assertEqual(driver.user.SendMessageTimeoutW.call_args.args[:6], (456, 0, 0, 0, 0x23, 2000))
        for owner, exists in [(999, True), (123, False)]:
            driver, process = self.native_status_fixture(owner=owner, exists=exists)
            value = driver.exit_status(process, probe_responsiveness=True)
            self.assertFalse(value['window']['owned_by_launched_process'])
            driver.user.SendMessageTimeoutW.assert_not_called()
            driver.user.GetGUIThreadInfo.assert_not_called()

    def test_probe_failure_is_safe_status_and_diagnostic_exception_is_not_fatal(self):
        driver, process = self.native_status_fixture()
        driver.user.SendMessageTimeoutW.return_value = 0
        with mock.patch.object(ctypes, 'set_last_error', create=True), \
                mock.patch.object(ctypes, 'get_last_error', return_value=1460, create=True):
            value = driver.exit_status(process, probe_responsiveness=True)
        self.assertFalse(value['window']['responsiveness']['responded'])
        self.assertEqual(value['window']['responsiveness']['winerror'], 1460)
        driver.exit_status = mock.Mock(side_effect=OSError('unavailable'))
        self.assertEqual(d.exit_snapshot(driver, process), {'unavailable': 'OSError'})

    def test_both_desktop_backends_use_tracked_application_f10_exit(self):
        self.assertEqual(d.WindowsDriver.KEYS['F10'], 0x79)
        for native in (mock.Mock(spec=d.WindowsDriver), mock.Mock(spec=d.X11Driver)):
            tracked = d.TrackedDriver(native)
            with mock.patch.object(d.time, 'sleep'):
                tracked.close()
            self.assertEqual(native.key.call_args_list, [mock.call('F10', True), mock.call('F10', False)])
            native.close.assert_not_called()
            self.assertEqual(tracked.held_keys, set())

    def test_x11_binding_requires_intersection_and_verifies_pid(self):
        driver = object.__new__(d.X11Driver)
        driver.command = mock.Mock(side_effect=['777', '123'])
        driver.bind(123)
        self.assertEqual(driver.window, '777')
        self.assertIn('--all', driver.command.call_args_list[0].args)
        self.assertEqual(driver.command.call_args_list[1], mock.call('getwindowpid', '777'))
        driver.command = mock.Mock(side_effect=['777', '456'])
        with self.assertRaisesRegex(d.DriverError, 'PID'):
            driver.bind(123)

    def test_cleanup_releases_aim_when_keyboard_release_fails(self):
        native = mock.Mock()
        driver = d.TrackedDriver(native)
        driver.key('w', True)
        driver.aim(True)
        native.key.side_effect = d.DriverError('key release failed')
        self.assertEqual(driver.release_inputs(), ['key release failed'])
        native.aim.assert_called_with(False)
        self.assertFalse(driver.aim_held)
        self.assertEqual(driver.held_keys, {'w'})

    def test_replay_alternates_movement_and_releases_inputs(self):
        driver = mock.Mock()
        process = mock.Mock()
        process.poll.return_value = None
        with mock.patch.object(d.time, 'monotonic', side_effect=[0, 0, 2, 4, 4.1]), mock.patch.object(d.time, 'sleep'):
            result = d.replay(driver, process, [1920, 1080], 'movement', 4)
        self.assertEqual(driver.key.call_args_list,
                         [mock.call('w', True), mock.call('w', False), mock.call('s', True), mock.call('s', False)])
        self.assertEqual(result['elapsed_seconds'], 4.1)
        self.assertEqual(driver.aim.call_args_list[-1], mock.call(False))

    def test_focus_failure_releases_held_inputs(self):
        driver = mock.Mock()
        driver.check.side_effect = [None, d.DriverError('focus lost')]
        process = mock.Mock()
        process.poll.return_value = None
        with mock.patch.object(d.time, 'monotonic', side_effect=[0, 0, 1]), mock.patch.object(d.time, 'sleep'):
            with self.assertRaises(d.DriverError):
                d.replay(driver, process, [1920, 1080], 'movement', 4)
        self.assertEqual(driver.key.call_args_list[-1], mock.call('w', False))
        self.assertEqual(driver.aim.call_args_list[-1], mock.call(False))

    def test_no_display_or_xdotool_does_not_install_or_allocate(self):
        with mock.patch.dict(d.os.environ, {}, clear=True), mock.patch.object(d.subprocess, 'run') as run:
            with self.assertRaises(d.DriverError):
                d.X11Driver()
        run.assert_not_called()


class BuildComparisonTests(unittest.TestCase):
    """Original source-pair fixtures; no native process or downloaded binary."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = {label: {'commit': char * 40, 'runtime_files_sha256': {
            **{name: (label + name) for name in m.CPU_SOURCE_PATHS}, 'src/common.rs': 'common'}}
            for label, char in (('baseline', 'a'), ('candidate', 'b'))}
        for label, name in (('baseline', 'AUDITED_GPU_CPU_BASELINE_MANIFEST'),
                            ('candidate', 'AUDITED_GPU_CANDIDATE_MANIFEST')):
            item = mock.patch.object(m, name, m.canonical_hash(self.sources[label]['runtime_files_sha256']))
            item.start()
            self.addCleanup(item.stop)
        settings = self.root / 'settings.cfg'
        settings.write_bytes(b'original settings')
        self.args = SimpleNamespace(execute=True, driver='win32', force_fallback=True,
            graphics_settings=None, hardware=None, settings=settings, output=self.root / 'comparison',
            baseline_source_witness=self.root / 'baseline', baseline_witness_sha256='1' * 64,
            candidate_source_witness=self.root / 'candidate', candidate_witness_sha256='2' * 64,
            baseline_executable=self.root / 'baseline.exe', candidate_executable=self.root / 'candidate.exe',
            warmup_seconds=15, sample_seconds=45, procedural_baseline=True,
            lock_file=self.root / 'desktop.lock',
            baseline_build_receipt=self.root / 'baseline-build.json',
            candidate_build_receipt=self.root / 'candidate-build.json')
        import run_cpu_image_preservation as pair
        production = {label: {**source['runtime_files_sha256'], 'Cargo.toml': 'same manifest'}
                      for label, source in self.sources.items()}
        for item in (mock.patch.object(pair, 'PRODUCTION_MANIFEST', m.canonical_hash(production['candidate'])),
                     mock.patch.object(pair, 'CPU_BASELINE', {name: production['baseline'][name] for name in m.CPU_SOURCE_PATHS})):
            item.start()
            self.addCleanup(item.stop)
        for label in ('baseline', 'candidate'):
            dump(getattr(self.args, label + '_build_receipt'), {
                'schema': 'rust-duty-performance-release-build/v1', 'source_commit': self.sources[label]['commit'],
                'production_files_sha256': production[label], 'executable_sha256': label,
                'ci_run_source_commit': self.sources['candidate']['commit'],
                'command': ['cargo', 'build', '--locked', '--release', '--no-default-features',
                            '--features', 'wgpu-runtime', '--bin', 'vector-range'],
                'build_settings': {'CARGO_INCREMENTAL': '0', 'CARGO_BUILD_JOBS': '2', 'CARGO_PROFILE_RELEASE_DEBUG': '0'},
                'build_result': {'exit_code': 0}, 'toolchain': {
                    'rustc': 'rustc 1.99.0\nhost: x86_64-pc-windows-msvc\nrelease: 1.99.0\n',
                    'cargo': 'cargo 1.99.0 synthetic'}})
        self.calls = []

    def exercise(self, mutation=None):
        def source(path, digest):
            return copy.deepcopy(self.sources[Path(path).name])
        def package(exe, source, renderer):
            return {'adjacent_files_sha256': {'ui/theme.css': (
                'changed' if mutation == 'assets' and Path(exe).stem == 'candidate' else 'same')},
                'executable_sha256': Path(exe).stem,
                'build': {'repository': 'RHS059/rust_duty', 'target': 'x86_64-pc-windows-msvc',
                    'display_version': 'different' if mutation == 'label' and Path(exe).stem == 'candidate' else 'same',
                    'source': {'commit': source['commit'], 'workflow': '.github/workflows/build.yml',
                               'run_attempt': 2 if mutation == 'run-attempt' and Path(exe).stem == 'candidate' else 1}}}
        def run(args):
            self.assertTrue(self.args.lock_file.is_file())
            self.assertNotEqual(args.lock_file, self.args.lock_file)
            self.assertFalse(args.continue_after_exit_timeout)
            label = Path(args.executable).stem
            self.calls.append(label)
            plan = m.json_read(args.plan)
            self.assertTrue(plan['gpu_timestamps'] and plan['baseline_only'] and plan['procedural_baseline'])
            self.assertEqual(len(plan['order']), 1)
            args.output.mkdir()
            if mutation == 'settings':
                self.args.settings.write_bytes(b'changed settings')
            pinned = package(args.executable, self.sources[label], 'dx12')
            if mutation == 'child-package' and len(self.calls) == 2:
                pinned['executable_sha256'] = 'changed executable'
            dump(args.output / 'MANIFEST.json', {'settings_sha256': m.sha256(args.settings),
                'graphics': {'schema': 'rust-duty-graphics-device/v1', 'adapter': None},
                'package': pinned, 'plan': plan})
            if mutation == 'earlier-evidence' and len(self.calls) == 2:
                (self.args.output / 'r01-baseline/MANIFEST.json').write_bytes(b'changed old evidence')
        def analyze(folder):
            n = int(Path(folder).name.split('-')[0][1:])
            ready = not (mutation == 'undersampled' and n == 2)
            adapter = {'name': 'changed' if mutation == 'adapter' and n == 2 else 'same'}
            return {'state': 'complete', 'measurement_readiness': {'ready': ready},
                    'runs': [{'runtime_observed': {'actual_adapter': adapter,
                         'initial_window': {'physical_width': 1920, 'physical_height': 1080, 'scale_factor': 1},
                         'scene': {'presentation': 'procedural'}},
                         'started_unix_ns': 0 if mutation == 'overlap' and n == 2 else n * 100,
                         'finished_unix_ns': n * 100 + 50}]}
        with mock.patch.object(m, 'artifact_source', side_effect=source), \
                mock.patch.object(m, 'package_identity', side_effect=package), \
                mock.patch.object(m, 'run_matrix', side_effect=run), \
                mock.patch.object(m, 'analyze_matrix', side_effect=analyze):
            return m.compare_builds(self.args)

    def test_eight_run_bracketed_order_holds_outer_lock_and_keeps_no_performance_verdict(self):
        result = self.exercise()
        self.assertEqual(self.calls, ['baseline', 'candidate', 'candidate', 'baseline'] * 2)
        self.assertFalse(self.args.lock_file.exists())
        self.assertEqual(result['state'], 'complete')
        self.assertIsNone(result['performance_improvement'])
        self.assertFalse(result['target_1080p60_proven'])
        self.assertEqual(result, m.json_read(self.args.output / 'COMPARE_SUMMARY.json'))

    def test_different_assets_stop_before_any_game(self):
        with self.assertRaisesRegex(ValueError, 'adjacent assets'):
            self.exercise('assets')
        self.assertEqual(self.calls, [])

    def test_changed_settings_adapter_overlapping_or_undersampled_run_stops_comparison(self):
        for mutation in ('settings', 'adapter', 'overlap', 'undersampled'):
            with self.subTest(mutation=mutation):
                if self.args.output.exists():
                    shutil.rmtree(self.args.output)
                self.args.settings.write_bytes(b'original settings')
                self.calls.clear()
                with self.assertRaises(ValueError):
                    self.exercise(mutation)
                self.assertLessEqual(len(self.calls), 2)
                self.assertFalse(self.args.lock_file.exists())
                self.assertEqual(m.json_read(self.args.output / 'COMPARE_FAILURE.json')['state'], 'incomplete')

    def test_changed_child_package_and_earlier_retained_evidence_fail(self):
        for mutation, error in (('child-package', 'child package'), ('earlier-evidence', 'Earlier comparison evidence')):
            with self.subTest(mutation=mutation):
                if self.args.output.exists():
                    shutil.rmtree(self.args.output)
                self.calls.clear()
                with self.assertRaisesRegex(ValueError, error):
                    self.exercise(mutation)
                self.assertFalse(self.args.lock_file.exists())

    def test_unreviewed_non_runtime_compile_input_or_compiler_identity_fails(self):
        receipt = m.json_read(self.args.candidate_build_receipt)
        original = copy.deepcopy(receipt)
        receipt['production_files_sha256']['Cargo.toml'] = 'different manifest'
        dump(self.args.candidate_build_receipt, receipt)
        with self.assertRaisesRegex(ValueError, 'closed reviewed production'):
            self.exercise()
        receipt = copy.deepcopy(original)
        receipt['toolchain']['rustc'] = 'unreviewed compiler'
        dump(self.args.candidate_build_receipt, receipt)
        with self.assertRaisesRegex(ValueError, 'compiler identities'):
            self.exercise()
        self.assertEqual(self.calls, [])

    def test_mixed_ci_attempts_labels_or_receipt_source_fail_before_launch(self):
        for mutation in ('label', 'run-attempt'):
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'CI run identities'):
                self.exercise(mutation)
        receipt = m.json_read(self.args.baseline_build_receipt)
        receipt['ci_run_source_commit'] = 'c' * 40
        dump(self.args.baseline_build_receipt, receipt)
        with self.assertRaisesRegex(ValueError, 'different candidate CI source'):
            self.exercise()
        self.assertEqual(self.calls, [])

    def test_unreviewed_source_or_reused_commit_is_rejected_before_launch(self):
        self.sources['baseline']['runtime_files_sha256']['src/common.rs'] = 'unreviewed'
        with self.assertRaisesRegex(ValueError, 'exact reviewed baseline'):
            self.exercise()
        self.sources['baseline']['runtime_files_sha256']['src/common.rs'] = 'common'
        self.sources['baseline']['commit'] = self.sources['candidate']['commit']
        receipt = m.json_read(self.args.baseline_build_receipt)
        receipt['source_commit'] = self.sources['candidate']['commit']
        dump(self.args.baseline_build_receipt, receipt)
        with self.assertRaisesRegex(ValueError, 'distinct real source commits'):
            self.exercise()
        self.assertEqual(self.calls, [])


class SourceWitnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        # This is a deliberately synthetic Git fixture. These protocol tests
        # must work in a tools-only checkout and must not inspect the current
        # game's source, production hashes, or historical Git objects.
        self.repository = self.root / 'synthetic-repository'
        self.repository.mkdir()
        hashes = {}
        for name in (*m.SOURCE_PATHS, *m.CPU_SOURCE_PATHS, *m.PRESENT_SOURCE_PATHS[1:]):
            path = self.repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('// Synthetic witness protocol fixture: ' + name + '\n').encode())
            hashes[name] = m.sha256(path)
        subprocess.run(['git', 'init', '--quiet', str(self.repository)], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(['git', '-C', str(self.repository), 'add', '--', *m.SOURCE_PATHS,
                        *m.CPU_SOURCE_PATHS, *m.PRESENT_SOURCE_PATHS[1:]],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        hooks = self.root / 'empty-hooks'
        hooks.mkdir()
        subprocess.run(['git', '-C', str(self.repository), '-c', 'user.name=Matrix Protocol Test',
                        '-c', 'user.email=matrix-protocol@example.invalid',
                        '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=' + str(hooks),
                        'commit', '--quiet', '-m', 'Synthetic source-witness test fixture'],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        cpu_audit = mock.patch.object(m, 'CPU_BASELINE_MANIFEST',
                                      m.canonical_hash({name: hashes[name] for name in m.CPU_SOURCE_PATHS}))
        cpu_audit.start()
        self.addCleanup(cpu_audit.stop)
        present_audit = mock.patch.object(m, 'PRESENT_BASELINE_MANIFEST',
                                          m.canonical_hash({name: hashes[name] for name in m.PRESENT_SOURCE_PATHS[1:]}))
        present_audit.start()
        self.addCleanup(present_audit.stop)
        audit = mock.patch.object(m, 'AUDITED_RUNTIME_MANIFEST',
                                  m.canonical_hash({name: hashes[name] for name in m.SOURCE_PATHS}))
        audit.start()
        self.addCleanup(audit.stop)
        self.witness = self.root / 'witness'
        self.digest = m.export_witness(self.repository, self.witness)

    def tearDown(self):
        self.temp.cleanup()

    def test_real_git_export_roundtrips_without_git_in_artifact(self):
        self.assertFalse((self.witness / '.git').exists())
        with mock.patch.object(m.subprocess, 'check_output', side_effect=AssertionError('artifact route must not invoke Git')):
            source = m.artifact_source(self.witness, self.digest)
        self.assertEqual(m.canonical_hash(source['runtime_files_sha256']), m.AUDITED_RUNTIME_MANIFEST)
        self.assertEqual(len(source['runtime_files_sha256']), 17)
        args = SimpleNamespace(source_witness=self.witness, witness_sha256=self.digest, repository=None)
        actual, origin, root = m.resolve_source(args)
        self.assertEqual(source, actual)
        self.assertEqual(origin, {'mode': 'artifact-witness', 'witness_sha256': self.digest})
        self.assertEqual(root, self.witness)
        plan = m.make_plan(actual, smoke=True, source_origin=origin)
        m.validate_plan(plan)

    def test_synthetic_source_ignores_windows_text_defaults(self):
        # Emulate Windows' text-mode LF -> CRLF conversion on every host. The
        # synthetic committed source must explicitly retain LF bytes.
        write_text = Path.write_text

        def windows_text(path, data, *args, **kwargs):
            kwargs.setdefault('newline', '\r\n')
            return write_text(path, data, *args, **kwargs)

        with mock.patch.object(Path, 'write_text', windows_text):
            self.gpu_fixture()
            source = m.source_identity(self.repository)
        self.assertEqual(len(source['runtime_files_sha256']), 29)
        for name in source['runtime_files_sha256']:
            self.assertNotIn(b'\r\n', (self.repository / name).read_bytes())

    def test_git_clean_crlf_worktree_still_fails_exact_byte_guard(self):
        path = self.repository / m.SOURCE_PATHS[0]
        path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
        # Git may call a CRLF worktree clean while its committed blob is LF.
        # The production witness must reject that byte mismatch regardless.
        subprocess.run(['git', '-C', str(self.repository), '-c', 'core.autocrlf=true',
                        'add', '--', m.SOURCE_PATHS[0]], check=True, capture_output=True)
        status = subprocess.check_output([
            'git', '-C', str(self.repository), '-c', 'core.autocrlf=true',
            'status', '--porcelain', '--untracked-files=no'])
        self.assertEqual(status.strip(), b'')
        with self.assertRaisesRegex(ValueError, 'Uncommitted runtime source'):
            m.source_identity(self.repository)

    def test_separate_expected_digest_is_mandatory_and_not_self_accepted(self):
        for digest in (None, '', '0' * 64):
            with self.assertRaises(ValueError):
                m.artifact_source(self.witness, digest)

    def test_file_mutation_is_rejected_even_with_original_manifest(self):
        (self.witness / 'src/main.rs').write_text('// changed\n', encoding='utf-8', newline='\n')
        with self.assertRaisesRegex(ValueError, 'source bytes'):
            m.artifact_source(self.witness, self.digest)

    def test_manifest_mutation_is_rejected_by_independent_digest(self):
        value = m.json_read(self.witness / 'SOURCE_WITNESS.json')
        value['source']['commit'] = '0' * 40
        dump(self.witness / 'SOURCE_WITNESS.json', value)
        with self.assertRaisesRegex(ValueError, 'digest differs'):
            m.artifact_source(self.witness, self.digest)

    def test_unreviewed_inventory_rejected_even_with_updated_expected_digest(self):
        value = m.json_read(self.witness / 'SOURCE_WITNESS.json')
        value['source']['runtime_files_sha256']['src/main.rs'] = '0' * 64
        dump(self.witness / 'SOURCE_WITNESS.json', value)
        with self.assertRaisesRegex(ValueError, 'audited runtime'):
            m.artifact_source(self.witness, m.sha256(self.witness / 'SOURCE_WITNESS.json'))

    def test_extra_files_and_source_mode_conflicts_rejected(self):
        (self.witness / 'extra.rs').write_text('// not inventoried', encoding='utf-8', newline='\n')
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            m.artifact_source(self.witness, self.digest)
        args = SimpleNamespace(source_witness=self.witness, witness_sha256=self.digest, repository=self.repository)
        with self.assertRaisesRegex(ValueError, 'not both'):
            m.resolve_source(args)

    def sidecar_fixture(self):
        # Change an inventoried runtime file, then commit exactly the expanded
        # synthetic inventory. This is not a production hash or performance run.
        (self.repository / m.SOURCE_PATHS[0]).write_text('// Synthetic sidecar-enabled source\n', encoding='utf-8', newline='\n')
        for name in m.SUBSTAGE_SOURCE_PATHS[len(m.SOURCE_PATHS):]:
            path = self.repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('// Synthetic additional sidecar source: ' + name + '\n', encoding='utf-8', newline='\n')
        subprocess.run(['git', '-C', str(self.repository), 'add', '--', *m.SUBSTAGE_SOURCE_PATHS],
                       check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.repository), '-c', 'user.name=Matrix Protocol Test',
                        '-c', 'user.email=matrix-protocol@example.invalid', '-c', 'commit.gpgsign=false',
                        '-c', 'core.hooksPath=' + str(self.root / 'empty-hooks'),
                        'commit', '--quiet', '-m', 'Synthetic reviewed sidecar inventory'],
                       check=True, capture_output=True)
        digest = m.canonical_hash({name: m.sha256(self.repository / name) for name in m.SUBSTAGE_SOURCE_PATHS})
        audit = mock.patch.object(m, 'AUDITED_SUBSTAGE_RUNTIME_MANIFEST', digest)
        audit.start()
        self.addCleanup(audit.stop)
        witness = self.root / 'sidecar-witness'
        expected = m.export_witness(self.repository, witness)
        return witness, expected

    def test_sidecar_exact_inventory_roundtrips_and_historical_witness_still_works(self):
        witness, expected = self.sidecar_fixture()
        source = m.artifact_source(witness, expected)
        self.assertEqual(set(source['runtime_files_sha256']), set(m.SUBSTAGE_SOURCE_PATHS))
        self.assertEqual(len(source['runtime_files_sha256']), 20)
        self.assertEqual(m.canonical_hash(source['runtime_files_sha256']), m.AUDITED_SUBSTAGE_RUNTIME_MANIFEST)
        self.assertEqual(len(m.artifact_source(self.witness, self.digest)['runtime_files_sha256']), 17)

    def test_inventory_label_cannot_substitute_for_exact_path_set_and_digest(self):
        witness, expected = self.sidecar_fixture()
        control = m.json_read(witness / 'SOURCE_WITNESS.json')
        for mutate in (
            lambda value: value.update(audited_runtime_manifest_sha256=m.AUDITED_RUNTIME_MANIFEST),
            lambda value: value['source']['runtime_files_sha256'].pop('src/frame_cpu_substages.rs'),
            lambda value: value['source']['runtime_files_sha256'].update({'src/lib.rs': '0' * 64}),
        ):
            value = copy.deepcopy(control)
            mutate(value)
            dump(witness / 'SOURCE_WITNESS.json', value)
            with self.assertRaisesRegex(ValueError, 'audited runtime'):
                m.artifact_source(witness, m.sha256(witness / 'SOURCE_WITNESS.json'))

    def test_dirty_additional_source_is_rejected_before_export(self):
        self.sidecar_fixture()
        (self.repository / 'src/frame_cpu_substages.rs').write_text('// Unreviewed dirty bytes\n', encoding='utf-8', newline='\n')
        with self.assertRaisesRegex(ValueError, 'Uncommitted runtime source'):
            m.source_identity(self.repository)

    def commit_cpu_fixture(self):
        subprocess.run(['git', '-C', str(self.repository), 'add', '--', *m.CPU_SOURCE_PATHS],
                       check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.repository), '-c', 'user.name=Matrix Protocol Test',
                        '-c', 'user.email=matrix-protocol@example.invalid', '-c', 'commit.gpgsign=false',
                        '-c', 'core.hooksPath=' + str(self.root / 'empty-hooks'),
                        'commit', '--quiet', '-m', 'Synthetic CPU inventory change'],
                       check=True, capture_output=True)

    def test_cpu_candidate_requires_exact_expanded_inventory_and_keeps_old_witnesses(self):
        old_sidecar, old_digest = self.sidecar_fixture()
        for name in m.CPU_SOURCE_PATHS:
            (self.repository / name).write_text('// Synthetic reviewed CPU candidate: ' + name + '\n', encoding='utf-8', newline='\n')
        self.commit_cpu_fixture()
        hashes = {name: m.sha256(self.repository / name) for name in m.CPU_CANDIDATE_SOURCE_PATHS}
        with mock.patch.object(m, 'AUDITED_CPU_CANDIDATE_MANIFEST', m.canonical_hash(hashes)):
            witness = self.root / 'cpu-witness'
            digest = m.export_witness(self.repository, witness)
            source = m.artifact_source(witness, digest)
            self.assertEqual(source['runtime_files_sha256'], hashes)
            self.assertEqual(len(source['runtime_files_sha256']), 24)
            self.assertEqual(len(m.artifact_source(self.witness, self.digest)['runtime_files_sha256']), 17)
            self.assertEqual(len(m.artifact_source(old_sidecar, old_digest)['runtime_files_sha256']), 20)
            control = m.json_read(witness / 'SOURCE_WITNESS.json')
            for name in m.CPU_SOURCE_PATHS:
                value = copy.deepcopy(control)
                value['source']['runtime_files_sha256'].pop(name)
                dump(witness / 'SOURCE_WITNESS.json', value)
                with self.assertRaisesRegex(ValueError, 'audited runtime'):
                    m.artifact_source(witness, m.sha256(witness / 'SOURCE_WITNESS.json'))

    def test_changed_cpu_source_cannot_fall_back_to_old_or_sidecar_inventory(self):
        for sidecar in (False, True):
            if sidecar:
                self.sidecar_fixture()
            for name in m.CPU_SOURCE_PATHS:
                with self.subTest(sidecar=sidecar, name=name):
                    path = self.repository / name
                    original = path.read_bytes()
                    path.write_bytes(original + b'// Unreviewed CPU change\n')
                    with self.assertRaisesRegex(ValueError, 'Uncommitted runtime source'):
                        m.source_identity(self.repository)
                    self.commit_cpu_fixture()
                    with self.assertRaisesRegex(ValueError, 'cannot fall back'):
                        m.source_identity(self.repository)
                    path.write_bytes(original)
                    self.commit_cpu_fixture()
                    self.assertEqual(len(m.source_identity(self.repository)['runtime_files_sha256']),
                                     20 if sidecar else 17)

    def present_fixture(self):
        self.sidecar_fixture()
        for name in m.CPU_SOURCE_PATHS:
            (self.repository / name).write_text('// Synthetic reviewed CPU candidate: ' + name + '\n', encoding='utf-8', newline='\n')
        self.commit_cpu_fixture()
        cpu_hashes = {name: m.sha256(self.repository / name) for name in m.CPU_CANDIDATE_SOURCE_PATHS}
        audit = mock.patch.object(m, 'AUDITED_CPU_CANDIDATE_MANIFEST', m.canonical_hash(cpu_hashes))
        audit.start()
        self.addCleanup(audit.stop)
        old_witness = self.root / 'cpu-witness'
        old_digest = m.export_witness(self.repository, old_witness)
        for name in m.PRESENT_SOURCE_PATHS:
            (self.repository / name).write_text('// Synthetic reviewed present integration: ' + name + '\n', encoding='utf-8', newline='\n')
        self.commit_present_fixture()
        hashes = {name: m.sha256(self.repository / name) for name in m.PRESENT_CANDIDATE_SOURCE_PATHS}
        audit = mock.patch.object(m, 'AUDITED_PRESENT_CANDIDATE_MANIFEST', m.canonical_hash(hashes))
        audit.start()
        self.addCleanup(audit.stop)
        witness = self.root / 'present-witness'
        digest = m.export_witness(self.repository, witness)
        return witness, digest, old_witness, old_digest

    def commit_present_fixture(self):
        subprocess.run(['git', '-C', str(self.repository), 'add', '-A', '--', *m.PRESENT_SOURCE_PATHS],
                       check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.repository), '-c', 'user.name=Matrix Protocol Test',
                        '-c', 'user.email=matrix-protocol@example.invalid', '-c', 'commit.gpgsign=false',
                        '-c', 'core.hooksPath=' + str(self.root / 'empty-hooks'),
                        'commit', '--quiet', '-m', 'Synthetic present inventory change'],
                       check=True, capture_output=True)

    def test_present_candidate_roundtrip_keeps_fifo_matrix_and_historical_evidence(self):
        witness, digest, old_witness, old_digest = self.present_fixture()
        source = m.artifact_source(witness, digest)
        self.assertEqual(set(source['runtime_files_sha256']), set(m.PRESENT_CANDIDATE_SOURCE_PATHS))
        self.assertEqual(len(source['runtime_files_sha256']), 27)
        self.assertEqual(len(m.artifact_source(old_witness, old_digest)['runtime_files_sha256']), 24)
        plan = m.make_plan(source, smoke=True)
        m.validate_plan(plan)
        self.assertEqual(plan['fixed_runtime']['present_mode'], 'Fifo')
        self.assertIn('matrix fixes Fifo', plan['unavailable_axes']['vsync_choices'])

    def test_present_sources_cannot_be_changed_or_removed_to_use_narrower_inventory(self):
        self.present_fixture()
        for name in m.PRESENT_SOURCE_PATHS:
            with self.subTest(name=name):
                path = self.repository / name
                original = path.read_bytes()
                path.write_bytes(original + b'// Unreviewed present change\n')
                with self.assertRaisesRegex(ValueError, 'Uncommitted runtime source'):
                    m.source_identity(self.repository)
                self.commit_present_fixture()
                with self.assertRaisesRegex(ValueError, 'cannot fall back'):
                    m.source_identity(self.repository)
                path.unlink()
                self.commit_present_fixture()
                with self.assertRaisesRegex(ValueError, 'missing present inventory|cannot fall back'):
                    m.source_identity(self.repository)
                path.write_bytes(original)
                self.commit_present_fixture()
                self.assertEqual(len(m.source_identity(self.repository)['runtime_files_sha256']), 27)


    def commit_gpu_fixture(self):
        subprocess.run(['git', '-C', str(self.repository), 'add', '-A', '--',
                        *m.GPU_CANDIDATE_SOURCE_PATHS], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.repository), '-c', 'user.name=Matrix Protocol Test',
                        '-c', 'user.email=matrix-protocol@example.invalid', '-c', 'commit.gpgsign=false',
                        '-c', 'core.hooksPath=' + str(self.root / 'empty-hooks'),
                        'commit', '--quiet', '-m', 'Synthetic GPU inventory change'],
                       check=True, capture_output=True)

    def gpu_fixture(self):
        old_witness, old_digest, _, _ = self.present_fixture()
        for name in (*m.GPU_SOURCE_PATHS, 'src/main.rs', 'src/render/mod.rs'):
            (self.repository / name).write_text('// Synthetic reviewed GPU session source: ' + name + '\n', encoding='utf-8', newline='\n')
        self.commit_gpu_fixture()
        hashes = {name: m.sha256(self.repository / name) for name in m.GPU_CANDIDATE_SOURCE_PATHS}
        audit = mock.patch.object(m, 'AUDITED_GPU_CANDIDATE_MANIFEST', m.canonical_hash(hashes))
        audit.start()
        self.addCleanup(audit.stop)
        return old_witness, old_digest

    def test_gpu_inventory_roundtrip_preserves_old_present_witness_and_default_off_matrix(self):
        old_witness, old_digest = self.gpu_fixture()
        witness = self.root / 'gpu-witness'
        digest = m.export_witness(self.repository, witness)
        source = m.artifact_source(witness, digest)
        self.assertEqual(set(source['runtime_files_sha256']), set(m.GPU_CANDIDATE_SOURCE_PATHS))
        self.assertEqual(len(source['runtime_files_sha256']), 29)
        self.assertEqual(len(m.artifact_source(old_witness, old_digest)['runtime_files_sha256']), 27)
        plan = m.make_plan(source, smoke=True)
        m.validate_plan(plan)
        self.assertEqual(plan['fixed_runtime']['present_mode'], 'Fifo')
        self.assertIn('leaves them disabled', plan['unavailable_axes']['gpu_frame_duration'])

    def gpu_cpu_baseline_fixture(self):
        self.gpu_fixture()
        for name in m.CPU_SOURCE_PATHS:
            (self.repository / name).write_text('// Synthetic reviewed CPU baseline: ' + name + '\n',
                                                encoding='utf-8', newline='\n')
        self.commit_gpu_fixture()
        hashes = {name: m.sha256(self.repository / name) for name in m.GPU_CANDIDATE_SOURCE_PATHS}
        audit = mock.patch.object(m, 'AUDITED_GPU_CPU_BASELINE_MANIFEST', m.canonical_hash(hashes))
        audit.start()
        self.addCleanup(audit.stop)

    def test_exact_gpu_cpu_baseline_roundtrip_and_timestamp_plan(self):
        self.gpu_cpu_baseline_fixture()
        witness = self.root / 'gpu-cpu-baseline-witness'
        digest = m.export_witness(self.repository, witness)
        source = m.artifact_source(witness, digest)
        self.assertEqual(source, m.source_identity(self.repository))
        self.assertEqual(len(source['runtime_files_sha256']), 29)
        self.assertEqual(m.canonical_hash(source['runtime_files_sha256']), m.AUDITED_GPU_CPU_BASELINE_MANIFEST)
        plan = m.make_plan(source, repeats=1, baseline_only=True, gpu_timestamps=True)
        m.validate_plan(plan)
        self.assertEqual([row['case_id'] for row in plan['order']], ['baseline'])
        self.assertEqual(plan['cases'][0]['settings']['surface_extent'], [1920, 1080])
        self.assertTrue(plan['gpu_timestamps'])
        self.assertEqual(plan['fixed_runtime']['present_mode'], 'Fifo')

    def test_each_gpu_cpu_baseline_file_rejects_dirty_and_committed_mutations(self):
        self.gpu_cpu_baseline_fixture()
        for name in m.CPU_SOURCE_PATHS:
            path = self.repository / name
            original = path.read_bytes()
            with self.subTest(name=name):
                path.write_bytes(original + b'// Unreviewed mixed baseline\n')
                with self.assertRaisesRegex(ValueError, 'Uncommitted runtime source'):
                    m.source_identity(self.repository)
                self.commit_gpu_fixture()
                with self.assertRaisesRegex(ValueError, 'cannot fall back'):
                    m.source_identity(self.repository)
                path.write_bytes(original)
                self.commit_gpu_fixture()
                self.assertEqual(m.canonical_hash(m.source_identity(self.repository)['runtime_files_sha256']),
                                 m.AUDITED_GPU_CPU_BASELINE_MANIFEST)

    def test_first_gpu_witness_remains_exact_after_reviewed_same_scope_revision(self):
        self.gpu_fixture()
        witness = self.root / 'first-gpu-witness'
        digest = m.export_witness(self.repository, witness)
        initial = m.AUDITED_GPU_CANDIDATE_MANIFEST
        with mock.patch.object(m, 'AUDITED_GPU_INITIAL_MANIFEST', initial), \
                mock.patch.object(m, 'AUDITED_GPU_CANDIDATE_MANIFEST', '0' * 64):
            source = m.artifact_source(witness, digest)
            self.assertEqual(m.canonical_hash(source['runtime_files_sha256']), initial)
            self.assertEqual(m.source_identity(self.repository), source)
            plan = m.make_plan(source, smoke=True)
            m.validate_plan(plan)
            self.assertIn('leaves them disabled', plan['unavailable_axes']['gpu_frame_duration'])
            changed = self.repository / m.GPU_SOURCE_PATHS[0]
            changed.write_bytes(changed.read_bytes() + b'// Unreviewed same-scope change\n')
            self.commit_gpu_fixture()
            with self.assertRaisesRegex(ValueError, 'cannot fall back'):
                m.source_identity(self.repository)

    def test_gpu_sources_cannot_change_or_disappear_into_narrower_inventory(self):
        self.gpu_fixture()
        for name in m.GPU_SOURCE_PATHS:
            path = self.repository / name
            original = path.read_bytes()
            with self.subTest(name=name):
                path.write_bytes(original + b'// Unreviewed GPU change\n')
                with self.assertRaisesRegex(ValueError, 'Uncommitted runtime source'):
                    m.source_identity(self.repository)
                self.commit_gpu_fixture()
                with self.assertRaisesRegex(ValueError, 'cannot fall back'):
                    m.source_identity(self.repository)
                path.unlink()
                self.commit_gpu_fixture()
                with self.assertRaisesRegex(ValueError, 'missing GPU inventory'):
                    m.source_identity(self.repository)
                path.write_bytes(original)
                self.commit_gpu_fixture()
                self.assertEqual(len(m.source_identity(self.repository)['runtime_files_sha256']), 29)
        for name in m.GPU_SOURCE_PATHS:
            (self.repository / name).unlink()
        self.commit_gpu_fixture()
        with self.assertRaisesRegex(ValueError, 'cannot fall back'):
            m.source_identity(self.repository)

    def test_gpu_file_added_to_old_inventory_cannot_be_silently_ignored(self):
        for name in m.GPU_SOURCE_PATHS:
            path = self.repository / name
            path.write_text('// New unreviewed GPU source\n', encoding='utf-8', newline='\n')
            with self.assertRaisesRegex(ValueError, 'cannot fall back'):
                m.source_identity(self.repository)
            path.unlink()


if __name__ == '__main__':
    unittest.main()

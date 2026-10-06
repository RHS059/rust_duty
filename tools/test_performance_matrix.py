"""CPU-only matrix protocol tests. All timing/game reports here are synthetic."""
import copy
import json
from pathlib import Path
import subprocess
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


def trace(case, adapter, build):
    report = control()
    report['start_ns'] = 0
    report['records'] = [present(10)] + [present(10 + index * 50_000_000, 50_000_000)
                                        for index in range(1, 201)]
    report['successful_present_count'] = 201
    report['last_observed_ns'] = report['records'][-1]['at_ns']
    report['stop_requested_ns'] = report['stopped_at_ns'] = report['last_observed_ns']
    report['summary'] = {'interval_count': 200, 'total_interval_ns': 10_000_000_000,
                         'min_ns': 50_000_000, 'max_ns': 50_000_000,
                         'p50_ns': 50_000_000, 'p95_ns': 50_000_000, 'p99_ns': 50_000_000,
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
    for index in range(1, 201):
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

    def csv(self, speed, ads):
        header = 'time,x,y,z,speed,grounded,crouched,sprinting,ads,recoil_pitch_deg,ammo,shots,hits,kills,render_fps\n'
        (self.session / 'gameplay.csv').write_text(header + ''.join(
            f'{i / 10},0,0,0,{speed},1,0,0,{ads},0,30,0,0,0,999999\n' for i in range(100)))

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

    def test_full_analysis_stays_scoped_even_when_complete(self):
        result = m.analyze_matrix(self.root)
        self.assertEqual(result['state'], 'complete')
        self.assertFalse(result['acceptance_proven'])
        self.assertEqual(result['case_comparisons'][0]['p99_ms_by_run'], [50])
        self.assertEqual(result['paired_baseline_comparisons'], [])

    def test_missing_run_is_incomplete_and_never_zero_filled(self):
        (self.folder / 'RESULT.json').unlink()
        result = m.analyze_matrix(self.root)
        self.assertEqual(result['state'], 'incomplete')
        self.assertEqual(len(result['failures']), 1)
        self.assertIsNone(result['case_comparisons'][0]['median_run_p99_ms'])

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
        for name in m.SOURCE_PATHS:
            path = self.repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('// Synthetic witness protocol fixture: ' + name + '\n').encode())
            hashes[name] = m.sha256(path)
        subprocess.run(['git', 'init', '--quiet', str(self.repository)], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(['git', '-C', str(self.repository), 'add', '--', *m.SOURCE_PATHS],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        hooks = self.root / 'empty-hooks'
        hooks.mkdir()
        subprocess.run(['git', '-C', str(self.repository), '-c', 'user.name=Matrix Protocol Test',
                        '-c', 'user.email=matrix-protocol@example.invalid',
                        '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=' + str(hooks),
                        'commit', '--quiet', '-m', 'Synthetic source-witness test fixture'],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        audit = mock.patch.object(m, 'AUDITED_RUNTIME_MANIFEST', m.canonical_hash(hashes))
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

    def test_separate_expected_digest_is_mandatory_and_not_self_accepted(self):
        for digest in (None, '', '0' * 64):
            with self.assertRaises(ValueError):
                m.artifact_source(self.witness, digest)

    def test_file_mutation_is_rejected_even_with_original_manifest(self):
        (self.witness / 'src/main.rs').write_text('// changed\n')
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
        (self.witness / 'extra.rs').write_text('// not inventoried')
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            m.artifact_source(self.witness, self.digest)
        args = SimpleNamespace(source_witness=self.witness, witness_sha256=self.digest, repository=self.repository)
        with self.assertRaisesRegex(ValueError, 'not both'):
            m.resolve_source(args)


if __name__ == '__main__':
    unittest.main()

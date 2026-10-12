"""Synthetic boundary tests; never build or launch a real game/profiler."""
import contextlib
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import performance_matrix as matrix
import run_cpu_image_preservation as pair
import run_windows_cpu_profile as profile


class GeometryProfilePairTests(unittest.TestCase):
    def flow(self, mutation=None, failed_shutdown=False, experiment='geometry-reuse'):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        root, output = base / 'checkout', base / 'evidence'
        root.mkdir()
        output.mkdir()
        production = {'Cargo.toml': b'[package]\nname="synthetic"\n',
                      'src/lib.rs': b'// Synthetic noncompilable source receipt.\n',
                      pair.UPLOAD_POLICY_PATH: b'pub const REUSE_ENABLED: bool = true;\n'}
        old_arena = {pair.ARENA_PATH: b'// Historical scalar arena fixture.\n'}
        old_loader = {name: ('old synthetic loader '+name).encode() for name in pair.LOADER_BASELINE}
        if experiment == 'authored-dedup':
            production.update({name: ('new synthetic loader '+name).encode() for name in pair.LOADER_BASELINE})
            production[pair.ARENA_PATH] = b'// Same current arena serializer in both variants.\n'
        if experiment == 'arena-serialization':
            production[pair.ARENA_PATH] = b'// New serialization arena fixture.\n'
        for name, raw in {**production, 'settings.cfg': b'settings fixture\n',
                          'ui/theme.css': b'fixture\n', 'assets/animations.cfg': b'fixture\n',
                          'assets/locomotion/asset.vrs': b'synthetic asset\n'}.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        tools = {}
        for name in ('wpr', 'xperf'):
            path = base / (name + '.exe')
            path.write_bytes(b'nonexecutable installed-tool fixture')
            tools[name] = {'path': str(path), 'sha256': profile.digest(path)}
        profile.write(output / 'tools.json', tools)
        profile.write(output / 'materialize.json', {'synthetic': True})
        compiler = {'rustc': 'release: 1.99.0\nhost: x86_64-pc-windows-msvc\n',
                    'cargo': 'cargo 1.99.0 synthetic'}
        events, locked, changed_toolchain = [], [], []
        self.last = {'root': root, 'output': output, 'events': events,
                     'production': production, 'compiler': compiler}

        def source(_root):
            self.assertEqual(_root, root)
            return {'commit': 'a' * 40, 'tree': 'b' * 40,
                    'files_sha256': profile.inventory(root), 'generated_asset_transports': {}}

        def toolchain(cwd):
            if changed_toolchain:
                return {**compiler, 'rustc': compiler['rustc'] + 'changed\n'}
            return compiler.copy()

        def config(cwd, env):
            if (Path(cwd) / '.cargo/config.toml').exists():
                raise ValueError('external Cargo configuration changed')

        @contextlib.contextmanager
        def lock(path):
            self.assertFalse(locked)
            locked.append(path)
            try:
                yield
            finally:
                locked.pop()

        def build(command, cwd, log, *, env, timeout, owned_tree=False):
            self.assertFalse(locked)
            self.assertTrue(owned_tree)
            self.assertEqual(command, profile.BUILD)
            self.assertEqual(timeout, 1800)
            label = Path(cwd).name.removesuffix('-source')
            events.append(('build', label))
            self.assertEqual({k: env[k] for k in profile.SETTINGS}, profile.SETTINGS)
            target = Path(env['CARGO_TARGET_DIR'])
            self.assertFalse(target.exists())
            (target / 'release').mkdir(parents=True)
            (target / 'release/vector-range.exe').write_bytes(b'synthetic exe ' + label.encode())
            (target / 'release/vector_range.pdb').write_bytes(b'synthetic pdb ' + label.encode())
            Path(log).write_bytes(b'synthetic successful compiler log\n')
            if mutation == 'build_timeout':
                raise subprocess.TimeoutExpired(command, timeout)
            if mutation == 'compiled_source':
                (Path(cwd) / 'src/lib.rs').write_bytes(b'changed by synthetic compiler')
            if mutation == 'compiler':
                changed_toolchain.append(True)
            if mutation == 'cargo_config':
                (Path(cwd) / '.cargo').mkdir()
                (Path(cwd) / '.cargo/config.toml').write_bytes(b'not executed')
            if label == 'candidate':
                paths = {
                    'prior_build_log': output / 'baseline-build/build.log',
                    'prior_pdb': output / 'baseline-build/vector_range.pdb',
                    'compiled_exe': output / 'baseline-build/target/release/vector-range.exe',
                    'source_receipt': output / 'sources/baseline-source.json',
                    'verifier_receipt': output / 'sources/verifier-source.json',
                    'pair_inputs': output / 'pair-inputs.json',
                    'assets': root / 'assets/animations.cfg',
                    'profiler': Path(tools['xperf']['path']),
                }
                if mutation in paths:
                    p = paths[mutation]
                    p.write_bytes(p.read_bytes() + b' changed')

        def measurements(runtime, exe_hash):
            data = matrix.json_read(runtime / 'telemetry-sessions/s1/measurement.json')
            self.assertEqual(exe_hash, profile.digest(runtime.parent / 'vector-range.exe'))
            return data

        def sample(sample_root, folder, actual_tools, target, actual_source, bound, env,
                   verify_inputs, *, record=False, source_variant=None, source_receipt_sha256=None):
            self.assertEqual(sample_root, root)
            self.assertEqual(actual_tools, tools)
            self.assertTrue(record)
            self.assertEqual(len(locked), 1)
            verify_inputs()
            label = target.parent.name.removesuffix('-build')
            events.append(('sample', label))
            for name in ('vector-range.exe', 'vector_range.pdb'):
                shutil.copyfile(target / 'release' / name, folder / name)
            runtime = folder / 'runtime'
            (runtime / 'telemetry-sessions/s1').mkdir(parents=True)
            shutil.copyfile(root / 'settings.cfg', runtime / 'settings.cfg')
            measured = {'session': 's1', 'adapter': {'backend': 'Dx12', 'name': 'synthetic WARP'},
                        'build': {'version': 'synthetic'}, 'scene': {'name': 'synthetic range'},
                        'initial_window': {'physical_width': 1920, 'physical_height': 1080},
                        'upload_policy': pair.experiment_metadata(experiment)['upload_policies'][label],
                        'tail_comparison_ready': True, 'present_intervals': 101}
            if mutation == 'policy' and label == 'candidate':
                measured['upload_policy'] = 'immutable_per_frame_v1'
            if mutation == 'device' and label == 'candidate':
                measured['adapter']['name'] = 'different adapter'
            profile.write(runtime / 'telemetry-sessions/s1/measurement.json', measured)
            (folder / 'game.log').write_bytes(
                b'renderer requested=dx12 backend=Dx12 adapter=Microsoft Basic Render Driver\n'
                b'window physical_extent_verified=1920x1080\n'
                b'Loaded Blender-authored viewmodel: synthetic fixture\n')
            (folder / 'cpu.etl').write_bytes(b'synthetic trace')
            (folder / 'profile.txt').write_bytes(b'synthetic report')
            failure = 'Game did not exit normally; inspect shutdown attempts' if failed_shutdown else None
            if mutation == 'runtime_settings':
                (runtime / 'settings.cfg').write_bytes(b'changed at shutdown')
                failure = 'Runtime settings changed during capture'
            if mutation == 'other_capture_failure':
                failure = 'Unrelated validation failed'
            capture = {'passed': failure is None, 'trace_saved': True,
                       'trace_export': {'passed': True, 'trace_sha256': profile.digest(folder / 'cpu.etl'),
                                        'reports_sha256': {'profile': profile.digest(folder / 'profile.txt')}},
                       'exit_code': 1 if failed_shutdown else 0, 'cleanup_errors': [],
                       'cleanup': {'forced': failed_shutdown, 'process_action': 'terminate' if failed_shutdown else 'already_exited'},
                       'shutdown': {'normal_exit': not failed_shutdown},
                       'post_capture_inputs_verified': mutation not in ('runtime_settings', 'other_capture_failure', 'final_checks'),
                       'post_capture_checks': {'attempted': True, 'passed': mutation != 'final_checks'},
                       'source_variant': source_variant, 'source_receipt_sha256': source_receipt_sha256,
                       'counterfactual_source': label == 'baseline', 'source_commit': actual_source['commit'],
                       'runtime_before_sampling': {'settings.cfg': profile.digest(root / 'settings.cfg')},
                       'initial_settings_sha256': profile.digest(root / 'settings.cfg'),
                       'measurements': measured,
                       'measurement_files': profile.inventory(runtime / 'telemetry-sessions'),
                       'record_start': {'session': 's1', 'requested_unix_ns': 1, 'observed_unix_ns': 2},
                       'record_stop': {'session': 's1', 'requested_unix_ns': 5, 'observed_unix_ns': 6},
                       'sample_started_unix_ns': 3, 'sample_finished_unix_ns': 4,
                       **bound}
            if failure:
                capture.update(error=failure, error_type='NormalShutdownFailure' if failed_shutdown else 'ValueError')
            if mutation == 'source_variant':
                capture['source_variant'] = 'wrong'
            if mutation == 'record_window':
                capture['record_start']['observed_unix_ns'] = 7
            if mutation == 'record_session':
                capture['record_stop']['session'] = 'different'
            profile.write(folder / 'capture.json', capture)
            if mutation == 'trace':
                (folder / 'cpu.etl').write_bytes(b'changed trace after export')
            if mutation == 'report':
                (folder / 'profile.txt').write_bytes(b'changed report after export')
            if mutation == 'extra_runtime':
                (runtime / 'unexpected.cfg').write_bytes(b'extra runtime input')
            if label == 'candidate':
                paths = {'prior_capture': output / 'r01-baseline/capture.json',
                         'prior_record': output / 'r01-baseline/runtime/telemetry-sessions/s1/measurement.json',
                         'prior_report': output / 'r01-baseline/profile.txt'}
                if mutation in paths:
                    p = paths[mutation]
                    p.write_bytes(p.read_bytes() + b' changed')
            if failure:
                raise (profile.NormalShutdownFailure if failed_shutdown else ValueError)(failure)

        with contextlib.ExitStack() as stack:
            patches = [patch.object(profile, '__file__', str(root / 'tools/run_windows_cpu_profile.py')),
                       patch.object(profile, 'require_host'), patch.object(profile, 'checked_source', side_effect=source),
                       patch.object(pair, 'check_environment'), patch.object(pair, 'check_cargo_configuration', side_effect=config),
                       patch.object(pair, 'toolchain_at', side_effect=toolchain),
                       patch.object(pair, 'read_sources', side_effect=lambda _root, commit, paths:
                                    copy.deepcopy(old_arena if paths == [pair.ARENA_PATH] else
                                                  old_loader if paths == sorted(pair.LOADER_BASELINE) else production)),
                       patch.object(pair, 'LOADER_BASELINE', pair.hashes(old_loader)),
                       patch.object(pair, 'ARENA_BASELINE_SHA256', pair.controls.digest(old_arena[pair.ARENA_PATH])),
                       patch.object(pair, 'PRODUCTION_MANIFEST', matrix.canonical_hash(pair.hashes(production))),
                       patch.object(profile, 'command_log', side_effect=build),
                       patch.object(profile, 'sample_build', side_effect=sample),
                       patch.object(profile, 'recorded_measurements', side_effect=measurements),
                       patch.object(matrix, 'desktop_lock', side_effect=lock),
                       patch.object(profile.subprocess, 'Popen', side_effect=AssertionError('Real process forbidden'))]
            for p in patches:
                stack.enter_context(p)
            return profile.compare_uploads(root, output, experiment)

    def test_two_fresh_symbolized_builds_and_four_locked_abba_captures(self):
        self.flow()
        self.assertEqual(self.last['events'], [('build', 'baseline'), ('build', 'candidate'),
                                             ('sample', 'baseline'), ('sample', 'candidate'),
                                             ('sample', 'candidate'), ('sample', 'baseline')])
        output = self.last['output']
        summary = matrix.json_read(output / 'pair-summary.json')
        self.assertTrue(summary['passed'])
        self.assertEqual(summary['diagnostic_runs_complete'], 4)
        self.assertFalse(summary['target_1080p60_proven'])
        self.assertIsNone(summary['performance_improvement'])
        baseline = (output / 'sources/baseline-source' / pair.UPLOAD_POLICY_PATH).read_bytes()
        candidate = (output / 'sources/candidate-source' / pair.UPLOAD_POLICY_PATH).read_bytes()
        self.assertEqual(baseline, candidate.replace(pair.UPLOAD_POLICY_ENABLED, pair.UPLOAD_POLICY_DISABLED))
        for label in ('baseline', 'candidate'):
            receipt = matrix.json_read(output / (label + '-build/build.json'))
            self.assertEqual(receipt['source_variant'], label)
            self.assertEqual(receipt['counterfactual'], label == 'baseline')
            self.assertEqual(receipt['source_commit'], 'a' * 40)
            self.assertEqual(receipt['source_receipt_sha256'], profile.digest(output / ('sources/' + label + '-source.json')))

    def test_failed_normal_shutdown_keeps_all_diagnostics_but_never_passes(self):
        with self.assertRaisesRegex(ValueError, 'normal capture exits failed'):
            self.flow(failed_shutdown=True)
        output = self.last['output']
        summary = matrix.json_read(output / 'pair-summary.json')
        self.assertFalse(summary['passed'])
        self.assertEqual(summary['diagnostic_runs_complete'], 4)
        self.assertTrue(all(not row['capture_passed'] for row in summary['runs']))
        self.assertEqual(matrix.json_read(output / 'pair-failure.json')['completed_runs'], 4)

    def test_compile_source_toolchain_configuration_and_retained_build_mutations_fail(self):
        for mutation in ('compiled_source', 'compiler', 'cargo_config', 'prior_build_log', 'prior_pdb',
                         'compiled_exe', 'source_receipt', 'verifier_receipt', 'pair_inputs', 'assets', 'profiler'):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.flow(mutation)
            self.assertFalse((self.last['output'] / 'pair-summary.json').exists())
            self.assertTrue((self.last['output'] / 'pair-failure.json').is_file())

    def test_build_timeout_retains_failed_pair_without_launch(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.flow('build_timeout')
        self.assertEqual(self.last['events'], [('build', 'baseline')])
        self.assertEqual(matrix.json_read(self.last['output'] / 'pair-failure.json')['error_type'], 'TimeoutExpired')

    def test_later_capture_cannot_change_prior_receipts_measurements_or_reports(self):
        for mutation in ('prior_capture', 'prior_record', 'prior_report'):
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'Earlier retained'):
                self.flow(mutation)
            self.assertFalse((self.last['output'] / 'pair-summary.json').exists())

    def test_actual_policy_and_device_must_match_the_paired_sources(self):
        for mutation in ('policy', 'device'):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.flow(mutation)
            self.assertFalse((self.last['output'] / 'pair-summary.json').exists())


    def test_trace_report_record_window_and_runtime_inventory_are_bound(self):
        for mutation in ('trace', 'report', 'record_window', 'record_session', 'extra_runtime', 'source_variant', 'final_checks'):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.flow(mutation)
            self.assertFalse((self.last['output'] / 'pair-summary.json').exists())
            self.assertEqual(matrix.json_read(self.last['output'] / 'pair-failure.json')['completed_runs'], 0)

    def test_unrelated_capture_errors_and_changed_settings_are_not_normal_exit_continuations(self):
        for mutation in ('other_capture_failure', 'runtime_settings'):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.flow(mutation)
            self.assertFalse((self.last['output'] / 'pair-summary.json').exists())
            self.assertEqual(matrix.json_read(self.last['output'] / 'pair-failure.json')['completed_runs'], 0)


class RecordControlTests(unittest.TestCase):
    def test_start_waits_for_one_session_without_requiring_final_exports(self):
        driver = MagicMock()
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            folder = runtime / 'telemetry-sessions/s1'
            def wait(probe, *, timeout, label):
                self.assertEqual(timeout, 10)
                self.assertEqual(label, 'Record start')
                return probe()
            with patch.object(profile, 'tap') as tap, patch.object(matrix, 'wait_until', side_effect=wait), \
                    patch.object(matrix, 'sole_session', return_value=folder) as sole, \
                    patch.object(profile.time, 'time_ns', side_effect=[10, 20, 30]):
                result = profile.record_request(driver, runtime, start=True)
            tap.assert_called_once_with(driver, 'F8')
            sole.assert_called_once_with(runtime, complete=False)
            self.assertEqual(result, {'key': 'F8', 'requested_unix_ns': 10,
                                     'key_released_unix_ns': 20, 'observed_unix_ns': 30, 'session': 's1'})

    def test_stop_waits_for_both_json_sidecars_with_bounded_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            folder = runtime / 'telemetry-sessions/s1'
            folder.mkdir(parents=True)
            (folder / 'frames.cpu-substages.json').write_bytes(b'{}')
            def wait(probe, *, timeout, label):
                self.assertEqual(timeout, 30)
                self.assertEqual(label, 'complete CPU-detail export')
                self.assertIsNone(probe())
                (folder / 'frames.cpu-encode-detail.json').write_bytes(b'{invalid')
                self.assertIsNone(probe())
                (folder / 'frames.cpu-encode-detail.json').write_bytes(b'{}')
                return probe()
            with patch.object(profile, 'tap'), patch.object(matrix, 'wait_until', side_effect=wait), \
                    patch.object(matrix, 'sole_session', return_value=folder) as sole:
                result = profile.record_request(MagicMock(), runtime, start=False)
            self.assertEqual(result['session'], 's1')
            self.assertTrue(all(call.kwargs == {'complete': True} for call in sole.call_args_list))

    def test_failed_final_inputs_preserve_original_shutdown_and_separate_export_result(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            original = profile.NormalShutdownFailure('normal close failed')
            failure = ValueError('source or runtime input changed')
            receipt = {'error': str(original), 'shutdown': {'normal_exit': False}}
            order = []
            def cleanup(*args):
                order.append('cleanup')
                args[-1].update(forced=True, process_action='terminate')
                return [], 1
            def verify():
                order.append('verify')
                raise failure
            def export(*args):
                order.append('export')
                return {'passed': True}
            with patch.object(profile, 'cleanup_owned', side_effect=cleanup), \
                    patch.object(profile, 'export_trace', side_effect=export):
                result = profile.finalize_capture(output, output, MagicMock(), MagicMock(),
                    'wpr.exe', 'owned-instance', False, True, {}, output, receipt, original,
                    verify_final=verify)
            self.assertIs(result, original)
            self.assertEqual(order, ['cleanup', 'verify', 'export'])
            saved = matrix.json_read(output / 'capture.json')
            self.assertFalse(saved['passed'])
            self.assertFalse(saved['post_capture_inputs_verified'])
            self.assertEqual(saved['post_capture_checks'], {'attempted': True, 'passed': False,
                'error': str(failure), 'error_type': 'ValueError'})
            self.assertTrue(saved['trace_export']['passed'])
            self.assertEqual(saved['error'], str(original))
            self.assertEqual(saved['error_type'], 'NormalShutdownFailure')

    def measurements(self, mutate=None):
        from test_summarize_cpu_encode_detail import fixture, rebind
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        runtime = Path(temporary.name).resolve()
        folder = runtime / 'telemetry-sessions/s1'
        folder.mkdir(parents=True)
        primary, child, detail, _, _ = fixture()
        def scale(value):
            if isinstance(value, dict):
                return {key: item * 300_000_000 if key.endswith('_ns') and type(item) is int
                        else scale(item) for key, item in value.items()}
            if isinstance(value, list):
                return [scale(item) for item in value]
            return value
        primary, child, detail = map(scale, (primary, child, detail))
        observed = primary['identity']['runtime_observed']
        observed['actual_adapter'].update(backend='Dx12', name='Microsoft Basic Render Driver',
            device_type='Cpu', force_fallback_requested=True, present_mode='Immediate',
            gpu_timestamps_requested=False, gpu_timestamp_features_enabled=False)
        observed['actual_adapter']['instance_descriptor'].update(flags_bits=32, debug=False, validation=False,
                                                               application_debug_assertions=False)
        if mutate == 'debug_profile':
            observed['actual_adapter']['instance_descriptor']['application_debug_assertions'] = True
        observed['initial_window'].update(physical_width=1920, physical_height=1080)
        observed['scene'] = {'name': 'vector_range_default_range', 'presentation': 'authored_viewmodel',
            'profile_base': 'm4a1', 'weapon_id': 'hk416a5', 'reference_viewport': False,
            'diagnostic_capture': False, 'demo': False, 'capture_sequence': None}
        for sample in primary['cpu_frame_stages']['samples']:
            sample.update(physical_width=1920, physical_height=1080)
        if mutate == 'incomplete':
            detail['samples'][0]['details'].update(state='incomplete', error='encode_incomplete')
        if mutate == 'backend':
            observed['actual_adapter']['name'] = 'different adapter'
        if mutate == 'scene':
            observed['scene']['presentation'] = 'procedural'
        if mutate == 'extent':
            primary['cpu_frame_stages']['samples'][0]['physical_width'] = 1280
        raw, _ = rebind(primary, child, detail)
        if mutate == 'hash':
            detail['frame_report_sha256'] = '0' * 64
        (folder / 'frames.json').write_bytes(raw)
        profile.write(folder / 'frames.cpu-substages.json', child)
        if mutate != 'missing_detail':
            profile.write(folder / 'frames.cpu-encode-detail.json', detail)
        profile.write(folder / 'IDENTITY.json', {'schema': 'rust-duty-local-playtest-session/v1',
            'executable_sha256': 'b' * 64 if mutate == 'executable' else 'a' * 64,
            'build': observed['build'], 'graphics_device': observed['actual_adapter'],
            'source': {'state': 'unavailable'}})
        profile.write(folder / 'CSV_STATUS.json', {'state': 'stopped', 'error': None})
        if mutate == 'gpu_sidecar':
            (folder / 'frames.gpu-timing.json').write_bytes(b'{}')
        gameplay = {'speed_max': 1 if mutate == 'movement' else 0, 'ads_max': 0}
        with patch.object(matrix, 'sole_session', return_value=folder), \
                patch.object(matrix, 'gameplay_summary', return_value=gameplay), \
                patch.object(matrix, 'gpu_export_summary', return_value={'synthetic': True}):
            return profile.recorded_measurements(runtime, 'a' * 64)

    def test_recorded_measurements_use_real_readers_and_preserve_small_sample_warning(self):
        result = self.measurements()
        self.assertEqual(result['present_intervals'], 1)
        self.assertEqual(result['present_interval_total_ns'], 30_000_000_000)
        self.assertFalse(result['tail_comparison_ready'])
        self.assertEqual(result['cpu_encode_detail']['summarized_attempts'], 1)
        self.assertIsNone(result['upload_policy'])  # Legacy v1 does not invent the new policy.

    def test_recorded_measurements_reject_incomplete_tampered_or_wrong_runtime_evidence(self):
        for mutation in ('incomplete', 'hash', 'backend', 'scene', 'extent', 'executable',
                         'gpu_sidecar', 'movement', 'missing_detail', 'debug_profile'):
            with self.subTest(mutation=mutation), self.assertRaises((ValueError, OSError)):
                self.measurements(mutation)


if __name__ == '__main__':
    unittest.main()

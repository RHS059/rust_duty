import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml
import windows_acquire_diagnostic as d

ROOT = Path(__file__).resolve().parents[1]


class ObserverTests(unittest.TestCase):
    def test_candidate_changes_only_false_wait_before_backbuffer(self):
        original = b'''    unsafe fn acquire_texture() {
        match wait_mode {
            Wait => {
                unsafe { sc.wait(timeout) }?;
            }
        }
        let base_index = unsafe { sc.raw.GetCurrentBackBufferIndex() } as usize;
        sc.acquired_count += 1;
    }
'''
        with patch.object(d, 'HAL_FILE_SHA256', d.digest(original)):
            baseline = d.instrument('hal/src/dx12/mod.rs', original).decode()
            candidate = d.instrument('hal/src/dx12/mod.rs', original, d.MODES[1]).decode()
        self.assertIn('diagnostic_wait_result?;', baseline)
        self.assertNotIn('SurfaceError::Timeout', baseline)
        self.assertIn('if !diagnostic_wait_result? {', candidate)
        # ? preserves Lost/Outdated/Device/Other errors; false alone returns Timeout.
        self.assertLess(candidate.index('if !diagnostic_wait_result?'), candidate.index('return Err(crate::SurfaceError::Timeout)'))
        self.assertLess(candidate.index('return Err(crate::SurfaceError::Timeout)'), candidate.index('GetCurrentBackBufferIndex'))
        self.assertLess(candidate.index('GetCurrentBackBufferIndex'), candidate.index('sc.acquired_count += 1'))
        self.assertNotIn('DontWait', candidate)
        self.assertEqual(candidate.count('sc.acquired_count += 1'), 1)

    def test_wait_false_is_retained_with_duration(self):
        result = d.parse_log('unrelated game output\n' +
            d.PREFIX + 'event=hal_wait_result sequence=0 elapsed_ns=1000123000 wait_ok=false timeout_ns=1000000000 waitable=true\n' +
            d.PREFIX + 'event=hal_wait_result sequence=1 elapsed_ns=39000 wait_ok=true timeout_ns=1000000000 waitable=true\n')
        self.assertEqual(result['wait_false_count'], 1)
        self.assertEqual(result['wait_true_count'], 1)
        self.assertEqual(result['waits'][0]['elapsed_ns'], 1000123000)

    def test_wait_error_is_not_misreported_as_timeout(self):
        result = d.parse_log(d.PREFIX + 'event=hal_wait_result sequence=0 elapsed_ns=4 wait_ok=error waitable=true')
        self.assertEqual(result['wait_false_count'], 0)
        self.assertEqual(result['waits'][0]['wait_ok'], 'error')

    def test_missing_wait_record_and_invalid_result_fail(self):
        for row in ('sequence=1 elapsed_ns=4 wait_ok=false waitable=true',
                    'sequence=0 elapsed_ns=-1 wait_ok=false waitable=true',
                    'sequence=0 elapsed_ns=4 wait_ok=0 waitable=true'):
            with self.subTest(row=row), self.assertRaises(ValueError):
                d.parse_log(d.PREFIX + 'event=hal_wait_result ' + row)

    def test_missing_lifecycle_end_stays_missing(self):
        result = d.parse_log(d.PREFIX + 'event=hooks_drop_enter unix_ns=123 elapsed_ns=0')
        self.assertTrue(result['lifecycle']['hooks_drop']['entered'])
        self.assertFalse(result['lifecycle']['hooks_drop']['returned'])
        self.assertFalse(result['lifecycle']['run_app']['entered'])

    def test_source_drift_fails_before_patching(self):
        with self.assertRaisesRegex(ValueError, 'hash differs'):
            d.instrument('src/app.rs', b'changed production source')

    def test_production_patch_preserves_exit_and_wait_control_flow(self):
        # Bounded anchor fixtures exercise the patcher on shallow CI checkouts.
        # Only this test substitutes expected hashes. The isolated caller's
        # prepare step verifies the complete pinned production source and HAL.
        originals = {
            'src/app.rs': b'''        if focus_input.is_key_pressed(KeyCode::F10) {
            frame_trace::log_completion(frame_trace::set_eligibility(Eligibility::Ineligible(
                BoundaryReason::Shutdown,
            )));
            break;
        }
''',
            'src/platform/window.rs': b'''    event_loop.set_control_flow(ControlFlow::Wait);
    let result = event_loop.run_app(&mut runtime).map_err(|e| e.to_string());
    runtime.hooks.take();
            WindowEvent::CloseRequested | WindowEvent::Destroyed => event_loop.exit(),
''',
            'src/render/device.rs': b'''            let status = surface.surface.get_current_texture();
''',
        }
        with patch.dict(d.ORIGINALS, {name: d.digest(data) for name, data in originals.items()}), \
                patch.object(subprocess, 'check_output', side_effect=AssertionError('No Git/history/network allowed')):
            patches = {name: d.instrument(name, data).decode() for name, data in originals.items()}
        window = patches['src/platform/window.rs']
        self.assertIn('event_loop.set_control_flow(ControlFlow::Wait)', window)
        self.assertLess(window.index('"run_app_exit"'), window.index('"hooks_drop_enter"'))
        self.assertLess(window.index('    runtime.hooks.take();'), window.index('"hooks_drop_exit"'))
        self.assertIn('"native_close"', window)
        self.assertIn('"f10_enter"', patches['src/app.rs'])
        self.assertIn('"f10_exit"', patches['src/app.rs'])
        self.assertIn('let status = surface.surface.get_current_texture();', patches['src/render/device.rs'])

    def test_archive_links_and_traversal_fail(self):
        for name, kind in (('../escaped', tarfile.REGTYPE), ('good', tarfile.SYMTYPE)):
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode='w') as archive:
                item = tarfile.TarInfo(name)
                item.type = kind
                item.linkname = '/tmp/other'
                archive.addfile(item)
            stream.seek(0)
            with tempfile.TemporaryDirectory() as directory, tarfile.open(fileobj=stream) as archive:
                with self.assertRaises(ValueError):
                    d.extract_regular(archive, Path(directory))


class ExitTests(unittest.TestCase):
    def test_native_close_only_targets_owned_window(self):
        driver, process = Mock(), Mock()
        driver.window = 82
        driver.user.PostMessageW.return_value = 1
        snapshot = {'process_alive': True, 'window': {'owned_by_launched_process': True}}
        with patch.object(d, 'exit_snapshot', return_value=snapshot):
            d.request_exit(driver, process, 'native-close')
        driver.user.PostMessageW.assert_called_once_with(82, 0x10, 0, 0)

    def test_unowned_window_never_gets_close_or_f10(self):
        for method in ('native-close', 'f10'):
            driver = Mock()
            with patch.object(d, 'exit_snapshot', return_value={'process_alive': True, 'window': {}}), \
                    patch.object(d, 'tap') as tap:
                with self.assertRaisesRegex(ValueError, 'PID-owned'):
                    d.request_exit(driver, Mock(), method)
                driver.user.PostMessageW.assert_not_called()
                tap.assert_not_called()

    def test_exception_after_launch_always_cleans_owned_child(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            package = root / 'package'
            package.mkdir()
            executable = package / 'DIAGNOSTIC.exe'
            executable.write_bytes(b'diagnostic test executable')
            (package / 'settings.cfg').write_text('settings')
            build = {'diagnostic_executable': executable.name,
                     'diagnostic_executable_sha256': d.matrix.sha256(executable),
                     'runtime_files_sha256': d.tree_hashes(package)}
            (package / 'DIAGNOSTIC_BUILD.json').write_text(json.dumps(build))
            driver = Mock()
            driver.bind.side_effect = RuntimeError('injected failure after child launch')
            driver.release_inputs.return_value = []
            process = Mock(pid=123)
            process.poll.return_value = 0
            with patch.object(d.sys, 'platform', 'win32'), \
                    patch.object(d, 'create_driver', return_value=driver), \
                    patch.object(d.subprocess, 'Popen', return_value=process), \
                    patch.object(d.matrix, 'cleanup_owned_process', return_value={'process_exit_verified': True}) as cleanup:
                summary = d.run(package, root / 'output')
            cleanup.assert_called_once_with(process)
            self.assertIn('injected failure', summary['run']['error'])
            self.assertEqual(summary['state'], 'diagnostic_incomplete')
            self.assertFalse(summary['full_matrix_passed'])
            self.assertFalse(summary['acceptance_proven'])
            self.assertTrue((root / 'output/RUN.json').is_file())

    def test_cleanup_terminate_timeout_escalates_only_owned_handle(self):
        process = Mock(pid=123)
        process.poll.side_effect = [None, 1]
        process.wait.side_effect = [subprocess.TimeoutExpired('owned', 5), 1]
        result = d.matrix.cleanup_owned_process(process)
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        self.assertTrue(result['process_exit_verified'])


class SummaryTests(unittest.TestCase):
    def test_short_cpu_trace_is_diagnostic_only_and_failed_exit_stays_failed(self):
        from test_performance_matrix import trace
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            session = root / 'telemetry-sessions/session-test'
            session.mkdir(parents=True)
            adapter = {'backend': 'Dx12', 'device_type': 'Cpu', 'present_mode': 'Fifo',
                       'force_fallback_requested': True}
            report = trace({'id': 'baseline', 'settings': {'surface_extent': [1920, 1080]}},
                           adapter, {'label': 'synthetic diagnostic'}, intervals=3)
            (session / 'frames.json').write_text(json.dumps(report))
            for name in ('CSV_STATUS.json', 'GPU_STATUS.json', 'IDENTITY.json'):
                (session / name).write_text('{}')
            run = {'exit_method': 'f10', 'graceful_shutdown': True,
                   'cleanup': {'process_exit_verified': True}}
            (root / 'RUN.json').write_text(json.dumps(run))
            lines = [d.PREFIX + 'event=hal_wait_result sequence=' + str(i) +
                     ' elapsed_ns=1000000000 wait_ok=false waitable=true' for i in range(3)]
            lines.extend(d.PREFIX + 'event=' + phase + suffix + ' unix_ns=123 elapsed_ns=0'
                         for phase in ('f10', 'run_app', 'hooks_drop') for suffix in ('_enter', '_exit'))
            (root / 'game.log').write_text('\n'.join(lines))
            result = d.summarize(root)
            self.assertEqual(result['state'], 'diagnostic_complete')
            self.assertEqual(result['retained_interval_count'], 3)
            self.assertFalse(result['full_matrix_passed'])
            self.assertFalse(result['acceptance_proven'])
            run['graceful_shutdown'] = False
            run['exit_timed_out'] = True
            (root / 'RUN.json').write_text(json.dumps(run))
            self.assertEqual(d.summarize(root)['state'], 'diagnostic_incomplete')
            report['identity']['runtime_observed']['actual_adapter']['device_type'] = 'DiscreteGpu'
            (session / 'frames.json').write_text(json.dumps(report))
            self.assertIn('Observed runtime does not establish Windows CPU DX12/Fifo/1080p',
                          d.summarize(root)['errors'])


class CandidateTests(unittest.TestCase):
    @staticmethod
    def records():
        rows = [
            'event=hal_wait_result sequence=0 elapsed_ns=1 wait_ok=false waitable=true',
            'event=hal_wait_exit elapsed_ns=1',
            'event=hal_timeout_return sequence=0 acquired_count=0',
            'event=surface_acquire_exit elapsed_ns=1',
            'event=surface_status status=timeout',
            'event=frame_skip elapsed_ns=0',
            'event=hal_wait_result sequence=1 elapsed_ns=1000000000 wait_ok=true waitable=true',
            'event=hal_backbuffer_enter elapsed_ns=0',
            'event=surface_status status=success',
            'event=frame_ready elapsed_ns=0',
        ]
        return d.parse_log('\n'.join(d.PREFIX + row for row in rows))

    def test_actual_boolean_and_resume_not_duration_determine_success(self):
        result = d.candidate_observations(self.records())
        self.assertTrue(result['passed'])
        self.assertEqual(len(result['completed_timeout_skips']), 1)

    def test_incomplete_timeout_paths_and_app_consumption_fail(self):
        for event in ('hal_timeout_return', 'surface_status', 'frame_skip', 'frame_ready'):
            parsed = self.records()
            parsed['records'] = [row for row in parsed['records'] if row['event'] != event]
            with self.subTest(event=event), self.assertRaises(ValueError):
                d.candidate_observations(parsed)
        for event in ('hal_backbuffer_enter', 'frame_ready'):
            parsed = self.records()
            parsed['records'].insert(3, {'event': event})
            with self.subTest(event=event), self.assertRaises(ValueError):
                d.candidate_observations(parsed)

    def test_wrong_sequence_and_error_are_not_timeout_success(self):
        parsed = self.records()
        parsed['records'][2]['sequence'] = 1
        with self.assertRaises(ValueError):
            d.candidate_observations(parsed)
        parsed = self.records()
        parsed['records'][0]['wait_ok'] = 'error'
        with self.assertRaisesRegex(ValueError, 'returned an error'):
            d.candidate_observations(parsed)

    def test_no_real_timeout_is_unproven(self):
        parsed = self.records()
        parsed['records'] = parsed['records'][6:]
        parsed['wait_false_count'] = 0
        with self.assertRaisesRegex(ValueError, 'at least one real'):
            d.candidate_observations(parsed)

    def test_image_comparison_is_exact_including_witness_and_alpha(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            left, right = Path(folder) / 'baseline.png', Path(folder) / 'candidate.png'
            image = Image.new('RGBA', (960, 540), (20, 30, 40, 255))
            image.save(left)
            image.save(right)
            result = d.compare_pixels(left, right)
            self.assertEqual(result['pixels_compared'], 518400)
            self.assertEqual(result['masked_pixels'], 0)
            for location, pixel in [((0, 0), (21, 30, 40, 255)),
                                    ((959, 539), (20, 30, 40, 254))]:
                changed = image.copy()
                changed.putpixel(location, pixel)
                changed.save(right)
                with self.subTest(location=location), self.assertRaises(ValueError):
                    d.compare_pixels(left, right)

    def test_image_pipeline_retains_four_captures_and_failures_without_rebuilding(self):
        from PIL import Image
        import run_calibrated_presentation as calibrated
        import verify_calibrated_presentation as validator
        import run_dx12_authored as captures
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original, candidate = root / 'original', root / 'candidate'
            for package in (original, candidate):
                (package / 'assets/weapons').mkdir(parents=True)
                (package / 'assets/weapons/hk416a5.vrm').write_bytes(b'fixture asset')
                (package / 'vector-range.exe').write_bytes(package.name.encode())
            baseline = {'executable_sha256': d.matrix.sha256(original / 'vector-range.exe')}
            build = {'mode': d.MODES[1], 'original_package': baseline,
                     'diagnostic_executable': 'vector-range.exe', 'derivation_sha256': 'a' * 64,
                     'diagnostic_executable_sha256': d.matrix.sha256(candidate / 'vector-range.exe'),
                     'runtime_files_sha256': d.tree_hashes(candidate)}
            (candidate / 'DIAGNOSTIC_BUILD.json').write_text(json.dumps(build))
            def execute(command, package, logs, timeout, renderer):
                output = Path(next(arg.split('=', 1)[1] for arg in command if arg.startswith('--output=')))
                image = Image.new('RGBA', (960, 540), (20, 30, 40, 255))
                image.save(output)
                image.save(str(output) + '.world.png')
            with patch.object(d.sys, 'platform', 'win32'), \
                    patch.object(d.matrix, 'package_identity', return_value=baseline), \
                    patch.object(validator, 'ASSET_SHA256', d.digest(b'fixture asset')), \
                    patch.object(captures, 'execute', side_effect=execute) as run, \
                    patch.object(calibrated, 'native_receipt'), \
                    patch.object(validator, 'validate_capture', return_value={'within_tolerance': True}) as validate:
                result = d.image_controls(original, candidate, root / 'images')
                self.assertTrue(result['passed'])
                self.assertEqual(len(result['comparisons']), 4)
                self.assertEqual(run.call_count, 4)
                self.assertEqual(validate.call_count, 4)
                for pose in ('hip', 'ads'):
                    commands = [call.args[0] for call in run.call_args_list
                                if call.args[0][-1] == '--capture-ads'] if pose == 'ads' else [
                        call.args[0] for call in run.call_args_list if '--capture-ads' not in call.args[0]]
                    witnesses = [next(arg for arg in command if arg.startswith('--capture-frame-witness='))
                                 for command in commands]
                    self.assertEqual(len(witnesses), 2)
                    self.assertEqual(witnesses[0], witnesses[1])
                validate.side_effect = ValueError('original calibration gate failed')
                failed = d.image_controls(original, candidate, root / 'failed-images')
                self.assertFalse(failed['passed'])
                self.assertEqual(len(failed['errors']), 4)
                self.assertTrue((root / 'failed-images/SUMMARY.json').is_file())


class WorkflowTests(unittest.TestCase):
    def test_one_bounded_derived_binary_and_single_run(self):
        raw = (ROOT / '.github/workflows/windows-acquire-diagnostic.yml').read_text()
        value = yaml.load(raw, Loader=yaml.BaseLoader)
        steps = value['jobs']['diagnostic']['steps']
        scripts = '\n'.join(s.get('run', '') for s in steps)
        self.assertEqual(scripts.count('cargo --config diagnostic-cargo.toml build'), 1)
        self.assertEqual(scripts.count('windows_acquire_diagnostic.py run '), 1)
        self.assertIn('--seconds 25', scripts)
        self.assertIn('CARGO_TARGET_DIR', raw)
        caches = [s for s in steps if s.get('uses') == 'actions/cache@v4']
        self.assertEqual(len(caches), 1)
        self.assertNotIn('target', caches[0]['with']['path'])
        self.assertNotIn('derived', caches[0]['with']['path'])
        downloads = [s for s in steps if s.get('uses') == 'actions/download-artifact@v8']
        self.assertEqual(len(downloads), 1)
        self.assertEqual(downloads[0]['with']['digest-mismatch'], 'error')
        self.assertEqual(downloads[0]['with']['artifact-ids'], '11432281909')
        self.assertEqual(downloads[0]['with']['run-id'], '37505927104')
        self.assertEqual(value['permissions'], {'contents': 'read', 'actions': 'read'})
        upload = next(s for s in steps if s.get('uses') == 'actions/upload-artifact@v4')
        self.assertEqual(upload['with']['path'], 'evidence/')
        self.assertEqual(upload['if'], 'always()')

    def test_candidate_gates_reuse_same_target_and_original_package(self):
        raw = (ROOT / '.github/workflows/windows-acquire-diagnostic.yml').read_text()
        value = yaml.load(raw, Loader=yaml.BaseLoader)
        steps = value['jobs']['diagnostic']['steps']
        image = next(s for s in steps if 'windows_acquire_diagnostic.py images ' in s.get('run', ''))
        policy = next(s for s in steps if 'INPUT_RETENTION_TEST.log' in s.get('run', ''))
        build = next(s for s in steps if s.get('id') == 'build')
        self.assertEqual(policy['env']['CARGO_TARGET_DIR'], build['env']['CARGO_TARGET_DIR'])
        self.assertIn('--locked --release --features wgpu-runtime --lib', policy['run'])
        self.assertIn('steps.stage.outcome', image['if'])
        self.assertIn('!cancelled()', image['if'])
        self.assertIn('--original package --candidate diagnostic-package', image['run'])
        self.assertNotIn('continue-on-error', raw)
        self.assertNotIn('--example', raw)
        self.assertIn('Pillow==11.3.0', raw)
        self.assertNotIn('artifact-ids: \'11442486459\'', raw)
        self.assertEqual(value['on']['workflow_dispatch']['inputs']['mode']['default'], d.MODES[1])

    def test_existing_fail_closed_provider_validation_is_reused_exactly(self):
        original = yaml.load((ROOT / '.github/workflows/performance-matrix-feedback.yml').read_text(), Loader=yaml.BaseLoader)
        derived = yaml.load((ROOT / '.github/workflows/windows-acquire-diagnostic.yml').read_text(), Loader=yaml.BaseLoader)
        def provider(workflow):
            steps = next(iter(workflow['jobs'].values()))['steps']
            return next(s['with']['script'] for s in steps if s.get('id') == 'provider')
        self.assertEqual(provider(original), provider(derived))


if __name__ == '__main__':
    unittest.main()

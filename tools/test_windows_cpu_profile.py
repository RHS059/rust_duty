import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import run_windows_cpu_profile as profile


class ProfileGuards(unittest.TestCase):
    def test_instance_is_scoped_for_every_session_command(self):
        for args in (('-start', 'CPU'), ('-stop', 'out.etl'), ('-cancel',), ('-status',)):
            value = profile.wpr_command('wpr.exe', 'rust-duty-abc123', *args)
            self.assertEqual(value[-2:], ['-instancename', 'rust-duty-abc123'])
            self.assertNotIn('-filemode', value)
        for invalid in ('other', 'rust-duty-a b', 'rust-duty-a;stop', 'rust-duty-/tmp'):
            with self.assertRaises(ValueError):
                profile.wpr_command('wpr.exe', invalid, '-cancel')

    def test_user_desktop_is_rejected(self):
        for env in ({}, {'GITHUB_ACTIONS': 'true'},
                    {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'self-hosted'}):
            with patch.dict(os.environ, env, clear=True), patch.object(profile.sys, 'platform', 'win32'):
                with self.assertRaises(ValueError):
                    profile.require_host()
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted'}, clear=True), patch.object(profile.sys, 'platform', 'win32'):
            profile.require_host()

    def test_tools_must_already_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {'SystemRoot': str(root / 'Windows'), 'ProgramFiles(x86)': str(root / 'Programs')}
            with self.assertRaisesRegex(ValueError, 'missing'):
                profile.installed_tools(env)
            wpr = root / 'Windows/System32/wpr.exe'
            xperf = root / 'Programs/Windows Kits/10/Windows Performance Toolkit/xperf.exe'
            for path in (wpr, xperf):
                path.parent.mkdir(parents=True)
                path.write_bytes(b'fixture')
            self.assertEqual(profile.installed_tools(env), {'wpr': wpr, 'xperf': xperf})

    def test_logs_preserve_failure_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(profile.subprocess, 'run', return_value=subprocess.CompletedProcess([], 7)):
                with self.assertRaisesRegex(ValueError, 'failed'):
                    profile.command_log(['x'], root, root / 'result.log')
            self.assertTrue((root / 'result.log').exists())
            with self.assertRaises(FileExistsError):
                profile.command_log(['x'], root, root / 'result.log')

    def test_build_timeout_or_interrupt_retires_owned_descendants_and_retains_cleanup(self):
        import dx12_contract_process as processes
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, error in enumerate((subprocess.TimeoutExpired('cargo', 5), KeyboardInterrupt())):
                child = MagicMock()
                child.wait.side_effect = error
                receipt = {'pid': 1234, 'succeeded': False, 'errors': ['synthetic tree cleanup failure']}
                log = root / f'build-{index}.log'
                with patch.object(profile.subprocess, 'CREATE_NEW_PROCESS_GROUP', 512, create=True), \
                        patch.object(profile.subprocess, 'Popen', return_value=child) as launch, \
                        patch.object(processes, '_terminate_process_tree', return_value=receipt) as cleanup:
                    with self.assertRaises(type(error)) as caught:
                        profile.command_log(['cargo', 'build'], root, log, timeout=5, owned_tree=True)
                    self.assertIs(caught.exception, error)
                cleanup.assert_called_once_with(child)
                self.assertEqual(launch.call_args.kwargs['creationflags'], 512)
                self.assertEqual(profile.json.loads(log.with_suffix('.cleanup.json').read_text()), receipt)
                self.assertTrue(log.is_file())

    def test_source_bytes_must_match_real_git_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args])
            git('init', '-q')
            git('config', 'user.name', 'Profile Test')
            git('config', 'user.email', 'test@example.invalid')
            (root / 'input.rs').write_bytes(b'original\n')
            git('add', 'input.rs')
            git('commit', '-qm', 'fixture')
            sha = git('rev-parse', 'HEAD').decode().strip()
            with patch.dict(os.environ, {'GITHUB_SHA': sha}):
                source = profile.checked_source(root)
                self.assertEqual(source['files_sha256']['input.rs'], profile.digest(root / 'input.rs'))
                (root / 'input.rs').write_bytes(b'changed\n')
                with self.assertRaisesRegex(ValueError, 'changed'):
                    profile.checked_source(root)
            with patch.dict(os.environ, {'GITHUB_SHA': '0' * 40}):
                with self.assertRaisesRegex(ValueError, 'actual CI'):
                    profile.checked_source(root)

    def test_untracked_and_ignored_compile_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args])
            git('init', '-q')
            git('config', 'user.name', 'Profile Test')
            git('config', 'user.email', 'test@example.invalid')
            (root / '.gitignore').write_bytes(b'updater/notices/\n')
            (root / 'Cargo.toml').write_bytes(b'# fixture\n')
            git('add', '.')
            git('commit', '-qm', 'fixture')
            sha = git('rev-parse', 'HEAD').decode().strip()
            with patch.dict(os.environ, {'GITHUB_SHA': sha}):
                profile.checked_source(root)
                for name in ('src/extra.rs', 'updater/notices/extra.txt',
                             '.cargo/other-input', 'rust-toolchain', 'rust-toolchain.toml'):
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b'fixture')
                    with self.assertRaisesRegex(ValueError, 'Untracked or ignored'):
                        profile.checked_source(root)
                    path.unlink()

    def test_generated_asset_boundary_does_not_relax_source_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args])
            git('init', '-q')
            git('config', 'user.name', 'Profile Test')
            git('config', 'user.email', 'test@example.invalid')
            for name in ('assets/directional/manifest.json', 'assets/authoring/input.py',
                         'src/app.rs', 'tools/probe.py', 'ui/theme.css', 'settings.cfg'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'committed\n')
            git('add', '.')
            git('commit', '-qm', 'fixture')
            sha = git('rev-parse', 'HEAD').decode().strip()
            with patch.dict(os.environ, {'GITHUB_SHA': sha}):
                path = root / 'assets/directional/manifest.json'
                path.write_bytes(b'generated\n')
                source = profile.checked_source(root)
                bound = source['generated_asset_transports']['assets/directional/manifest.json']
                self.assertEqual(bound['materialized_sha256'], profile.digest(path))
                self.assertNotEqual(bound['materialized_sha256'], bound['committed_sha256'])
                for name in ('assets/authoring/input.py', 'src/app.rs', 'tools/probe.py',
                             'ui/theme.css', 'settings.cfg'):
                    changed = root / name
                    changed.write_bytes(b'changed\n')
                    with self.assertRaisesRegex(ValueError, 'Tracked source changed'):
                        profile.checked_source(root)
                    changed.write_bytes(b'committed\n')

    def test_profile_has_every_existing_companion_dependency(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / '.github/workflows/windows-cpu-profile.yml').read_text()
        # These checks are deliberately usable before optional YAML dependencies.
        self.assertIn('needs: [pair-admission, animation-assets, walk-assets, ads-assets, directional-assets, jump-assets]', text)
        for name, workflow in (('reload', 'blender'), ('walk', 'walk'), ('ads', 'ads'),
                               ('directional', 'directional'), ('jump', 'jump')):
            self.assertIn('uses: ./.github/workflows/' + workflow + '-assets.yml', text)
            self.assertIn('name: generated-' + name + '-runtime', text)
            self.assertIn('path: assets/' + name, text)
        self.assertLess(text.index('name: generated-jump-runtime'),
                        text.index('python tools/package_game.py materialize'))

    def test_cleanup_retains_all_independent_failures(self):
        process = MagicMock()
        process.poll.return_value = None
        process.terminate.side_effect = OSError('termination failed')
        driver = MagicMock()
        driver.release_inputs.side_effect = OSError('release failed')
        with patch.object(profile, 'command_log', side_effect=OSError('cancel failed')) as cancel:
            errors, code = profile.cleanup_owned(Path('.'), Path('out'), driver, process,
                                                  'wpr.exe', 'rust-duty-test1', True)
        self.assertEqual(len(errors), 3)
        self.assertIsNone(code)
        self.assertEqual(cancel.call_args.args[0], ['wpr.exe', '-cancel', '-instancename', 'rust-duty-test1'])

    def test_cleanup_does_not_cancel_unstarted_or_kill_exited_process(self):
        driver, process = MagicMock(), MagicMock()
        driver.release_inputs.return_value = []
        process.poll.return_value = 0
        with patch.object(profile, 'command_log') as cancel:
            errors, code = profile.cleanup_owned(Path('.'), Path('out'), driver, process,
                                                  'wpr.exe', 'rust-duty-test1', False)
        self.assertEqual((errors, code), ([], 0))
        cancel.assert_not_called()
        process.terminate.assert_not_called()

    def test_python_imports_do_not_create_self_rejected_bytecode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'tools').mkdir()
            (root / 'tools/probe.py').write_text('value = 7\n')
            subprocess.run([profile.sys.executable, '-c', 'import probe; assert probe.value == 7'],
                           cwd=root, env=dict(os.environ, PYTHONPATH=str(root / 'tools'),
                                             PYTHONDONTWRITEBYTECODE='1'), check=True)
            self.assertFalse((root / 'tools/__pycache__').exists())
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/windows-cpu-profile.yml').read_text()
        self.assertIn("PYTHONDONTWRITEBYTECODE: '1'", workflow)

    def test_authored_load_is_positive_and_errors_remain_failures(self):
        valid = ('renderer requested=dx12 backend=Dx12 adapter=Microsoft Basic Render Driver\nwindow physical_extent_verified=1920x1080\n'
                 'Loaded Blender-authored viewmodel: 10 bones, 3 clips, selected normal_ready\n')
        profile.validate_scene_log(valid)
        for invalid in (valid.splitlines()[0], valid + 'Authored viewmodel could not load: fixture',
                        valid + 'Authored viewmodel playback failed: fixture',
                        valid + 'Action clip timings: fixture',
                        valid + 'renderer requested=dx12 backend=Vulkan adapter=other'):
            with self.assertRaises(ValueError):
                profile.validate_scene_log(invalid)

    def test_renderer_stack_filters_cpu_samples_and_keeps_unfiltered_stacks(self):
        source = (Path(__file__).resolve().parents[1] / 'tools/run_windows_cpu_profile.py').read_text()
        self.assertIn("('stack', ['-butterfly'])", source)
        self.assertIn("('renderer-stack', ['-butterfly', '-event', 'Profile', '-pid', str(process.pid)", source)
        self.assertIn("'-tid', str(receipt['renderer_window_thread_id'])", source)

    def shutdown_fixture(self, owner=41):
        driver, process = MagicMock(), MagicMock()
        process.pid, process.returncode = 41, None
        process.poll.return_value = None
        driver.window = 123
        driver.user.IsWindow.return_value = True
        def identify(window, out):
            out._obj.value = owner
            return 77
        driver.user.GetWindowThreadProcessId.side_effect = identify
        driver.user.PostMessageW.return_value = True
        return driver, process

    def test_normal_f10_exit_never_posts_another_close(self):
        driver, process = self.shutdown_fixture()
        process.wait.return_value = 0
        with patch.object(profile, 'exit_snapshot', return_value={'synthetic': True}):
            result = profile.normal_shutdown(driver, process)
        self.assertTrue(result['normal_exit'])
        self.assertEqual(result['method'], 'f10')
        self.assertFalse(result['wm_close']['attempted'])
        driver.close.assert_called_once_with()
        driver.user.PostMessageW.assert_not_called()
        process.wait.assert_called_once_with(timeout=20)

    def test_f10_timeout_retained_before_pid_verified_normal_window_close(self):
        driver, process = self.shutdown_fixture()
        process.wait.side_effect = [subprocess.TimeoutExpired('synthetic game', 20), 0]
        with patch.object(profile, 'exit_snapshot', return_value={'synthetic': True}) as snapshot:
            result = profile.normal_shutdown(driver, process)
        self.assertTrue(result['normal_exit'])
        self.assertEqual(result['method'], 'wm_close')
        self.assertTrue(result['f10']['timed_out'])
        self.assertIn('after', result['f10'])
        self.assertEqual(result['wm_close']['owner_pid'], process.pid)
        driver.user.PostMessageW.assert_called_once_with(123, 0x0010, 0, 0)
        snapshot.assert_any_call(driver, process, probe_responsiveness=True)
        self.assertEqual([call.kwargs for call in process.wait.call_args_list], [{'timeout': 20}] * 2)
        process.terminate.assert_not_called()

    def test_reused_or_missing_window_never_receives_close(self):
        for absent in (False, True):
            driver, process = self.shutdown_fixture(owner=99)
            driver.user.IsWindow.return_value = not absent
            process.wait.side_effect = subprocess.TimeoutExpired('synthetic game', 20)
            with patch.object(profile, 'exit_snapshot', return_value={}):
                result = profile.normal_shutdown(driver, process)
            self.assertFalse(result['normal_exit'])
            self.assertFalse(result['wm_close']['attempted'])
            self.assertIn('error', result['wm_close'])
            driver.user.PostMessageW.assert_not_called()
            process.wait.assert_called_once_with(timeout=20)

    def test_two_timeouts_preserve_failure_without_forced_shutdown(self):
        driver, process = self.shutdown_fixture()
        process.wait.side_effect = subprocess.TimeoutExpired('synthetic game', 20)
        with patch.object(profile, 'exit_snapshot', return_value={}):
            result = profile.normal_shutdown(driver, process)
        self.assertFalse(result['normal_exit'])
        self.assertTrue(result['f10']['timed_out'])
        self.assertTrue(result['wm_close']['timed_out'])
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    def test_nonzero_normal_exit_and_failed_post_are_not_success(self):
        driver, process = self.shutdown_fixture()
        process.wait.return_value = 3
        with patch.object(profile, 'exit_snapshot', return_value={}):
            result = profile.normal_shutdown(driver, process)
        self.assertFalse(result['normal_exit'])
        self.assertEqual(result['exit_code'], 3)
        driver.user.PostMessageW.assert_not_called()
        driver, process = self.shutdown_fixture()
        process.wait.side_effect = subprocess.TimeoutExpired('synthetic game', 20)
        driver.user.PostMessageW.return_value = False
        with patch.object(profile, 'exit_snapshot', return_value={}):
            result = profile.normal_shutdown(driver, process)
        self.assertFalse(result['normal_exit'])
        self.assertIn('Owned WM_CLOSE request failed', result['wm_close']['error'])
        self.assertEqual(process.wait.call_count, 1)

    def test_normal_verified_capture_and_export_are_both_required_for_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            receipt = {'shutdown': {'normal_exit': True, 'method': 'wm_close'},
                       'post_capture_inputs_verified': True}
            with patch.object(profile, 'cleanup_owned', return_value=([], 0)), \
                    patch.object(profile, 'export_trace', return_value={'passed': True}):
                result = profile.finalize_capture(out, out, MagicMock(), MagicMock(),
                    'wpr.exe', 'rust-duty-test', False, True, {}, out, receipt, None)
            self.assertIsNone(result)
            self.assertTrue(receipt['passed'])

    def test_failed_normal_exit_still_exports_stopped_trace_without_becoming_passed(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            original = ValueError('original shutdown failed')
            receipt = {'error': str(original), 'shutdown': {'normal_exit': False}}
            def cleanup(*args):
                args[-1].update(forced=True, process_action='terminate')
                return [], 1
            with patch.object(profile, 'cleanup_owned', side_effect=cleanup), \
                    patch.object(profile, 'export_trace', return_value={'passed': True}) as export:
                result = profile.finalize_capture(out, out, MagicMock(), MagicMock(),
                    'wpr.exe', 'rust-duty-test', False, True, {}, out, receipt, original)
            self.assertIs(result, original)
            export.assert_called_once()
            self.assertFalse(receipt['passed'])
            self.assertTrue(receipt['trace_export']['passed'])
            self.assertTrue(receipt['cleanup']['forced'])
            self.assertEqual(receipt['exit_code'], 1)
            self.assertTrue((out / 'capture.json').exists())

    def test_export_failure_cannot_replace_original_error_or_claim_success(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            for original in (None, ValueError('original source failure')):
                receipt = {'shutdown': {'normal_exit': True}, 'post_capture_inputs_verified': True}
                failure = ValueError('export failed')
                with patch.object(profile, 'cleanup_owned', return_value=([], 0)), \
                        patch.object(profile, 'export_trace', side_effect=failure):
                    result = profile.finalize_capture(out, out, MagicMock(), MagicMock(),
                        'wpr.exe', 'rust-duty-test', False, True, {}, out, receipt, original)
                self.assertIs(result, failure if original is None else original)
                self.assertFalse(receipt['passed'])
                self.assertEqual(receipt['trace_export']['error'], 'export failed')

    def test_interrupt_during_export_retains_receipt_then_propagates_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            for original in (None, ValueError('original shutdown failure')):
                receipt = {'shutdown': {'normal_exit': original is None},
                           'post_capture_inputs_verified': original is None}
                if original is not None:
                    receipt['error'] = str(original)
                interrupt = KeyboardInterrupt()
                with patch.object(profile, 'cleanup_owned', return_value=([], 1)), \
                        patch.object(profile, 'export_trace', side_effect=interrupt) as export:
                    result = profile.finalize_capture(out, out, MagicMock(), MagicMock(),
                        'wpr.exe', 'rust-duty-test', False, True, {}, out, receipt, original)
                self.assertIs(result, interrupt)
                export.assert_called_once()
                self.assertFalse(receipt['passed'])
                self.assertEqual(receipt['trace_export']['error_type'], 'KeyboardInterrupt')
                self.assertTrue((out / 'capture.json').exists())
                if original is not None:
                    self.assertEqual(receipt['error'], str(original))
                    self.assertEqual(receipt['error_type'], 'ValueError')

    def test_unsaved_or_interrupted_trace_never_starts_report_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            for saved, error in ((False, ValueError('save failed')), (True, KeyboardInterrupt())):
                receipt = {}
                with patch.object(profile, 'cleanup_owned', return_value=([], 1)), \
                        patch.object(profile, 'export_trace') as export:
                    result = profile.finalize_capture(out, out, MagicMock(), MagicMock(),
                        'wpr.exe', 'rust-duty-test', False, saved, {}, out, receipt, error)
                self.assertIs(result, error)
                self.assertFalse(receipt['passed'])
                export.assert_not_called()

    def test_forced_cleanup_is_explicit_in_retained_observation(self):
        driver, process = MagicMock(), MagicMock()
        driver.release_inputs.return_value = []
        process.poll.side_effect = [None, 1]
        process.wait.return_value = 1
        observation = {}
        errors, code = profile.cleanup_owned(Path('.'), Path('out'), driver, process,
                                              'wpr.exe', 'rust-duty-test', False, observation)
        self.assertEqual((errors, code), ([], 1))
        self.assertEqual(observation, {'forced': True, 'process_action': 'terminate'})

    def test_optimized_symbols_settings_are_explicit(self):
        self.assertIn('--release', profile.BUILD)
        self.assertIn('--locked', profile.BUILD)
        self.assertEqual(profile.SETTINGS['CARGO_PROFILE_RELEASE_DEBUG'], '2')
        self.assertEqual(profile.SETTINGS['CARGO_PROFILE_RELEASE_STRIP'], 'none')
        self.assertEqual(profile.SECONDS, 30)
        self.assertEqual(profile.EXTENT, [1920, 1080])

    def test_pinned_reader_dependencies_precede_all_guard_imports(self):
        import yaml
        root = Path(__file__).resolve().parents[1]
        workflow = yaml.safe_load((root / '.github/workflows/windows-cpu-profile.yml').read_text())
        steps = workflow['jobs']['cpu-sampling']['steps']
        installs = [index for index, step in enumerate(steps)
                    if 'python -m pip install Pillow==11.3.0 PyYAML==6.0.3' in step.get('run', '')]
        self.assertEqual(len(installs), 1)
        imports = [index for index, step in enumerate(steps)
                   if ('python -m unittest' in step.get('run', '')
                       or 'python tools/run_windows_cpu_profile.py' in step.get('run', '')
                       or 'python tools/package_game.py' in step.get('run', ''))]
        self.assertTrue(imports)
        self.assertLess(installs[0], min(imports))
        self.assertIn('if ($LASTEXITCODE -ne 0)', steps[installs[0]]['run'])

    def test_workflow_is_bounded_read_only_and_retains_symbols(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / '.github/workflows/windows-cpu-profile.yml').read_text()
        self.assertIn('branches: [aella/wgpu-1080p-diagnostics]', workflow)
        self.assertIn('cancel-in-progress: false', workflow)
        self.assertIn('contents: read', workflow)
        self.assertIn('persist-credentials: false', workflow)
        self.assertNotIn('secrets:', workflow)
        self.assertNotIn('workflow_dispatch', workflow)
        self.assertIn('timeout-minutes: 90', workflow)
        self.assertIn('timeout-minutes: 84', workflow)
        self.assertIn('run_windows_cpu_profile.py compare-loaders --root .', workflow)
        self.assertIn('test_windows_cpu_profile test_geometry_profile_pair test_arena_serialization_pair', workflow)
        self.assertIn('git fetch --no-write-fetch-head --no-tags --depth=1 origin 5a88053e1668000744bbebbf967c6d24833dddd5', workflow)
        for folder in ('target', 'symbols', 'symcache'):
            self.assertIn('!evidence/cpu-profile/**/' + folder + '/**', workflow)
        self.assertIn('evidence/cpu-profile/r*/runtime/telemetry-sessions/**', workflow)
        compact = workflow.split('name: windows-cpu-profile-reports-attempt-', 1)[1]
        self.assertIn('evidence/cpu-profile/sources/*.json', compact)
        self.assertIn('if: always()', workflow)
        self.assertNotIn('!evidence/cpu-profile/*.pdb', workflow)
        self.assertNotIn('${{ runner.', workflow)
        source = (root / 'tools/run_windows_cpu_profile.py').read_text()
        self.assertIn("'top_functions_reviewed': False", source)
        self.assertIn("'renderer_window_thread_id'", source)
        self.assertNotIn('-disablepagingexecutive', source)
        self.assertNotIn('-setprofint', source)
        self.assertNotIn('-boottrace', source)


if __name__ == '__main__':
    unittest.main()

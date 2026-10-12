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
        self.assertIn('needs: [animation-assets, walk-assets, ads-assets, directional-assets, jump-assets]', text)
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

    def test_optimized_symbols_settings_are_explicit(self):
        self.assertIn('--release', profile.BUILD)
        self.assertIn('--locked', profile.BUILD)
        self.assertEqual(profile.SETTINGS['CARGO_PROFILE_RELEASE_DEBUG'], '2')
        self.assertEqual(profile.SETTINGS['CARGO_PROFILE_RELEASE_STRIP'], 'none')
        self.assertEqual(profile.SECONDS, 30)
        self.assertEqual(profile.EXTENT, [1920, 1080])

    def test_workflow_is_bounded_read_only_and_retains_symbols(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / '.github/workflows/windows-cpu-profile.yml').read_text()
        self.assertIn('branches: [aella/wgpu-1080p-diagnostics]', workflow)
        self.assertIn('cancel-in-progress: false', workflow)
        self.assertIn('contents: read', workflow)
        self.assertIn('persist-credentials: false', workflow)
        self.assertNotIn('secrets:', workflow)
        self.assertNotIn('workflow_dispatch', workflow)
        self.assertIn('timeout-minutes: 45', workflow)
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

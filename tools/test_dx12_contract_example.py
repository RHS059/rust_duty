"""CLI dispatch tests with process mocks; never native renderer evidence."""

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import run_dx12_contract_example as example


class ContractExampleTests(unittest.TestCase):
    def arguments(self, fixture='world-primitives'):
        return ['--fixture', fixture, '--executable', 'fixture.exe', '--root', '.',
                '--evidence', 'evidence/process', '--output', 'evidence/output', '--timeout', '17']

    def test_dispatches_each_named_fixture_to_its_strict_validator(self):
        for fixture, module in [
                ('world-primitives', 'verify_world_primitives_contract'),
                ('frame-identity', 'verify_renderer_frame_identity'),
                ('ui-theme', 'verify_ui_theme_contract'),
                ('effects', 'verify_effects_contract')]:
            with self.subTest(fixture=fixture):
                validator = Mock()
                imported = Mock(validate_outputs=validator)
                with patch.object(example.sys, 'platform', 'win32'), \
                        patch.object(example.importlib, 'import_module', return_value=imported) as load, \
                        patch.object(example.dx12_contract_process, 'run', return_value={'passed': True}) as run, \
                        patch.object(example.sys, 'stdout', io.StringIO()) as stdout:
                    self.assertEqual(example.main(self.arguments(fixture)), 0)
                load.assert_called_once_with(module)
                run.assert_called_once_with(Path('fixture.exe'), Path('.'), Path('evidence/process'),
                                            Path('evidence/output'), 17, fixture, validator)
                self.assertIn('"passed": true', stdout.getvalue())

    def test_non_windows_fails_before_import_or_execution(self):
        with patch.object(example.sys, 'platform', 'linux'), \
                patch.object(example.importlib, 'import_module') as load, \
                patch.object(example.dx12_contract_process, 'run') as run, \
                patch.object(example.sys, 'stderr', io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                example.main(self.arguments())
        self.assertEqual(error.exception.code, 1)
        load.assert_not_called()
        run.assert_not_called()

    def test_unknown_fixture_fails_before_import_or_execution(self):
        with patch.object(example.importlib, 'import_module') as load, \
                patch.object(example.dx12_contract_process, 'run') as run, \
                patch.object(example.sys, 'stderr', io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                example.main(self.arguments('unknown'))
        self.assertEqual(error.exception.code, 2)
        load.assert_not_called()
        run.assert_not_called()

    def test_runner_failures_cannot_print_success(self):
        for failure in (ValueError('wrong pixels'), OSError('missing file'),
                        subprocess.TimeoutExpired(['fixture.exe'], 17)):
            with self.subTest(failure=type(failure).__name__), \
                    patch.object(example.sys, 'platform', 'win32'), \
                    patch.object(example.importlib, 'import_module', return_value=Mock(validate_outputs=Mock())), \
                    patch.object(example.dx12_contract_process, 'run', side_effect=failure), \
                    patch.object(example.sys, 'stdout', io.StringIO()) as stdout, \
                    patch.object(example.sys, 'stderr', io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as error:
                    example.main(self.arguments())
                self.assertEqual(error.exception.code, 1)
                self.assertEqual(stdout.getvalue(), '')
                self.assertIn('DX12 contract example failed:', stderr.getvalue())

    def test_real_cli_runner_and_validators_with_synthetic_process_outputs(self):
        from test_renderer_frame_identity import build_fixture as frame_fixture
        from test_world_primitives_contract import build_fixture as world_fixture
        from test_ui_theme_contract import build_fixture as ui_fixture
        from test_effects_contract import build_fixture as effects_fixture

        for fixture, builder in [('world-primitives', world_fixture), ('frame-identity', frame_fixture),
                                 ('ui-theme', ui_fixture), ('effects', effects_fixture)]:
            for corrupt in (False, True):
                with self.subTest(fixture=fixture, corrupt=corrupt), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary).resolve()
                    reference, evidence, output = (root / name for name in ('reference', 'evidence', 'output'))
                    if fixture == 'ui-theme':
                        builder(reference, active_path=output / 'active-theme.css')
                    else:
                        builder(reference)

                    def launch(argv, **kwargs):
                        destination = Path(argv[argv.index('--output-dir') + 1])
                        shutil.copytree(reference, destination, dirs_exist_ok=True)
                        if corrupt:
                            next(destination.glob('*.png')).write_bytes(b'invalid PNG')
                        kwargs['stderr'].write(
                            b'renderer requested=dx12 backend=Dx12 adapter=Microsoft Basic Render Driver\n'
                            b'renderer dx12_shader_compiler=Fxc\n')
                        process = Mock(returncode=0)
                        process.wait.return_value = 0
                        return process

                    arguments = ['--fixture', fixture, '--executable', sys.executable, '--root', str(root),
                                 '--evidence', str(evidence), '--output', str(output)]
                    with patch.object(example.sys, 'platform', 'win32'), \
                            patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'}), \
                            patch.object(example.dx12_contract_process.subprocess, 'Popen', side_effect=launch), \
                            patch.object(example.sys, 'stdout', io.StringIO()), \
                            patch.object(example.sys, 'stderr', io.StringIO()):
                        if corrupt:
                            with self.assertRaises(SystemExit) as error:
                                example.main(arguments)
                            self.assertEqual(error.exception.code, 1)
                        else:
                            self.assertEqual(example.main(arguments), 0)
                    self.assertEqual((evidence / 'summary.json').exists(), not corrupt)
                    self.assertEqual((evidence / 'failure.json').exists(), corrupt)
                    if not corrupt:
                        summary = json.loads((evidence / 'summary.json').read_text())
                        self.assertIs(summary['passed'], True)
                        self.assertEqual(summary['fixture'], fixture)
                        self.assertEqual(summary['dx12_shader_compiler'], 'Fxc')


if __name__ == '__main__':
    unittest.main()

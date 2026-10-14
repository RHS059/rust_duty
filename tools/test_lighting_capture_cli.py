"""Backend selection is forwarded without weakening the existing lighting gate."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import verify_lighting_capture as lighting


class LightingRendererSelectionTests(unittest.TestCase):
    def capture_commands(self, renderer=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(lighting.subprocess, 'run') as run, \
                    patch.object(lighting, 'contact_sheet'):
                run.return_value = subprocess.CompletedProcess([], 0, '', '')
                lighting.capture(root / 'vector-range', root / 'captures', renderer)
            self.assertEqual(run.call_count, 12)
            self.assertTrue(all(call.kwargs['timeout'] == 60 for call in run.call_args_list))
            return [call.args[0] for call in run.call_args_list]

    def test_legacy_default_adds_no_renderer_override(self):
        for command in self.capture_commands():
            self.assertFalse(any(arg.startswith('--renderer=') for arg in command))
            self.assertIn('--capture-lighting', command)
            self.assertIn('--reference-viewport', command)

    def test_all_declared_backends_are_forwarded_to_every_pose(self):
        for renderer in lighting.RENDERERS:
            with self.subTest(renderer=renderer):
                for command in self.capture_commands(renderer):
                    self.assertEqual(command.count(f'--renderer={renderer}'), 1)
                    self.assertIn('--no-update', command)

    def test_invalid_programmatic_backend_never_starts_a_capture(self):
        with patch.object(lighting.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                lighting.capture(Path('missing'), Path('missing'), 'invented')
            run.assert_not_called()

    def test_real_cli_rejects_unknown_backend_and_missing_binary(self):
        for arguments in [
                ['unused', '--renderer=invented'],
                ['unused', '--renderer=vulkan']]:
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, str(Path(lighting.__file__)), *arguments],
                    text=True, capture_output=True, check=False)
                self.assertEqual(result.returncode, 2)
                self.assertIn('error:', result.stderr)


if __name__ == '__main__':
    unittest.main()

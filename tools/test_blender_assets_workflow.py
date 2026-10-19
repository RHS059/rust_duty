"""The reusable reload producer matches the current exporter and runtime checks."""
import contextlib
import io
from pathlib import Path
import shlex
import sys
import unittest
from unittest.mock import patch

import yaml
import build_blender_assets

ROOT = Path(__file__).resolve().parents[1]


class BlenderAssetsWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.load((ROOT / '.github/workflows/blender-assets.yml').read_text(),
                                 Loader=yaml.BaseLoader)
        cls.steps = cls.workflow['jobs']['export']['steps']

    def test_workflow_invokes_supported_exporter_cli(self):
        export = next(step for step in self.steps
                      if 'build_blender_assets.py' in step.get('run', ''))
        command = shlex.split(export['run'])
        self.assertEqual(export['if'], "steps.asset-cache.outputs.cache-hit != 'true'")
        with patch.object(sys, 'argv', command[1:]), patch.object(build_blender_assets, 'build') as build:
            with contextlib.redirect_stdout(io.StringIO()):
                build_blender_assets.main()
            build.assert_called_once_with('blender', Path('.'), Path('build-assets'))

    def test_current_parser_and_hash_checks_are_fatal_for_both_cache_paths(self):
        validation = next(step for step in self.steps
                          if 'check_generated_assets.py' in step.get('run', ''))
        self.assertEqual(validation['run'],
                         'python tools/check_generated_assets.py --kind reload --directory build-assets/reload')
        self.assertNotIn('if', validation)
        uploads = [step for step in self.steps if step.get('uses') == 'actions/upload-artifact@v4'
                   and step['with']['name'].startswith('generated-reload-runtime')]
        self.assertEqual(len(uploads), 2)
        for step in uploads:
            self.assertLess(self.steps.index(validation), self.steps.index(step))
            self.assertEqual(step['with']['if-no-files-found'], 'error')
            for name in ('asset.vra', 'asset.vrs', 'asset.vrm', 'manifest.json',
                         'export-manifest.json', 'source.json'):
                self.assertIn('build-assets/reload/' + name, step['with']['path'])
        for step in self.steps:
            self.assertNotIn('continue-on-error', step)
            for removed in ('--verify-sampler', 'sample_viewmodel_clip', 'cargo build'):
                self.assertNotIn(removed, step.get('run', ''))

    def test_export_cache_tracks_producer_and_current_validators(self):
        cache = next(step for step in self.steps if step.get('id') == 'asset-cache')
        self.assertNotIn('restore-keys', cache['with'])
        self.assertTrue(cache['with']['key'].startswith('reload-v2-'))
        for name in ('assets/source/reload/current.blend', 'assets/source/reload/source.json',
                     'tools/build_blender_assets.py', 'tools/import_fbx_viewmodel.py',
                     'tools/prone_camera_pair.py', 'tools/single_stack_fbx.py',
                     'tools/check_generated_assets.py', 'tools/package_game.py', 'tools/vr*.py',
                     '.github/actions/setup-blender/action.yml', '.github/workflows/blender-assets.yml'):
            self.assertIn("'" + name + "'", cache['with']['key'])


if __name__ == '__main__':
    unittest.main()

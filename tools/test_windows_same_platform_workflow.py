"""Static wiring guards; these tests do not execute a native renderer."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkflowTests(unittest.TestCase):
    def test_same_run_inputs_and_combined_executable(self):
        workflow = (ROOT / '.github/workflows/windows-same-platform-return.yml').read_text()
        for pack in ('reload', 'walk', 'ads', 'directional', 'jump'):
            self.assertEqual(workflow.count(f'name: generated-{pack}-runtime'), 1)
            self.assertIn(f'path: assets/{pack}', workflow)
        for forbidden in ('run-id:', 'repository:', 'github-token:', 'continue-on-error:', 'contents: write', 'workflow_dispatch:'):
            self.assertNotIn(forbidden, workflow)
        self.assertIn('--features legacy-macroquad,wgpu-runtime --bin vector-range', workflow)
        self.assertIn('--include-jump --require-generated', workflow)
        self.assertIn('--timeout 1800 --run-timeout 4500', workflow)
        self.assertIn('if: always()', workflow)
        self.assertIn('windows-same-platform-return-attempt-${{ github.run_attempt }}', workflow)
        for forbidden in ('gh release', 'release_update.py', 'create-release', 'upload-release-asset'):
            self.assertNotIn(forbidden, workflow)

    def test_caller_waits_for_all_five_current_producers_only(self):
        caller = (ROOT / '.github/workflows/build.yml').read_text()
        expected = ('  windows-same-platform-return:\n'
                    '    needs: [animation-assets, walk-assets, ads-assets, directional-assets, jump-assets]\n'
                    '    uses: ./.github/workflows/windows-same-platform-return.yml\n')
        self.assertEqual(caller.count(expected), 1)

    def test_staging_precedes_native_call_with_bounded_outer_timeout(self):
        workflow = (ROOT / '.github/workflows/windows-same-platform-return.yml').read_text()
        self.assertLess(workflow.index('New-Item -ItemType Directory -Path evidence'),
                        workflow.index('./tools/stage_windows_gl_reference.ps1'))
        self.assertLess(workflow.index('./tools/stage_windows_gl_reference.ps1'),
                        workflow.index('python tools/run_windows_same_platform_return.py'))
        self.assertIn('timeout-minutes: 100', workflow)
        self.assertIn('timeout-minutes: 76', workflow)
        self.assertNotIn('native-validation]', workflow)


if __name__ == '__main__':
    unittest.main()

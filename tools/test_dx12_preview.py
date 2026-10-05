"""Synthetic preview/provenance tests; no Windows or human playtest claim."""

import io
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import stage_dx12_preview as preview
import test_dx12_smoke as smoke_fixtures


ROOT = Path(__file__).resolve().parents[1]


class Dx12PreviewTests(unittest.TestCase):
    def setUp(self):
        # Reuse the independent complete synthetic image/telemetry fixture.
        smoke_fixtures.Dx12SmokeTests.setUpClass()
        fixture = smoke_fixtures.Dx12SmokeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root = fixture.root.resolve()
        self.binary = self.root / 'target/release/vector-range.exe'
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(b'MZ synthetic mock executable, not Windows execution')
        (self.root / 'Cargo.toml').write_text((ROOT / 'Cargo.toml').read_text())
        (self.root / 'Cargo.lock').write_bytes(b'synthetic lock fixture')
        (self.root / 'THIRD_PARTY_LICENSES.txt').write_bytes(b'synthetic notice fixture')
        inventory_path = self.root / 'tools/game-dependency-notices.json'
        inventory_path.parent.mkdir()
        inventory_path.write_text(json.dumps({
            'schema': 'rust-duty-game-dependency-notices/v1', 'target': 'x86_64-pc-windows-msvc',
            'cargo_features': {'default_enabled': True, 'explicit': ['wgpu-runtime']},
            'cargo_lock_sha256': preview.digest(self.root / 'Cargo.lock'),
            'cargo_lock_hash_policy': 'CRLF converted to LF; no other changes',
            'notice_sha256': preview.digest(self.root / 'THIRD_PARTY_LICENSES.txt'),
            'notice_bytes': (self.root / 'THIRD_PARTY_LICENSES.txt').stat().st_size,
            'preserved_baseline_caveats': []}))
        self.evidence = self.root / 'evidence/dx12-warp'
        self.evidence.mkdir(parents=True)
        fixture.captures.rename(self.evidence / 'captures')
        self.output = self.root / 'dist/preview'
        self.env = {'GITHUB_REPOSITORY': 'RHS059/rust_duty', 'GITHUB_SHA': 'a' * 40,
                    'GITHUB_RUN_ID': '80', 'GITHUB_RUN_NUMBER': '9', 'GITHUB_RUN_ATTEMPT': '2',
                    'GITHUB_REF_NAME': 'test/preview'}
        identity_line = 'renderer requested=dx12 backend=Dx12 adapter=Microsoft Basic Render Driver'
        (self.evidence / 'stdout.log').write_text('')
        (self.evidence / 'stderr.log').write_text(identity_line + '\nrenderer dx12_shader_compiler=Fxc\n')
        binary_hash = preview.digest(self.binary)
        self.write('invocation.json', {'command': preview.smoke.game_command(self.binary, self.evidence / 'captures'),
                                      'cwd': str(self.root), 'source_commit': 'a' * 40,
                                      'run_id': '80', 'run_attempt': '2', 'executable_sha256': binary_hash})
        self.write('summary.json', {'schema': 'rust-duty-dx12-warp-smoke/v1', 'passed': True,
                                   'backend': 'Dx12', 'frames': 127, 'exit_code': 0,
                                   'renderer_logs': [identity_line], 'executable_sha256': binary_hash,
                                   'adapters': ['Microsoft Basic Render Driver']})
        self.packager = patch.object(preview.package_game, 'stage', side_effect=self.fake_package).start()
        self.stamper = patch.object(preview.build_identity, 'stamp', side_effect=self.fake_stamp).start()
        self.addCleanup(patch.stopall)

    def write(self, filename, value):
        (self.evidence / filename).write_text(json.dumps(value), encoding='utf-8')

    def mutate(self, filename, field, value):
        record = json.loads((self.evidence / filename).read_text())
        record[field] = value
        self.write(filename, record)

    def fake_package(self, root, binary, destination, *, require_generated):
        self.assertTrue(require_generated)
        destination.mkdir()
        shutil.copy2(root / binary, destination / 'vector-range.exe')
        shutil.copy2(root / 'THIRD_PARTY_LICENSES.txt', destination / 'THIRD_PARTY_LICENSES.txt')
        for name in ('ui/theme.css', 'docs/UI_THEME.md', 'assets/animations.cfg'):
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('synthetic packaged resource')

    def fake_stamp(self, destination, platform, env):
        self.assertEqual(platform, 'windows')
        result = preview.build_identity.context(env)
        result['executable'] = {'sha256': preview.digest(destination / 'vector-range.exe')}
        (destination / 'BUILD_IDENTITY.json').write_text(json.dumps(result))
        return result

    def run_stage(self):
        return preview.stage(self.root, 'target/release/vector-range.exe', self.evidence, self.output, self.env)

    def test_public_stager_binds_exact_smoke_binary_and_hardware_launcher(self):
        result = self.run_stage()
        self.assertEqual(result['executable_sha256'], preview.digest(self.binary))
        self.assertIn('-DX12-Preview-Windows-x64', result['artifact_name'])
        metadata = json.loads((self.output / 'DX12_PREVIEW.json').read_text())
        self.assertEqual(metadata['source']['commit'], self.env['GITHUB_SHA'])
        self.assertEqual(metadata['enabled_features'], ['audio', 'legacy-macroquad', 'wgpu-runtime'])
        self.assertEqual(metadata['default_renderer'], 'legacy')
        self.assertEqual(metadata['smoke']['summary_sha256'], preview.digest(self.evidence / 'summary.json'))
        self.assertEqual(metadata['human_launch'], ['vector-range.exe', '--renderer=dx12', '--no-update'])
        launcher = (self.output / 'PLAYTEST_DX12.cmd').read_text()
        self.assertIn('--renderer=dx12 --no-update', launcher)
        self.assertNotIn('--force-fallback-adapter', launcher)
        self.assertIn('WIP', (self.output / 'DX12_PREVIEW_README.txt').read_text())
        self.assertTrue((self.output / 'ui/theme.css').exists())
        self.packager.assert_called_once()
        self.stamper.assert_called_once()

    def test_wrong_source_run_attempt_or_hash_never_stages(self):
        original = (self.evidence / 'invocation.json').read_text()
        for field, value in (('source_commit', 'b' * 40), ('run_id', '81'), ('run_attempt', '1'),
                             ('executable_sha256', '0' * 64), ('cwd', str(self.root / 'other')),
                             ('command', ['other-game.exe'])):
            with self.subTest(field=field):
                self.mutate('invocation.json', field, value)
                with self.assertRaises(ValueError):
                    self.run_stage()
                self.assertFalse(self.output.exists())
                (self.evidence / 'invocation.json').write_text(original)
        self.packager.assert_not_called()

    def test_invalid_success_or_summary_identity_never_stages(self):
        original = (self.evidence / 'summary.json').read_text()
        for field, value in (('passed', False), ('passed', 1), ('exit_code', 1), ('exit_code', False),
                             ('frames', 126), ('backend', 'Gl'), ('executable_sha256', '0' * 64),
                             ('renderer_logs', []), ('adapters', ['other'])):
            with self.subTest(field=field):
                self.mutate('summary.json', field, value)
                with self.assertRaises(ValueError):
                    self.run_stage()
                (self.evidence / 'summary.json').write_text(original)
        self.packager.assert_not_called()

    def test_missing_corrupt_captures_and_wrong_api_cannot_hide_behind_summary(self):
        path = self.evidence / 'captures/0000.png'
        original = path.read_bytes()
        path.unlink()
        with self.assertRaises(ValueError):
            self.run_stage()
        path.write_bytes(original[:-1])
        with self.assertRaises(ValueError):
            self.run_stage()
        path.write_bytes(original)
        sidecar = self.evidence / 'captures/0000.png.json'
        record = json.loads(sidecar.read_text())
        record['backend'] = 'Gl'
        sidecar.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            self.run_stage()
        self.packager.assert_not_called()

    def test_failure_record_and_existing_output_fail_closed(self):
        self.write('failure.json', {'passed': False})
        with self.assertRaisesRegex(ValueError, 'contains a failure'):
            self.run_stage()
        (self.evidence / 'failure.json').unlink()
        self.output.mkdir(parents=True)
        (self.output / 'sentinel').write_text('untouched')
        with self.assertRaisesRegex(ValueError, 'existing preview'):
            self.run_stage()
        self.assertEqual((self.output / 'sentinel').read_text(), 'untouched')
        self.packager.assert_not_called()

    def test_changed_packaged_executable_fails_atomically(self):
        def bad_package(*args, **kwargs):
            self.fake_package(*args, **kwargs)
            (args[2] / 'vector-range.exe').write_bytes(b'wrong binary')
        self.packager.side_effect = bad_package
        with self.assertRaisesRegex(ValueError, 'differs from the tested binary'):
            self.run_stage()
        self.assertFalse(self.output.exists())
        self.stamper.assert_not_called()

    def test_package_or_stamp_failure_never_leaves_a_preview(self):
        self.packager.side_effect = ValueError('missing generated assets')
        with self.assertRaisesRegex(ValueError, 'generated assets'):
            self.run_stage()
        self.assertFalse(self.output.exists())
        self.packager.side_effect = self.fake_package
        self.stamper.side_effect = ValueError('bad embedded build identity')
        with self.assertRaisesRegex(ValueError, 'embedded build identity'):
            self.run_stage()
        self.assertFalse(self.output.exists())

    def test_changed_feature_defaults_fail_before_staging(self):
        (self.root / 'Cargo.toml').write_text('[features]\ndefault=["wgpu-runtime"]\nwgpu-runtime=[]\n')
        with self.assertRaisesRegex(ValueError, 'feature contract'):
            self.run_stage()
        self.packager.assert_not_called()

    def test_missing_or_stale_game_notice_inventory_blocks_preview(self):
        inventory = self.root / 'tools/game-dependency-notices.json'
        original = inventory.read_bytes()
        inventory.unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.run_stage()
        inventory.write_bytes(original)
        (self.root / 'Cargo.lock').write_bytes(b'changed lock')
        with self.assertRaisesRegex(ValueError, 'stale Cargo.lock'):
            self.run_stage()
        (self.root / 'Cargo.lock').write_bytes(b'synthetic lock fixture')
        (self.root / 'THIRD_PARTY_LICENSES.txt').write_bytes(b'changed notices')
        with self.assertRaisesRegex(ValueError, 'differ from verified inventory'):
            self.run_stage()
        self.packager.assert_not_called()

    def test_python_entry_point_success_and_wrong_commit(self):
        args = ['--root', str(self.root), '--smoke-evidence', str(self.evidence), '--output', str(self.output)]
        with patch.dict(os.environ, self.env, clear=True), patch('sys.stdout', io.StringIO()):
            self.assertEqual(preview.main(args), 0)
        shutil.rmtree(self.output)
        self.mutate('invocation.json', 'source_commit', 'b' * 40)
        with patch.dict(os.environ, self.env, clear=True), patch('sys.stderr', io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                preview.main(args)
        self.assertEqual(error.exception.code, 1)
        self.assertFalse(self.output.exists())


class Dx12PreviewWorkflowTests(unittest.TestCase):
    def test_preview_reuses_smoke_binary_and_keeps_stable_aliases_separate(self):
        workflow = (ROOT / '.github/workflows/wgpu-dx12-smoke.yml').read_text()
        self.assertIn(' '.join(preview.BUILD_COMMAND), workflow)
        self.assertEqual(workflow.count('cargo build '), 1)
        self.assertNotIn('--no-default-features', workflow)
        self.assertLess(workflow.index('tools/run_dx12_smoke.py'), workflow.index('tools/stage_dx12_preview.py'))
        self.assertIn('Rust-Duty-${{ steps.identity.outputs.label }}-DX12-Preview-Windows-x64', workflow)
        self.assertNotIn('vector-range-windows-x64', workflow)
        self.assertNotIn('overwrite:', workflow)
        self.assertNotIn('publish_game_build', workflow)
        for artifact in ('reload', 'walk', 'ads', 'directional', 'jump'):
            self.assertIn(f'name: generated-{artifact}-runtime', workflow)
        self.assertNotIn('run-id:', workflow)
        self.assertNotIn('github-token:', workflow)
        caller = (ROOT / '.github/workflows/build.yml').read_text()
        preview_job = caller.split('  dx12-warp-smoke:\n')[1].split('  build:\n')[0]
        self.assertIn('needs: [animation-assets, walk-assets, ads-assets, directional-assets, jump-assets]', preview_job)
        publisher = caller.split('  publish-game-update:\n')[1]
        self.assertIn('needs: [build]', publisher)
        self.assertNotIn('dx12', publisher)


if __name__ == '__main__':
    unittest.main()

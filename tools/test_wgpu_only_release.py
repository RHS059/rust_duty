import copy
import json
from pathlib import Path
import struct
import tempfile
import tomllib
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import verify_wgpu_only_release as verify

ROOT = Path(__file__).resolve().parents[1]


def metadata():
    return {
        'packages': [
            {'id': 'game', 'name': 'vector-range', 'version': '1'},
            {'id': 'gpu', 'name': 'wgpu', 'version': '30'},
            {'id': 'hal', 'name': 'wgpu-hal', 'version': '30'},
        ],
        'resolve': {'root': 'game', 'nodes': [
            {'id': 'game', 'features': ['audio', 'default', 'wgpu-runtime'], 'deps': [{'pkg': 'gpu'}]},
            {'id': 'gpu', 'features': ['dx12', 'vulkan', 'wgsl'], 'deps': [{'pkg': 'hal'}]},
            {'id': 'hal', 'features': ['dx12', 'vulkan'], 'deps': []},
        ]},
    }


def executable():
    data = bytearray(256)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 128)
    data[128:132] = b'PE\0\0'
    struct.pack_into('<H', data, 132, 0x8664)
    return bytes(data)


def build_info():
    return {'schema': 'rust-duty-renderer-build/v1', 'wgpu_runtime': True,
            'debug_assertions': False, 'native_backends': ['dx12', 'vulkan'],
            'build_version': '0.1.12', 'build_number': '1234.1'}


class WgpuOnlyReleaseTests(unittest.TestCase):
    def test_current_manifest_requires_no_legacy_or_hidden_gles_feature(self):
        manifest = tomllib.loads((ROOT / 'Cargo.toml').read_text())
        verify.verify_manifest(manifest)
        for mutate in (
            lambda x: x['features'].update({'legacy-macroquad': []}),
            lambda x: x['features'].update({'default': ['audio']}),
            lambda x: x['dependencies']['wgpu'].update({'default-features': True}),
            lambda x: x['dependencies']['wgpu']['features'].append('gles'),
            lambda x: x['dependencies'].update({'macroquad': '0.4.14'}),
        ):
            bad = copy.deepcopy(manifest)
            mutate(bad)
            with self.assertRaises(ValueError):
                verify.verify_manifest(bad)

    def test_resolved_closure_finds_transitive_packages_and_features(self):
        self.assertEqual(len(verify.verify_metadata(metadata())), 3)
        for name in verify.FORBIDDEN_PACKAGES:
            bad = metadata()
            bad['packages'][2]['name'] = name
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'dependency'):
                verify.verify_metadata(bad)
        for feature in verify.FORBIDDEN_FEATURES:
            bad = metadata()
            bad['resolve']['nodes'][2]['features'].append(feature)
            with self.subTest(feature=feature), self.assertRaisesRegex(ValueError, 'features'):
                verify.verify_metadata(bad)

    def test_incomplete_or_wrong_feature_graph_cannot_pass(self):
        for mutate in (
            lambda x: x['resolve'].update({'root': 'absent'}),
            lambda x: x['resolve']['nodes'].pop(),
            lambda x: x['resolve']['nodes'][0].update({'features': ['wgpu-runtime']}),
            lambda x: x['resolve']['nodes'][0]['features'].append('legacy-macroquad'),
            lambda x: x['packages'][0].update({'name': 'unrelated'}),
        ):
            bad = metadata()
            mutate(bad)
            with self.assertRaises(ValueError):
                verify.verify_metadata(bad)

    def test_actual_executable_bytes_reject_ascii_and_wide_loader_markers(self):
        self.assertEqual(verify.verify_binary(executable())['sha256'], verify.digest(executable()))
        for marker in verify.BINARY_MARKERS:
            for encoding in ('ascii', 'utf-16le'):
                with self.subTest(marker=marker, encoding=encoding), self.assertRaises(ValueError):
                    verify.verify_binary(executable() + marker.upper().encode(encoding))
        for malformed in (b'', b'MZ', executable()[:132], executable().replace(b'PE\0\0', b'BAD!')):
            with self.assertRaises(ValueError):
                verify.verify_binary(malformed)

    def test_compiled_backends_require_windows_release_and_wgpu(self):
        verify.verify_build_info(build_info())
        for field, value in (('native_backends', ['dx12', 'vulkan', 'gl']),
                             ('native_backends', ['dx12']), ('wgpu_runtime', False),
                             ('debug_assertions', True), ('build_number', ''), ('schema', 'old')):
            bad = build_info()
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify.verify_build_info(bad)

    def test_entry_point_binds_binary_and_requires_both_gl_rejections(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'Cargo.toml').write_bytes((ROOT / 'Cargo.toml').read_bytes())
            (root / 'Cargo.lock').write_text('fixture lock')
            binary = root / 'game.exe'
            binary.write_bytes(executable())
            output = root / 'evidence/report.json'
            commands = []

            def command(argv, cwd):
                commands.append(argv)
                if argv[0] == 'cargo':
                    self.assertIn('--locked', argv)
                    self.assertIn(verify.TARGET, argv)
                    return json.dumps(metadata())
                if argv[0] == str(binary):
                    return json.dumps(build_info())
                return 'source-commit' if argv[0] == 'git' else 'rustc fixture'

            with patch.object(verify, 'command', side_effect=command), patch.object(
                    verify.subprocess, 'run', return_value=SimpleNamespace(
                        returncode=1, stderr=b'unknown renderer')) as rejected:
                report = verify.verify(root, binary, output)
                self.assertEqual(rejected.call_count, 2)
                self.assertEqual(report['binary']['sha256'], verify.digest(binary.read_bytes()))
                self.assertEqual(json.loads(output.read_text()), report)
            output.unlink()
            with patch.object(verify, 'command', side_effect=command), patch.object(
                    verify.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stderr=b'')):
                with self.assertRaisesRegex(ValueError, 'removed GL selection'):
                    verify.verify(root, binary, output)
            self.assertFalse(output.exists())

    def test_release_gate_is_fatal_and_precedes_artifact_and_package(self):
        import yaml
        workflow = yaml.load((ROOT / '.github/workflows/build.yml').read_text(), Loader=yaml.BaseLoader)
        steps = workflow['jobs']['build']['steps']
        index = next(i for i, step in enumerate(steps)
                     if 'tools/verify_wgpu_only_release.py' in step.get('run', ''))
        step = steps[index]
        self.assertNotIn('if', step)
        self.assertNotIn('continue-on-error', step)
        self.assertIn('--executable target/release/vector-range.exe', step['run'])
        self.assertIn('--output evidence/quality-checks/wgpu-only-release.json', step['run'])
        self.assertLess(index, next(i for i, s in enumerate(steps)
                                   if s.get('id') == 'archive_attempt_2'))
        self.assertLess(index, next(i for i, s in enumerate(steps)
                                   if 'package_game.py stage' in s.get('run', '')))


if __name__ == '__main__':
    unittest.main()

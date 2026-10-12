"""Synthetic source-bound caller controls; no renderer or native pass claimed."""
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

import revalidate_ads_offset as revalidate
import test_ads_source_visibility_binding as packet_tests
import test_aggregate_dx12_authored as fixtures
from test_capture_frame_witness import marker
from verify_render_capture import CaptureError, CaptureStructureError, verify, load_png


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + '\n')


class ImageFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_only_decoded_coverage_or_structure_errors_have_fallback_type(self):
        image = self.root / 'empty.png'
        Image.new('RGBA', (960, 540), revalidate.authored.BACKGROUND).save(image)
        with self.assertRaises(CaptureStructureError):
            verify(image, (960, 540), revalidate.authored.BACKGROUND, .01, 8, None)
        image.write_bytes(b'broken PNG')
        with self.assertRaises(CaptureError) as caught:
            verify(image, (960, 540), revalidate.authored.BACKGROUND, .01, 8, None)
        self.assertNotIsInstance(caught.exception, CaptureStructureError)
        Image.new('RGBA', (100, 100)).save(image)
        with self.assertRaises(CaptureError) as caught:
            verify(image, (960, 540), revalidate.authored.BACKGROUND, .01, 8, None)
        self.assertNotIsInstance(caught.exception, CaptureStructureError)

    def test_old_normal_image_validation_never_consults_source(self):
        folder = self.root / 'capture'
        from test_run_dx12_authored_shard import make_sequence
        make_sequence(folder, 'dx12', count=3)
        class ForbiddenFallback:
            def verify_image(self, *args, **kwargs):
                raise AssertionError('already passing images need no source gate')
        result = revalidate.shard.validate_role_images(folder, 'dx12', 3, source_visibility=ForbiddenFallback())
        self.assertEqual(result['frames'], 3)

    def test_fallback_rejects_non_rgba8_and_missing_required_source_pixel(self):
        folder = self.root / 'ads-offset'
        folder.mkdir()
        image = folder / '0000.png'
        row = dict(required_contrast_runs=[[96000, 1]], required_contrast_samples=1,
                   possible_support_runs=[[96000, 1]], possible_samples=1,
                   unsupported_clip_triangles=0, possible_support_complete=True,
                   unclassified_triangles=1, classification='potentially_visible_unresolved')
        bound = revalidate.source_binding.BoundSourcePacket()
        fallback = revalidate.AdsOffsetFallback(bound, {role: folder for role in revalidate.ROLES},
                                                 conditional_diagnostic=True)
        with patch.object(bound, 'verify_frame_binding', return_value=row):
            Image.new('RGB', (960, 540), (36,48,61)).save(image)
            with self.assertRaisesRegex(ValueError, 'actual RGBA8'):
                fallback.verify_image(image, 'dx12', 0, original_error='coverage')
            Image.new('RGBA', (960, 540), revalidate.authored.BACKGROUND).save(image)
            with self.assertRaisesRegex(ValueError, 'missing source-derived'):
                fallback.verify_image(image, 'dx12', 0, original_error='coverage')
            with self.assertRaisesRegex(ValueError, 'restricted to'):
                fallback.verify_image(self.root / 'other.png', 'dx12', 0, original_error='coverage')


class RevalidationCallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = packet_tests.BindingTests()
        cls.fixture.setUp()
        cls.addClassCleanup(cls.fixture.doCleanups)
        cls.f = f = cls.fixture
        cls.output_temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.output_temp.cleanup)
        cls.output_root = Path(cls.output_temp.name)
        cls.serial = 0
        cls.root = f.root / 'capture-root'
        generated = fixtures.make_root(cls.root)
        f.native.update({key: value for key, value in generated.items() if key not in ('source_commit', 'run_id', 'run_attempt', 'runtime_and_manifest_sha256')})
        f.packet['capture_binding'] = deepcopy(f.native)
        cls.capture = {key: f.native[key] for key in ('source_commit', 'run_id', 'run_attempt')}
        cls.verifier = {'source_commit': '2' * 40, 'run_id': '5678', 'run_attempt': '1'}
        cls.environment = {'GITHUB_SHA': cls.verifier['source_commit'], 'GITHUB_RUN_ID': '5678', 'GITHUB_RUN_ATTEMPT': '1'}
        cls.folders = {}
        for scenario in revalidate.SCENARIOS:
            folder = f.root / 'shards' / scenario
            folder.mkdir(parents=True)
            cls.folders[scenario] = folder
            for role in revalidate.ROLES:
                frames = folder / revalidate.shared.capture_paths(scenario)[role]
                fixtures.make_sequence(frames, scenario, role, f.native)
                # Full schema comes from the source/native binding fixture.
                for index in range(553):
                    for suffix in ('.gameplay.json', '.time.json'):
                        shutil.copyfile(f.frame_dirs[role] / f'{index:04}.png{suffix}', frames / f'{index:04}.png{suffix}')
                fixtures.make_logs(folder / 'logs' / f'{role}-capture', role, scenario, cls.root, folder, f.native)
                if scenario == 'ads-offset':
                    witness = revalidate.shard.role_witness_identity(f.native, scenario, role)
                    empty = Image.new('RGBA', (960, 540), revalidate.authored.BACKGROUND)
                    empty.paste(marker(0, witness).crop((0, 0, 64, 22)), (0, 0))
                    empty.save(frames / '0000.png')
                    f.invocations[role] = json.loads((folder / 'logs' / f'{role}-capture/invocation.json').read_text())
            stock = folder / 'stock-gl'
            stock.mkdir()
            (stock / 'stock-gl.png').write_bytes(fixtures.image_bytes((120, 90, 60, 255)))
            metadata = json.loads((folder / revalidate.shared.capture_paths(scenario)['windows-legacy'] / '0000.png.json').read_text())
            metadata.pop('frame_witness')
            write(stock / 'stock-gl.png.json', metadata)
            fixtures.make_logs(folder / 'logs/windows-legacy-stock-probe', 'windows-legacy', root=cls.root, evidence=folder)
            if scenario == 'ads-offset':
                shutil.copyfile(f.native_offset, folder / 'ads-offset.cfg')
                identity = revalidate.shard.role_witness_identity(f.native, scenario, 'windows-legacy')
                output = next(arg.split('=', 1)[1] for arg in f.invocations['windows-legacy']['command'] if arg.startswith('--output='))
                cap = dict(schema='rust-duty-gl-precision-receipt/v1', backend='OpenGl', platform='windows', architecture='x86_64',
                           capture_identity=identity, adapter='llvmpipe (synthetic unit fixture)', measurement_complete=True,
                           phase='capture_before_readback', subpixel={'status': 'reported', 'bits': 8},
                           shader_precision={key: {'status': 'reported', 'precision_bits': bits, 'range': [exponent, exponent]}
                              for key, bits, exponent in [('vertex_high_float', 23, 127), ('vertex_low_float', 10, 15),
                                   ('fragment_medium_float', 10, 15), ('fragment_low_float', 10, 15)]})
                target = dict(schema='rust-duty-gl-target-capture-receipt/v1', capture_identity=identity, width=960, height=540,
                              depth=True, miniquad_sample_count_parameter=0, allocation='plain_non_resolving_texture_target',
                              phase='capture_before_readback', capture_path=output + '/0000.png')
                log = folder / 'logs/windows-legacy-capture/stderr.log'
                log.write_text('renderer gl_precision_receipt=' + json.dumps(cap) + '\nrenderer gl_target_capture_receipt=' + json.dumps(target) + '\n')
            report = fixtures.summary(folder, scenario, f.native)
            if scenario == 'ads-offset':
                report.update(passed=False, status='failed')
                for row in report['checks']:
                    if row['name'].endswith(('/finite-images', '/existing-validator')) or row['name'] == 'same-windows-strict-parity':
                        row.pop('result')
                        row.update(passed=False, error='CaptureError: original foreground coverage failure, subsequent checks blocked')
                write(folder / 'summary.json', report)
        manifest = json.loads((cls.root / 'input-manifest.json').read_text())
        manifest['binding'] = f.native
        write(cls.root / 'input-manifest.json', manifest)
        f.packet['original_invocations'] = deepcopy(f.invocations)
        for role in revalidate.ROLES:
            path = f.root / f.outputs[role]
            records = [json.loads(line) for line in path.read_bytes().splitlines()]
            for row in records[1:]:
                row.update(classification='expected_empty_under_profile', unsupported_clip_triangles=0,
                           possible_support_complete=True, unclassified_triangles=0)
            data = b''.join(packet_tests.encoded(row) for row in records)
            path.write_bytes(data)
            f.receipt['backend_reports'][revalidate.source_binding.BACKENDS[role][0]]['output'] = packet_tests.digest(data)
        f.save()
        cls.receipt_hash = hashlib.sha256((f.root / 'receipt.json').read_bytes()).hexdigest()

    def call(self):
        type(self).serial += 1
        self.output = self.output_root / str(type(self).serial)
        self.processes = []
        def execute(command, root, logs, timeout, **kwargs):
            self.processes.append(command)
            logs.mkdir(parents=True)
            if Path(command[1]).name == 'verify_gameplay_ads_capture.py':
                verdict = {'schema': 'rust-duty-native-ads-capture/v1', 'passed': True, 'frames': 553}
                write(Path(command[2]) / 'verification.json', verdict)
            elif Path(command[1]).name == 'verify_ads_placement_capture.py':
                verdict = {'schema': 'rust-duty-ads-placement-capture/v1', 'passed': True, 'frames': 553}
            else:
                raise AssertionError(command)
            write(logs / 'stdout.log', verdict)
            return {'exit_code': 0}
        with patch.dict(os.environ, self.environment), patch.object(revalidate.authored, 'execute', side_effect=execute):
            return revalidate.run(input_manifest=self.root / 'input-manifest.json', gameplay_shard=self.folders['ads-gameplay'],
                                  offset_shard=self.folders['ads-offset'], source_packet=self.f.packet_path,
                                  source_receipt_sha256=self.receipt_hash, capture_rustc_sha256=self.f.expected_compiler_sha256, evidence=self.output,
                                  capture_context=self.capture, verifier_context=self.verifier, conditional_diagnostic=True)

    def test_full_bound_caller_preserves_failed_verdict_and_different_contexts(self):
        old_path = self.folders['ads-offset'] / 'summary.json'
        old = old_path.read_bytes()
        result = self.call()
        self.assertTrue(result['passed'], result.get('failure'))
        self.assertFalse(result['acceptance_complete'])
        self.assertTrue(result['conditional_diagnostic'])
        self.assertFalse(result['bounded_ads_profile_established'])
        self.assertEqual(result['capture_context'], self.capture)
        self.assertEqual(result['verifier_context'], self.verifier)
        self.assertFalse(result['original_capture_verdicts']['ads-offset']['passed'])
        self.assertEqual(old_path.read_bytes(), old)
        self.assertEqual((self.output / 'original-verdicts/ads-offset-summary.json').read_bytes(), old)
        self.assertEqual(len(self.processes), 6)
        self.assertEqual([r['frame'] for r in result['source_fallback']['dx12']], [0])
        self.assertEqual([r['frame'] for r in result['source_fallback']['windows-legacy']], [0])
        self.assertEqual(len(result['checks']), 13)

    def test_mismatched_reload_fails_before_any_validator_or_fallback(self):
        key = self.f.inputs['assets/reload/asset.vrs']
        path = self.f.root / self.f.files[key]
        old = path.read_bytes()
        path.write_bytes(old + b'changed')
        try:
            result = self.call()
            self.assertFalse(result['passed'])
            self.assertIn('source bytes', result['failure'])
            self.assertFalse(self.processes)
        finally:
            path.write_bytes(old)

    def test_original_wrong_rate_cannot_be_fixed_by_source_packet(self):
        folder = self.folders['ads-offset']
        path = folder / 'logs/dx12-capture/invocation.json'
        old = path.read_bytes()
        summary = folder / 'summary.json'
        old_summary = summary.read_bytes()
        invocation = json.loads(old)
        invocation['command'].append('--capture-hz=60')
        write(path, invocation)
        report = json.loads(old_summary)
        report['files'] = revalidate.shared.inventory_files(folder)
        write(summary, report)
        try:
            result = self.call()
            self.assertFalse(result['passed'])
            self.assertIn('changed --capture-hz=', result['failure'])
            self.assertFalse(self.processes)
        finally:
            path.write_bytes(old)
            summary.write_bytes(old_summary)

    def test_unexpected_pose_flag_and_other_offset_file_are_rejected(self):
        folder = self.folders['ads-offset']
        path = folder / 'logs/dx12-capture/invocation.json'
        old = path.read_bytes()
        report = json.loads((folder / 'summary.json').read_text())
        try:
            original = json.loads(old)
            changed = deepcopy(original)
            changed['command'].append('--reference-hfov=100')
            write(path, changed)
            with self.assertRaisesRegex(ValueError, 'exact native argv'):
                revalidate.exact_invocation(folder, report, 'dx12', 'ads-offset')
            changed = deepcopy(original)
            changed['command'] = ['--settings=C:/other/ads-offset.cfg' if arg.startswith('--settings=') else arg for arg in changed['command']]
            write(path, changed)
            with self.assertRaisesRegex(ValueError, 'unexpected original offset'):
                revalidate.exact_invocation(folder, report, 'dx12', 'ads-offset')
        finally:
            path.write_bytes(old)


if __name__ == '__main__':
    unittest.main()

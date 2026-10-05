"""Synthetic frame-identity validator proof; native Windows execution is pending.

These independently authored images/report literals describe the finalized
renderer_frame_identity.rs contract. No Cargo build, renderer, or GPU is run;
success below establishes checker discrimination, never a native DX12 pass.
"""

import copy
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from PIL import Image

import verify_renderer_frame_identity as validator


REPORT_NAME = 'renderer-frame-identity-report.json'
ADAPTER = 'Microsoft Basic Render Driver'
SCOPE = ('headless production-recorder DX12 frame identity; not authored '
         'pose-to-pixel parity, window presentation, gameplay or artistic approval')
PROVENANCE = 'require renderer initialization stderr: renderer dx12_shader_compiler=Fxc'
R, G, B = (255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)
Y, M, C = (255, 255, 0, 255), (255, 0, 255, 255), (0, 255, 255, 255)
T, K = (0, 0, 0, 0), (0, 0, 0, 255)
# Explicit per-image colors, not the validator's frame/stage generation logic.
IDENTITIES = (
    (0, 'early-target', (R, T, T, T)),
    (0, 'late-target', (R, T, T, Y)),
    (0, 'main', (R, K, K, Y)),
    (1, 'early-target', (T, T, G, T)),
    (1, 'late-target', (T, M, G, T)),
    (1, 'main', (K, M, G, K)),
    (2, 'early-target', (T, B, T, T)),
    (2, 'late-target', (T, B, C, T)),
    (2, 'main', (K, B, C, K)),
    (3, 'early-target', (T, T, T, Y)),
    (3, 'late-target', (B, T, T, Y)),
    (3, 'main', (B, K, K, Y)),
    (4, 'early-target', (M, T, T, T)),
    (4, 'late-target', (M, T, G, T)),
    (4, 'main', (M, K, G, K)),
    (5, 'early-target', (T, T, C, T)),
    (5, 'late-target', (T, T, C, R)),
    (5, 'main', (K, K, C, R)),
)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def build_fixture(output):
    """Build synthetic pixels and metadata without any validator helpers."""
    output.mkdir()
    captures = []
    for frame, stage, colors in IDENTITIES:
        background = K if stage == 'main' else T
        image = Image.new('RGBA', (65, 49), background)
        for color, box in zip(colors, ((4, 4, 27, 20), (38, 4, 61, 20),
                                       (4, 29, 27, 45), (38, 29, 61, 45))):
            image.paste(color, box)
        filename = f'frame-{frame:02}-{stage}.png'
        image.save(output / filename)
        captures.append({
            'filename': filename, 'frame': frame, 'stage': stage,
            'width': 65, 'height': 49, 'row_origin': 'top-left',
            'expected_probes': [
                [[5, 5, 26, 19], list(colors[0])],
                [[39, 5, 60, 19], list(colors[1])],
                [[5, 30, 26, 44], list(colors[2])],
                [[39, 30, 60, 44], list(colors[3])],
                [[30, 0, 35, 49], list(background)],
            ],
            'checked_pixels': 1421, 'channel_tolerance': 2,
            'other_identities_rejected': 17,
        })
    report = {
        'schema_version': 1, 'status': 'passed', 'native_execution': True,
        'requested': 'dx12', 'backend': 'Dx12', 'adapter': ADAPTER,
        'force_fallback_adapter': True, 'platform': 'windows',
        'build_version': '0.1.13', 'build_number': '8800.2',
        'compiler_provenance': PROVENANCE,
        'frame_count': 6, 'capture_count': 18, 'captures': captures,
        'cross_identity_rejections': 306, 'rechecked_after_all_submissions': True,
        'persistent_renderer': True, 'persistent_target': True, 'scope': SCOPE,
    }
    write_json(output / REPORT_NAME, report)
    return report


def png_chunk(kind, payload):
    return (struct.pack('>I', len(payload)) + kind + payload
            + struct.pack('>I', zlib.crc32(kind + payload)))


class FrameIdentitySyntheticTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name) / 'synthetic-output'
        self.report = build_fixture(self.output)
        self.environment = patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def save_report(self, report=None):
        write_json(self.output / REPORT_NAME, self.report if report is None else report)

    def reject_report(self, change, message):
        report = copy.deepcopy(self.report)
        change(report)
        self.save_report(report)
        with self.assertRaisesRegex(ValueError, message):
            validator.validate_outputs(self.output)

    def modify_image(self, index, transform):
        path = self.output / self.report['captures'][index]['filename']
        with Image.open(path) as source:
            image = source.copy()
        result = transform(image)
        (image if result is None else result).save(path)
        return path

    def assert_pixel_rejection(self):
        with self.assertRaisesRegex(ValueError, 'pixel probe|nonopaque alpha'):
            validator.validate_outputs(self.output)

    def test_complete_independent_synthetic_control(self):
        summary = validator.validate_outputs(self.output)
        self.assertEqual(summary, {
            'schema': 'rust-duty-renderer-frame-identity-validation/v1', 'passed': True,
            'backend': 'Dx12', 'adapter': ADAPTER, 'frame_count': 6,
            'capture_count': 18, 'checked_pixels': 25578, 'cross_identity_rejections': 306,
            'build_version': '0.1.13', 'build_number': '8800.2', 'scope': SCOPE,
        })
        self.assertIs(summary['passed'], True)
        json.dumps(summary, allow_nan=False)
        self.assertFalse({'fixture', 'exit_code', 'renderer_logs', 'dx12_shader_compiler',
                          'executable_sha256', 'source_commit', 'run_id', 'run_attempt',
                          'command', 'cwd', 'timeout_seconds'} & summary.keys())

    def test_reopens_every_file_and_recomputes_all_306_rejections(self):
        with patch.object(validator, '_load_rgba8', wraps=validator._load_rgba8) as load:
            with patch.object(validator, '_verify_pixels', wraps=validator._verify_pixels) as check:
                summary = validator.validate_outputs(self.output)
        self.assertEqual([call.args[0].name for call in load.call_args_list],
                         [entry['filename'] for entry in self.report['captures']])
        self.assertEqual(check.call_count, 324)
        self.assertEqual(summary['cross_identity_rejections'], 306)
        for start in range(0, 324, 18):
            calls = check.call_args_list[start:start + 18]
            self.assertEqual(len({call.args[1]['filename'] for call in calls}), 18)
            self.assertTrue(all(call.args[0] is calls[0].args[0] for call in calls))

    def test_ambiguous_pixels_fail_even_when_report_claims_306_rejections(self):
        with patch.object(validator, '_verify_pixels', return_value=1421):
            with self.assertRaisesRegex(ValueError, 'identity is ambiguous'):
                validator.validate_outputs(self.output)

    def test_missing_any_required_output_is_rejected(self):
        for path in sorted(self.output.iterdir()):
            with self.subTest(filename=path.name):
                data = path.read_bytes()
                path.unlink()
                with self.assertRaisesRegex(ValueError, 'output set differs.*missing='):
                    validator.validate_outputs(self.output)
                path.write_bytes(data)

    def test_extra_sidecar_png_log_or_subdirectory_is_rejected(self):
        for name in ('frame-00-main.png.json', 'frame-06-main.png', 'stderr.log', 'nested'):
            with self.subTest(name=name):
                path = self.output / name
                if name == 'nested':
                    path.mkdir()
                    (path / 'stale.png').write_bytes(b'stale')
                else:
                    path.write_bytes(b'extra')
                with self.assertRaisesRegex(ValueError, 'output set differs.*extra='):
                    validator.validate_outputs(self.output)
                shutil.rmtree(path) if path.is_dir() else path.unlink()

    def test_expected_filename_as_directory_is_rejected(self):
        path = self.output / 'frame-00-main.png'
        path.unlink()
        path.mkdir()
        with self.assertRaisesRegex(ValueError, 'not a regular file'):
            validator.validate_outputs(self.output)

    def test_symlinked_file_or_root_is_rejected(self):
        original = self.output / 'frame-00-main.png'
        moved = self.output.parent / 'outside.png'
        original.rename(moved)
        try:
            original.symlink_to(moved)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f'symlink capability unavailable: {error}')
        with self.assertRaisesRegex(ValueError, 'not a regular file'):
            validator.validate_outputs(self.output)
        original.unlink()
        moved.rename(original)
        linked = self.output.parent / 'linked'
        linked.symlink_to(self.output, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'real directory'):
            validator.validate_outputs(linked)

    def test_missing_or_non_directory_root_is_rejected(self):
        for path in (self.output.parent / 'missing', self.output / REPORT_NAME):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ValueError, 'real directory'):
                    validator.validate_outputs(path)

    def test_missing_or_extra_report_field_is_rejected(self):
        for key in self.report:
            with self.subTest(missing=key):
                self.reject_report(lambda report: report.pop(key), 'report fields differ')
        self.reject_report(lambda report: report.update(unexpected=True), 'report fields differ')

    def test_forged_report_values_fail_closed(self):
        changes = {
            'schema_version': 2, 'status': 'failed', 'native_execution': False,
            'requested': 'auto', 'backend': 'Vulkan', 'adapter': 'Hardware Adapter',
            'force_fallback_adapter': False, 'platform': 'linux',
            'compiler_provenance': 'renderer dx12_shader_compiler=Dxc',
            'frame_count': 5, 'capture_count': 17, 'cross_identity_rejections': 305,
            'rechecked_after_all_submissions': False, 'persistent_renderer': False,
            'persistent_target': False, 'scope': 'authored pose-to-pixel parity',
        }
        for key, value in changes.items():
            with self.subTest(field=key):
                self.reject_report(lambda report: report.update({key: value}), 'report')

    def test_scalar_json_types_are_exact(self):
        changes = {
            'schema_version': True, 'status': True, 'native_execution': 1,
            'requested': ['dx12'], 'backend': ['Dx12'], 'adapter': 1,
            'force_fallback_adapter': 1, 'platform': ['windows'],
            'compiler_provenance': [PROVENANCE], 'frame_count': 6.0,
            'capture_count': '18', 'cross_identity_rejections': 306.0,
            'rechecked_after_all_submissions': 1, 'persistent_renderer': 1,
            'persistent_target': 1, 'scope': [SCOPE],
        }
        for key, value in changes.items():
            with self.subTest(field=key):
                self.reject_report(lambda report: report.update({key: value}), 'report')

    def test_build_identity_and_adapter_must_be_nonempty_strings(self):
        for key in ('adapter', 'build_version', 'build_number'):
            for value in ('', '  \n', None, 0, [], {}):
                with self.subTest(field=key, value=value):
                    self.reject_report(lambda report: report.update({key: value}), 'report')

    def test_capture_collection_is_exact_and_ordered(self):
        changes = (
            lambda report: report.update(captures={}),
            lambda report: report['captures'].pop(),
            lambda report: report['captures'].append(copy.deepcopy(report['captures'][-1])),
            lambda report: report['captures'].reverse(),
            lambda report: report['captures'].__setitem__(1, copy.deepcopy(report['captures'][0])),
        )
        for change in changes:
            with self.subTest(change=change):
                self.reject_report(change, 'report.captures')

    def test_every_capture_field_is_required_and_extra_fields_fail(self):
        for key in self.report['captures'][0]:
            with self.subTest(missing=key):
                self.reject_report(lambda report: report['captures'][0].pop(key), 'JSON fields differ')
        self.reject_report(lambda report: report['captures'][0].update(extra='forged'),
                           'JSON fields differ')

    def test_capture_scalar_metadata_values_and_types_are_exact(self):
        changes = (
            ('filename', 'frame-01-early-target.png'), ('filename', '../frame-00-early-target.png'),
            ('frame', 1), ('frame', False), ('stage', 'main'), ('width', 64),
            ('width', 65.0), ('height', 50), ('height', '49'), ('row_origin', 'bottom-left'),
            ('checked_pixels', 1420), ('checked_pixels', 1421.0),
            ('channel_tolerance', 3), ('channel_tolerance', 2.0),
            ('other_identities_rejected', 16), ('other_identities_rejected', 17.0),
        )
        for key, value in changes:
            with self.subTest(field=key, value=value):
                self.reject_report(lambda report: report['captures'][0].update({key: value}),
                                   'report.captures')

    def test_fixed_probe_shapes_order_coordinates_colors_and_types(self):
        changes = (
            lambda probes: probes.pop(),
            lambda probes: probes.append(copy.deepcopy(probes[0])),
            lambda probes: probes.reverse(),
            lambda probes: probes.__setitem__(0, {}),
            lambda probes: probes[0].append('extra'),
            lambda probes: probes[0][0].__setitem__(0, 4),
            lambda probes: probes[0][0].__setitem__(0, 5.0),
            lambda probes: probes[0][0].__setitem__(3, 18),
            lambda probes: probes[0][1].__setitem__(0, 0),
            lambda probes: probes[0][1].__setitem__(0, 255.0),
            lambda probes: probes[0][1].__setitem__(1, False),
            lambda probes: probes[4][1].__setitem__(3, 255),
        )
        for change in changes:
            with self.subTest(change=change):
                self.reject_report(lambda report: change(report['captures'][0]['expected_probes']),
                                   'expected_probes')

    def test_duplicate_keys_nonfinite_and_malformed_json_are_rejected(self):
        clean = json.dumps(self.report)
        invalid = [
            clean.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1', 1),
            clean.replace('"width": 65', '"width": 65, "width": 65', 1),
            clean[:-1], '[]', '{}', 'null', '\ufeff' + clean,
        ]
        for value in ('NaN', 'Infinity', '-Infinity', '1e9999'):
            invalid.append(clean.replace('"frame_count": 6', f'"frame_count": {value}', 1))
        for data in invalid:
            with self.subTest(data=data[:80]):
                (self.output / REPORT_NAME).write_text(data, encoding='utf-8')
                with self.assertRaises(ValueError):
                    validator.validate_outputs(self.output)

    def test_fractional_and_exponent_notation_cannot_retype_integer_metadata(self):
        clean = json.dumps(self.report)
        for token in ('1.0', '1e0', '1.0000000000000000000000000000000000001'):
            (self.output / REPORT_NAME).write_text(
                clean.replace('"schema_version": 1', f'"schema_version": {token}', 1), encoding='utf-8')
            with self.subTest(token=token):
                with self.assertRaisesRegex(ValueError, 'JSON type differs'):
                    validator.validate_outputs(self.output)

    def test_truncation_crc_corruption_and_trailing_png_bytes_are_rejected(self):
        path = self.output / 'frame-00-early-target.png'
        original = path.read_bytes()
        corrupt = bytearray(original)
        corrupt[-1] ^= 1
        for data in (b'not a PNG', original[:-1], original[:-12], bytes(corrupt), original + b'trailing'):
            with self.subTest(size=len(data)):
                path.write_bytes(data)
                with self.assertRaisesRegex(ValueError, 'PNG'):
                    validator.validate_outputs(self.output)

    def test_wrong_extent_fails_even_with_forged_matching_report(self):
        self.modify_image(0, lambda image: image.crop((0, 0, 64, 49)))
        with self.assertRaisesRegex(ValueError, 'wrong extent'):
            validator.validate_outputs(self.output)
        self.report['captures'][0]['width'] = 64
        self.save_report()
        with self.assertRaisesRegex(ValueError, 'captures.*width'):
            validator.validate_outputs(self.output)

    def test_rgb_and_palette_png_are_not_rgba8_evidence(self):
        path = self.output / 'frame-00-early-target.png'
        original = path.read_bytes()
        for mode in ('RGB', 'P', 'L'):
            with self.subTest(mode=mode):
                path.write_bytes(original)
                self.modify_image(0, lambda image: image.convert(mode))
                with self.assertRaisesRegex(ValueError, 'not RGBA8 PNG'):
                    validator.validate_outputs(self.output)

    def test_rgba16_png_is_rejected_even_when_pillow_decodes_matching_rgba8(self):
        path = self.output / 'frame-00-early-target.png'
        with Image.open(path) as image:
            rows = b''.join(b'\x00' + b''.join(struct.pack('>4H', *(value * 257 for value in image.getpixel((x, y))))
                                               for x in range(65)) for y in range(49))
        header = struct.pack('>IIBBBBB', 65, 49, 16, 6, 0, 0, 0)
        path.write_bytes(b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', header)
                         + png_chunk(b'IDAT', zlib.compress(rows)) + png_chunk(b'IEND', b''))
        with self.assertRaisesRegex(ValueError, 'not RGBA8 PNG'):
            validator.validate_outputs(self.output)

    def test_animated_png_is_rejected(self):
        path = self.output / 'frame-00-early-target.png'
        with Image.open(path) as image:
            first = image.copy()
        second = first.copy()
        second.putpixel((0, 0), (1, 1, 1, 0))
        first.save(path, save_all=True, append_images=[second], duration=100, loop=0)
        with self.assertRaisesRegex(ValueError, 'one static PNG frame'):
            validator.validate_outputs(self.output)

    def test_previous_frame_same_stage_substitution_is_rejected(self):
        for stage in ('early-target', 'late-target', 'main'):
            for frame in range(1, 6):
                with self.subTest(frame=frame, stage=stage):
                    destination = self.output / f'frame-{frame:02}-{stage}.png'
                    original = destination.read_bytes()
                    shutil.copyfile(self.output / f'frame-{frame - 1:02}-{stage}.png', destination)
                    self.assert_pixel_rejection()
                    destination.write_bytes(original)

    def test_every_same_frame_early_late_main_substitution_is_rejected(self):
        for frame in range(6):
            for target in ('early-target', 'late-target', 'main'):
                for replacement in ('early-target', 'late-target', 'main'):
                    if target == replacement:
                        continue
                    with self.subTest(frame=frame, target=target, replacement=replacement):
                        path = self.output / f'frame-{frame:02}-{target}.png'
                        original = path.read_bytes()
                        shutil.copyfile(self.output / f'frame-{frame:02}-{replacement}.png', path)
                        self.assert_pixel_rejection()
                        path.write_bytes(original)

    def test_earlier_output_overwritten_after_success_is_reopened_and_rejected(self):
        self.assertIs(validator.validate_outputs(self.output)['passed'], True)
        shutil.copyfile(self.output / 'frame-05-main.png', self.output / 'frame-00-main.png')
        self.assert_pixel_rejection()

    def test_blank_flip_channel_and_alpha_errors_reach_pixel_guard(self):
        mutations = (
            (0, lambda image: Image.new('RGBA', image.size, T)),
            (1, lambda image: image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)),
            (1, lambda image: Image.merge('RGBA', (image.getchannel('B'), image.getchannel('G'),
                                                 image.getchannel('R'), image.getchannel('A')))),
            (0, lambda image: image.putpixel((30, 0), (0, 0, 0, 255))),
            (1, lambda image: image.putpixel((39, 5), (0, 0, 0, 3))),
            (2, lambda image: image.putpixel((0, 0), (0, 0, 0, 254))),
            (2, lambda image: image.putpixel((5, 5), (255, 0, 0, 254))),
        )
        for index, transform in mutations:
            path = self.output / self.report['captures'][index]['filename']
            original = path.read_bytes()
            with self.subTest(index=index, transform=transform):
                self.modify_image(index, transform)
                self.assert_pixel_rejection()
            path.write_bytes(original)

    def test_every_probe_including_final_boundary_pixel_is_checked(self):
        path = self.output / 'frame-00-early-target.png'
        original = path.read_bytes()
        for x, y in ((5, 5), (25, 18), (39, 5), (59, 18), (5, 30),
                     (25, 43), (39, 30), (59, 43), (30, 0), (34, 48)):
            with self.subTest(pixel=(x, y)):
                self.modify_image(0, lambda image: image.putpixel((x, y), (128, 128, 128, 128)))
                with self.assertRaisesRegex(ValueError, rf'pixel probe at \({x},{y}\)'):
                    validator.validate_outputs(self.output)
                path.write_bytes(original)

    def test_tolerance_two_passes_but_three_fails_for_rgb_and_raw_alpha(self):
        for pixel, value in (((5, 5), (253, 2, 2, 253)), ((39, 5), (2, 2, 2, 2)),
                             ((30, 0), (2, 2, 2, 2))):
            self.modify_image(0, lambda image: image.putpixel(pixel, value))
        self.assertIs(validator.validate_outputs(self.output)['passed'], True)
        path = self.output / 'frame-00-early-target.png'
        original = path.read_bytes()
        for pixel, value in (((5, 5), (252, 0, 0, 255)), ((5, 5), (255, 3, 0, 255)),
                             ((39, 5), (0, 0, 0, 3)), ((30, 0), (0, 0, 0, 3))):
            with self.subTest(pixel=pixel, value=value):
                self.modify_image(0, lambda image: image.putpixel(pixel, value))
                self.assert_pixel_rejection()
                path.write_bytes(original)

    def test_forged_probes_and_matching_wrong_pixels_cannot_redefine_contract(self):
        self.modify_image(0, lambda image: image.paste(B, (4, 4, 27, 20)))
        self.report['captures'][0]['expected_probes'][0][1] = list(B)
        self.save_report()
        with self.assertRaisesRegex(ValueError, 'expected_probes'):
            validator.validate_outputs(self.output)
        self.report['captures'][0]['expected_probes'][0][1] = list(R)
        self.save_report()
        # With producer metadata restored, rejection must reach the actual PNG.
        self.assert_pixel_rejection()

    def test_reduced_probe_or_forged_success_counts_cannot_hide_bad_pixel(self):
        self.modify_image(0, lambda image: image.putpixel((25, 18), (0, 0, 0, 0)))
        self.report['captures'][0]['expected_probes'][0][0][2:] = [25, 18]
        self.report['captures'][0]['checked_pixels'] = 1400
        self.save_report()
        with self.assertRaisesRegex(ValueError, 'expected_probes|checked_pixels'):
            validator.validate_outputs(self.output)
        self.report['captures'][0]['expected_probes'][0][0][2:] = [26, 19]
        self.report['captures'][0]['checked_pixels'] = 1421
        self.save_report()
        self.assert_pixel_rejection()

    def test_ci_build_identity_is_bound_to_this_attempt(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
            with patch('build_identity.context', return_value={
                    'version': '0.1.13', 'build_number': '8800.2'}) as context:
                self.assertIs(validator.validate_outputs(self.output)['passed'], True)
                context.assert_called_once_with()
            for identity in ({'version': '0.1.12', 'build_number': '8800.2'},
                             {'version': '0.1.13', 'build_number': '8800.1'}):
                with self.subTest(identity=identity):
                    with patch('build_identity.context', return_value=identity):
                        with self.assertRaisesRegex(ValueError, 'CI build identity'):
                            validator.validate_outputs(self.output)
            with patch('build_identity.context', side_effect=ValueError('invalid CI context')):
                with self.assertRaisesRegex(ValueError, 'invalid CI context'):
                    validator.validate_outputs(self.output)

    def test_build_context_is_not_invented_outside_github_actions(self):
        for value in ('false', '', 'TRUE', '1'):
            with self.subTest(GITHUB_ACTIONS=value):
                with patch.dict(os.environ, {'GITHUB_ACTIONS': value}):
                    with patch('build_identity.context', side_effect=AssertionError('unexpected call')):
                        self.assertIs(validator.validate_outputs(self.output)['passed'], True)


if __name__ == '__main__':
    unittest.main()

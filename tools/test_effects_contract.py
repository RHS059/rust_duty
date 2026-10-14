"""Independent synthetic controls for the effects evidence checker.

These tests never launch Cargo, a renderer or a GPU. Their images and report
literals are authored here, without using validator expectations or probes.
Passing synthetic evidence is not proof of native execution.
"""

import copy
import io
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

import verify_effects_contract as validator


REPORT_NAME = 'effects-contract-report.json'
ADAPTER = 'Microsoft Basic Render Driver'
SCOPE = ('actual muzzle_fx public draw API through facade and headless DX12; '
         'effect visibility, additive emission, expiration and subsequent '
         'normal-geometry state; not window presentation, gameplay, artistic '
         'approval or cross-backend depth parity')
INVENTORY = (
    ('barrel.png', 'barrel', 0.0),
    ('barrel-twice.png', 'barrel', 0.0),
    ('barrel-after-markers.png', 'barrel', 0.0),
    ('world-live.png', 'world-live', 0.0),
    ('world-live-after-markers.png', 'world-live', 0.0),
    ('world-aged.png', 'world-aged', 0.10000000149011612),
    ('world-aged-after-markers.png', 'world-aged', 0.10000000149011612),
    ('world-expired.png', 'world-expired', 5.0),
    ('world-expired-after-markers.png', 'world-expired', 5.0),
)
ZERO = (0, 0, 0, 0)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def build_fixture(output):
    """Create all 19 synthetic output files, independently of validator code."""
    output = Path(output)
    output.mkdir()
    captures = []
    for filename, scene, age in INVENTORY:
        image = Image.new('RGBA', (800, 600), ZERO)
        image.paste((64, 16, 32, 255), (600, 450, 740, 540))
        probes = [{'label': 'untouched-clear', 'pixel_bounds': [30, 30, 100, 100],
                   'expected_rgba': [0, 0, 0, 0], 'matching_pixels': 4900,
                   'channel_tolerance': 3}]
        if scene == 'barrel':
            twice = filename != 'barrel.png'
            image.paste((160, 80, 40, 0) if twice else (80, 40, 20, 0),
                        (390, 265, 410, 285))
            image.paste((255, 255, 255, 0) if twice else (180, 130, 250, 0),
                        (420, 280, 430, 290))
        elif scene == 'world-live':
            image.paste((80, 40, 20, 0), (450, 280, 475, 300))
        elif scene == 'world-aged':
            image.paste((29, 31, 32, 50), (410, 270, 430, 290))
            image.paste((193, 140, 61, 255), (190, 220, 202, 224))
        if filename.endswith('-after-markers.png'):
            image.paste((32, 128, 224, 255), (600, 450, 740, 540))
            probes.append({
                'label': 'normal-opaque-marker-replaces-background-and-occludes-later-far-marker',
                'pixel_bounds': [610, 460, 730, 530], 'expected_rgba': [32, 128, 224, 255],
                'matching_pixels': 8400, 'channel_tolerance': 3})
        elif scene in ('barrel', 'world-live'):
            probes.append({
                'label': 'real-effect-zero-coverage-emission',
                'pixel_bounds': [380, 250, 485, 350] if scene == 'barrel' else [445, 270, 480, 330],
                'minimum_red': 16, 'expected_alpha': 0, 'matching_pixels': 500,
                'minimum_pixels': 100 if scene == 'barrel' else 200})
            if filename == 'barrel-twice.png':
                probes.append({
                    'label': 'repeat-real-flash-adds-radiance', 'pixel_bounds': [380, 250, 485, 350],
                    'equation': 'twice.rgb = min(255, 2 * once.rgb); both alpha = 0',
                    'channel_tolerance': 3, 'checked_pixels': 10500,
                    'unsaturated_pixels': 400, 'minimum_unsaturated_pixels': 32})
        elif scene == 'world-aged':
            probes.extend([
                {'label': 'unlit-aged-smoke-associated-tint', 'pixel_bounds': [400, 255, 470, 315],
                 'source_rgb': [147, 158, 163], 'alpha_range': [20, 230],
                 'matching_pixels': 400, 'minimum_pixels': 100, 'channel_tolerance': 3},
                {'label': 'unlit-aged-casing-visible', 'pixel_bounds': [150, 160, 290, 285],
                 'expected_rgba': [193, 140, 61, 255], 'matching_pixels': 48,
                 'minimum_pixels': 8, 'channel_tolerance': 3},
            ])
        else:
            probes.append({'label': 'expired-effects-leave-no-pixels', 'checked_pixels': 466936,
                           'expected_rgba': [0, 0, 0, 0]})
        image.save(output / filename)
        metadata = {
            'schema_version': 1, 'fixture_case': scene, 'filename': filename,
            'requested': 'dx12', 'backend': 'Dx12', 'adapter': ADAPTER,
            'force_fallback_adapter': True, 'width': 800, 'height': 600,
            'row_origin': 'top-left', 'alpha_representation': 'raw-associated-emissive-rgba8',
            'diagnostic_raw_target': True, 'age_seconds': age,
            'probes': probes, 'caller_camera_model_restored': True,
        }
        write_json(output / (filename + '.json'), metadata)
        captures.append(metadata)
    report = {
        'schema_version': 1, 'status': 'passed', 'native_execution': True,
        'requested': 'dx12', 'backend': 'Dx12', 'adapter': ADAPTER,
        'platform': 'windows', 'force_fallback_adapter': True,
        'build_version': '0.1.13', 'build_number': '8800.2',
        'shot': {'time': 12.5, 'spread_degrees': 0.75, 'caliber_mm': 5.56,
                 'initial_effect_seed_u32': 3787887164, 'muzzle': [0, 1, 0],
                 'barrel_forward': [1, 0, 0], 'barrel_right': [0, 0, 1],
                 'barrel_up': [0, 1, 0], 'carrier_velocity': [0, 0, 0]},
        'camera': {'position': [0, 1, 1], 'target': [0, 1, 0],
                   'fovy_degrees': 90, 'z_near': 0.01, 'z_far': 10},
        'captures': captures, 'scope': SCOPE,
    }
    write_json(output / REPORT_NAME, report)
    return report


def png_chunk(kind, payload):
    return (struct.pack('>I', len(payload)) + kind + payload
            + struct.pack('>I', zlib.crc32(kind + payload)))


class EffectsSyntheticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.baseline.cleanup)
        cls.baseline_path = Path(cls.baseline.name) / 'baseline'
        cls.baseline_report = build_fixture(cls.baseline_path)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name) / 'synthetic-output'
        shutil.copytree(self.baseline_path, self.output)
        self.report = copy.deepcopy(self.baseline_report)
        self.environment = patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def reset(self):
        shutil.rmtree(self.output)
        shutil.copytree(self.baseline_path, self.output)
        self.report = copy.deepcopy(self.baseline_report)

    def save(self):
        write_json(self.output / REPORT_NAME, self.report)
        for (filename, _, _), capture in zip(INVENTORY, self.report['captures']):
            write_json(self.output / (filename + '.json'), capture)

    def edit(self, index, transform):
        path = self.output / self.report['captures'][index]['filename']
        with Image.open(path) as source:
            image = source.copy()
        result = transform(image)
        (image if result is None else result).save(path)

    def repair(self):
        """Repair reported statistics without validator helpers or assertions.

        A pixel failure then cannot be attributed just to an out-of-date count
        or a report/sidecar mismatch. Fixed constants remain source literals.
        """
        with Image.open(self.output / 'barrel.png') as source:
            first = source.copy()
        for entry in self.report['captures']:
            with Image.open(self.output / entry['filename']) as source:
                image = source.copy()
            for probe in entry['probes']:
                label = probe['label']
                if label == 'expired-effects-leave-no-pixels':
                    # The producer records number of checked positions, not a
                    # count of transparent pixels. Repair that statistic only.
                    probe['checked_pixels'] = 480000 - 142 * 92
                    continue
                region = list(image.crop(tuple(probe['pixel_bounds'])).getdata())
                if label == 'real-effect-zero-coverage-emission':
                    count = sum(p[0] >= 16 and p[3] == 0 for p in region)
                elif label == 'repeat-real-flash-adds-radiance':
                    probe['checked_pixels'] = len(region)
                    probe['unsaturated_pixels'] = sum(8 <= p[0] <= 100
                        for p in first.crop((380, 250, 485, 350)).getdata())
                    continue
                elif label == 'unlit-aged-smoke-associated-tint':
                    count = sum(20 <= p[3] <= 230 and p[2] > p[0]
                        and all(abs(p[c] - ((rgb * p[3] + 127) // 255)) <= 3
                                for c, rgb in enumerate((147, 158, 163))) for p in region)
                else:
                    count = sum(all(abs(a - b) <= 3 for a, b in zip(p, probe['expected_rgba']))
                                for p in region)
                probe['matching_pixels'] = count
        self.save()

    def reject(self, expression):
        with self.assertRaisesRegex(ValueError, expression):
            validator.validate_outputs(self.output)

    def test_independent_complete_control_and_content_only_summary(self):
        result = validator.validate_outputs(self.output)
        self.assertEqual(result, {
            'schema': 'rust-duty-effects-contract-validation/v1', 'passed': True,
            'backend': 'Dx12', 'adapter': ADAPTER, 'captures': 9,
            'build_version': '0.1.13', 'build_number': '8800.2', 'scope': SCOPE})
        self.assertIs(result['passed'], True)
        json.dumps(result, allow_nan=False)
        self.assertFalse({'fixture', 'exit_code', 'renderer_logs', 'dx12_shader_compiler',
                          'executable_sha256', 'source_commit', 'run_id', 'run_attempt',
                          'command', 'cwd', 'timeout_seconds'} & result.keys())

    def test_all_nine_raw_images_are_reopened_in_source_order(self):
        with patch.object(validator, '_load_rgba8', wraps=validator._load_rgba8) as load:
            validator.validate_outputs(self.output)
        self.assertEqual([call.args[0].name for call in load.call_args_list],
                         [name for name, _, _ in INVENTORY])

    def test_cli_actual_entry_point_accepts_and_rejects(self):
        stream = io.StringIO()
        with patch('sys.stdout', stream):
            self.assertEqual(validator.main([str(self.output)]), 0)
        self.assertIs(json.loads(stream.getvalue())['passed'], True)
        (self.output / 'barrel.png').unlink()
        with patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit) as error:
            validator.main([str(self.output)])
        self.assertEqual(error.exception.code, 1)

    def test_accepts_exact_minimum_effect_samples(self):
        def once(image):
            image.paste(ZERO, (380, 250, 485, 350))
            image.paste((80, 40, 20, 0), (380, 250, 412, 251))  # 32 unsaturated
            image.paste((200, 150, 130, 0), (380, 251, 448, 252))  # total 100
        def twice(image):
            image.paste(ZERO, (380, 250, 485, 350))
            image.paste((160, 80, 40, 0), (380, 250, 412, 251))
            image.paste((255, 255, 255, 0), (380, 251, 448, 252))
        def live(image):
            image.paste(ZERO, (445, 270, 480, 330))
            image.paste((16, 2, 1, 0), (450, 280, 470, 290))  # 200
        def aged(image):
            image.paste(ZERO, (400, 255, 470, 315))
            image.paste((29, 31, 32, 50), (410, 270, 420, 280))  # 100
            image.paste(ZERO, (150, 160, 290, 285))
            image.paste((193, 140, 61, 255), (190, 220, 198, 221))  # 8
        for index, transform in ((0, once), (1, twice), (3, live), (5, aged)):
            self.edit(index, transform)
        self.repair()
        self.assertIs(validator.validate_outputs(self.output)['passed'], True)

    def test_all_source_inclusive_channel_tolerance_boundaries_pass(self):
        for index in range(9):
            self.edit(index, lambda image: image.paste((3, 3, 3, 3), (30, 30, 100, 100)))
        # The expired capture additionally requires exact zeros outside marker.
        self.edit(7, lambda image: image.paste(ZERO, (30, 30, 100, 100)))
        for index in (2, 4, 6, 8):
            self.edit(index, lambda image: image.paste((35, 125, 227, 252), (610, 460, 730, 530)))
        self.edit(1, lambda image: image.putpixel((390, 265), (157, 83, 37, 0)))
        self.edit(5, lambda image: image.paste((196, 137, 64, 252), (190, 220, 202, 224)))
        self.repair()
        self.assertIs(validator.validate_outputs(self.output)['passed'], True)

    def test_invisible_double_alpha_and_nonzero_coverage_emission_fail(self):
        for index, bounds in ((0, (380, 250, 485, 350)), (3, (445, 270, 480, 330))):
            for color in (ZERO, (0, 0, 0, 100), (80, 40, 20, 1), (80, 40, 20, 128)):
                with self.subTest(index=index, color=color):
                    self.reset()
                    self.edit(index, lambda image: image.paste(color, bounds))
                    self.repair()
                    self.reject('real effect emission')

    def test_emission_minimum_99_and_199_fail_with_repaired_statistics(self):
        for index, bounds, count in ((0, (380, 250, 485, 350), 99), (3, (445, 270, 480, 330), 199)):
            self.reset()
            def paint(image):
                image.paste(ZERO, bounds)
                for n in range(count):
                    image.putpixel((bounds[0] + n % 20, bounds[1] + n // 20), (80, 40, 20, 0))
            self.edit(index, paint)
            self.repair()
            self.reject('real effect emission')

    def test_emission_red_threshold_15_fails(self):
        self.edit(3, lambda image: image.paste((15, 255, 255, 0), (445, 270, 480, 330)))
        self.repair()
        self.reject('real effect emission')

    def test_repeat_noop_is_rejected_with_matching_counts(self):
        shutil.copyfile(self.output / 'barrel.png', self.output / 'barrel-twice.png')
        self.repair()
        self.reject('did not add radiance')

    def test_repeat_equation_checks_each_rgb_channel_and_entire_region(self):
        for point in ((390, 265), (380, 250), (484, 349)):
            for channel in range(3):
                with self.subTest(point=point, channel=channel):
                    self.reset()
                    def change(image):
                        pixel = list(image.getpixel(point))
                        pixel[channel] += 4
                        image.putpixel(point, tuple(pixel))
                    self.edit(1, change)
                    self.repair()
                    self.reject('did not add radiance')

    def test_repeat_must_clip_saturated_channels_to_255(self):
        self.edit(1, lambda image: image.paste((104, 4, 244, 0), (420, 280, 430, 290)))
        self.repair()
        self.reject('did not add radiance')

    def test_repeat_requires_zero_alpha_even_on_nonemitting_samples(self):
        for index in (0, 1):
            self.reset()
            self.edit(index, lambda image: image.putpixel((484, 349), (0, 0, 0, 1)))
            self.repair()
            self.reject('changed coverage alpha')

    def test_repeat_rejects_saturated_and_31_unsaturated_vacuous_controls(self):
        for unsaturated in (0, 31):
            self.reset()
            def single(image):
                image.paste((255, 255, 255, 0), (380, 250, 485, 350))
                if unsaturated:
                    image.paste((80, 40, 20, 0), (380, 250, 380 + unsaturated, 251))
            def twice(image):
                image.paste((255, 255, 255, 0), (380, 250, 485, 350))
                if unsaturated:
                    image.paste((160, 80, 40, 0), (380, 250, 380 + unsaturated, 251))
            self.edit(0, single)
            self.edit(1, twice)
            self.repair()
            self.reject('needs 32 nontrivial unsaturated pixels')

    def test_smoke_missing_wrong_tint_unassociated_double_alpha_and_opaque_fail(self):
        for color in (ZERO, (32, 31, 29, 50), (147, 158, 163, 50),
                      (6, 6, 6, 50), (147, 158, 163, 255), (29, 31, 32, 0),
                      (11, 12, 12, 19), (133, 143, 148, 231)):
            with self.subTest(color=color):
                self.reset()
                self.edit(5, lambda image: image.paste(color, (400, 255, 470, 315)))
                self.repair()
                self.reject('aged smoke')

    def test_smoke_minimum_99_fails_with_repaired_statistics(self):
        def change(image):
            image.paste(ZERO, (400, 255, 470, 315))
            image.paste((29, 31, 32, 50), (410, 270, 421, 279))
        self.edit(5, change)
        self.repair()
        self.reject('aged smoke: 99')

    def test_smoke_alpha_endpoints_and_tint_tolerance_pass(self):
        for alpha in (20, 230):
            self.reset()
            expected = [(c * alpha + 127) // 255 for c in (147, 158, 163)]
            rgba = (expected[0], expected[1] + 3, expected[2], alpha)
            self.edit(5, lambda image: image.paste(rgba, (410, 270, 430, 290)))
            self.repair()
            self.assertIs(validator.validate_outputs(self.output)['passed'], True)

    def test_smoke_tint_tolerance_four_fails_and_blue_must_exceed_red(self):
        for color in ((29, 35, 32, 50), (12, 12, 12, 20)):
            self.reset()
            self.edit(5, lambda image: image.paste(color, (400, 255, 470, 315)))
            self.repair()
            self.reject('aged smoke')

    def test_casing_missing_wrong_tint_or_coverage_fails(self):
        for color in (ZERO, (140, 193, 61, 255), (193, 140, 61, 0),
                      (193, 140, 61, 251), (197, 140, 61, 255)):
            self.reset()
            self.edit(5, lambda image: image.paste(color, (150, 160, 290, 285)))
            self.repair()
            self.reject('aged casing')

    def test_casing_minimum_7_fails_with_repaired_statistics(self):
        def change(image):
            image.paste(ZERO, (150, 160, 290, 285))
            image.paste((193, 140, 61, 255), (190, 220, 197, 221))
        self.edit(5, change)
        self.repair()
        self.reject('aged casing: 7')

    def test_pixels_outside_fixed_effect_regions_cannot_meet_probes(self):
        for index, source, destination, message in (
            (0, (380, 250, 485, 350), (0, 200), 'real effect emission'),
            (3, (445, 270, 480, 330), (0, 200), 'real effect emission'),
            (5, (400, 255, 470, 315), (0, 200), 'aged smoke'),
            (5, (150, 160, 290, 285), (0, 200), 'aged casing'),
        ):
            self.reset()
            def move(image):
                region = image.crop(source)
                image.paste(ZERO, source)
                image.paste(region, destination)
            self.edit(index, move)
            self.repair()
            self.reject(message)

    def test_expiration_checks_each_channel_exactly_outside_exception(self):
        for point in ((598, 500), (741, 500), (650, 448), (650, 541),
                      (0, 0), (799, 599), (400, 300)):
            for channel in range(4):
                with self.subTest(point=point, channel=channel):
                    self.reset()
                    rgba = [0, 0, 0, 0]
                    rgba[channel] = 1
                    self.edit(7, lambda image: image.putpixel(point, tuple(rgba)))
                    self.repair()
                    self.reject('expired effects leave pixels')

    def test_expiration_exception_inclusive_boundary_is_allowed(self):
        for point in ((599, 449), (740, 449), (599, 540), (740, 540)):
            self.edit(7, lambda image: image.putpixel(point, (17, 83, 29, 11)))
        self.repair()
        self.assertIs(validator.validate_outputs(self.output)['passed'], True)
        self.assertEqual(self.report['captures'][7]['probes'][1]['checked_pixels'], 466936)

    def test_every_clear_probe_rejects_single_bad_pixel_each_channel(self):
        for index in range(9):
            for channel in range(4):
                with self.subTest(index=index, channel=channel):
                    self.reset()
                    color = [0, 0, 0, 0]
                    color[channel] = 4
                    self.edit(index, lambda image: image.putpixel((99, 99), tuple(color)))
                    self.repair()
                    self.reject('untouched-clear: fixed pixel probe failed')

    def test_each_after_marker_rejects_blend_depth_transform_or_target_leak(self):
        for index in (2, 4, 6, 8):
            for rgba in ((96, 144, 255, 255), (224, 32, 64, 255),
                         (64, 16, 32, 255), ZERO):
                with self.subTest(index=index, rgba=rgba):
                    self.reset()
                    self.edit(index, lambda image: image.paste(rgba, (610, 460, 730, 530)))
                    self.repair()
                    self.reject('normal-opaque-marker.*fixed pixel probe failed')

    def test_marker_checks_every_pixel_with_tolerance_three(self):
        for index in (2, 4, 6, 8):
            self.reset()
            self.edit(index, lambda image: image.putpixel((729, 529), (36, 128, 224, 255)))
            self.repair()
            self.reject('normal-opaque-marker.*fixed pixel probe failed')

    def test_report_fields_are_exact_and_required(self):
        for key in self.baseline_report:
            with self.subTest(key=key):
                self.reset()
                del self.report[key]
                write_json(self.output / REPORT_NAME, self.report)
                self.reject('report fields differ')
        self.reset()
        self.report['new_claim'] = True
        write_json(self.output / REPORT_NAME, self.report)
        self.reject('report fields differ')

    def test_report_native_dx12_warp_and_boolean_identity_is_strict(self):
        for key, values in {
            'schema_version': (True, 1.0, 2), 'status': ('failed', True),
            'native_execution': (False, 1, 'true'), 'requested': ('auto', 'Dx12'),
            'backend': ('Vulkan', 'dx12'), 'adapter': ('', 'GPU', ADAPTER.lower()),
            'platform': ('linux', 'Windows'), 'force_fallback_adapter': (False, 1),
            'scope': ('native game approval', None),
        }.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    self.reset()
                    self.report[key] = value
                    write_json(self.output / REPORT_NAME, self.report)
                    self.reject('effects report')

    def test_shot_and_camera_every_literal_is_pinned_and_typed(self):
        for section in ('shot', 'camera'):
            for key, value in self.baseline_report[section].items():
                with self.subTest(section=section, key=key):
                    self.reset()
                    self.report[section][key] = [9, 9, 9] if isinstance(value, list) else value + 1
                    write_json(self.output / REPORT_NAME, self.report)
                    self.reject('effects report.' + section)
        for section, key, value in (('shot', 'initial_effect_seed_u32', 3787887164.0),
                                    ('camera', 'z_far', 10.0), ('camera', 'z_near', '0.01')):
            self.reset()
            self.report[section][key] = value
            write_json(self.output / REPORT_NAME, self.report)
            self.reject('JSON type differs')

    def test_build_fields_must_be_nonblank_strings(self):
        for key in ('build_version', 'build_number'):
            for value in ('', '  ', None, 8800.2, True):
                self.reset()
                self.report[key] = value
                write_json(self.output / REPORT_NAME, self.report)
                self.reject('missing ' + key)

    def test_ci_build_identity_is_checked_without_cargo_execution(self):
        import build_identity
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
            with patch.object(build_identity, 'context', return_value={
                    'version': '0.1.13', 'build_number': '8800.2'}) as context:
                self.assertIs(validator.validate_outputs(self.output)['passed'], True)
                context.assert_called_once_with()
            for identity in ({'version': '0.1.14', 'build_number': '8800.2'},
                             {'version': '0.1.13', 'build_number': '8800.3'}):
                with patch.object(build_identity, 'context', return_value=identity):
                    self.reject('CI build identity')
            with patch.object(build_identity, 'context', side_effect=ValueError('invalid run identity')):
                self.reject('invalid run identity')

    def test_capture_inventory_count_order_and_report_sidecar_equality(self):
        for captures in (None, {}, [], self.baseline_report['captures'][:-1],
                         self.baseline_report['captures'] + self.baseline_report['captures'][:1]):
            self.reset()
            self.report['captures'] = captures
            write_json(self.output / REPORT_NAME, self.report)
            self.reject('all 9 ordered captures')
        self.reset()
        self.report['captures'][0], self.report['captures'][1] = self.report['captures'][1], self.report['captures'][0]
        write_json(self.output / REPORT_NAME, self.report)
        self.reject('report/sidecar')
        for index in range(9):
            self.reset()
            self.report['captures'][index]['age_seconds'] = 'changed'
            write_json(self.output / REPORT_NAME, self.report)
            self.reject('report/sidecar')

    def test_every_metadata_field_is_required_and_no_extras_are_allowed(self):
        for key in self.baseline_report['captures'][0]:
            self.reset()
            del self.report['captures'][0][key]
            self.save()
            self.reject('metadata fields differ')
        self.reset()
        self.report['captures'][0]['renderer'] = {'backend': 'Dx12'}
        self.save()
        self.reject('metadata fields differ')

    def test_metadata_literals_and_types_cannot_be_relabelled(self):
        for key, value in {
            'schema_version': True, 'fixture_case': 'world-live', 'requested': 'auto',
            'backend': 'Vulkan', 'adapter': 'hardware', 'force_fallback_adapter': 1,
            'width': 800.0, 'height': 599, 'row_origin': 'bottom-left',
            'alpha_representation': 'straight', 'diagnostic_raw_target': 1,
            'age_seconds': 0, 'caller_camera_model_restored': False,
        }.items():
            self.reset()
            self.report['captures'][0][key] = value
            self.save()
            self.reject('barrel.png')
        self.reset()
        self.report['captures'][0]['filename'] = 'world-live.png'
        # Keep the actual barrel sidecar location while repairing report equality.
        write_json(self.output / 'barrel.png.json', self.report['captures'][0])
        write_json(self.output / REPORT_NAME, self.report)
        self.reject('barrel.png.filename')

    def test_each_scene_age_is_exact_serde_value_f32_serialization(self):
        self.assertEqual(json.dumps(struct.unpack('<f', struct.pack('<f', 0.1))[0]),
                         '0.10000000149011612')
        for index, wrong in ((0, 0), (3, 0), (5, 0.1), (6, 0.1), (7, 5), (8, 4.999)):
            self.reset()
            self.report['captures'][index]['age_seconds'] = wrong
            self.save()
            self.reject('age_seconds')
        # Difference well below f64 resolution must not disappear in parsing.
        self.reset()
        for path in (self.output / REPORT_NAME, self.output / 'world-aged.png.json',
                     self.output / 'world-aged-after-markers.png.json'):
            path.write_text(path.read_text().replace('0.10000000149011612',
                            '0.100000001490116120000000000000000001'))
        self.reject('age_seconds')

    def test_all_probe_declarations_and_statistics_are_exact(self):
        # One occurrence of each probe contract, every field. Repair producer
        # report and sidecar together so declaration validation is the guard.
        for index, probe_index in ((0, 0), (0, 1), (1, 2), (2, 1), (3, 1), (5, 1), (5, 2), (7, 1)):
            baseline = self.baseline_report['captures'][index]['probes'][probe_index]
            for key, value in baseline.items():
                with self.subTest(index=index, probe=probe_index, key=key):
                    self.reset()
                    wrong = ([999] if isinstance(value, list) else
                             value + 1 if type(value) is int else 'different')
                    self.report['captures'][index]['probes'][probe_index][key] = wrong
                    self.save()
                    self.reject('probes')

    def test_probe_order_shape_missing_extra_and_typed_counts_fail(self):
        for change in (
            lambda c: c.update(probes=[]),
            lambda c: c.update(probes={}),
            lambda c: c['probes'].reverse(),
            lambda c: c['probes'].append(copy.deepcopy(c['probes'][0])),
            lambda c: c['probes'][0].pop('label'),
            lambda c: c['probes'][0].update(extra=True),
            lambda c: c['probes'][1].update(matching_pixels=500.0),
            lambda c: c['probes'][1].update(expected_alpha=False),
        ):
            self.reset()
            change(self.report['captures'][0])
            self.save()
            self.reject('probes')

    def test_every_output_is_required(self):
        for path in sorted(self.output.iterdir()):
            with self.subTest(name=path.name):
                data = path.read_bytes()
                path.unlink()
                self.reject('output set differs.*missing=')
                path.write_bytes(data)

    def test_extra_files_or_subdirectories_fail(self):
        for name in ('extra.png', 'world-aged.png.time.json', 'stderr.log', 'nested'):
            self.reset()
            path = self.output / name
            path.mkdir() if name == 'nested' else path.write_bytes(b'extra')
            self.reject('output set differs.*extra=')

    def test_output_root_and_each_file_must_be_regular_not_symlink(self):
        for path in (self.output.parent / 'missing', self.output / REPORT_NAME):
            with self.assertRaisesRegex(ValueError, 'real directory'):
                validator.validate_outputs(path)
        path = self.output / 'barrel.png'
        path.unlink()
        path.mkdir()
        self.reject('not a regular file')
        self.reset()
        original = self.output / 'barrel.png'
        target = self.output.parent / 'external.png'
        original.rename(target)
        try:
            original.symlink_to(target)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f'symlink capability unavailable: {error}')
        self.reject('not a regular file')
        alias = self.output.parent / 'alias'
        alias.symlink_to(self.output, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'real directory'):
            validator.validate_outputs(alias)

    def test_json_duplicate_nonfinite_deep_numeric_difference_and_wrong_roots_fail(self):
        for text in ('{}', '[]', 'null', '{', '{"x":NaN}', '{"x":Infinity}',
                     '{"x":1e9999}', '{"x":1,"x":2}'):
            self.reset()
            (self.output / REPORT_NAME).write_text(text)
            self.reject('capture record|non-finite|duplicate|Expecting')
        for name in (REPORT_NAME, 'barrel.png.json'):
            self.reset()
            path = self.output / name
            path.write_text(path.read_text().replace('"schema_version": 1',
                            '"schema_version": 1, "schema_version": 1'))
            self.reject('duplicate JSON field')
        self.reset()
        path = self.output / REPORT_NAME
        path.write_bytes(b'\xff')
        self.reject('decode')

    def test_png_requires_exact_extent_and_on_disk_rgba8(self):
        for mode, size in (('RGBA', (801, 600)), ('RGBA', (800, 599)),
                           ('RGB', (800, 600)), ('L', (800, 600)), ('P', (800, 600))):
            with self.subTest(mode=mode, size=size):
                self.reset()
                Image.new(mode, size).save(self.output / 'barrel.png')
                self.reject('wrong extent|raw RGBA8')
        # A valid 16-bit RGBA stream decodes to Pillow RGBA but must fail the
        # actual IHDR contract; all CRCs and compressed framing are repaired.
        ihdr = struct.pack('>IIBBBBB', 800, 600, 16, 6, 0, 0, 0)
        scanlines = (b'\x00' + b'\x00' * (800 * 8)) * 600
        data = (b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', ihdr)
                + png_chunk(b'IDAT', zlib.compress(scanlines)) + png_chunk(b'IEND', b''))
        (self.output / 'barrel.png').write_bytes(data)
        self.reject('raw RGBA8')

    def test_png_framing_crc_decode_and_static_frame_required(self):
        path = self.output / 'barrel.png'
        original = path.read_bytes()
        for data in (b'not png', original[:-1], original[:-12], original + b'extra',
                     original[:-1] + bytes([original[-1] ^ 1])):
            path.write_bytes(data)
            self.reject('PNG')
        ihdr = struct.pack('>IIBBBBB', 800, 600, 8, 6, 0, 0, 0)
        bad_decode = (b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', ihdr)
                      + png_chunk(b'IDAT', b'not zlib') + png_chunk(b'IEND', b''))
        path.write_bytes(bad_decode)
        self.reject('data|stream|image|file')
        first = Image.new('RGBA', (800, 600), (1, 0, 0, 0))
        second = Image.new('RGBA', (800, 600), (0, 1, 0, 0))
        first.save(path, save_all=True, append_images=[second], duration=10)
        self.reject('one static PNG frame')

    def test_all_pngs_get_crc_validation_even_last_capture(self):
        for filename, _, _ in INVENTORY:
            self.reset()
            path = self.output / filename
            data = path.read_bytes()
            path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
            self.reject('invalid PNG chunk CRC')


if __name__ == '__main__':
    unittest.main()

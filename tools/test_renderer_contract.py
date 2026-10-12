"""Synthetic source-schema fixtures and process mocks; never Windows execution.

The literal cases, pixels, metadata and ordering below are independent of the
validator. They describe examples/renderer_contract.rs at renderer PR 44's
428cd2a head plus the renderer owner's named-target orientation extension.
No Cargo command or renderer process is executed by this suite.
"""

import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import run_renderer_contract as contract


REPORT_NAME = 'renderer-contract-report.json'
ADAPTER = 'Microsoft Basic Render Driver'
OPAQUE = 'opaque-rgba8-rgb-preserved-over-black'
ASSOCIATED = 'raw-associated-emissive-rgba8'
IDENTITY_LOG = f'renderer requested=dx12 backend=Dx12 adapter={ADAPTER}\n'
COMPILER_LOG = 'renderer dx12_shader_compiler=Fxc\n'
GOOD_LOG = IDENTITY_LOG + COMPILER_LOG
BLOCKED_PARENT = b'This regular file intentionally blocks PNG parent creation.\n'
SCOPE = ('headless DX12 renderer contract; not window presentation, native DPI, '
         'gameplay, performance or artistic approval')


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def probe(label, bounds, rgba):
    return {'label': label, 'normalized_bounds': bounds, 'expected_rgba': rgba,
            'minimum_match_fraction': 0.9, 'channel_tolerance': 8}


def solid_probe(rgba):
    return [probe('solid interior', [0.1, 0.9, 0.1, 0.9], rgba)]


def image_statistics(image, metadata):
    """Populate producer statistics, without importing any validator helpers."""
    width, height = image.size
    nonblack = sum(any(pixel[:3]) for pixel in image.getdata())
    metadata['coverage'] = {'nonblack_pixels': nonblack,
                            'total_pixels': width * height,
                            'nonblack_fraction': nonblack / (width * height)}
    for item in metadata['probes']:
        x0, x1, y0, y1 = item['normalized_bounds']
        left, right = int(x0 * width), int(x1 * width)
        top, bottom = int(y0 * height), int(y1 * height)
        count = (right - left) * (bottom - top)
        matched = sum(all(abs(a - b) <= 8 for a, b in
                          zip(image.getpixel((x, y)), item['expected_rgba']))
                      for y in range(top, bottom) for x in range(left, right))
        item.update(pixel_bounds=[left, right, top, bottom],
                    matching_pixels=matched, total_pixels=count,
                    match_fraction=matched / count)


def build_fixture(output):
    """Write all 21 renderer-owned contract cases with synthetic pixels."""
    output.mkdir(parents=True, exist_ok=True)
    records = []

    def capture(filename, case, image, alpha=OPAQUE, probes=None, extra=None):
        width, height = image.size
        metadata = {
            'schema_version': 1, 'fixture_case': case, 'filename': filename,
            'requested': 'dx12', 'backend': 'Dx12', 'adapter': ADAPTER,
            'renderer': {'requested': 'dx12', 'backend': 'Dx12', 'adapter': ADAPTER},
            'force_fallback_adapter': True, 'alpha_representation': alpha,
            'diagnostic_raw_target': alpha == ASSOCIATED, 'row_origin': 'top-left',
            'size': {'width': width, 'height': height}, 'width': width, 'height': height,
            'probes': probes or [], 'extra': extra,
        }
        image_statistics(image, metadata)
        image.save(output / filename)
        write_json(output / (filename + '.json'), metadata)
        records.append(metadata)

    for filename, case, size in [
            ('quadrant.png', 'orientation-quadrants', (96, 64)),
            ('readback-width-65.png', 'readback-width-65', (65, 49))]:
        width, height = size
        image = Image.new('RGBA', size)
        for y in range(height):
            for x in range(width):
                colors = ((255, 0, 0, 255), (0, 255, 0, 255),
                          (0, 0, 255, 255), (255, 255, 0, 255))
                image.putpixel((x, y), colors[2 * (y >= height / 2) + (x >= width / 2)])
        capture(filename, case, image, probes=[
            probe('top-left red', [0.1, 0.4, 0.1, 0.4], [255, 0, 0, 255]),
            probe('top-right green', [0.6, 0.9, 0.1, 0.4], [0, 255, 0, 255]),
            probe('bottom-left blue', [0.1, 0.4, 0.6, 0.9], [0, 0, 255, 255]),
            probe('bottom-right yellow', [0.6, 0.9, 0.6, 0.9], [255, 255, 0, 255]),
        ], extra={'row_padding_required': width == 65})

    # The raw capture and sampled-main capture retain the same unchanged target.
    with Image.open(output / 'quadrant.png') as original:
        target = original.copy()
    for filename, case, alpha, stage in [
            ('quadrant-target.png', 'orientation-named-target-raw', ASSOCIATED, 'raw-target'),
            ('quadrant-target-composite.png', 'orientation-named-target-composite', OPAQUE, 'sampled-main')]:
        capture(filename, case, target, alpha=alpha,
                probes=copy.deepcopy(records[0]['probes']),
                extra={'orientation_group': 'named-target-to-main', 'stage': stage})

    for filename, case, rgba, checkpoint in [
            ('ordered-a-red.png', 'same-submission-checkpoint-a', [255, 0, 0, 255], 0),
            ('ordered-b-green.png', 'same-submission-checkpoint-b', [0, 255, 0, 255], 1)]:
        capture(filename, case, Image.new('RGBA', (96, 64), tuple(rgba)),
                probes=solid_probe(rgba),
                extra={'submission_group': 'red-then-green', 'checkpoint': checkpoint})

    for filename, case, rgba, alpha in [
            ('depth-main-near.png', 'near-surface-occludes-far', [255, 0, 0, 255], OPAQUE),
            ('depth-target-near.png', 'camera-selects-named-target', [0, 0, 255, 255], ASSOCIATED),
            ('depth-target-reset.png', 'named-target-clear-resets-depth', [255, 255, 0, 255], ASSOCIATED),
            ('depth-main-preserved.png', 'named-target-clear-preserves-main', [255, 0, 0, 255], OPAQUE),
            ('depth-main-reset.png', 'main-clear-resets-depth', [0, 255, 0, 255], OPAQUE),
            ('depth-disabled.png', 'screen-camera-disables-depth', [0, 0, 255, 255], OPAQUE)]:
        capture(filename, case, Image.new('RGBA', (96, 64), tuple(rgba)),
                alpha=alpha, probes=solid_probe(rgba))

    for filename, case, alpha, colors in [
            ('alpha-target.png', 'raw-associated-and-emissive-target', ASSOCIATED,
             [[127, 127, 127, 127], [127, 0, 0, 0], [0, 0, 0, 0]]),
            ('alpha-main-display.png', 'main-capture-flattens-coverage-preserving-emission', OPAQUE,
             [[127, 127, 127, 255], [127, 0, 0, 255], [0, 0, 0, 255]]),
            ('alpha-composite.png', 'target-composited-over-opaque-black', OPAQUE,
             [[127, 127, 127, 255], [127, 0, 0, 255], [0, 0, 0, 255]]),
            ('alpha-tinted-composite.png', 'target-tint-opacity-scales-associated-rgb', OPAQUE,
             [[32, 16, 63, 255], [32, 0, 0, 255], [0, 0, 0, 255]])]:
        image = Image.new('RGBA', (96, 64))
        for x0, color in zip((0, 32, 64), colors):
            image.paste(tuple(color), (x0, 0, x0 + 32, 64))
        capture(filename, case, image, alpha=alpha, probes=[
            probe('half-alpha white', [0.1, 0.25, 0.1, 0.9], colors[0]),
            probe('red emission with zero coverage', [0.4, 0.6, 0.1, 0.9], colors[1]),
            probe('transparent untouched region', [0.75, 0.9, 0.1, 0.9], colors[2]),
        ], extra={'vertex_alpha_u8': 127})

    for filename, case, rgba in [
            ('alpha-clear.png', 'clear-associates-straight-color', [128, 128, 128, 128]),
            ('alpha-opaque-source.png', 'opaque-replacement-associates-straight-source',
             [127, 127, 127, 127])]:
        capture(filename, case, Image.new('RGBA', (96, 64), tuple(rgba)),
                alpha=ASSOCIATED, probes=solid_probe(rgba))

    for scale, filename in [(1, 'text-100-percent.png'), (2, 'text-200-percent.png')]:
        image = Image.new('RGBA', (64 * scale, 48 * scale), (0, 0, 0, 255))
        # The renderer contract checks ink bounds, not the shape of these glyphs.
        # A rectangle is intentionally sufficient synthetic data for that boundary.
        ImageDraw.Draw(image).rectangle((11 * scale, 12 * scale,
                                        23 * scale - 1, 23 * scale - 1), fill='white')
        capture(filename, 'physical-pixel-text-rasterization', image, extra={
            'dpi_percent': 100 * scale, 'font_size_physical_px': 16.0 * scale,
            'text': 'Ag', 'measured_with_trailing_space': 'Ag ',
            'metrics': {'width': 21.0 * scale, 'height': 11.0 * scale, 'offset_y': 8.0 * scale},
            'ink_bounds_exclusive': [11 * scale, 12 * scale, 23 * scale, 23 * scale],
            'claim': 'raster dimensions only; no font-style or OS-DPI claim',
        })

    (output / 'blocked-parent').write_bytes(BLOCKED_PARENT)
    (output / 'capture-is-directory.png').mkdir()
    capture('after-errors.png', 'renderer-recovers-after-rejected-captures',
            Image.new('RGBA', (16, 16), (0, 255, 0, 255)),
            probes=solid_probe([0, 255, 0, 255]))
    failures = [
        {'expected_error': 'create capture directory',
         'actual_error': 'create capture directory blocked-parent: synthetic filesystem failure'},
        {'expected_error': 'write capture',
         'actual_error': 'write capture capture-is-directory.png: synthetic filesystem failure'},
        {'expected_error': 'capture path must not be empty',
         'actual_error': 'capture path must not be empty'},
        {'expected_error': 'non-finite', 'actual_error': 'mesh has non-finite position'},
    ]
    # These fields model the producer's report. The tests do not claim its mocked
    # native_execution/platform values are evidence of a real Windows execution.
    report = {
        'schema_version': 1, 'status': 'passed', 'native_execution': True,
        'requested': 'dx12', 'backend': 'Dx12', 'adapter': ADAPTER,
        'force_fallback_adapter': True, 'platform': 'windows',
        'build_version': '0.1.11', 'build_number': '0',
        'captures': records, 'expected_failures': failures, 'scope': SCOPE,
    }
    write_json(output / REPORT_NAME, report)
    return report


class RendererContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.reference = Path(cls.temporary.name).resolve() / 'synthetic-reference'
        build_fixture(cls.reference)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        # Windows tempfile paths can contain an 8.3 alias. Match run()'s resolve.
        self.root = Path(temporary.name).resolve()
        self.output = self.root / 'synthetic-output'
        shutil.copytree(self.reference, self.output)
        # Synthetic build identity must not inherit the real CI run's identity.
        environment = patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'})
        environment.start()
        self.addCleanup(environment.stop)

    def reset(self):
        shutil.rmtree(self.output)
        shutil.copytree(self.reference, self.output)

    def report(self):
        return json.loads((self.output / REPORT_NAME).read_text(encoding='utf-8'))

    def edit_report(self, edit):
        report = self.report()
        edit(report)
        write_json(self.output / REPORT_NAME, report)

    def metadata(self, name):
        return json.loads((self.output / (name + '.json')).read_text(encoding='utf-8'))

    def edit_metadata(self, name, edit, mirror=True):
        metadata = self.metadata(name)
        edit(metadata)
        write_json(self.output / (name + '.json'), metadata)
        if mirror:
            def update(report):
                index = next(i for i, item in enumerate(report['captures'])
                             if item['filename'] == name)
                report['captures'][index] = copy.deepcopy(metadata)
            self.edit_report(update)

    def update_image(self, name, edit):
        with Image.open(self.output / name) as original:
            image = original.copy()
        changed = edit(image)
        if changed is not None:
            image = changed
        image.save(self.output / name)
        self.edit_metadata(name, lambda record: image_statistics(image, record))

    def assert_invalid(self):
        with self.assertRaises((ValueError, OSError)):
            contract.validate_outputs(self.output)

    @staticmethod
    def call_main(argv):
        # Both returning an exit code and argparse's SystemExit are CLI exits.
        try:
            return contract.main(argv)
        except SystemExit as error:
            return error.code

    def process(self, log=GOOD_LOG, modify=None, returncode=0):
        def fake(command, **kwargs):
            destination = Path(command[command.index('--output-dir') + 1])
            shutil.copytree(self.output, destination, dirs_exist_ok=True)
            if modify:
                modify(destination)
            kwargs['stderr'].write(log.encode('utf-8'))
            kwargs['stdout'].write(b'DX12 renderer contract passed (synthetic process mock)\n')
            return subprocess.CompletedProcess(command, returncode)
        return fake

    def test_full_source_schema_control(self):
        result = contract.validate_outputs(self.output)
        self.assertTrue(result['passed'])
        self.assertEqual(result['captures'], 21)
        self.assertEqual(len(self.report()['captures']), 21)
        self.assertEqual(len(list(self.output.iterdir())), 45)
        self.assertEqual([item['filename'] for item in self.report()['captures'][:6]], [
            'quadrant.png', 'readback-width-65.png', 'quadrant-target.png',
            'quadrant-target-composite.png', 'ordered-a-red.png', 'ordered-b-green.png'])
        self.assertEqual(len(self.report()['expected_failures']), 4)
        self.assertEqual((self.output / 'blocked-parent').read_bytes(), BLOCKED_PARENT)
        self.assertEqual(list((self.output / 'capture-is-directory.png').iterdir()), [])

    def test_every_png_sidecar_and_report_is_required(self):
        paths = [self.output / REPORT_NAME]
        paths += [self.output / (item['filename'] + suffix)
                  for item in self.report()['captures'] for suffix in ('', '.json')]
        for path in paths:
            with self.subTest(path=path.name):
                data = path.read_bytes()
                path.unlink()
                self.assert_invalid()
                path.write_bytes(data)

    def test_report_identity_and_proof_flags_are_required(self):
        mutations = [('schema_version', 2), ('status', 'failed'),
                     ('native_execution', False), ('native_execution', 1),
                     ('requested', 'auto'), ('backend', 'Vulkan'),
                     ('backend', 'DX12'), ('adapter', 'NVIDIA GeForce'),
                     ('adapter', ''), ('force_fallback_adapter', False),
                     ('platform', 'linux'), ('scope', 'artistic approval')]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                self.reset()
                self.edit_report(lambda record: record.update({field: value}))
                self.assert_invalid()

    def test_report_captures_cannot_be_missing_duplicated_or_reordered(self):
        for mutation in (lambda items: items.pop(),
                         lambda items: items.append(copy.deepcopy(items[0])),
                         lambda items: items.reverse(),
                         lambda items: items.__setitem__(3, copy.deepcopy(items[2]))):
            self.reset()
            self.edit_report(lambda record: mutation(record['captures']))
            self.assert_invalid()

    def test_altered_sidecar_disagrees_with_report(self):
        self.edit_metadata('quadrant.png', lambda record: record.update(adapter='other'), mirror=False)
        self.assert_invalid()

    def test_consistently_forged_metadata_still_fails_fixed_contract(self):
        changes = [('fixture_case', 'other-case'), ('requested', 'auto'),
                   ('backend', 'Vulkan'), ('adapter', 'WARP'),
                   ('renderer', {'requested': 'dx12', 'backend': 'Vulkan', 'adapter': ADAPTER}),
                   ('force_fallback_adapter', False), ('row_origin', 'bottom-left'),
                   ('width', 95), ('size', {'width': 95, 'height': 64}),
                   ('diagnostic_raw_target', True), ('alpha_representation', ASSOCIATED),
                   ('extra', {'row_padding_required': True})]
        for field, value in changes:
            with self.subTest(field=field):
                self.reset()
                self.edit_metadata('quadrant.png', lambda record: record.update({field: value}))
                self.assert_invalid()

    def test_duplicate_keys_and_nonfinite_json_are_rejected(self):
        path = self.output / REPORT_NAME
        original = path.read_text(encoding='utf-8')
        for bad in ('{', '[]', '{}', original.replace('"schema_version": 1',
                    '"schema_version": 1, "schema_version": 1', 1),
                    original.replace('"schema_version": 1', '"schema_version": NaN', 1),
                    original.replace('"schema_version": 1', '"schema_version": 1e9999', 1)):
            with self.subTest(prefix=bad[:50]):
                path.write_text(bad, encoding='utf-8')
                self.assert_invalid()
        path.write_text(original, encoding='utf-8')

    def test_truncated_and_non_png_files_fail(self):
        path = self.output / 'readback-width-65.png'
        data = path.read_bytes()
        for broken in (b'not a PNG', data[:64], data[:-1], data[:-12]):
            with self.subTest(length=len(broken)):
                path.write_bytes(broken)
                self.assert_invalid()

    def test_wrong_extent_or_rgb_format_fails(self):
        for mode, size in [('RGBA', (64, 49)), ('RGB', (65, 49))]:
            with self.subTest(mode=mode, size=size):
                self.reset()
                Image.new(mode, size, 'red').save(self.output / 'readback-width-65.png')
                self.assert_invalid()

    def test_extra_capture_or_telemetry_is_rejected(self):
        for name in ('unused.png', 'quadrant.png.time.json', 'stdout.log', 'summary.json'):
            with self.subTest(name=name):
                path = self.output / name
                path.write_bytes(b'extraneous')
                self.assert_invalid()
                path.unlink()

    def test_width65_vertical_flip_and_channel_swap_fail(self):
        for mutate in (lambda image: image.transpose(Image.Transpose.FLIP_TOP_BOTTOM),
                       lambda image: Image.merge('RGBA', (image.getchannel('B'), image.getchannel('G'),
                                                         image.getchannel('R'), image.getchannel('A')))):
            self.reset()
            self.update_image('readback-width-65.png', mutate)
            self.assert_invalid()

    def test_named_target_composite_vertical_flip_fails_with_valid_raw_target(self):
        raw = self.output / 'quadrant-target.png'
        raw_pixels = raw.read_bytes()
        raw_metadata = self.metadata(raw.name)
        composite = 'quadrant-target-composite.png'
        self.assertEqual(raw_pixels, (self.output / composite).read_bytes())
        self.assertTrue(contract.validate_outputs(self.output)['passed'])

        # Repair producer statistics/report so only the sampled pixel orientation
        # is wrong; valid raw-target evidence must not bless a flipped composite.
        self.update_image(composite, lambda image: image.transpose(Image.Transpose.FLIP_TOP_BOTTOM))
        self.assertEqual(raw.read_bytes(), raw_pixels)
        self.assertEqual(self.metadata(raw.name), raw_metadata)
        with self.assertRaisesRegex(ValueError,
                                    r'quadrant-target-composite\.png: pixel probe top-left red failed'):
            contract.validate_outputs(self.output)

    def test_named_target_raw_orientation_is_independently_checked(self):
        self.update_image('quadrant-target.png',
                          lambda image: image.transpose(Image.Transpose.FLIP_TOP_BOTTOM))
        with self.assertRaisesRegex(ValueError,
                                    r'quadrant-target\.png: pixel probe top-left red failed'):
            contract.validate_outputs(self.output)

    def test_named_target_stages_and_alpha_metadata_cannot_be_forged(self):
        for name in ('quadrant-target.png', 'quadrant-target-composite.png'):
            metadata = self.metadata(name)
            mutations = [
                ('fixture_case', 'orientation-quadrants'),
                ('alpha_representation', OPAQUE if metadata['diagnostic_raw_target'] else ASSOCIATED),
                ('diagnostic_raw_target', not metadata['diagnostic_raw_target']),
                ('extra', dict(metadata['extra'], orientation_group='other-target')),
                ('extra', dict(metadata['extra'], stage='sampled-main' if name == 'quadrant-target.png' else 'raw-target')),
            ]
            for field, value in mutations:
                with self.subTest(name=name, field=field):
                    self.reset()
                    self.edit_metadata(name, lambda record: record.update({field: value}))
                    self.assert_invalid()

    def test_swapped_ordered_red_green_checkpoints_fail(self):
        self.update_image('ordered-a-red.png',
                          lambda image: Image.new('RGBA', image.size, (0, 255, 0, 255)))
        self.update_image('ordered-b-green.png',
                          lambda image: Image.new('RGBA', image.size, (255, 0, 0, 255)))
        self.assert_invalid()

    def test_swapped_checkpoint_metadata_fails_without_image_change(self):
        self.edit_metadata('ordered-a-red.png', lambda record: record['extra'].update(checkpoint=1))
        self.assert_invalid()

    def test_each_depth_checkpoint_is_independently_checked(self):
        for name in ('depth-main-near.png', 'depth-target-near.png', 'depth-target-reset.png',
                     'depth-main-preserved.png', 'depth-main-reset.png', 'depth-disabled.png'):
            with self.subTest(name=name):
                self.reset()
                self.update_image(name, lambda image: Image.new('RGBA', image.size, (255, 0, 255, 255)))
                self.assert_invalid()

    def test_double_alpha_and_lost_emission_fail(self):
        for name, box, rgba in [
                ('alpha-target.png', (0, 0, 32, 64), (255, 255, 255, 127)),
                ('alpha-main-display.png', (0, 0, 32, 64), (63, 63, 63, 255)),
                ('alpha-composite.png', (0, 0, 32, 64), (63, 63, 63, 255)),
                ('alpha-target.png', (32, 0, 64, 64), (0, 0, 0, 0)),
                ('alpha-main-display.png', (32, 0, 64, 64), (0, 0, 0, 255)),
                ('alpha-composite.png', (32, 0, 64, 64), (0, 0, 0, 255))]:
            with self.subTest(name=name, rgba=rgba):
                self.reset()
                self.update_image(name, lambda image: image.paste(rgba, box))
                self.assert_invalid()

    def test_tint_and_opacity_mistakes_fail(self):
        for rgba in ((63, 31, 127, 255), (16, 8, 32, 255), (32, 63, 16, 255)):
            with self.subTest(rgba=rgba):
                self.reset()
                self.update_image('alpha-tinted-composite.png',
                                  lambda image: image.paste(rgba, (0, 0, 32, 64)))
                self.assert_invalid()

    def test_opaque_alpha_is_checked_outside_probe_regions(self):
        self.update_image('quadrant.png', lambda image: image.putpixel((0, 0), (255, 0, 0, 254)))
        self.assert_invalid()

    def test_raw_associated_alpha_is_checked(self):
        for name in ('alpha-clear.png', 'alpha-opaque-source.png'):
            with self.subTest(name=name):
                self.reset()
                self.update_image(name, lambda image: image.putalpha(255))
                self.assert_invalid()

    def test_forged_probe_goldens_cannot_bless_wrong_pixels(self):
        self.update_image('ordered-a-red.png',
                          lambda image: Image.new('RGBA', image.size, (0, 255, 0, 255)))
        def forge(record):
            record['probes'][0]['expected_rgba'] = [0, 255, 0, 255]
            with Image.open(self.output / 'ordered-a-red.png') as image:
                image_statistics(image, record)
        self.edit_metadata('ordered-a-red.png', forge)
        self.assert_invalid()

    def test_forged_probe_bounds_tolerance_and_counts_fail(self):
        changes = [('normalized_bounds', [0.0, 1.0, 0.0, 1.0]),
                   ('pixel_bounds', [0, 96, 0, 64]), ('channel_tolerance', 255),
                   ('minimum_match_fraction', 0), ('matching_pixels', 0),
                   ('total_pixels', 1), ('match_fraction', 0), ('label', 'different')]
        for field, value in changes:
            with self.subTest(field=field):
                self.reset()
                self.edit_metadata('ordered-a-red.png',
                                   lambda record: record['probes'][0].update({field: value}))
                self.assert_invalid()

    def test_tolerance_boundary_and_ninety_percent_threshold(self):
        name = 'ordered-a-red.png'
        self.update_image(name, lambda image: Image.new('RGBA', image.size, (247, 8, 8, 255)))
        self.assertTrue(contract.validate_outputs(self.output)['passed'])
        self.update_image(name, lambda image: Image.new('RGBA', image.size, (246, 8, 8, 255)))
        self.assert_invalid()
        for bad_count, passed in [(392, True), (393, False)]:
            self.reset()
            def edit(image):
                for index in range(bad_count):
                    image.putpixel((9 + index % 77, 6 + index // 77), (0, 0, 255, 255))
            self.update_image(name, edit)
            with self.subTest(bad_pixels=bad_count):
                if passed:
                    self.assertTrue(contract.validate_outputs(self.output)['passed'])
                else:
                    self.assert_invalid()

    def test_coverage_is_recomputed_not_trusted(self):
        for field, value in [('nonblack_pixels', 1), ('total_pixels', 1), ('nonblack_fraction', 0.5)]:
            self.reset()
            self.edit_metadata('quadrant.png', lambda record: record['coverage'].update({field: value}))
            self.assert_invalid()

    def test_text_ink_bounds_at_both_scales_fail_on_extra_pixel(self):
        for name in ('text-100-percent.png', 'text-200-percent.png'):
            with self.subTest(name=name):
                self.reset()
                self.update_image(name, lambda image: image.putpixel((0, 0), (255, 255, 255, 255)))
                self.assert_invalid()

    def test_text_metrics_and_bounds_cannot_be_forged_consistently(self):
        for field, value in [('dpi_percent', 101), ('font_size_physical_px', 15.0),
                             ('ink_bounds_exclusive', [0, 0, 64, 48]),
                             ('metrics', {'width': 22.0, 'height': 11.0, 'offset_y': 8.0}),
                             ('measured_with_trailing_space', 'Ag')]:
            self.reset()
            self.edit_metadata('text-100-percent.png', lambda record: record['extra'].update({field: value}))
            self.assert_invalid()

    def test_missing_or_malformed_expected_error_records_fail(self):
        valid = self.report()['expected_failures']
        for bad in ([], valid[:-1], valid + [valid[0]], list(reversed(valid)),
                    [{'expected_error': item['expected_error'], 'actual_error': ''} for item in valid],
                    [{'expected_error': item['expected_error'], 'actual_error': 'wrong failure'} for item in valid],
                    [dict(valid[0], unexpected=True)] + valid[1:],
                    [{'expected_error': valid[0]['expected_error']}] + valid[1:]):
            self.reset()
            self.edit_report(lambda record: record.update(expected_failures=bad))
            self.assert_invalid()

    def test_expected_failure_filesystem_entries_are_required(self):
        for name in ('blocked-parent', 'capture-is-directory.png'):
            with self.subTest(name=name):
                self.reset()
                path = self.output / name
                path.rmdir() if path.is_dir() else path.unlink()
                self.assert_invalid()

    def test_expected_failure_entry_types_and_contents_are_checked(self):
        for mutation in ('blocked-is-directory', 'blocked-wrong-text', 'capture-is-file', 'capture-not-empty'):
            with self.subTest(mutation=mutation):
                self.reset()
                blocked = self.output / 'blocked-parent'
                directory = self.output / 'capture-is-directory.png'
                if mutation == 'blocked-is-directory':
                    blocked.unlink()
                    blocked.mkdir()
                elif mutation == 'blocked-wrong-text':
                    blocked.write_text('unrelated stale file', encoding='utf-8')
                elif mutation == 'capture-is-file':
                    directory.rmdir()
                    directory.write_bytes(b'not a directory')
                else:
                    (directory / 'unexpected').write_bytes(b'stale')
                self.assert_invalid()

    def test_symlinked_output_or_capture_is_rejected(self):
        link = self.root / 'linked-output'
        try:
            link.symlink_to(self.output, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f'symlinks unavailable on this test host: {error}')
        with self.assertRaises(ValueError):
            contract.validate_outputs(link)
        path = self.output / 'quadrant.png'
        path.unlink()
        path.symlink_to(self.reference / 'quadrant.png')
        self.assert_invalid()

    def test_run_invokes_exact_renderer_owned_example_and_separates_evidence(self):
        evidence, output = self.root / 'evidence', self.root / 'actual-output'
        with patch.object(contract.subprocess, 'run', side_effect=self.process()) as process:
            result = contract.run(self.root, evidence, output, 123)
        self.assertTrue(result['passed'])
        self.assertEqual(process.call_args.args[0], [
            'cargo', 'run', '--locked', '--no-default-features', '--features', 'wgpu-runtime',
            '--example', 'renderer_contract', '--', '--renderer=dx12', '--force-fallback-adapter',
            '--output-dir', str(output.resolve())])
        self.assertEqual(process.call_args.kwargs['cwd'], self.root)
        self.assertEqual(process.call_args.kwargs['timeout'], 123)
        self.assertFalse(process.call_args.kwargs['check'])
        self.assertTrue((evidence / 'summary.json').is_file())
        self.assertFalse((evidence / 'failure.json').exists())
        for name in ('invocation.json', 'stdout.log', 'stderr.log'):
            self.assertTrue((evidence / name).is_file())
            self.assertFalse((output / name).exists())
        invocation = json.loads((evidence / 'invocation.json').read_text(encoding='utf-8'))
        self.assertEqual(invocation['command'], process.call_args.args[0])

    def test_stale_evidence_or_output_never_launches(self):
        for stale in ('evidence', 'output'):
            with self.subTest(stale=stale):
                evidence = self.root / f'{stale}-evidence'
                output = self.root / f'{stale}-output'
                path = evidence if stale == 'evidence' else output
                path.mkdir()
                (path / 'existing').write_text('must survive', encoding='utf-8')
                with patch.object(contract.subprocess, 'run') as process:
                    with self.assertRaises((FileExistsError, ValueError)):
                        contract.run(self.root, evidence, output, 1)
                    process.assert_not_called()
                self.assertEqual((path / 'existing').read_text(encoding='utf-8'), 'must survive')

    def test_existing_empty_directories_are_not_fresh_evidence(self):
        for stale in ('evidence', 'output'):
            with self.subTest(stale=stale):
                evidence = self.root / f'{stale}-evidence'
                output = self.root / f'{stale}-output'
                (evidence if stale == 'evidence' else output).mkdir()
                with patch.object(contract.subprocess, 'run') as process:
                    with self.assertRaises((FileExistsError, ValueError)):
                        contract.run(self.root, evidence, output, 1)
                    process.assert_not_called()

    def test_evidence_and_output_must_be_separate_trees(self):
        evidence = self.root / 'evidence'
        for output in (evidence, evidence / 'output', self.root):
            with self.subTest(output=output), patch.object(contract.subprocess, 'run') as process:
                with self.assertRaises(ValueError):
                    contract.run(self.root, evidence, output, 1)
                process.assert_not_called()
                self.assertFalse(evidence.exists())

    def test_missing_root_never_launches(self):
        with patch.object(contract.subprocess, 'run') as process:
            with self.assertRaises(ValueError):
                contract.run(self.root / 'missing', self.root / 'evidence', self.root / 'actual-output', 1)
            process.assert_not_called()

    def test_timeout_and_nonzero_exit_never_publish_summary(self):
        for mode in ('timeout', 'nonzero'):
            with self.subTest(mode=mode):
                evidence, output = self.root / f'{mode}-evidence', self.root / f'{mode}-output'
                behavior = (subprocess.TimeoutExpired(['cargo'], 1) if mode == 'timeout'
                            else self.process(returncode=7))
                with patch.object(contract.subprocess, 'run', side_effect=behavior):
                    with self.assertRaises(subprocess.TimeoutExpired if mode == 'timeout' else ValueError):
                        contract.run(self.root, evidence, output, 1)
                self.assertFalse((evidence / 'summary.json').exists())
                failure = json.loads((evidence / 'failure.json').read_text(encoding='utf-8'))
                self.assertFalse(failure['passed'])

    def test_zero_exit_without_outputs_or_report_fails(self):
        evidence, output = self.root / 'evidence', self.root / 'actual-output'
        def fake(command, **kwargs):
            kwargs['stderr'].write(GOOD_LOG.encode('utf-8'))
            return subprocess.CompletedProcess(command, 0)
        with patch.object(contract.subprocess, 'run', side_effect=fake):
            with self.assertRaises(ValueError):
                contract.run(self.root, evidence, output, 1)
        self.assertFalse((evidence / 'summary.json').exists())
        self.assertTrue((evidence / 'failure.json').is_file())

    def test_process_success_requires_actual_dx12_warp_and_exact_fxc_logs(self):
        bad_logs = ['', COMPILER_LOG, IDENTITY_LOG,
                    GOOD_LOG.replace('backend=Dx12', 'backend=Vulkan'),
                    GOOD_LOG.replace('requested=dx12', 'requested=auto'),
                    GOOD_LOG.replace(ADAPTER, 'NVIDIA GeForce'),
                    GOOD_LOG.replace('=Fxc', '=Auto'), GOOD_LOG.replace('=Fxc', '=fxc'),
                    GOOD_LOG + 'renderer dx12_shader_compiler=DynamicDxc\n',
                    GOOD_LOG + 'renderer requested=gl backend=Gl adapter=other\n']
        for index, log in enumerate(bad_logs):
            with self.subTest(log=log):
                evidence, output = self.root / f'evidence-{index}', self.root / f'output-{index}'
                with patch.object(contract.subprocess, 'run', side_effect=self.process(log=log)):
                    with self.assertRaises(ValueError):
                        contract.run(self.root, evidence, output, 1)
                self.assertTrue((evidence / 'failure.json').is_file())
                self.assertFalse((evidence / 'summary.json').exists())

    def test_corrupt_output_does_not_publish_summary_despite_good_logs(self):
        evidence, output = self.root / 'evidence', self.root / 'actual-output'
        def corrupt(destination):
            (destination / 'ordered-a-red.png').write_bytes(b'bad PNG')
        with patch.object(contract.subprocess, 'run', side_effect=self.process(modify=corrupt)):
            with self.assertRaises((ValueError, OSError)):
                contract.run(self.root, evidence, output, 1)
        self.assertTrue((evidence / 'failure.json').is_file())
        self.assertFalse((evidence / 'summary.json').exists())

    def test_process_launch_failure_preserves_failure_without_summary(self):
        evidence, output = self.root / 'evidence', self.root / 'actual-output'
        with patch.object(contract.subprocess, 'run', side_effect=OSError('synthetic cargo launch failure')):
            with self.assertRaises(OSError):
                contract.run(self.root, evidence, output, 1)
        self.assertTrue((evidence / 'failure.json').is_file())
        self.assertFalse((evidence / 'summary.json').exists())

    def test_ci_build_identity_matches_this_attempt(self):
        for expected, passes in [({'version': '0.1.11', 'build_number': '0'}, True),
                                 ({'version': '0.1.11', 'build_number': '123'}, False),
                                 ({'version': '0.1.12', 'build_number': '0'}, False)]:
            with self.subTest(identity=expected):
                tag = expected['version'] + '-' + expected['build_number']
                evidence, output = self.root / ('evidence-' + tag), self.root / ('output-' + tag)
                with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
                    with patch('build_identity.context', return_value=expected):
                        with patch.object(contract.subprocess, 'run', side_effect=self.process()):
                            if passes:
                                self.assertTrue(contract.run(self.root, evidence, output, 1)['passed'])
                            else:
                                with self.assertRaises(ValueError):
                                    contract.run(self.root, evidence, output, 1)
                self.assertEqual((evidence / 'summary.json').exists(), passes)
                self.assertEqual((evidence / 'failure.json').exists(), not passes)

    def test_invalid_timeout_never_launches(self):
        for timeout in (0, -1, float('inf'), float('nan')):
            with self.subTest(timeout=timeout), patch.object(contract.subprocess, 'run') as process:
                with self.assertRaises(ValueError):
                    contract.run(self.root, self.root / 'evidence', self.root / 'actual-output', timeout)
                process.assert_not_called()

    def test_real_python_entry_point_with_mocked_process(self):
        for fail in (False, True):
            evidence, output = self.root / f'evidence-{fail}', self.root / f'output-{fail}'
            if fail:
                self.edit_metadata('quadrant.png', lambda record: record.update(backend='Vulkan'))
            with patch.object(contract.sys, 'platform', 'win32'):
                with patch.object(contract.subprocess, 'run', side_effect=self.process()):
                    with patch.object(contract.sys, 'stdout', io.StringIO()), \
                            patch.object(contract.sys, 'stderr', io.StringIO()):
                        status = self.call_main(['--root', str(self.root), '--evidence', str(evidence),
                                                 '--output', str(output), '--timeout', '60'])
            self.assertEqual(status, 1 if fail else 0)
            self.assertEqual((evidence / 'summary.json').exists(), not fail)
            self.assertEqual((evidence / 'failure.json').exists(), fail)

    def test_non_windows_entry_point_fails_before_launch(self):
        with patch.object(contract.sys, 'platform', 'linux'):
            with patch.object(contract.subprocess, 'run') as process:
                with patch.object(contract.sys, 'stderr', io.StringIO()):
                    status = self.call_main(['--root', str(self.root),
                                             '--evidence', str(self.root / 'evidence'),
                                             '--output', str(self.root / 'actual-output')])
                process.assert_not_called()
        self.assertEqual(status, 1)
        self.assertFalse((self.root / 'evidence').exists())
        self.assertFalse((self.root / 'actual-output').exists())


if __name__ == '__main__':
    unittest.main()

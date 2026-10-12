"""Independent synthetic validator controls; not native Windows/DX12 evidence.

This suite writes synthetic PNGs and renderer-shaped JSON in temporary folders.
It never launches Cargo or a renderer. Its literal fixtures and statistics do
not import validator constants/helpers. Native Windows execution is pending.
Image mutations repair coverage/probe statistics and both JSON copies so a
failure reaches the intended image guard instead of a stale metadata mismatch.
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

from PIL import Image, ImageDraw

import verify_world_primitives_contract as contract


REPORT_NAME = 'world-primitives-contract-report.json'
SCOPE = ('headless public-facade world primitive projection, model transforms, '
         'clipping and depth; not window presentation, gameplay, performance or artistic approval')
ADAPTER = 'Microsoft Basic Render Driver'
BLACK = (0, 0, 0, 255)
RED = (255, 0, 0, 255)
GREEN = (0, 255, 0, 255)
BLUE = (0, 0, 255, 255)
CYAN = (0, 255, 255, 255)
YELLOW = (255, 255, 0, 255)
MAGENTA = (255, 0, 255, 255)


def fixture_specs():
    """Independent transcription of renderer-owned cases, never contract.cases()."""
    return [
        ('world-lines-perspective.png', 'facade-lines-perspective-model-and-clipping', [
            ('near red perspective line', 'horizontal', [23, 57, 39, 42], RED),
            ('far green perspective line', 'horizontal', [53, 67, 49, 52], GREEN),
            ('cyan vertical world line', 'vertical', [139, 142, 43, 77], CYAN),
            ('rotated translated blue model line', 'vertical', [79, 82, 63, 97], BLUE),
            ('clear background', 'area', [5, 15, 5, 15], BLACK),
        ], [[18, 62, 38, 42], [48, 72, 48, 52], [138, 142, 38, 82], [78, 82, 58, 102]],
         [RED, GREEN, CYAN, BLUE], [MAGENTA, YELLOW]),
        ('world-wires-perspective.png', 'facade-wire-box-twelve-edges-and-model', [
            ('green near top', 'horizontal', [23, 57, 39, 42], GREEN),
            ('green near bottom', 'horizontal', [23, 57, 79, 82], GREEN),
            ('green near left', 'vertical', [19, 22, 43, 77], GREEN),
            ('green near right', 'vertical', [59, 62, 43, 77], GREEN),
            ('green far top', 'horizontal', [47, 65, 47, 50], GREEN),
            ('green far bottom', 'horizontal', [47, 65, 71, 74], GREEN),
            ('green far left', 'vertical', [43, 46, 51, 69], GREEN),
            ('green far right', 'vertical', [67, 70, 51, 69], GREEN),
            ('green upper left connector', 'any', [30, 35, 42, 47], GREEN),
            ('green upper right connector', 'any', [62, 67, 42, 47], GREEN),
            ('green lower left connector', 'any', [30, 35, 74, 79], GREEN),
            ('green lower right connector', 'any', [62, 67, 74, 79], GREEN),
            ('yellow model near top', 'horizontal', [103, 137, 49, 52], YELLOW),
            ('yellow model near bottom', 'horizontal', [103, 137, 69, 72], YELLOW),
            ('yellow model near left', 'vertical', [99, 102, 53, 67], YELLOW),
            ('yellow model near right', 'vertical', [139, 142, 53, 67], YELLOW),
            ('yellow model far top', 'horizontal', [95, 113, 53, 56], YELLOW),
            ('yellow model far bottom', 'horizontal', [95, 113, 65, 68], YELLOW),
            ('yellow model far left', 'vertical', [91, 94, 57, 63], YELLOW),
            ('yellow model far right', 'vertical', [115, 118, 57, 63], YELLOW),
            ('yellow upper left connector', 'any', [94, 99, 51, 54], YELLOW),
            ('yellow upper right connector', 'any', [125, 131, 51, 54], YELLOW),
            ('yellow lower left connector', 'any', [94, 99, 67, 70], YELLOW),
            ('yellow lower right connector', 'any', [125, 131, 67, 70], YELLOW),
            ('wire interior is unfilled', 'area', [25, 35, 50, 70], BLACK),
            ('transformed wire interior is unfilled', 'area', [123, 133, 57, 63], BLACK),
            ('clear background', 'area', [5, 15, 5, 15], BLACK),
        ], [[18, 70, 38, 82], [90, 142, 48, 72]], [GREEN, YELLOW], []),
        ('world-spheres-depth.png', 'facade-sphere-perspective-model-and-occluded-lines', [
            ('near sphere occludes later far sphere and line', 'area', [40, 58, 56, 65], RED),
            ('near sphere upper interior', 'area', [45, 55, 49, 54], RED),
            ('near sphere lower interior', 'area', [45, 55, 67, 72], RED),
            ('near cyan line in front of sphere', 'horizontal', [29, 71, 44, 47], CYAN),
            ('far yellow line exposed left', 'horizontal', [21, 28, 59, 62], YELLOW),
            ('far yellow line exposed right', 'horizontal', [69, 77, 59, 62], YELLOW),
            ('scaled sphere upper interior', 'area', [107, 113, 50, 55], GREEN),
            ('scaled sphere lower interior', 'area', [107, 113, 65, 70], GREEN),
            ('clear background', 'area', [5, 15, 5, 15], BLACK),
            ('sphere gap remains clear', 'area', [85, 95, 50, 70], BLACK),
        ], [[18, 82, 39, 81], [98, 122, 42, 78]], [RED, CYAN, YELLOW, GREEN], [BLUE]),
    ]


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def image_statistics(image, record):
    """Repair a producer's counts, without importing validator implementation.

    The forged success claims forbidden_color_pixels/outside_envelope_pixels
    stay zero on deliberately violating controls, so the pixel guards must find
    the violation independently rather than trusting those success claims.
    """
    evidence = record['evidence']
    tolerance = evidence['channel_tolerance']

    def near(pixel, color, limit=tolerance):
        return max(abs(a - b) for a, b in zip(pixel, color)) <= limit

    pixels = [image.getpixel((x, y)) for y in range(image.height) for x in range(image.width)]
    nonblack = sum(not near(pixel, BLACK) for pixel in pixels)
    evidence['coverage'] = {'nonblack_pixels': nonblack, 'total_pixels': len(pixels),
                            'nonblack_fraction': nonblack / len(pixels)}
    evidence['palette_pixel_counts'] = [sum(near(pixel, color) for pixel in pixels)
                                        for color in evidence['palette']]
    for probe in evidence['probes']:
        left, right, top, bottom = probe['pixel_bounds']
        limit = probe['channel_tolerance']
        points = {(x, y) for y in range(top, bottom) for x in range(left, right)
                  if near(image.getpixel((x, y)), probe['expected_rgba'], limit)}
        if probe['mode'] == 'horizontal':
            count, total = len({x for x, _ in points}), right - left
        elif probe['mode'] == 'vertical':
            count, total = len({y for _, y in points}), bottom - top
        elif probe['mode'] == 'any':
            count, total = int(bool(points)), 1
        else:
            count, total = len(points), (right - left) * (bottom - top)
        probe.update(matching_samples=count, total_samples=total, match_fraction=count / total)


def build_fixture(output):
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for filename, case, probes, envelopes, palette, forbidden in fixture_specs():
        image = Image.new('RGBA', (160, 120), BLACK)
        drawer = ImageDraw.Draw(image)
        for _, mode, (left, right, top, bottom), color in probes:
            if mode == 'horizontal':
                drawer.line((left, (top + bottom) // 2, right - 1, (top + bottom) // 2), fill=color)
            elif mode == 'vertical':
                drawer.line(((left + right) // 2, top, (left + right) // 2, bottom - 1), fill=color)
            elif mode == 'any':
                drawer.point(((left + right) // 2, (top + bottom) // 2), fill=color)
            else:
                drawer.rectangle((left, top, right - 1, bottom - 1), fill=color)
        renderer = {'requested': 'dx12', 'backend': 'Dx12', 'adapter': ADAPTER}
        record = {'schema_version': 1, 'fixture_case': case, 'filename': filename,
                  **renderer, 'renderer': renderer, 'force_fallback_adapter': True,
                  'alpha_representation': 'opaque-rgba8-rgb-preserved-over-black',
                  'diagnostic_raw_target': False, 'row_origin': 'top-left',
                  'width': 160, 'height': 120, 'size': {'width': 160, 'height': 120},
                  'evidence': {'projection_envelopes': envelopes, 'palette': palette,
                               'forbidden_colors': forbidden, 'forbidden_color_pixels': 0,
                               'outside_envelope_pixels': 0, 'channel_tolerance': 8,
                               'probes': [{'label': label, 'mode': mode, 'pixel_bounds': bounds,
                                           'expected_rgba': color, 'channel_tolerance': 8,
                                           'minimum_match_fraction': {'area': 0.95, 'horizontal': 0.9,
                                                                      'vertical': 0.9, 'any': 1.0}[mode]}
                                          for label, mode, bounds, color in probes]}}
        image_statistics(image, record)
        image.save(output / filename)
        write_json(output / (filename + '.json'), record)
        records.append(record)
    report = {'schema_version': 1, 'status': 'passed', 'native_execution': True,
              'requested': 'dx12', 'backend': 'Dx12', 'adapter': ADAPTER,
              'force_fallback_adapter': True, 'platform': 'windows',
              'build_version': '0.1.11', 'build_number': '12345.2',
              'captures': records, 'scope': SCOPE}
    write_json(output / REPORT_NAME, report)


class WorldPrimitivesOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.control_dir = tempfile.TemporaryDirectory()
        cls.control = Path(cls.control_dir.name)
        build_fixture(cls.control)

    @classmethod
    def tearDownClass(cls):
        cls.control_dir.cleanup()

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.output = Path(self.scratch.name) / 'output'
        self.restore()
        env = patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'})
        env.start()
        self.addCleanup(env.stop)

    def restore(self):
        if self.output.exists():
            shutil.rmtree(self.output)
        shutil.copytree(self.control, self.output)

    def report(self):
        return json.loads((self.output / REPORT_NAME).read_text(encoding='utf-8'))

    def save_report(self, report, sync_sidecars=True):
        if sync_sidecars:
            for record in report['captures']:
                write_json(self.output / (record['filename'] + '.json'), record)
        write_json(self.output / REPORT_NAME, report)

    def mutate_record(self, index, mutate):
        report = self.report()
        mutate(report['captures'][index])
        self.save_report(report)

    def mutate_image(self, index, mutate):
        report = self.report()
        record = report['captures'][index]
        path = self.output / record['filename']
        with Image.open(path) as source:
            image = source.copy()
        changed = mutate(image)
        image = image if changed is None else changed
        image_statistics(image, record)
        image.save(path)
        self.save_report(report)

    def reject(self, message):
        with self.assertRaisesRegex(ValueError, message):
            contract.validate_outputs(self.output)

    def test_independent_synthetic_control_and_summary_boundary(self):
        result = contract.validate_outputs(self.output)
        self.assertEqual(result, {'schema': 'rust-duty-world-primitives-contract-validation/v1',
                                 'passed': True, 'backend': 'Dx12', 'adapter': ADAPTER, 'captures': 3,
                                 'build_version': '0.1.11', 'build_number': '12345.2', 'scope': SCOPE})
        self.assertIs(result['passed'], True)
        json.dumps(result, allow_nan=False)

    def test_all_missing_files_fail(self):
        for path in sorted(self.control.iterdir()):
            with self.subTest(filename=path.name):
                self.restore()
                (self.output / path.name).unlink()
                self.reject('output set differs')

    def test_extra_stale_files_and_directories_fail(self):
        for name, directory in [('stale.png', False), ('old-report.json', False), ('old-run', True)]:
            with self.subTest(name=name):
                self.restore()
                path = self.output / name
                path.mkdir() if directory else path.write_text('{}', encoding='utf-8')
                self.reject('output set differs|nonempty JSON object')

    def test_output_root_and_entries_must_not_be_symlinks(self):
        link = Path(self.scratch.name) / 'linked-output'
        try:
            link.symlink_to(self.output, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('This host does not permit symlink creation')
        with self.assertRaisesRegex(ValueError, 'symbolic link'):
            contract.validate_outputs(link)
        for filename in ('world-lines-perspective.png', 'world-lines-perspective.png.json', REPORT_NAME):
            with self.subTest(filename=filename):
                self.restore()
                path = self.output / filename
                path.unlink()
                path.symlink_to(self.control / filename)
                self.reject('symbolic link')

    def test_png_path_cannot_be_a_directory(self):
        path = self.output / 'world-lines-perspective.png'
        path.unlink()
        path.mkdir()
        self.reject('regular files')

    def test_missing_reordered_and_duplicate_report_captures(self):
        for kind in ('missing', 'reordered', 'duplicate'):
            with self.subTest(kind=kind):
                self.restore()
                report = self.report()
                if kind == 'missing':
                    report['captures'].pop()
                elif kind == 'reordered':
                    report['captures'].reverse()
                else:
                    report['captures'][1] = copy.deepcopy(report['captures'][0])
                self.save_report(report, sync_sidecars=False)
                self.reject('3 ordered captures|report/sidecar')

    def test_report_and_sidecars_must_match_exactly(self):
        report = self.report()
        report['captures'][0]['width'] = 160.0
        self.save_report(report, sync_sidecars=False)
        self.reject('report/sidecar.*JSON type differs')

    def test_native_and_renderer_identity_are_literal(self):
        changes = [('schema_version', True), ('schema_version', 1.0), ('status', 'skipped'),
                   ('native_execution', 1), ('native_execution', False), ('requested', 'auto'),
                   ('backend', 'Vulkan'), ('adapter', 'hardware adapter'),
                   ('adapter', ADAPTER.lower()), ('force_fallback_adapter', False),
                   ('force_fallback_adapter', 1), ('platform', 'linux'), ('scope', 'all gameplay verified')]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                self.restore()
                report = self.report()
                report[key] = value
                self.save_report(report, sync_sidecars=False)
                self.reject('world primitives report')

    def test_report_build_identity_and_schema_fail_closed(self):
        for key, value in [('build_version', ''), ('build_version', '  '), ('build_number', 123),
                           ('build_number', None), ('captures', {}), ('captures', True)]:
            with self.subTest(key=key, value=value):
                self.restore()
                report = self.report()
                report[key] = value
                self.save_report(report, sync_sidecars=False)
                self.reject('world primitives report')
        for remove in (True, False):
            self.restore()
            report = self.report()
            if remove:
                del report['scope']
            else:
                report['approved'] = True
            self.save_report(report, sync_sidecars=False)
            self.reject('report fields differ')

    def test_capture_metadata_and_nested_renderer_are_literal(self):
        changes = [('requested', 'auto'), ('backend', 'Vulkan'), ('adapter', 'hardware'),
                   ('renderer', {'requested': 'dx12', 'backend': 'Vulkan', 'adapter': ADAPTER}),
                   ('force_fallback_adapter', 1), ('alpha_representation', 'raw-associated-emissive-rgba8'),
                   ('diagnostic_raw_target', 0), ('row_origin', 'bottom-left'), ('width', 160.0),
                   ('height', True), ('size', {'width': 160, 'height': 120, 'depth': 1}),
                   ('fixture_case', 'pretend'), ('schema_version', True)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                self.restore()
                self.mutate_record(0, lambda record: record.update({key: value}))
                self.reject('backend|expected|JSON type differs|JSON fields differ')

    def test_missing_extra_or_wrong_type_evidence(self):
        for mutate in (lambda r: r.update(extra={}), lambda r: r.pop('evidence'),
                       lambda r: r.update(evidence=[]), lambda r: r['evidence'].update(extra=0),
                       lambda r: r['evidence'].pop('coverage')):
            self.restore()
            self.mutate_record(0, mutate)
            self.reject('metadata fields differ|evidence fields differ')

    def test_duplicate_nonfinite_and_malformed_json_fail(self):
        for filename in (REPORT_NAME, 'world-lines-perspective.png.json'):
            for text in ('{"schema_version":1,"schema_version":1}', '{"x":NaN}',
                         '{"x":Infinity}', '{"x":-Infinity}', '{"x":1e9999}',
                         '{"x":{"nested":1,"nested":1}}', '{}', '[]', '{'):
                with self.subTest(filename=filename, text=text):
                    self.restore()
                    (self.output / filename).write_text(text, encoding='utf-8')
                    self.reject('duplicate JSON|non-finite JSON|nonempty JSON|Expecting')

    def test_invalid_json_encoding_fails(self):
        (self.output / REPORT_NAME).write_bytes(b'\xff\xfe\xff')
        self.reject('decode')

    def test_probe_specification_cannot_be_forged(self):
        changes = [('label', 'weakened'), ('mode', 'any'), ('pixel_bounds', [0, 160, 0, 120]),
                   ('pixel_bounds', [23, 23, 39, 42]), ('expected_rgba', [0, 0, 0, 255]),
                   ('minimum_match_fraction', 0.0), ('minimum_match_fraction', 1),
                   ('channel_tolerance', 255), ('channel_tolerance', 8.0)]
        for key, value in changes:
            with self.subTest(key=key):
                self.restore()
                self.mutate_record(0, lambda r: r['evidence']['probes'][0].update({key: value}))
                self.reject('near red perspective line.*expected|near red perspective line.*JSON type differs')

    def test_probe_inventory_and_extra_fields_cannot_change(self):
        mutations = [lambda p: p.pop(), lambda p: p.reverse(),
                     lambda p: p.__setitem__(1, copy.deepcopy(p[0])), lambda p: p[0].update(extra=0),
                     lambda p: p[0].pop('match_fraction')]
        for mutate in mutations:
            self.restore()
            self.mutate_record(0, lambda r: mutate(r['evidence']['probes']))
            self.reject('probes differ|probe fields differ|expected')

    def test_fixed_palette_envelopes_forbidden_and_tolerance(self):
        changes = [('projection_envelopes', [[0, 160, 0, 120]]), ('palette', [[255, 255, 255, 255]]),
                   ('forbidden_colors', []), ('forbidden_color_pixels', 1),
                   ('outside_envelope_pixels', False), ('channel_tolerance', 9)]
        for key, value in changes:
            with self.subTest(key=key):
                self.restore()
                self.mutate_record(0, lambda r: r['evidence'].update({key: value}))
                self.reject('evidence.*JSON array length differs|evidence.*expected|evidence.*JSON type differs')

    def test_recomputed_counts_and_fractions_cannot_be_forged(self):
        mutations = [lambda e: e['palette_pixel_counts'].__setitem__(0, 999),
                     lambda e: e['coverage'].update(nonblack_pixels=True),
                     lambda e: e['coverage'].update(total_pixels=19200.0),
                     lambda e: e['coverage'].update(nonblack_fraction=1.0),
                     lambda e: e['coverage'].update(extra=0),
                     lambda e: e['probes'][0].update(matching_samples=1),
                     lambda e: e['probes'][0].update(total_samples=34.0),
                     lambda e: e['probes'][0].update(match_fraction=1),
                     lambda e: e['probes'][0].update(match_fraction=0.99999999999999)]
        for mutate in mutations:
            self.restore()
            self.mutate_record(0, lambda r: mutate(r['evidence']))
            self.reject('palette_pixel_counts|coverage|statistics')

    def test_tiny_decimal_fraction_forgery_does_not_round_to_success(self):
        for path in (self.output / REPORT_NAME, self.output / 'world-lines-perspective.png.json'):
            text = path.read_text(encoding='utf-8')
            path.write_text(text.replace('"match_fraction": 1.0',
                                         '"match_fraction": 1.00000000000000000000000000001'), encoding='utf-8')
        self.reject('statistics.match_fraction')

    def test_empty_and_missing_required_colors_fail_after_statistics_repair(self):
        for index in range(3):
            with self.subTest(index=index):
                self.restore()
                self.mutate_image(index, lambda image: Image.new('RGBA', image.size, BLACK))
                self.reject('missing a required primitive color')
        self.restore()
        self.mutate_image(0, lambda image: image.paste(BLACK, (79, 63, 82, 97)))
        self.reject('missing a required primitive color')

    def test_main_alpha_must_be_exactly_opaque(self):
        for alpha in (0, 247, 254):
            with self.subTest(alpha=alpha):
                self.restore()
                self.mutate_image(0, lambda image: image.putpixel((0, 0), (0, 0, 0, alpha)))
                self.reject('alpha is not opaque')

    def test_vertical_orientation_and_reflection_fail(self):
        for index in range(3):
            for operation in (Image.Transpose.FLIP_TOP_BOTTOM, Image.Transpose.FLIP_LEFT_RIGHT):
                # The wire boxes are symmetric in Y, as the source's CPU tests
                # also document. Only lines and spheres witness vertical origin.
                if index == 1 and operation == Image.Transpose.FLIP_TOP_BOTTOM:
                    continue
                with self.subTest(index=index, operation=operation):
                    self.restore()
                    self.mutate_image(index, lambda image: image.transpose(operation))
                    self.reject('outside fixed projection envelopes|pixel probe')

    def test_whole_sequence_vertical_flip_fails_but_wire_symmetry_is_not_overclaimed(self):
        self.mutate_image(1, lambda image: image.transpose(Image.Transpose.FLIP_TOP_BOTTOM))
        contract.validate_outputs(self.output)
        self.mutate_image(0, lambda image: image.transpose(Image.Transpose.FLIP_TOP_BOTTOM))
        self.mutate_image(2, lambda image: image.transpose(Image.Transpose.FLIP_TOP_BOTTOM))
        self.reject('outside fixed projection envelopes|pixel probe')

    def test_wrong_channels_fail_after_statistics_repair(self):
        def swap_channels(image):
            red, green, blue, alpha = image.split()
            return Image.merge('RGBA', (blue, red, green, alpha))
        for index in range(3):
            with self.subTest(index=index):
                self.restore()
                self.mutate_image(index, swap_channels)
                self.reject('forbidden clipped/occluded color|unexpected color|pixel probe')

    def test_wrong_projection_rejected_inside_otherwise_valid_envelopes(self):
        def shift_red(image):
            image.paste(BLACK, (23, 39, 57, 42))
            # An orthographic-looking near/far equal span at the wrong x is
            # still entirely in the conservative near-line envelope.
            ImageDraw.Draw(image).line((40, 40, 59, 40), fill=RED)
        self.mutate_image(0, shift_red)
        self.reject('pixel probe near red perspective line failed')

    def test_wrong_model_transform_preserves_palette_but_fails_probe(self):
        def unrotated_model(image):
            image.paste(BLACK, (78, 58, 82, 102))
            ImageDraw.Draw(image).line((79, 80, 81, 80), fill=BLUE)
        self.mutate_image(0, unrotated_model)
        self.reject('pixel probe rotated translated blue model line failed')

    def test_clipping_and_depth_forbidden_colors_fail(self):
        for index, color in [(0, MAGENTA), (0, YELLOW), (2, BLUE)]:
            with self.subTest(index=index, color=color):
                self.restore()
                self.mutate_image(index, lambda image: image.putpixel((50, 40 if index == 0 else 60), color))
                self.reject('forbidden clipped/occluded color')

    def test_far_line_over_near_sphere_fails_depth_probe(self):
        self.mutate_image(2, lambda image: ImageDraw.Draw(image).line((40, 60, 57, 60), fill=YELLOW))
        self.reject('pixel probe near sphere occludes later far sphere and line failed')

    def test_missing_every_positive_probe_fails_after_statistics_repair(self):
        for index, spec in enumerate(fixture_specs()):
            for label, _, (left, right, top, bottom), color in spec[2]:
                if color == BLACK:
                    continue
                with self.subTest(case=index, label=label):
                    self.restore()
                    self.mutate_image(index, lambda image: image.paste(BLACK, (left, top, right, bottom)))
                    self.reject('pixel probe|missing a required primitive color')

    def test_wire_interiors_must_remain_unfilled(self):
        for bounds, color, label in [((25, 50, 35, 70), GREEN, 'wire interior is unfilled'),
                                     ((123, 57, 133, 63), YELLOW, 'transformed wire interior is unfilled')]:
            with self.subTest(label=label):
                self.restore()
                self.mutate_image(1, lambda image: image.paste(color, bounds))
                self.reject('pixel probe ' + label + ' failed')

    def test_stray_pixels_and_unknown_colors_fail(self):
        for position, color, message in [((1, 1), RED, 'outside fixed projection envelopes'),
                                          ((24, 40), (255, 255, 255, 255), 'unexpected color')]:
            with self.subTest(position=position):
                self.restore()
                self.mutate_image(0, lambda image: image.putpixel(position, color))
                self.reject(message)

    def test_stroke_requires_span_coverage_not_dense_cluster(self):
        def cluster(image):
            image.paste(BLACK, (23, 39, 57, 42))
            image.paste(RED, (23, 39, 35, 42))  # 36 pixels exceed the 34-column span.
        self.mutate_image(0, cluster)
        self.reject('pixel probe near red perspective line failed')

    def test_fixed_stroke_and_area_thresholds(self):
        # 31/34 columns pass 90%, 30/34 fail. Area 48/50 passes 95%, 47/50 fails.
        for retained, accepted in [(31, True), (30, False)]:
            self.restore()
            self.mutate_image(0, lambda image: image.paste(BLACK, (23 + retained, 39, 57, 42)))
            if accepted:
                contract.validate_outputs(self.output)
            else:
                self.reject('pixel probe near red perspective line failed')
        for removed, accepted in [(2, True), (3, False)]:
            self.restore()
            self.mutate_image(2, lambda image: image.paste(BLACK, (45, 49, 45 + removed, 50)))
            if accepted:
                contract.validate_outputs(self.output)
            else:
                self.reject('pixel probe near sphere upper interior failed')

    def test_channel_tolerance_boundary(self):
        def paint_red(image, channel):
            image.paste((channel, 8, 8, 255), (23, 40, 57, 41))
        self.mutate_image(0, lambda image: paint_red(image, 247))
        contract.validate_outputs(self.output)
        self.restore()
        self.mutate_image(0, lambda image: paint_red(image, 246))
        self.reject('unexpected color')

    def test_repaired_bounds_and_tolerance_do_not_authorize_bad_image(self):
        self.mutate_image(0, lambda image: image.paste(BLACK, (23, 39, 57, 42)))
        report = self.report()
        probe = report['captures'][0]['evidence']['probes'][0]
        probe.update(pixel_bounds=[5, 15, 5, 15], expected_rgba=list(BLACK), channel_tolerance=255)
        with Image.open(self.output / report['captures'][0]['filename']) as image:
            image_statistics(image, report['captures'][0])
        self.save_report(report)
        self.reject('near red perspective line.pixel_bounds|near red perspective line.expected_rgba')

    def test_truncated_corrupt_and_trailing_png_fail(self):
        path = self.output / 'world-lines-perspective.png'
        original = path.read_bytes()
        for data, message in [(b'', 'expected PNG'), (b'not PNG', 'expected PNG'),
                              (original[:-1], 'truncated'), (original[:-12], 'truncated'),
                              (original + b'stale', 'trailing bytes'),
                              (original[:-1] + bytes([original[-1] ^ 1]), 'invalid PNG chunk CRC')]:
            with self.subTest(message=message):
                path.write_bytes(data)
                self.reject(message)

    def test_png_wrong_extent_rgb_and_16bit_rgba_fail(self):
        path = self.output / 'world-lines-perspective.png'
        Image.new('RGBA', (159, 120), BLACK).save(path)
        self.reject('wrong extent')
        Image.new('RGB', (160, 120), BLACK[:3]).save(path)
        self.reject('expected RGBA8 PNG')
        # Construct a well-framed 16-bit RGBA PNG; Pillow exposes this as RGBA
        # after downconversion, so the disk's actual IHDR must also be checked.
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
        with Image.open(self.control / 'world-lines-perspective.png') as image:
            raw = b''.join(b'\x00' + b''.join(struct.pack('>H', channel * 257)
                                            for x in range(160) for channel in image.getpixel((x, y)))
                           for y in range(120))
        path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 160, 120, 16, 6, 0, 0, 0))
                         + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
        self.reject('expected RGBA8 PNG')

    def test_animated_png_is_not_a_capture(self):
        path = self.output / 'world-lines-perspective.png'
        with Image.open(path) as source:
            image = source.copy()
        second = image.copy()
        second.putpixel((0, 0), RED)
        image.save(path, save_all=True, append_images=[second], duration=100, loop=0)
        self.reject('one static PNG frame')

    def test_ci_uses_existing_identity_context_and_rejects_other_attempt(self):
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'RHS059/rust_duty',
               'GITHUB_RUN_NUMBER': '20', 'GITHUB_RUN_ID': '12345', 'GITHUB_RUN_ATTEMPT': '2',
               'GITHUB_SHA': 'a' * 40, 'GITHUB_REF_NAME': 'test-world-primitives'}
        import build_identity
        with patch.dict(os.environ, env), patch.object(build_identity, 'package_version', return_value='0.1.11'):
            # Ensure a workflow-specific pin cannot leak from the test host.
            os.environ.pop('RUST_DUTY_BUILD_VERSION', None)
            contract.validate_outputs(self.output)
            for key, value in [('build_number', '12345.1'), ('build_version', '0.1.10')]:
                with self.subTest(key=key):
                    self.restore()
                    report = self.report()
                    report[key] = value
                    self.save_report(report)
                    self.reject('build identity does not match this CI attempt')
            self.restore()
            os.environ['GITHUB_RUN_ATTEMPT'] = '0'
            self.reject('invalid run attempt')

    def test_non_ci_validation_does_not_invoke_identity_context(self):
        import build_identity
        with patch.object(build_identity, 'context', side_effect=AssertionError('unexpected CI dependency')):
            contract.validate_outputs(self.output)

    def test_cli_prints_only_serializable_content_summary(self):
        with patch('sys.stdout', new_callable=io.StringIO) as stdout:
            self.assertEqual(contract.main([str(self.output)]), 0)
        self.assertIs(json.loads(stdout.getvalue())['passed'], True)
        (self.output / REPORT_NAME).unlink()
        with patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(SystemExit) as failure:
            contract.main([str(self.output)])
        self.assertEqual(failure.exception.code, 1)


if __name__ == '__main__':
    unittest.main()

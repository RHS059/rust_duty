"""Independent synthetic controls for the UI-theme evidence checker.

No renderer is launched. Passing these tests is not native Windows evidence.
Fixtures use literal source contracts and a rational-area glyph rasterizer,
without importing production checker constants or its pixel/statistics helpers.
Pixel mutations repair producer statistics and both metadata copies, so they
exercise image guards rather than being rejected only for stale metadata.
"""

import copy
from fractions import Fraction
from functools import lru_cache
import io
import json
import math
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from PIL import Image, ImageDraw

import verify_ui_theme_contract as contract


REPORT_NAME = 'ui-theme-contract-report.json'
SCOPE = 'headless native DX12 UiTheme-to-facade-to-PNG contract'
ADAPTER = 'Microsoft Basic Render Driver'
PERCENTS = (100, 125, 150, 175, 200)
STAGES = ('initial', 'reloaded', 'invalid-last-good')
FIRST_CSS = ('#pause-menu .panel { background-color:#204060; border-color:#e0c020; border-width:4px; }\n'
             '#pause-menu .label { color:#40e080; font-size:16px; }\n'
             '#pause-menu .button { background-color:#8040c0; border-color:#20c0e0; border-width:8px; opacity:0.5; }\n')
SECOND_CSS = ('#pause-menu .panel { background-color:#502080; border-color:#20c080; border-width:8px; }\n'
              '#pause-menu .label { color:#e08040; font-size:32px; opacity:0.5; }\n'
              '#pause-menu .button { background-color:#4080c0; border-color:#e08020; border-width:4px; opacity:0.75; }\n')
BAD_CSS = ('#pause-menu .panel { background-color:#ff0000; border-width:1px; }\n'
           '#pause-menu .label { opacity:NaN; }\n')


def write_json(path, record):
    path.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')


def fixture_probes(reloaded):
    if reloaded:
        background, border, strip = [80, 32, 128, 255], [32, 192, 128, 255], [32, 192, 128, 255]
        button, button_border, button_strip = [48, 96, 144, 255], [180, 120, 60, 255], [48, 96, 144, 255]
    else:
        background, border, strip = [32, 64, 96, 255], [224, 192, 32, 255], [32, 64, 96, 255]
        button, button_border, button_strip = [64, 32, 96, 255], [48, 112, 160, 255], [48, 112, 160, 255]
    return [
        ('panel background', [96., 36., 184., 68.], background),
        ('panel top border', [32., 21., 192., 23.], border),
        ('panel bottom border', [32., 81., 192., 83.], border),
        ('panel left border', [25., 32., 27., 72.], border),
        ('panel right border', [197., 32., 199., 72.], border),
        ('panel border width', [32., 25., 192., 27.], strip),
        ('button background opacity', [40., 124., 184., 148.], button),
        ('button top border opacity', [32., 109., 192., 111.], button_border),
        ('button bottom border opacity', [32., 161., 192., 163.], button_border),
        ('button left border opacity', [25., 120., 27., 152.], button_border),
        ('button right border opacity', [197., 120., 199., 152.], button_border),
        ('button border width', [32., 113., 192., 115.], button_strip),
        ('inward panel left guard', [20., 20., 23., 84.], [0, 0, 0, 255]),
        ('inward panel right guard', [201., 20., 204., 84.], [0, 0, 0, 255]),
        ('inward button top guard', [24., 104., 200., 107.], [0, 0, 0, 255]),
        ('inward button bottom guard', [24., 165., 200., 168.], [0, 0, 0, 255]),
    ]


def bounds(logical, percent):
    values = [Fraction(value) * Fraction(percent, 100) for value in logical]
    return [math.ceil(values[0]), math.ceil(values[1]), math.floor(values[2]), math.floor(values[3])]


@lru_cache(maxsize=30)
def rational_text(reloaded, percent, font_size=None, alpha=None):
    """Rational geometry and blending, independently expressed as occupied cells."""
    background = (80, 32, 128, 255) if reloaded else (32, 64, 96, 255)
    color = (224, 128, 64) if reloaded else (64, 224, 128)
    font_size = (32 if reloaded else 16) if font_size is None else font_size
    alpha = (127 if reloaded else 255) if alpha is None else alpha
    scale = Fraction(percent, 100)
    step = Fraction(font_size, 16) * scale
    box = bounds((36, 36, 80, 68), percent)
    image = Image.new('RGBA', (box[2] - box[0], box[3] - box[1]), background)
    h = {(x, y) for y in range(8) for x in (0, 5)} | {(x, 3) for x in range(6)}
    i = {(2, y) for y in range(8)} | {(x, y) for x in (1, 3) for y in (0, 7)}
    overlaps = {}
    for baseline, cells in ((40, h), (64, i)):
        for col, row in cells:
            x0, y0 = baseline * scale + (col + 1) * step, 60 * scale + (row - 8) * step
            for y in range(math.floor(y0), math.ceil(y0 + step)):
                for x in range(math.floor(x0), math.ceil(x0 + step)):
                    if not (box[0] <= x < box[2] and box[1] <= y < box[3]):
                        continue
                    area = (min(x + 1, x0 + step) - max(x, x0)) * (min(y + 1, y0 + step) - max(y, y0))
                    overlaps[x, y] = overlaps.get((x, y), Fraction(0)) + area
    for (x, y), area in overlaps.items():
        coverage = min(area, 1) * Fraction(alpha, 255)
        blended = [Fraction(color[c]) * coverage + background[c] * (1 - coverage) for c in range(3)]
        # Integer rational round-half-up; never Python's ties-to-even round().
        pixel = tuple((2 * v.numerator + v.denominator) // (2 * v.denominator) for v in blended) + (255,)
        image.putpixel((x - box[0], y - box[1]), pixel)
    ink = sum(pixel != background for pixel in image.getdata())
    return image.size, image.tobytes(), ink


def fixture_image(reloaded, percent):
    image = Image.new('RGBA', (320 * percent // 100, 192 * percent // 100), (0, 0, 0, 255))
    draw = ImageDraw.Draw(image)
    s = Fraction(percent, 100)

    def rectangle(box, color):
        left, top, right, bottom = [int(value * s) for value in box]
        draw.rectangle((left, top, right - 1, bottom - 1), fill=color)

    # Paint full geometric rectangles, rather than only passing probe islands.
    if reloaded:
        panel, panel_edge, width = (80, 32, 128, 255), (32, 192, 128, 255), 8
        button, button_edge, button_width = (48, 96, 144, 255), (180, 120, 60, 255), 4
    else:
        panel, panel_edge, width = (32, 64, 96, 255), (224, 192, 32, 255), 4
        button, button_edge, button_width = (64, 32, 96, 255), (48, 112, 160, 255), 8
    rectangle((24, 20, 200, 84), panel_edge)
    rectangle((24 + width, 20 + width, 200 - width, 84 - width), panel)
    rectangle((24, 108, 200, 164), button_edge)
    rectangle((24 + button_width, 108 + button_width, 200 - button_width, 164 - button_width), button)
    size, pixels, _ = rational_text(reloaded, percent)
    left, top, _, _ = bounds((36, 36, 80, 68), percent)
    image.paste(Image.frombytes('RGBA', size, pixels), (left, top))
    return image


def image_statistics(image, record):
    """Recompute forged producer statistics after deliberate pixel corruption."""
    for probe in record['probes']:
        region = image.crop(probe['pixel_bounds']).convert('RGBA')
        probe['maximum_channel_error'] = max(
            abs(channel - want) for pixel in region.getdata() for channel, want in zip(pixel, probe['expected_rgba']))
    size, pixels, ink = rational_text(record['phase'] != 'initial', record['scale_percent'])
    wanted = Image.frombytes('RGBA', size, pixels)
    actual = image.crop(record['styled_text']['pixel_bounds']).convert('RGBA')
    record['styled_text']['maximum_channel_error'] = max(
        abs(a - b) for got, expected in zip(actual.getdata(), wanted.getdata()) for a, b in zip(got, expected))
    record['styled_text']['expected_ink_pixels'] = ink


def build_fixture(output, *, active_path=None):
    """Synthetic evidence only; active_path supports the process composition test."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for filename, css in [('initial-theme.css', FIRST_CSS), ('reloaded-theme.css', SECOND_CSS),
                          ('rejected-theme.css', BAD_CSS), ('active-theme.css', BAD_CSS)]:
        (output / filename).write_bytes(css.encode('utf-8'))
    records = []
    for phase in STAGES:
        for percent in PERCENTS:
            reloaded = phase != 'initial'
            filename = f'theme-{phase}-{percent}.png'
            image = fixture_image(reloaded, percent)
            probes = []
            for label, logical, rgba in fixture_probes(reloaded):
                box = bounds(logical, percent)
                probes.append({'label': label, 'logical_bounds': logical, 'pixel_bounds': box,
                               'expected_rgba': rgba, 'checked_pixels': (box[2] - box[0]) * (box[3] - box[1]),
                               'maximum_channel_error': 0, 'channel_tolerance': 4, 'required_match_fraction': 1.0})
            font_size = 32 if reloaded else 16
            text_size, _, ink = rational_text(reloaded, percent)
            styled = {'glyphs': [{'text': 'H', 'baseline_logical': [40, 60]},
                                 {'text': 'I', 'baseline_logical': [64, 60]}],
                      'font_size_css_px': font_size, 'font_size_physical_px': font_size * percent / 100.,
                      'pixel_bounds': bounds((36, 36, 80, 68), percent), 'expected_ink_pixels': ink,
                      'checked_pixels': text_size[0] * text_size[1], 'maximum_channel_error': 0,
                      'channel_tolerance': 4, 'required_match_fraction': 1.0,
                      'oracle': 'independent fixed ProggyClean H/I design-grid area coverage, including negative-space pixels',
                      'human_legibility_approved': False}
            record = {'schema_version': 1, 'filename': filename, 'phase': phase,
                      'requested': 'dx12', 'backend': 'Dx12', 'adapter': ADAPTER,
                      'scale_percent': percent, 'logical_size': [320, 192], 'physical_size': list(image.size),
                      'row_origin': 'top-left', 'alpha_representation': 'opaque-rgba8-rgb-preserved-over-black',
                      'probes': probes, 'styled_text': styled,
                      'last_good_identical_to_successful_reload': True if phase == 'invalid-last-good' else None}
            image.save(output / filename)
            write_json(output / (filename + '.json'), record)
            records.append(record)
    active = str(output / 'active-theme.css' if active_path is None else active_path)
    report = {'schema_version': 1, 'status': 'passed', 'native_execution': True,
              'requested': 'dx12', 'backend': 'Dx12', 'adapter': ADAPTER,
              'force_fallback_adapter': True, 'platform': 'windows',
              'build_version': '0.1.11', 'build_number': '12345.2', 'scales_percent': list(PERCENTS),
              'captures': records,
              'reload_checks': [{'phase': 'initial', 'api': 'load_theme', 'status': 'loaded'},
                                {'phase': 'reloaded', 'api': 'reload_theme', 'status': 'reloaded'},
                                {'phase': 'invalid-last-good', 'api': 'reload_theme', 'status': 'expected-error',
                                 'file': active, 'line': 2, 'column': 29,
                                 'error': f'{active}:2:29: synthetic invalid-opacity diagnostic'}],
              'cpu_hit_geometry': {
                  'evidence': 'CPU only; Rect::contains at the logical draw rectangle',
                  'button_logical_xywh': [24, 108, 176, 56],
                  'samples': [{'point': [24., 108.], 'inside': True},
                              {'point': [200., 164.], 'inside': True},
                              {'point': [112., 136.], 'inside': True},
                              {'point': [23.75, 136.], 'inside': False},
                              {'point': [200.25, 136.], 'inside': False}],
                  'native_pointer_or_click_verified': False},
              'compiler_identity_source': 'external captured renderer startup log; not inferred by this fixture',
              'scope': SCOPE,
              'boundaries': {'os_dpi_events_verified': False, 'window_presentation_verified': False,
                             'native_pointer_or_click_verified': False, 'human_legibility_approved': False,
                             'private_assets_loaded': False}}
    write_json(output / REPORT_NAME, report)


class UiThemeOutputTests(unittest.TestCase):
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
        report = self.report()
        active = str(self.output / 'active-theme.css')
        report['reload_checks'][2].update(file=active, error=f'{active}:2:29: synthetic invalid-opacity diagnostic')
        self.save_report(report, sync=False)

    def report(self):
        return json.loads((self.output / REPORT_NAME).read_text(encoding='utf-8'))

    def save_report(self, report, sync=True):
        if sync:
            for record in report['captures']:
                write_json(self.output / (record['filename'] + '.json'), record)
        write_json(self.output / REPORT_NAME, report)

    def mutate_record(self, index, mutate):
        report = self.report()
        mutate(report['captures'][index])
        self.save_report(report)

    def mutate_image(self, index, mutate, repair=True):
        report = self.report()
        record = report['captures'][index]
        path = self.output / record['filename']
        with Image.open(path) as source:
            image = source.copy()
        changed = mutate(image)
        if changed is not None:
            image = changed
        if repair:
            image_statistics(image, record)
        image.save(path)
        self.save_report(report)

    def reject(self, expression):
        with self.assertRaisesRegex(ValueError, expression):
            contract.validate_outputs(self.output)

    def test_independent_control_exact_summary_and_no_process_claims(self):
        result = contract.validate_outputs(self.output)
        self.assertEqual(result, {'schema': 'rust-duty-ui-theme-contract-validation/v1', 'passed': True,
                                 'backend': 'Dx12', 'adapter': ADAPTER, 'captures': 15,
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
        for filename, directory in [('stale.png', False), ('old-report.json', False), ('old-run', True)]:
            with self.subTest(filename=filename):
                self.restore()
                path = self.output / filename
                path.mkdir() if directory else path.write_text('{"old":true}', encoding='utf-8')
                self.reject('output set differs')

    def test_root_and_all_evidence_kinds_reject_symlinks(self):
        link = Path(self.scratch.name) / 'linked'
        try:
            link.symlink_to(self.output, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Host does not permit creating symlinks')
        with self.assertRaisesRegex(ValueError, 'symbolic link'):
            contract.validate_outputs(link)
        for filename in (REPORT_NAME, 'active-theme.css', 'theme-initial-100.png', 'theme-initial-100.png.json'):
            with self.subTest(filename=filename):
                self.restore()
                path = self.output / filename
                path.unlink()
                path.symlink_to(self.control / filename)
                self.reject('symbolic link')

    def test_regular_file_and_missing_root_guards(self):
        for filename in ('active-theme.css', 'theme-initial-100.png', REPORT_NAME):
            self.restore()
            path = self.output / filename
            path.unlink()
            path.mkdir()
            self.reject('regular files|not a file')
        with self.assertRaisesRegex(ValueError, 'missing or not a directory'):
            contract.validate_outputs(self.output / 'missing')

    def test_every_css_file_is_exact_source_bytes(self):
        for filename in ('active-theme.css', 'initial-theme.css', 'reloaded-theme.css', 'rejected-theme.css'):
            for mutation in (lambda b: b + b' ', lambda b: b.replace(b'\n', b'\r\n'),
                             lambda b: b.replace(b'#', b'/*altered*/#', 1)):
                with self.subTest(filename=filename, mutation=mutation):
                    self.restore()
                    path = self.output / filename
                    path.write_bytes(mutation(path.read_bytes()))
                    self.reject('CSS bytes differ')

    def test_native_identity_and_scope_are_literal(self):
        changes = [('schema_version', True), ('schema_version', 1.0), ('status', 'skipped'),
                   ('native_execution', 1), ('native_execution', False), ('requested', 'auto'),
                   ('backend', 'Vulkan'), ('adapter', 'hardware adapter'), ('adapter', ADAPTER.lower()),
                   ('force_fallback_adapter', False), ('force_fallback_adapter', 1), ('platform', 'linux'),
                   ('scope', 'human approved'), ('compiler_identity_source', 'Fxc')]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                self.restore()
                report = self.report()
                report[key] = value
                self.save_report(report, sync=False)
                self.reject('UI theme report')

    def test_build_fields_and_report_schema_fail_closed(self):
        for key, value in [('build_version', ''), ('build_version', 11), ('build_number', '  '),
                           ('build_number', None), ('captures', {}), ('captures', True)]:
            self.restore()
            report = self.report()
            report[key] = value
            self.save_report(report, sync=False)
            self.reject('UI theme report')
        for mutate in (lambda r: r.pop('scope'), lambda r: r.update(approved=True)):
            self.restore()
            report = self.report()
            mutate(report)
            self.save_report(report, sync=False)
            self.reject('report fields differ')

    def test_all_boundaries_remain_typed_false(self):
        for key in self.report()['boundaries']:
            for value in (True, 0, 'false'):
                with self.subTest(boundary=key, value=value):
                    self.restore()
                    report = self.report()
                    report['boundaries'][key] = value
                    self.save_report(report, sync=False)
                    self.reject('UI theme report.boundaries')
        for field in ('native_pointer_or_click_verified', 'samples', 'button_logical_xywh', 'evidence'):
            self.restore()
            report = self.report()
            report['cpu_hit_geometry'][field] = True
            self.save_report(report, sync=False)
            self.reject('cpu_hit_geometry')

    def test_scales_and_capture_inventory_are_ordered(self):
        for scales in ([100, 150, 125, 175, 200], [100, 125, 150, 175], [100, 125, 150, 175, 175],
                       [100., 125, 150, 175, 200]):
            self.restore()
            report = self.report()
            report['scales_percent'] = scales
            self.save_report(report, sync=False)
            self.reject('scales_percent')
        for change in ('missing', 'reversed', 'duplicate'):
            self.restore()
            report = self.report()
            if change == 'missing':
                report['captures'].pop()
            elif change == 'reversed':
                report['captures'].reverse()
            else:
                report['captures'][1] = copy.deepcopy(report['captures'][0])
            self.save_report(report, sync=False)
            self.reject('15 ordered captures|report/sidecar')

    def test_report_and_sidecar_identity_types_match_exactly(self):
        report = self.report()
        report['captures'][0]['scale_percent'] = 100.0
        self.save_report(report, sync=False)
        self.reject('report/sidecar.*JSON type differs')

    def test_capture_literal_fields_and_schema(self):
        changes = [('schema_version', True), ('filename', 'other.png'), ('phase', 'reloaded'),
                   ('requested', 'auto'), ('backend', 'Vulkan'), ('adapter', 'hardware'),
                   ('scale_percent', 125), ('scale_percent', 100.), ('logical_size', [321, 192]),
                   ('physical_size', [400, 240]), ('row_origin', 'bottom-left'),
                   ('alpha_representation', 'raw-associated-emissive-rgba8'),
                   ('last_good_identical_to_successful_reload', False)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                self.restore()
                # Filename mutation must not create an extra sidecar that masks
                # the actual metadata identity guard.
                report = self.report()
                report['captures'][0][key] = value
                write_json(self.output / 'theme-initial-100.png.json', report['captures'][0])
                self.save_report(report, sync=False)
                self.reject('expected|JSON type differs|backend')
        for mutate in (lambda r: r.pop('styled_text'), lambda r: r.update(extra=0)):
            self.restore()
            self.mutate_record(0, mutate)
            self.reject('metadata fields differ')

    def test_last_good_metadata_is_strict_true_only_in_final_phase(self):
        for index, value in ((0, True), (5, True), (10, None), (10, 1), (10, False)):
            self.restore()
            self.mutate_record(index, lambda r: r.update(last_good_identical_to_successful_reload=value))
            self.reject('last_good_identical')

    def test_probe_metadata_cannot_change_expected_contract(self):
        changes = [('label', 'different'), ('logical_bounds', [0., 0., 1., 1.]),
                   ('logical_bounds', [96, 36, 184, 68]), ('pixel_bounds', [0, 0, 1, 1]),
                   ('expected_rgba', [255, 0, 0, 255]), ('checked_pixels', 0),
                   ('channel_tolerance', 5), ('required_match_fraction', 0.9),
                   ('required_match_fraction', 1), ('maximum_channel_error', 0.0)]
        for key, value in changes:
            self.restore()
            self.mutate_record(0, lambda r: r['probes'][0].update({key: value}))
            self.reject('panel background')
        for mutate in (lambda r: r.update(probes={}), lambda r: r['probes'].reverse(),
                       lambda r: r['probes'].pop(), lambda r: r['probes'][0].update(extra=True),
                       lambda r: r['probes'][0].pop('label')):
            self.restore()
            self.mutate_record(0, mutate)
            self.reject('ordered probes|probe fields differ|panel background')

    def test_text_metadata_cannot_replace_or_weaken_oracle(self):
        changes = [('glyphs', []), ('font_size_css_px', 32), ('font_size_physical_px', 16),
                   ('pixel_bounds', [0, 0, 1, 1]), ('expected_ink_pixels', 0), ('checked_pixels', 1),
                   ('channel_tolerance', 255), ('required_match_fraction', 0.95), ('oracle', 'report says passed'),
                   ('human_legibility_approved', True), ('human_legibility_approved', 0), ('maximum_channel_error', True)]
        for key, value in changes:
            self.restore()
            self.mutate_record(0, lambda r: r['styled_text'].update({key: value}))
            self.reject('styled_text')
        for mutate in (lambda r: r.update(styled_text=[]), lambda r: r['styled_text'].pop('oracle'),
                       lambda r: r['styled_text'].update(extra=1)):
            self.restore()
            self.mutate_record(0, mutate)
            self.reject('styled_text fields differ')

    def test_loading_and_reload_status_are_exact_and_ordered(self):
        for mutate in (lambda r: r.update(reload_checks=[]), lambda r: r['reload_checks'].reverse(),
                       lambda r: r['reload_checks'][0].update(status='reloaded'),
                       lambda r: r['reload_checks'][0].update(api='reload_theme'),
                       lambda r: r['reload_checks'][1].update(status='loaded'),
                       lambda r: r['reload_checks'][1].update(api='load_theme'),
                       lambda r: r['reload_checks'][2].update(status='loaded'),
                       lambda r: r['reload_checks'][2].update(extra=1)):
            self.restore()
            report = self.report()
            mutate(report)
            self.save_report(report, sync=False)
            self.reject('reload_checks|invalid-theme diagnostic')

    def test_invalid_css_diagnostic_is_typed_located_and_nonblank(self):
        changes = [('file', ''), ('file', True), ('file', str(self.output / 'rejected-theme.css')),
                   ('file', str(Path(self.scratch.name) / 'active-theme.css')),
                   ('line', True), ('line', 2.0), ('line', 0), ('line', 3),
                   ('column', False), ('column', 29.0), ('column', -1), ('column', 999),
                   ('error', None), ('error', ''), ('error', 'NaN rejected'),
                   ('error', f'{self.output / "active-theme.css"}:2:29:   ')]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                self.restore()
                report = self.report()
                report['reload_checks'][2][key] = value
                self.save_report(report, sync=False)
                self.reject('invalid-theme diagnostic')

    def test_diagnostic_wording_is_not_fabricated_or_pinned(self):
        report = self.report()
        error = report['reload_checks'][2]
        error['error'] = f'{error["file"]}:2:29: another nonblank parser diagnostic'
        self.save_report(report, sync=False)
        self.assertTrue(contract.validate_outputs(self.output)['passed'])

    def test_duplicate_nonfinite_and_malformed_json(self):
        for filename in (REPORT_NAME, 'theme-initial-100.png.json'):
            for content in ('{"backend":"Dx12","backend":"Dx12"}', '{"x":NaN}', '{"x":Infinity}',
                            '{"x":-Infinity}', '{"x":1e9999}', '[]', '{}', 'not JSON'):
                with self.subTest(filename=filename, content=content):
                    self.restore()
                    (self.output / filename).write_text(content, encoding='utf-8')
                    self.reject('duplicate|non-finite|nonempty JSON|Expecting')

    def test_png_bad_framing_crc_trailing_and_non_png(self):
        filename = 'theme-initial-100.png'
        original = (self.control / filename).read_bytes()
        damaged_crc = bytearray(original)
        damaged_crc[-1] ^= 1
        for content in (b'not a PNG', original[:-1], original[:-12], original + b'extra', bytes(damaged_crc)):
            self.restore()
            (self.output / filename).write_bytes(content)
            self.reject('PNG|IEND|CRC')

    def test_png_rgba8_mode_extent_and_static_frame(self):
        for mode in ('RGB', 'L', 'P'):
            self.restore()
            self.mutate_image(0, lambda im: im.convert(mode), repair=False)
            self.reject('RGBA8')
        self.restore()
        self.mutate_image(0, lambda im: im.resize((321, 192)), repair=False)
        self.reject('wrong extent')
        self.restore()
        path = self.output / 'theme-initial-100.png'
        with Image.open(path) as im:
            first = im.copy()
        second = first.copy()
        second.putpixel((0, 0), (255, 0, 0, 255))
        first.save(path, save_all=True, append_images=[second], duration=10)
        self.reject('one static PNG frame')

    def test_sixteen_bit_rgba_is_not_converted_into_a_pass(self):
        self.restore()
        path = self.output / 'theme-initial-100.png'
        with Image.open(path) as im:
            raw = im.tobytes()
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
        scanlines = b''.join(b'\0' + b''.join(bytes((c, c)) for c in raw[y * 1280:(y + 1) * 1280]) for y in range(192))
        path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 320, 192, 16, 6, 0, 0, 0))
                         + chunk(b'IDAT', zlib.compress(scanlines)) + chunk(b'IEND', b''))
        self.reject('RGBA8')

    def test_full_frame_alpha_guard_covers_unprobed_pixels(self):
        self.mutate_image(0, lambda im: im.putpixel((310, 180), (0, 0, 0, 254)))
        self.reject('alpha must be opaque everywhere')

    def test_all_solid_probes_reject_one_bad_pixel_with_repaired_stats(self):
        for phase_index in (0, 5):
            for probe_index, (label, _, _) in enumerate(fixture_probes(phase_index == 5)):
                with self.subTest(phase_index=phase_index, probe=label):
                    self.restore()
                    probe = self.report()['captures'][phase_index]['probes'][probe_index]
                    x, y = probe['pixel_bounds'][:2]
                    rgba = tuple(probe['expected_rgba'])
                    changed = ((rgba[0] + 16) % 256,) + rgba[1:]
                    self.mutate_image(phase_index, lambda im: im.putpixel((x, y), changed))
                    self.reject('pixel probe')

    def test_wrong_panel_color_border_width_and_button_opacity_pixels(self):
        mutations = [('panel color', (100, 40), (80, 32, 128, 255)),
                     ('panel border width', (32, 25), (224, 192, 32, 255)),
                     ('button opacity', (40, 124), (128, 64, 192, 255)),
                     ('button border width', (32, 113), (64, 32, 96, 255)),
                     ('outward border', (20, 20), (224, 192, 32, 255))]
        for label, point, color in mutations:
            with self.subTest(label=label):
                self.restore()
                self.mutate_image(0, lambda im: im.putpixel(point, color))
                self.reject('pixel probe')

    def test_tolerance_four_is_accepted_but_five_fails(self):
        for delta in (4, 5):
            self.restore()
            self.mutate_image(0, lambda im: im.putpixel((100, 40), (32 + delta, 64, 96, 255)))
            if delta == 4:
                self.assertIs(contract.validate_outputs(self.output)['passed'], True)
            else:
                self.reject('pixel probe')

    def test_reported_maximum_error_must_be_recomputed(self):
        for target in ('panel', 'text'):
            self.restore()
            point = (100, 40) if target == 'panel' else (36, 36)
            self.mutate_image(0, lambda im: im.putpixel(point, (33, 64, 96, 255)), repair=False)
            self.reject('maximum_channel_error')

    def test_independent_known_glyph_samples_and_ink_counts(self):
        size, raw, ink = rational_text(False, 100)
        im = Image.frombytes('RGBA', size, raw)
        self.assertEqual(ink, 32)  # 20 H cells + 12 I cells, all 1x1 at 100%.
        for x, y in ((41, 52), (46, 59), (43, 55), (66, 52), (67, 56)):
            self.assertEqual(im.getpixel((x - 36, y - 36)), (64, 224, 128, 255))
        for x, y in ((42, 52), (45, 59), (65, 55), (40, 52), (68, 56)):
            self.assertEqual(im.getpixel((x - 36, y - 36)), (32, 64, 96, 255))
        self.assertEqual(rational_text(True, 100)[2], 128)
        self.assertEqual(contract._round_positive(32.5), 33)
        self.assertEqual(contract._round_positive(33.5), 34)

    def test_every_scale_and_phase_text_rejects_missing_ink(self):
        for index in range(15):
            with self.subTest(index=index):
                self.restore()
                record = self.report()['captures'][index]
                reloaded = record['phase'] != 'initial'
                size, pixels, _ = rational_text(reloaded, record['scale_percent'])
                text = Image.frombytes('RGBA', size, pixels)
                bg = (80, 32, 128, 255) if reloaded else (32, 64, 96, 255)
                x0, y0 = record['styled_text']['pixel_bounds'][:2]
                point = next((x + x0, y + y0) for y in range(text.height) for x in range(text.width)
                             if max(abs(a - b) for a, b in zip(text.getpixel((x, y)), bg)) > 4)
                self.mutate_image(index, lambda im: im.putpixel(point, bg))
                self.reject('styled H/I raster')

    def test_text_negative_space_wrong_color_missing_stroke_and_flip(self):
        changes = [('filled H hole', lambda im: im.putpixel((42, 52), (64, 224, 128, 255))),
                   ('wrong glyph color', lambda im: im.putpixel((41, 52), (255, 0, 255, 255))),
                   ('missing crossbar', lambda im: im.putpixel((43, 55), (32, 64, 96, 255))),
                   ('flip', lambda im: im.transpose(Image.Transpose.FLIP_TOP_BOTTOM))]
        for label, mutate in changes:
            with self.subTest(label=label):
                self.restore()
                if label == 'flip':
                    def flip_only_text(image):
                        box = (36, 36, 80, 68)
                        image.paste(mutate(image.crop(box)), box[:2])
                    self.mutate_image(0, flip_only_text)
                else:
                    self.mutate_image(0, mutate)
                self.reject('styled H/I raster')

    def test_wrong_font_size_and_text_opacity_all_fractional_scales(self):
        for index in (1, 2, 3, 6, 7, 8):
            for kind in ('size', 'alpha'):
                with self.subTest(index=index, kind=kind):
                    self.restore()
                    record = self.report()['captures'][index]
                    reloaded = index >= 5
                    kwargs = {'font_size': 16 if reloaded else 32} if kind == 'size' else {'alpha': 255 if reloaded else 127}
                    size, pixels, _ = rational_text(reloaded, record['scale_percent'], **kwargs)
                    box = record['styled_text']['pixel_bounds']
                    self.mutate_image(index, lambda im: im.paste(Image.frombytes('RGBA', size, pixels), box[:2]))
                    self.reject('styled H/I raster')

    def test_text_tolerance_and_true_statistics(self):
        self.mutate_image(0, lambda im: im.putpixel((41, 52), (68, 224, 128, 255)))
        self.assertIs(contract.validate_outputs(self.output)['passed'], True)
        self.restore()
        self.mutate_image(0, lambda im: im.putpixel((41, 52), (69, 224, 128, 255)))
        self.reject('styled H/I raster')

    def test_pixel_rescaling_cannot_pass_by_forging_report(self):
        self.mutate_image(1, lambda im: fixture_image(False, 100).resize(im.size, Image.Resampling.NEAREST))
        self.reject('pixel probe|styled H/I raster')

    def test_last_good_is_byte_exact_decoded_pixels_not_just_probes(self):
        for index in range(10, 15):
            with self.subTest(index=index):
                self.restore()
                # Outside all probes; <= tolerance still must fail exact retention.
                self.mutate_image(index, lambda im: im.putpixel((im.width - 1, im.height - 1), (1, 0, 0, 255)))
                self.reject('last-good pixels differ')

    def test_last_good_accepts_different_png_compression_same_pixels(self):
        path = self.output / 'theme-invalid-last-good-100.png'
        before = path.read_bytes()
        with Image.open(path) as im:
            image = im.copy()
        image.save(path, compress_level=0)
        self.assertNotEqual(path.read_bytes(), before)
        self.assertIs(contract.validate_outputs(self.output)['passed'], True)

    def test_ci_identity_uses_real_context_validation(self):
        import build_identity
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'RHS059/rust_duty',
               'GITHUB_RUN_NUMBER': '17', 'GITHUB_RUN_ID': '12345', 'GITHUB_RUN_ATTEMPT': '2',
               'GITHUB_SHA': 'a' * 40, 'GITHUB_REF_NAME': 'test/ui-theme',
               'RUST_DUTY_BUILD_VERSION': build_identity.package_version()}
        report = self.report()
        report['build_version'] = build_identity.package_version()
        self.save_report(report, sync=False)
        with patch.dict(os.environ, env):
            self.assertIs(contract.validate_outputs(self.output)['passed'], True)
            for key, value in [('GITHUB_RUN_ATTEMPT', '3'), ('GITHUB_RUN_ID', '999'),
                               ('GITHUB_SHA', 'invalid'), ('RUST_DUTY_BUILD_VERSION', '99.0.0')]:
                with self.subTest(key=key), patch.dict(os.environ, {key: value}):
                    self.reject('build identity|invalid exact source|build version')
        report['build_version'] = '99.0.0'
        self.save_report(report, sync=False)
        with patch.dict(os.environ, env):
            self.reject('build identity')

    def test_cli_entrypoint_good_and_bad_inputs(self):
        stdout = io.StringIO()
        with patch('sys.stdout', stdout):
            self.assertEqual(contract.main([str(self.output)]), 0)
        self.assertIs(json.loads(stdout.getvalue())['passed'], True)
        (self.output / 'active-theme.css').write_text('bad', encoding='utf-8')
        with patch('sys.stderr', io.StringIO()) as stderr:
            with self.assertRaises(SystemExit) as raised:
                contract.main([str(self.output)])
        self.assertEqual(raised.exception.code, 1)
        self.assertIn('CSS bytes differ', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()

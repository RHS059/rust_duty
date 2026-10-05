"""Synthetic fixture outputs only; never proof of native Windows DX12 output."""

import functools
import io
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import unittest
import zlib
from unittest.mock import patch

from PIL import Image, ImageDraw

import run_dx12_game_ui_fixture as fixture

GOLD = (255, 194, 51, 255)
WHITE = (255, 255, 255, 255)
FULL_TEXT = (224, 237, 222, 255)
ACCENT = (250, 158, 56, 255)
OVERLAY = (6, 9, 12, 255)
PROGRESS = {'idle': 0.0, 'half': 0.5, 'complete': 1.0, 'ammo-full': 0.0}


def prompt(percent, case, caption=True):
    """A stand-in prompt: clockwise gold sweep while held, key glyph and caption."""
    s = percent // 100
    w, h = fixture.LOGICAL_SIZE
    image = Image.new('RGBA', (w * s, h * s), (0, 0, 0, 255))
    draw = ImageDraw.Draw(image)
    if case == 'ammo-full':
        draw.rectangle((205 * s, 112 * s, 275 * s - 1, 120 * s - 1), fill=FULL_TEXT)
        return image
    sweep = {'half': 0.5, 'complete': 1.0}.get(case)
    if sweep:
        cx, cy, r = 240 * s, 120 * s, 19 * s
        for y in range(cy - r, cy + r):
            for x in range(cx - r, cx + r):
                dx, dy = x + 0.5 - cx, y + 0.5 - cy
                angle = math.atan2(dx, -dy) % (2 * math.pi)  # 0 at twelve, clockwise
                if dx * dx + dy * dy <= r * r and angle <= sweep * 2 * math.pi:
                    image.putpixel((x, y), GOLD)
    draw.rectangle((236 * s, 112 * s, 244 * s - 1, 126 * s - 1), fill=WHITE)
    if caption:
        draw.rectangle((200 * s, 150 * s, 280 * s - 1, 158 * s - 1), fill=WHITE)
    return image


def ui(percent, case, corners=4, accent=True):
    """Stand-ins for the menu, updater and HUD that satisfy their documented rules."""
    s = percent // 100
    w, h = fixture.LOGICAL_SIZE
    image = Image.new('RGBA', (w * s, h * s), (0, 0, 0, 255))
    draw = ImageDraw.Draw(image)

    def box(x0, y0, x1, y1, fill):
        draw.rectangle((x0 * s, y0 * s, x1 * s - 1, y1 * s - 1), fill=fill)
    if case == 'pause-menu':
        box(0, 0, w, h, OVERLAY)
        box(300, 40, 660, 100, WHITE)
        if accent:
            box(300, 120, 500, 130, ACCENT)
    elif case.startswith('updater-'):
        box(180, 90, 780, 240, OVERLAY)
        if accent:
            box(196, 100, 400 if case == 'updater-current' else 440, 106, GOLD)
        box(196, 120, 500, 126, WHITE)
    else:
        for x0, y0, _, _ in fixture.CORNERS[:corners]:
            box(x0 + 10, y0 + 10, x0 + 60, y0 + 20, WHITE)
        if case == 'hud-telemetry':
            box(40, 140, 300, 160, WHITE)
    return image


@functools.lru_cache(maxsize=None)
def cached(percent, case):
    if case in fixture.AMMO:
        return prompt(percent, fixture.AMMO[case][0])
    return ui(percent, case)


def capture(percent, case):
    return cached(percent, case).copy()


def ink(image, percent, case):
    s = percent // 100
    if case in fixture.AMMO:
        return fixture.measure(image, s, fixture.AMMO[case][2])
    return fixture.measure_ui(image, s)


def parameters(case):
    if case in fixture.AMMO:
        name, _, full = fixture.AMMO[case]
        return {'progress': PROGRESS[name], 'ammo_full': full, 'anchor_logical': [240.0, 120.0]}
    return dict(fixture.PARAMETERS[case])


class GameUiFixtureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / 'out'
        self.output.mkdir()
        captures = []
        for percent in fixture.SCALES:
            for case in fixture.CASES:
                name = f'{case}-{percent}.png'
                image = capture(percent, case)
                image.save(self.output / name)
                s = percent // 100
                sidecar = {'schema_version': 2, 'filename': name, 'element': fixture.ELEMENTS.get(case, 'ammo-hint'),
                           'case': case, 'parameters': parameters(case), 'requested': 'dx12', 'backend': 'Dx12',
                           'adapter': fixture.WARP, 'scale_percent': percent, 'logical_size': [960, 540],
                           'physical_size': [960 * s, 540 * s], 'ink': ink(image, percent, case)}
                self.write(f'{name}.json', sidecar)
                captures.append(sidecar)
        self.write(fixture.REPORT, {
            'schema_version': 2, 'status': 'passed', 'native_execution': True, 'requested': 'dx12',
            'backend': 'Dx12', 'adapter': fixture.WARP, 'force_fallback_adapter': True, 'platform': 'windows',
            'build_version': '0.1.11', 'build_number': '37339601251', 'live_logical_viewport': [960, 540],
            'scales_percent': [100, 200], 'cases': list(fixture.CASES), 'captures': captures,
            'elements_covered': fixture.ELEMENTS_COVERED,
            'compiler_identity_source': fixture.COMPILER_SOURCE, 'scope': fixture.SCOPE,
            'boundaries': fixture.BOUNDARIES})

    def write(self, name, value):
        (self.output / name).write_text(json.dumps(value), encoding='utf-8')

    def read(self, name):
        return json.loads((self.output / name).read_text())

    def edit(self, name, **fields):
        value = self.read(name)
        value.update(fields)
        self.write(name, value)

    def sync_report(self):
        """Keep the report's capture list equal to the sidecars, so only the probed field differs."""
        report = self.read(fixture.REPORT)
        report['captures'] = [self.read(f'{c}-{p}.png.json') for p in fixture.SCALES for c in fixture.CASES]
        self.write(fixture.REPORT, report)

    def replace(self, name, image, percent):
        image.save(self.output / name)
        case = name[:-len(f'-{percent}.png')]
        self.edit(f'{name}.json', ink=ink(image.convert('RGBA'), percent, case))
        self.sync_report()

    def rejects(self, pattern=None):
        if pattern:
            with self.assertRaisesRegex(ValueError, pattern):
                fixture.validate_outputs(self.output)
        else:
            with self.assertRaises(ValueError):
                fixture.validate_outputs(self.output)

    def test_synthetic_control_passes(self):
        summary = fixture.validate_outputs(self.output)
        self.assertTrue(summary['passed'])
        self.assertEqual(summary['captures'], 18)
        self.assertEqual(summary['elements_covered'], fixture.ELEMENTS_COVERED)

    def test_report_identity_schema_platform_and_build_are_exact(self):
        for field, value in [('status', 'failed'), ('native_execution', False), ('backend', 'Vulkan'),
                             ('adapter', 'NVIDIA'), ('force_fallback_adapter', False), ('requested', 'auto'),
                             ('schema_version', 1), ('schema_version', True), ('platform', 'linux'),
                             ('build_version', 'dev'), ('build_number', ''), ('scales_percent', [100]),
                             ('scales_percent', [100.0, 200.0]), ('elements_covered', ['ammo-hint']),
                             ('live_logical_viewport', [480, 270]), ('live_logical_viewport', [960.0, 540.0]),
                             ('cases', list(fixture.CASES[:-1])), ('elements_pending', {}),
                             ('scope', 'anything'), ('boundaries', dict(fixture.BOUNDARIES, human_legibility_approved=True)),
                             ('unexpected', 1)]:
            original = (self.output / fixture.REPORT).read_bytes()
            self.edit(fixture.REPORT, **{field: value})
            with self.subTest(field=field, value=value):
                self.rejects()
            (self.output / fixture.REPORT).write_bytes(original)

    def test_report_captures_must_equal_the_sidecars(self):
        self.edit(fixture.REPORT, captures=[None] * 18)
        self.rejects('capture entry vs sidecar')

    def test_sidecar_identity_and_types_are_exact(self):
        name = 'ammo-half-200.png.json'
        for field, value in [('requested', 'auto'), ('adapter', 'NVIDIA'), ('filename', 'ammo-half-100.png'),
                             ('physical_size', [960, 540]), ('scale_percent', 200.0), ('schema_version', 1),
                             ('case', 'ammo-complete'), ('element', 'hud'), ('logical_size', [960.0, 540.0])]:
            original = (self.output / name).read_bytes()
            self.edit(name, **{field: value})
            self.sync_report()
            with self.subTest(field=field, value=value):
                self.rejects('sidecar identity mismatch')
            (self.output / name).write_bytes(original)
            self.sync_report()

    def test_parameters_are_exact_and_typed(self):
        for name, change in [('ammo-half-200.png.json', {'progress': 0.25}),
                             ('ammo-half-200.png.json', {'progress': True}),
                             ('ammo-half-200.png.json', {'ammo_full': 0}),
                             ('ammo-half-200.png.json', {'anchor_logical': [241.0, 120.0]}),
                             ('ammo-half-200.png.json', {'anchor_logical': [True, 120.0]}),
                             ('pause-menu-100.png.json', {'initial': 0}),
                             ('pause-menu-100.png.json', {'weapon': 'm4'}),
                             ('updater-current-100.png.json', {'phase': 'unavailable'}),
                             ('hud-telemetry-200.png.json', {'debug': False}),
                             ('hud-200.png.json', {'extra': 1})]:
            original = (self.output / name).read_bytes()
            self.edit(name, parameters=dict(self.read(name)['parameters'], **change))
            self.sync_report()
            with self.subTest(name=name, change=change):
                self.rejects('parameters')
            (self.output / name).write_bytes(original)
            self.sync_report()

    def test_masks_match_reference_predicates(self):
        image = Image.new('RGBA', (64, 64))
        pixels = [(r, g, b, 255) for r in range(0, 256, 17) for g in range(0, 256, 17) for b in (0, 50, 95, 96, 110, 111, 200, 255)]
        image.putdata((pixels * (4096 // len(pixels) + 1))[:4096])
        masks = fixture.masks(image)
        rgba = image.tobytes()
        for i, (lit, white, gold, warm) in enumerate(zip(*(masks[k].tobytes() for k in ('lit', 'white', 'gold', 'warm')))):
            p = tuple(rgba[4 * i:4 * i + 4])
            self.assertEqual((lit, white, gold, warm),
                             tuple(255 if v else 0 for v in (p[:3] != (0, 0, 0), fixture.is_white(p),
                                                             fixture.is_gold(p), fixture.is_warm(p))), p)

    def test_menu_without_centred_accent_fails(self):
        self.replace('pause-menu-100.png', ui(100, 'pause-menu', accent=False), 100)
        self.rejects('pause-menu')

    def test_updater_without_gold_title_fails(self):
        self.replace('updater-unavailable-200.png', ui(200, 'updater-unavailable', accent=False), 200)
        self.rejects('updater-unavailable')

    def test_hud_missing_a_corner_fails(self):
        self.replace('hud-100.png', ui(100, 'hud', corners=3), 100)
        self.rejects('every HUD corner')

    def test_telemetry_panel_must_add_ink(self):
        image = ui(200, 'hud')
        ImageDraw.Draw(image).rectangle((1000, 600, 1010, 610), fill=WHITE)
        self.replace('hud-telemetry-200.png', image, 200)
        self.rejects('telemetry panel missing')

    def test_ink_counters_must_be_integers_matching_the_pixels(self):
        name = 'ammo-complete-100.png.json'
        ink = self.read(name)['ink']
        for change in [{'gold_left': True}, {'lit_pixels': float(ink['lit_pixels'])},
                       {'lit_bounds': [float(v) for v in ink['lit_bounds']]}, {'caption_white': ink['caption_white'] + 1},
                       {'extra': 0}]:
            self.edit(name, ink=dict(ink, **change))
            self.sync_report()
            with self.subTest(change=change):
                self.rejects()
        self.edit(name, ink=ink)
        self.sync_report()

    def test_transparent_or_rgb_png_is_rejected(self):
        transparent = prompt(100, 'idle')
        transparent.putpixel((0, 0), (0, 0, 0, 254))
        self.replace('ammo-idle-100.png', transparent, 100)
        self.rejects()
        rgb = prompt(100, 'idle').convert('RGB')
        rgb.save(self.output / 'ammo-idle-100.png')
        self.rejects('8-bit RGBA')

    def test_rgba16_png_is_rejected(self):
        # Pillow decodes RGBA16 as RGBA; the IHDR must still say 8-bit colour type 6.
        width, height = 960, 540
        raw = b''.join(b'\x00' + (b'\x00\x00\x00\x00\x00\x00\xff\xff' * width) for _ in range(height))

        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
        png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 16, 6, 0, 0, 0))
               + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
        (self.output / 'ammo-idle-100.png').write_bytes(png)
        self.rejects()

    def test_build_identity_is_this_package_and_ci_attempt(self):
        for version in ('not.a.version', '9.9.9'):
            self.edit(fixture.REPORT, build_version=version)
            with self.subTest(version=version):
                self.rejects('build identity')
        self.edit(fixture.REPORT, build_version='0.1.11', build_number='1.1')
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'RHS059/rust_duty', 'GITHUB_RUN_NUMBER': '7',
               'GITHUB_RUN_ID': '37339601251', 'GITHUB_RUN_ATTEMPT': '2', 'GITHUB_SHA': 'a' * 40,
               'GITHUB_REF_NAME': 'aella/wgpu-renderer-port'}
        with patch.dict(fixture.os.environ, env, clear=False):
            self.rejects('this CI attempt')  # another attempt's build number
            self.edit(fixture.REPORT, build_number='37339601251.2')
            fixture.validate_outputs(self.output)

    def test_type_exact_report_fields_and_capture_entries(self):
        self.edit(fixture.REPORT, boundaries=dict(fixture.BOUNDARIES, os_dpi_events_verified=0))
        self.rejects('JSON type differs')
        self.setUp()
        report = self.read(fixture.REPORT)
        for field, value in [('scale_percent', 100.0), ('schema_version', 2.0), ('parameters', {})]:
            entries = json.loads(json.dumps(report['captures']))
            entries[0][field] = value
            self.edit(fixture.REPORT, captures=entries)
            with self.subTest(field=field):
                self.rejects('capture entry vs sidecar')
        self.edit(fixture.REPORT, captures=report['captures'])
        fixture.validate_outputs(self.output)

    def test_truncated_png_is_rejected(self):
        path = self.output / 'ammo-idle-100.png'
        path.write_bytes(path.read_bytes()[:-1])
        self.rejects()

    def test_symlinked_png_is_rejected(self):
        real = self.root / 'elsewhere.png'
        target = self.output / 'ammo-idle-100.png'
        target.rename(real)
        try:
            os.symlink(real, target)
        except OSError as error:
            self.skipTest(f'host cannot create symlinks: {error}')
        self.rejects('no links')

    def test_missing_extra_files_fail(self):
        (self.output / 'stray.txt').write_text('x')
        self.rejects('unexpected files')

    def test_missing_caption_in_held_states_fails(self):
        for percent in fixture.SCALES:
            for case in ('half', 'complete'):
                self.replace(f'ammo-{case}-{percent}.png', prompt(percent, case, caption=False), percent)
        self.rejects('caption text is missing')

    def test_gold_circle_where_none_may_be_drawn_fails(self):
        self.replace('ammo-idle-100.png', prompt(100, 'half'), 100)
        self.rejects('idle: no hold circle')

    def test_ammo_full_showing_the_hold_prompt_fails(self):
        self.replace('ammo-full-100.png', prompt(100, 'idle'), 100)
        self.rejects('only the AMMO FULL text')

    def test_counter_clockwise_sweep_fails(self):
        # Mirror the prompt about the anchor's vertical axis (x = 240).
        mirrored = Image.new('RGBA', fixture.LOGICAL_SIZE, (0, 0, 0, 255))
        mirrored.paste(prompt(100, 'half').crop((0, 0, 480, 540)).transpose(Image.Transpose.FLIP_LEFT_RIGHT), (0, 0))
        self.replace('ammo-half-100.png', mirrored, 100)
        self.rejects('right of the anchor')

    def test_no_growth_between_half_and_complete_fails(self):
        self.replace('ammo-complete-100.png', prompt(100, 'half'), 100)
        self.rejects()

    def test_stray_ink_outside_the_prompt_fails(self):
        image = prompt(200, 'idle')
        image.putpixel((4, 4), WHITE)
        self.replace('ammo-idle-200.png', image, 200)
        self.rejects('escape')

    def test_unscaled_200_percent_capture_fails(self):
        big = Image.new('RGBA', (1920, 1080), (0, 0, 0, 255))
        big.paste(prompt(100, 'idle'), (0, 0))
        self.replace('ammo-idle-200.png', big, 200)
        self.rejects()

    def test_cli_refuses_non_windows(self):
        with patch.object(fixture.sys, 'platform', 'linux'), patch.object(fixture.dx12_contract_process, 'run') as run, \
                patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit) as exit:
            fixture.main(['--executable', 'x', '--evidence', 'e', '--output', 'o'])
        self.assertEqual(exit.exception.code, 1)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()

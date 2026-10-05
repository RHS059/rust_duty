"""Synthetic fixture outputs only; never proof of native Windows DX12 output."""

import io
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import run_dx12_game_ui_fixture as fixture

GOLD = (255, 194, 51, 255)
WHITE = (255, 255, 255, 255)
FULL_TEXT = (224, 237, 222, 255)
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


class GameUiFixtureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / 'out'
        self.output.mkdir()
        captures = []
        for percent in fixture.SCALES:
            for case, _, full in fixture.CASES:
                name = f'ammo-{case}-{percent}.png'
                image = prompt(percent, case)
                image.save(self.output / name)
                s = percent // 100
                sidecar = {'schema_version': 1, 'filename': name, 'element': 'ammo-hint', 'case': case,
                           'progress': PROGRESS[case], 'ammo_full': full, 'requested': 'dx12', 'backend': 'Dx12',
                           'adapter': fixture.WARP, 'scale_percent': percent, 'logical_size': [480, 270],
                           'physical_size': [480 * s, 270 * s], 'anchor_logical': [240.0, 120.0],
                           'ink': fixture.measure(image, s, full)}
                self.write(f'{name}.json', sidecar)
                captures.append(sidecar)
        self.write(fixture.REPORT, {
            'schema_version': 1, 'status': 'passed', 'native_execution': True, 'requested': 'dx12',
            'backend': 'Dx12', 'adapter': fixture.WARP, 'force_fallback_adapter': True, 'platform': 'windows',
            'build_version': '0.1.11', 'build_number': '37339601251', 'scales_percent': [100, 200],
            'captures': captures, 'elements_covered': ['ammo-hint'],
            'elements_pending': {'pause-menu': 'pending', 'updater-panel': 'pending'},
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
        report['captures'] = [self.read(f'ammo-{c}-{p}.png.json') for p in fixture.SCALES for c, _, _ in fixture.CASES]
        self.write(fixture.REPORT, report)

    def replace(self, name, image, percent, full=False):
        image.save(self.output / name)
        self.edit(f'{name}.json', ink=fixture.measure(image.convert('RGBA'), percent // 100, full))
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
        self.assertEqual(summary['captures'], 8)

    def test_report_identity_schema_platform_and_build_are_exact(self):
        for field, value in [('status', 'failed'), ('native_execution', False), ('backend', 'Vulkan'),
                             ('adapter', 'NVIDIA'), ('force_fallback_adapter', False), ('requested', 'auto'),
                             ('schema_version', 2), ('schema_version', True), ('platform', 'linux'),
                             ('build_version', 'dev'), ('build_number', ''), ('scales_percent', [100]),
                             ('scales_percent', [100.0, 200.0]), ('elements_covered', ['ammo-hint', 'menu']),
                             ('scope', 'anything'), ('boundaries', dict(fixture.BOUNDARIES, human_legibility_approved=True)),
                             ('unexpected', 1)]:
            original = (self.output / fixture.REPORT).read_bytes()
            self.edit(fixture.REPORT, **{field: value})
            with self.subTest(field=field, value=value):
                self.rejects()
            (self.output / fixture.REPORT).write_bytes(original)

    def test_report_captures_must_equal_the_sidecars(self):
        self.edit(fixture.REPORT, captures=[None] * 8)
        self.rejects('differs from its sidecar')

    def test_sidecar_identity_and_types_are_exact(self):
        name = 'ammo-half-200.png.json'
        for field, value in [('requested', 'auto'), ('adapter', 'NVIDIA'), ('progress', 0.25),
                             ('progress', True), ('filename', 'ammo-half-100.png'),
                             ('physical_size', [480, 270]), ('anchor_logical', [241.0, 120.0]),
                             ('anchor_logical', [True, 120.0]), ('scale_percent', 200.0),
                             ('case', 'complete'), ('ammo_full', 0), ('logical_size', [480.0, 270.0])]:
            original = (self.output / name).read_bytes()
            self.edit(name, **{field: value})
            self.sync_report()
            with self.subTest(field=field, value=value):
                self.rejects('sidecar identity mismatch')
            (self.output / name).write_bytes(original)
            self.sync_report()

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
        self.rejects('RGBA8')

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
        self.replace('ammo-ammo-full-100.png', prompt(100, 'idle'), 100, full=True)
        self.rejects('only the AMMO FULL text')

    def test_counter_clockwise_sweep_fails(self):
        mirrored = prompt(100, 'half').transpose(Image.Transpose.FLIP_LEFT_RIGHT)
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
        big = Image.new('RGBA', (960, 540), (0, 0, 0, 255))
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

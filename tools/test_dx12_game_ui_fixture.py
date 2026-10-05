"""Synthetic fixture outputs only; never proof of native Windows DX12 output."""

import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import run_dx12_game_ui_fixture as fixture

GOLD = (255, 194, 51, 255)
WHITE = (255, 255, 255, 255)


def prompt(percent, case):
    """A stand-in prompt: caption bar, plus a clockwise gold sweep while held."""
    s = percent // 100
    w, h = fixture.LOGICAL_SIZE
    image = Image.new('RGBA', (w * s, h * s), (0, 0, 0, 255))
    draw = ImageDraw.Draw(image)
    if case == 'ammo-full':
        draw.rectangle((205 * s, 112 * s, 275 * s - 1, 120 * s - 1), fill=WHITE)
        return image
    draw.rectangle((200 * s, 150 * s, 280 * s - 1, 158 * s - 1), fill=WHITE)
    sweep = {'half': 0.5, 'complete': 1.0}.get(case)
    if sweep:
        cx, cy, r = 240 * s, 120 * s, 19 * s
        for y in range(cy - r, cy + r):
            for x in range(cx - r, cx + r):
                dx, dy = x + 0.5 - cx, y + 0.5 - cy
                angle = math.atan2(dx, -dy) % (2 * math.pi)  # 0 at twelve, clockwise
                if dx * dx + dy * dy <= r * r and angle <= sweep * 2 * math.pi:
                    image.putpixel((x, y), GOLD)
    return image


class GameUiFixtureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name) / 'out'
        self.output.mkdir()
        captures = []
        for percent in fixture.SCALES:
            for case, progress, full in fixture.CASES:
                name = f'ammo-{case}-{percent}.png'
                image = prompt(percent, case)
                image.save(self.output / name)
                sidecar = {'schema_version': 1, 'filename': name, 'element': 'ammo-hint', 'case': case,
                           'progress': progress, 'ammo_full': full, 'requested': 'dx12', 'backend': 'Dx12',
                           'adapter': fixture.WARP, 'scale_percent': percent,
                           'ink': fixture.measure(image, percent / 100)}
                self.write(f'{name}.json', sidecar)
                captures.append(sidecar)
        self.write(fixture.REPORT, {'schema_version': 1, 'status': 'passed', 'native_execution': True,
                                    'requested': 'dx12', 'backend': 'Dx12', 'adapter': fixture.WARP,
                                    'force_fallback_adapter': True, 'captures': captures})

    def write(self, name, value):
        (self.output / name).write_text(json.dumps(value), encoding='utf-8')

    def edit(self, name, **fields):
        path = self.output / name
        value = json.loads(path.read_text())
        value.update(fields)
        path.write_text(json.dumps(value))

    def replace(self, name, image, percent):
        image.save(self.output / name)
        self.edit(f'{name}.json', ink=fixture.measure(image, percent / 100))

    def test_synthetic_control_passes(self):
        summary = fixture.validate_outputs(self.output)
        self.assertTrue(summary['passed'])
        self.assertEqual(summary['captures'], 8)

    def test_report_identity_is_required(self):
        for field, value in [('status', 'failed'), ('native_execution', False), ('backend', 'Vulkan'),
                             ('adapter', 'NVIDIA'), ('force_fallback_adapter', False), ('requested', 'auto')]:
            original = (self.output / fixture.REPORT).read_bytes()
            self.edit(fixture.REPORT, **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                fixture.validate_outputs(self.output)
            (self.output / fixture.REPORT).write_bytes(original)

    def test_missing_extra_and_wrong_sidecar_fail(self):
        (self.output / 'stray.txt').write_text('x')
        with self.assertRaisesRegex(ValueError, 'unexpected files'):
            fixture.validate_outputs(self.output)
        (self.output / 'stray.txt').unlink()
        self.edit('ammo-half-100.png.json', case='complete')
        with self.assertRaisesRegex(ValueError, 'identity'):
            fixture.validate_outputs(self.output)

    def test_recorded_ink_must_match_the_pixels(self):
        self.edit('ammo-idle-200.png.json', ink={'lit_pixels': 1, 'lit_bounds': None, 'gold_left': 0, 'gold_right': 0})
        with self.assertRaisesRegex(ValueError, 'independent measurement'):
            fixture.validate_outputs(self.output)

    def test_gold_circle_where_none_may_be_drawn_fails(self):
        self.replace('ammo-idle-100.png', prompt(100, 'half'), 100)
        with self.assertRaisesRegex(ValueError, 'idle: no hold circle'):
            fixture.validate_outputs(self.output)

    def test_counter_clockwise_sweep_fails(self):
        mirrored = prompt(100, 'half').transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        self.replace('ammo-half-100.png', mirrored, 100)
        with self.assertRaisesRegex(ValueError, 'right of the anchor'):
            fixture.validate_outputs(self.output)

    def test_no_growth_between_half_and_complete_fails(self):
        self.replace('ammo-complete-100.png', prompt(100, 'half'), 100)
        with self.assertRaises(ValueError):
            fixture.validate_outputs(self.output)

    def test_stray_ink_outside_the_prompt_fails(self):
        image = prompt(200, 'idle')
        image.putpixel((4, 4), WHITE)
        self.replace('ammo-idle-200.png', image, 200)
        with self.assertRaisesRegex(ValueError, 'escape'):
            fixture.validate_outputs(self.output)

    def test_unscaled_200_percent_capture_fails(self):
        small = prompt(100, 'idle')
        big = Image.new('RGBA', (960, 540), (0, 0, 0, 255))
        big.paste(small, (0, 0))
        self.replace('ammo-idle-200.png', big, 200)
        with self.assertRaises(ValueError):
            fixture.validate_outputs(self.output)

    def test_non_opaque_or_truncated_png_fails(self):
        path = self.output / 'ammo-idle-100.png'
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaises(ValueError):
            fixture.validate_outputs(self.output)

    def test_cli_refuses_non_windows(self):
        with patch.object(fixture.sys, 'platform', 'linux'), patch.object(fixture.dx12_contract_process, 'run') as run, \
                patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit) as exit:
            fixture.main(['--executable', 'x', '--evidence', 'e', '--output', 'o'])
        self.assertEqual(exit.exception.code, 1)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()

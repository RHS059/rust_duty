"""Adversarial false-acceptance probes for run_dx12_authored.py.

Synthetic inputs only; never proof of native Windows output.
Frame binding uses explicit independently supplied capture identities.
"""

import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import run_dx12_authored as authored
from test_capture_frame_witness import marker, SCHEMA as WITNESS_SCHEMA

SOURCE_ROOT = Path(authored.__file__).resolve().parents[1]


class AdversarialAuthoredTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pngs = []
        for index in range(3):
            image = Image.new('RGBA', (960, 540), (36, 48, 61, 255))
            # Distinct content per frame so swaps are observable in principle.
            ImageDraw.Draw(image).rectangle((200 + 40 * index, 100, 700, 420), fill=(120, 90, 60, 255))
            image.paste(marker(index, 'a' * 64).crop((0, 0, 64, 22)), (0, 0))
            output = io.BytesIO()
            image.save(output, format='PNG')
            cls.pngs.append(output.getvalue())

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.captures = self.root / 'candidate'
        self.baseline = self.root / 'legacy'
        self.sequence(self.captures)
        self.sequence(self.baseline, 'OpenGl')
        self.verdict(self.baseline / 'verification.json')
        (self.root / 'settings.cfg').write_text('# synthetic\n', encoding='utf-8')

    def sequence(self, folder, backend='Dx12'):
        folder.mkdir(parents=True)
        for index in range(3):
            image = folder / f'{index:04}.png'
            image.write_bytes(self.pngs[index])
            authored.write_json(Path(f'{image}.json'), {
                'backend': backend, 'adapter': authored.WARP if backend == 'Dx12' else 'llvmpipe',
                'requested': 'dx12' if backend == 'Dx12' else 'legacy-default',
                'width': 960, 'height': 540, 'ads': 0.0 if index == 0 else 1.0, 'hfov': 76.0,
                'frame_witness': {'schema': WITNESS_SCHEMA, 'frame_index': index, 'capture_identity': 'a' * 64}})
            authored.write_json(Path(f'{image}.time.json'), {
                'elapsed_seconds': index / 60, 'sampling_hz': 60})
            authored.write_json(Path(f'{image}.gameplay.json'), {
                'simulation_time': index / 60, 'route': 'ready' if index == 0 else 'ads.hold',
                'run_weight': 0, 'speed': 0, 'simulation_ads': 0 if index == 0 else 1,
                'renderer_failed': False, 'pose': {'yaw': 0.5, 'contact': [1.0, 2.0]}})

    def verdict(self, path, **fields):
        authored.write_json(path, {'schema': 'synthetic', 'passed': True, 'frames': 3, **fields})

    def edit(self, folder, index, suffix, field, value):
        path = folder / f'{index:04}.png{suffix}'
        row = json.loads(path.read_text())
        if value is KeyError:
            del row[field]
        else:
            row[field] = value
        authored.write_json(path, row)

    def accepted(self):
        """True when both production candidate checks accept the evidence."""
        try:
            authored.validate_sequence(self.captures, expected_witness_identity='a' * 64)
            authored.compare_sequence(self.baseline, self.captures)
        except ValueError:
            return False
        return True

    # Regressions that hold on 72663e2.

    def test_control_is_accepted(self):
        self.assertTrue(self.accepted())

    def test_omitted_trailing_frame_is_rejected(self):
        for path in self.captures.glob('0002.png*'):
            path.unlink()
        self.assertFalse(self.accepted())

    def test_omitted_frame_in_both_sides_still_requires_contiguous_names(self):
        for folder in (self.captures, self.baseline):
            for path in folder.glob('0001.png*'):
                path.unlink()
        self.assertFalse(self.accepted())

    def test_reordered_telemetry_is_rejected(self):
        for suffix in ('.gameplay.json', '.time.json'):
            first = self.captures / f'0000.png{suffix}'
            second = self.captures / f'0001.png{suffix}'
            a, b = first.read_bytes(), second.read_bytes()
            first.write_bytes(b)
            second.write_bytes(a)
        self.assertFalse(self.accepted())

    def test_wrong_scenario_route_is_rejected(self):
        self.edit(self.captures, 1, '.gameplay.json', 'route', 'reload.tactical')
        self.assertFalse(self.accepted())

    def test_missing_or_extra_pose_and_contact_fields_are_rejected(self):
        cases = [('pose', KeyError), ('pose', {'yaw': 0.5}), ('pose', {'yaw': 0.5, 'contact': [1.0]}),
                 ('pose', {'yaw': 0.5, 'contact': [1.0, 2.0], 'extra': 0}),
                 ('pose', {'yaw': 0.5, 'contact': [1, 2.0]}), ('extra_field', 0)]
        path = self.captures / '0001.png.gameplay.json'
        original = path.read_bytes()
        for field, value in cases:
            self.edit(self.captures, 1, '.gameplay.json', field, value)
            with self.subTest(field=field, value=value):
                self.assertFalse(self.accepted())
            path.write_bytes(original)

    def test_nonfinite_values_in_every_sidecar_kind_are_rejected(self):
        for suffix in ('.json', '.time.json', '.gameplay.json'):
            path = self.captures / f'0001.png{suffix}'
            original = path.read_text()
            for literal in ('NaN', 'Infinity', '-Infinity', '1e9999'):
                path.write_text(original[:-2] + f', "probe": {literal}}}\n')
                with self.subTest(suffix=suffix, literal=literal):
                    self.assertFalse(self.accepted())
            path.write_text(original)

    def test_wrong_backend_in_baseline_is_rejected(self):
        self.edit(self.baseline, 2, '.json', 'backend', 'Dx12')
        self.assertFalse(self.accepted())

    def test_uncaught_validator_crash_leaves_stale_free_failed_summary(self):
        game = self.root / 'game.exe'
        fixture = self.root / 'renderer_contract.exe'
        for binary in (game, fixture):
            binary.write_bytes(b'synthetic')
        output = self.root / 'out'
        with patch.object(authored, 'asset_evidence', return_value={'synthetic': True}), \
                patch.object(authored, 'execute', return_value={'synthetic': True}), \
                patch.object(authored, 'validate_orientation', return_value={}), \
                patch.object(authored, 'validate_sequence', side_effect=AttributeError('crash')):
            with self.assertRaises(AttributeError):
                authored.run(game, fixture, self.root, output, self.baseline, 10)
        saved = json.loads((output / 'summary.json').read_text())
        self.assertFalse(saved['passed'])
        self.assertFalse(saved['acceptance_complete'])

    def test_one_failed_parity_fails_an_otherwise_mocked_pass(self):
        game = self.root / 'game.exe'
        fixture = self.root / 'renderer_contract.exe'
        for binary in (game, fixture):
            binary.write_bytes(b'synthetic')
        calls = []

        def parity(baseline, candidate):
            calls.append(candidate.name)
            if candidate.name == 'layered-60':
                raise ValueError('synthetic drift')
            return {}

        with patch.object(authored, 'asset_evidence', return_value={'synthetic': True}), \
                patch.object(authored, 'execute', return_value={'synthetic': True}), \
                patch.object(authored, 'validate_orientation', return_value={}), \
                patch.object(authored, 'validate_sequence', return_value={}), \
                patch.object(authored, 'compare_sequence', side_effect=parity), \
                patch.object(authored, 'validate_lighting', return_value={}), \
                patch.object(authored, 'review_guides', return_value={}):
            report = authored.run(game, fixture, self.root, self.root / 'out', self.baseline, 10)
        self.assertEqual(len(calls), 8)
        self.assertFalse(report['passed'])

    # Gaps found on 72663e2, fixed by the parity patch.

    def test_renderer_side_camera_drift_is_rejected(self):
        # *.png.json carries presentation state (ads weight, hfov, extent,
        # reload phase) besides renderer identity; all of it must match.
        for field, value in [('hfov', 90.0), ('ads', 0.0), ('reload_phase', 0.5),
                             ('capture', 'native window'), ('extra', 1), ('hfov', KeyError)]:
            path = self.captures / '0002.png.json'
            original = path.read_bytes()
            self.edit(self.captures, 2, '.json', field, value)
            with self.subTest(field=field, value=value):
                self.assertFalse(self.accepted())
            path.write_bytes(original)

    def test_renderer_identity_fields_alone_may_differ(self):
        # Control: the candidate is Dx12/WARP/dx12 and the baseline OpenGl.
        result = authored.compare_sequence(self.baseline, self.captures)
        self.assertEqual(result['capture_metadata_files'], 3)

    # The actual PNG marker must match its own contiguous source frame.

    def test_swapped_or_stale_candidate_frames_are_rejected(self):
        # Nothing binds a PNG to its own frame: a one-frame-late readback
        # (frame N shows N-1) passes inventory, image checks and parity.
        (self.captures / '0002.png').write_bytes(self.pngs[1])
        (self.captures / '0001.png').write_bytes(self.pngs[0])
        self.assertFalse(self.accepted())

    def test_same_frame_from_other_capture_and_rewritten_metadata_are_rejected(self):
        for index in range(3):
            path = self.captures / f'{index:04}.png'
            with Image.open(path) as original:
                image = original.copy()
            image.paste(marker(index, 'b' * 64).crop((0, 0, 64, 22)), (0, 0))
            image.save(path)
            row = json.loads(Path(f'{path}.json').read_text())
            row['frame_witness']['capture_identity'] = 'b' * 64
            authored.write_json(Path(f'{path}.json'), row)
        self.assertFalse(self.accepted())

    def test_removing_witness_metadata_cannot_disable_required_binding(self):
        for index in range(3):
            self.edit(self.captures, index, '.json', 'frame_witness', KeyError)
        self.assertFalse(self.accepted())

    def test_review_rejects_boolean_stationary_ads_fields(self):
        # review_guides compares with ==, so False == 0 and True == 1 select a
        # frame whose fields are booleans rather than finite numbers.
        for index in (1, 2):
            self.edit(self.captures, index, '.gameplay.json', 'run_weight', False)
            self.edit(self.captures, index, '.gameplay.json', 'speed', False)
            self.edit(self.captures, index, '.gameplay.json', 'simulation_ads', True)
        with self.assertRaisesRegex(ValueError, 'fully held ADS'):
            authored.review_guides(self.captures, self.baseline, self.root / 'review', SOURCE_ROOT)

    def test_baseline_with_failed_validator_report_is_rejected(self):
        for fields in [{'passed': False}, {'passed': 'true'}, {'passed': 1}, {'schema': None},
                       {'frames': 2}, {'frames': 3.0}, {'frames': True}]:
            self.verdict(self.baseline / 'verification.json', **fields)
            with self.subTest(fields=fields):
                self.assertFalse(self.accepted())

    def test_baseline_without_validator_report_is_rejected(self):
        (self.baseline / 'verification.json').unlink()
        self.assertFalse(self.accepted())

    def test_reports_without_frame_count_are_accepted(self):
        authored.write_json(self.baseline / 'verification.json', {'schema': 'synthetic', 'passed': True})
        self.assertTrue(self.accepted())

    def test_ads_offset_uses_its_sibling_placement_report(self):
        offset = self.root / 'ads-placement' / 'ads-offset'
        offset.parent.mkdir()
        self.baseline.rename(offset)
        (offset / 'verification.json').unlink()
        self.baseline = offset
        with self.assertRaisesRegex(ValueError, 'ads-offset-verification.json'):
            authored.compare_sequence(self.baseline, self.captures)
        self.verdict(offset.parent / 'ads-offset-verification.json', frames=3)
        self.assertTrue(self.accepted())
        self.verdict(offset.parent / 'ads-offset-verification.json', passed=False)
        self.assertFalse(self.accepted())

    # Layered cross-rate verdict: the real producer's CLI output, not a fabricated schema.

    def layered_capture(self, folder, hz):
        """Synthetic rows that pass verify_layered_locomotion_capture.verify."""
        folder.mkdir(parents=True)
        stride = 120 // hz
        for index, tick in enumerate(range(0, 11 * 120, stride)):
            second = tick // 120
            if second < 8:
                direction, kind = divmod(second, 2)
                segment = f"{('forward', 'backward', 'left', 'right')[direction]}_{('hip', 'ads')[kind]}"
                route, walk, run = ('ads.hold' if kind else 'locomotion'), 1.0, 0
                weights = [1.0 if i == direction else 0.0 for i in range(4)]
                ads_requested, sprinting = bool(kind), False
            elif second == 8:
                segment, route, walk, run, weights = 'rapid_run_interruptions', 'ads.hold', 0.5, 0.5, None
                ads_requested, sprinting = True, True
            else:
                segment, route, walk, run, weights = 'settle', 'ready', 0.0, 0, None
                ads_requested, sprinting = False, False
            stem = folder / f'{index:04}.png'
            Image.new('RGBA', (4, 4), (tick % 256, tick // 256, 7, 255)).save(stem)
            authored.write_json(Path(f'{stem}.gameplay.json'), {
                'sampling_hz': hz, 'simulation_time': tick / 120, 'segment': segment, 'route': route,
                'walk_weight': walk, 'run_weight': run, 'directional_weights': weights,
                'ads_requested': ads_requested, 'sprinting': sprinting,
                'simulation_ads': 1 if route.startswith('ads.') else 0, 'renderer_failed': False,
                'pose_crc32': (tick * 2654435761) % 2 ** 32, 'walk_seconds': None,
                'position': [tick / 120, 0.0, 0.0], 'velocity': [1.0, 0.0, 0.0], 'ammo': 30, 'shots': 0})
        return sorted(folder.glob('[0-9][0-9][0-9][0-9].png'))

    def layered_baselines(self):
        """Run the actual producer exactly as native-validation.yml does."""
        parent = self.root / 'layered'
        images = {hz: self.layered_capture(parent / f'layered-{hz}', hz) for hz in (30, 60)}
        producer = Path(authored.__file__).with_name('verify_layered_locomotion_capture.py')
        output = subprocess.run([sys.executable, str(producer), str(parent / 'layered-30'),
                                 str(parent / 'layered-60')], check=True, capture_output=True, text=True)
        (parent / 'layered-rate-verification.json').write_text(output.stdout, encoding='utf-8')
        return parent, images

    def test_layered_verdicts_accept_the_actual_producer_output(self):
        parent, images = self.layered_baselines()
        wrapper = json.loads((parent / 'layered-rate-verification.json').read_text())
        self.assertEqual(set(wrapper), {'captures', 'rate_comparison'})  # no top-level verdict
        for hz in (30, 60):
            self.assertEqual(authored.baseline_verdicts(parent / f'layered-{hz}', images[hz]),
                             ['verification.json', 'layered-rate-verification.json'])

    def test_layered_verdicts_reject_tampered_or_missing_cross_rate_evidence(self):
        parent, images = self.layered_baselines()
        path = parent / 'layered-rate-verification.json'
        original = json.loads(path.read_text())

        def tamper(change):
            data = json.loads(json.dumps(original))
            change(data)
            return data

        cases = {
            'fabricated top-level verdict': tamper(lambda d: d.update(passed=True, schema='x')),
            'missing rate comparison': tamper(lambda d: d.pop('rate_comparison')),
            'one capture only': tamper(lambda d: d['captures'].pop()),
            'failed capture': tamper(lambda d: d['captures'][0].update(passed=False)),
            'string passed': tamper(lambda d: d['captures'][1].update(passed='true')),
            'wrong schema': tamper(lambda d: d['captures'][0].update(schema='other/v1')),
            'two 30 Hz captures': tamper(lambda d: d['captures'][1].update(sampling_hz=30)),
            'capture differs from its folder report': tamper(lambda d: d['captures'][0].update(frames=1)),
            'tampered common ticks': tamper(lambda d: d['rate_comparison'].update(common_ticks=1)),
            'fewer compared fields': tamper(lambda d: d['rate_comparison']['compared_fields'].pop()),
        }
        for name, data in cases.items():
            authored.write_json(path, data)
            with self.subTest(name), self.assertRaises(ValueError):
                authored.baseline_verdicts(parent / 'layered-30', images[30])
        authored.write_json(path, original)
        authored.baseline_verdicts(parent / 'layered-30', images[30])
        # Rows changed after the report: the re-run compare_rates must reject it.
        row = parent / 'layered-60' / '0002.png.gameplay.json'
        data = json.loads(row.read_text())
        data['pose_crc32'] += 1
        row.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'render sampling changed committed output'):
            authored.baseline_verdicts(parent / 'layered-30', images[30])
        path.unlink()
        with self.assertRaises(ValueError):
            authored.baseline_verdicts(parent / 'layered-60', images[60])

if __name__ == '__main__':
    unittest.main()

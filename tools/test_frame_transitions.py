"""Synthetic captures only; never proof of native GPU output."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import io

from PIL import Image, ImageDraw

import review_frame_transitions as transitions

# Scene state per frame: static runs and moving runs give pattern edges.
STATES = [0, 0, 1, 2, 2, 2, 3, 4, 4]


def image(state, tint):
    """A frame whose content depends on scene state; tint stands in for a backend."""
    picture = Image.new('RGBA', (32, 24), (tint, 40, 60, 255))
    ImageDraw.Draw(picture).rectangle((state * 3, 4, state * 3 + 5, 12), fill=(200, 180, tint, 255))
    return picture


class FrameTransitionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.legacy = self.write(self.root / 'legacy', STATES, 'OpenGl', 10)
        self.candidate = self.write(self.root / 'candidate', STATES, 'Dx12', 90)

    def write(self, folder, states, backend, tint, adapter='synthetic'):
        folder.mkdir(parents=True, exist_ok=True)
        for index, state in enumerate(states):
            image(state, tint).save(folder / f'{index:04}.png')
            (folder / f'{index:04}.png.json').write_text(json.dumps(
                {'backend': backend, 'adapter': adapter, 'width': 32, 'height': 24}))
        return folder

    def candidate_states(self, states):
        for path in self.candidate.iterdir():
            path.unlink()
        self.write(self.candidate, states, 'Dx12', 90)

    def review(self):
        return transitions.review(self.legacy, self.candidate)

    def test_matching_pattern_never_claims_pixel_binding(self):
        report = self.review()
        self.assertEqual(report['status'], 'pattern-match')
        self.assertFalse(report['pixel_binding_proven'])
        self.assertEqual(report['human_review'], 'open')
        self.assertEqual(report['frames'], 9)
        self.assertEqual(report['legacy_unchanged_transitions'], 4)
        self.assertEqual(report['legacy_edges'], 4)
        self.assertEqual(len(report['frame_digests']), 9)
        # Different backends: digests differ even though the pattern matches.
        self.assertNotEqual(report['frame_digests'][0]['legacy_rgba_sha256'],
                            report['frame_digests'][0]['candidate_rgba_sha256'])

    def test_one_frame_late_readback_is_a_mismatch(self):
        self.candidate_states([STATES[0]] + STATES[:-1])
        report = self.review()
        self.assertEqual(report['status'], 'pattern-mismatch')
        self.assertFalse(report['pixel_binding_proven'])
        self.assertTrue(report['mismatched_transitions'])

    def test_duplicated_frame_is_a_mismatch(self):
        states = list(STATES)
        states[3] = states[2]  # frame 3 repeats frame 2 while legacy moved
        self.candidate_states(states)
        report = self.review()
        self.assertEqual(report['status'], 'pattern-mismatch')
        self.assertIn({'transition': '0002.png->0003.png', 'legacy_changed': True,
                       'candidate_changed': False}, report['mismatched_transitions'])

    def test_swap_at_a_static_boundary_is_a_mismatch(self):
        states = list(STATES)
        states[1], states[2] = states[2], states[1]
        self.candidate_states(states)
        self.assertEqual(self.review()['status'], 'pattern-mismatch')

    def test_swap_inside_motion_is_a_known_blind_spot(self):
        # Limitation: frames 6 and 7 both differ from their neighbours either way.
        states = [0, 0, 1, 2, 3, 3, 4, 5, 6, 6]
        self.legacy = self.write(self.root / 'legacy2', states, 'OpenGl', 10)
        swapped = list(states)
        swapped[6], swapped[7] = swapped[7], swapped[6]
        self.candidate = self.write(self.root / 'candidate2', swapped, 'Dx12', 90)
        self.assertEqual(self.review()['status'], 'pattern-match')

    def test_omitted_frames_are_invalid_input(self):
        (self.candidate / '0008.png').unlink()
        (self.candidate / '0008.png.json').unlink()
        report = self.review()
        self.assertEqual(report['status'], 'invalid-input')
        self.assertIn('frame names differ', report['error'])
        (self.candidate / '0004.png').unlink()
        self.assertIn('noncontiguous', self.review()['error'])

    def test_identity_extent_and_decoding_are_validated(self):
        cases = {
            'backend': lambda: (self.candidate / '0003.png.json').write_text(json.dumps(
                {'backend': 'OpenGl', 'adapter': 'synthetic', 'width': 32, 'height': 24})),
            'adapter change': lambda: (self.candidate / '0003.png.json').write_text(json.dumps(
                {'backend': 'Dx12', 'adapter': 'other', 'width': 32, 'height': 24})),
            'blank adapter': lambda: (self.candidate / '0000.png.json').write_text(json.dumps(
                {'backend': 'Dx12', 'adapter': ' ', 'width': 32, 'height': 24})),
            'float extent': lambda: (self.candidate / '0000.png.json').write_text(json.dumps(
                {'backend': 'Dx12', 'adapter': 'synthetic', 'width': 32.0, 'height': 24})),
            'sidecar extent vs pixels': lambda: (self.candidate / '0002.png.json').write_text(json.dumps(
                {'backend': 'Dx12', 'adapter': 'synthetic', 'width': 31, 'height': 24})),
            'truncated png': lambda: (self.candidate / '0005.png').write_bytes(
                (self.candidate / '0005.png').read_bytes()[:-1]),
            'missing sidecar': lambda: (self.candidate / '0005.png.json').unlink(),
            'nonfinite sidecar': lambda: (self.candidate / '0005.png.json').write_text(
                '{"backend": "Dx12", "adapter": "synthetic", "width": 32, "height": 24, "x": NaN}'),
        }
        for name, corrupt in cases.items():
            with self.subTest(name):
                self.candidate_states(STATES)
                corrupt()
                self.assertEqual(self.review()['status'], 'invalid-input')

    def test_backend_extent_mismatch_between_captures_is_invalid(self):
        for path in self.candidate.iterdir():
            path.unlink()
        for index, state in enumerate(STATES):
            image(state, 90).resize((64, 48)).save(self.candidate / f'{index:04}.png')
            (self.candidate / f'{index:04}.png.json').write_text(json.dumps(
                {'backend': 'Dx12', 'adapter': 'synthetic', 'width': 64, 'height': 48}))
        self.assertIn('extent differs', self.review()['error'])

    def test_continuously_moving_or_static_sequences_are_insufficient_signal(self):
        for states in (list(range(9)), [5] * 9):
            with self.subTest(states=states):
                self.legacy = self.write(self.root / f'legacy-{states[1]}', states, 'OpenGl', 10)
                self.candidate = self.write(self.root / f'candidate-{states[1]}', states, 'Dx12', 90)
                report = self.review()
                self.assertEqual(report['status'], 'insufficient-signal')
                self.assertFalse(report['pixel_binding_proven'])

    def test_lag_during_continuous_motion_is_not_detected(self):
        # Limitation: with no static runs a one-frame lag keeps every transition changed.
        moving = list(range(9))
        self.legacy = self.write(self.root / 'legacy-moving', moving, 'OpenGl', 10)
        # Frame i shows state i-1; frame 0 shows the pre-capture state 9.
        self.candidate = self.write(self.root / 'candidate-moving', [9] + moving[:-1], 'Dx12', 90)
        self.assertEqual(self.review()['status'], 'insufficient-signal')

    def test_cross_backend_subpixel_difference_is_reported_not_hidden(self):
        # A change legacy rasterizes but the candidate does not is a review finding.
        states = list(STATES)
        states[7] = states[6]
        self.candidate_states(states)
        report = self.review()
        self.assertEqual(report['status'], 'pattern-mismatch')
        self.assertEqual(report['human_review'], 'open')

    def test_pixels_not_file_bytes_decide_changes(self):
        # Same pixels re-encoded with another compression level are unchanged.
        buffer = io.BytesIO()
        with Image.open(self.candidate / '0000.png') as source:
            source.save(buffer, format='PNG', compress_level=0)
        (self.candidate / '0001.png').write_bytes(buffer.getvalue())
        self.assertNotEqual((self.candidate / '0000.png').read_bytes(),
                            (self.candidate / '0001.png').read_bytes())
        self.assertEqual(self.review()['status'], 'pattern-match')

    def test_optional_readback_witness_must_match_decoded_pixels(self):
        report = self.review()
        self.assertEqual(report['readback_witnessed_frames'], {'legacy': 0, 'candidate': 0})
        for index, row in enumerate(report['frame_digests']):
            path = self.candidate / f'{index:04}.png.json'
            record = json.loads(path.read_text())
            record['readback_rgba_sha256'] = row['candidate_rgba_sha256']
            path.write_text(json.dumps(record))
        report = self.review()
        self.assertEqual(report['readback_witnessed_frames']['candidate'], 9)
        self.assertFalse(report['pixel_binding_proven'])  # Still not a stale-GPU-image check.
        # A PNG replaced after readback no longer matches its witness.
        (self.candidate / '0004.png').write_bytes((self.candidate / '0006.png').read_bytes())
        self.assertIn('readback_rgba_sha256', self.review()['error'])

    def test_cli_exit_codes_and_report_is_never_overwritten(self):
        report = self.root / 'report.json'
        with patch('sys.stdout', io.StringIO()):
            self.assertEqual(transitions.main([str(self.legacy), str(self.candidate),
                                               '--report', str(report)]), 0)
            self.assertEqual(json.loads(report.read_text())['status'], 'pattern-match')
            before = report.read_bytes()
            with patch('sys.stderr', io.StringIO()):
                self.assertEqual(transitions.main([str(self.legacy), str(self.candidate),
                                                   '--report', str(report)]), 2)
            self.assertEqual(report.read_bytes(), before)
            self.candidate_states([STATES[0]] + STATES[:-1])
            self.assertEqual(transitions.main([str(self.legacy), str(self.candidate)]), 1)
            self.assertEqual(transitions.main([str(self.legacy), str(self.root / 'missing')]), 2)
            moving = list(range(9))
            legacy = self.write(self.root / 'legacy-cli', moving, 'OpenGl', 10)
            candidate = self.write(self.root / 'candidate-cli', moving, 'Dx12', 90)
            self.assertEqual(transitions.main([str(legacy), str(candidate)]), 3)


if __name__ == '__main__':
    unittest.main()
